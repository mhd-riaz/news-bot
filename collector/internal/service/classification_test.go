package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

type fakeClassificationRepo struct {
	article  *domain.Article
	updates  []domain.ClassificationResult
	released int
}

var _ repository.ArticleRepository = (*fakeClassificationRepo)(nil)

func (f *fakeClassificationRepo) Create(context.Context, *domain.Article) error { return nil }
func (f *fakeClassificationRepo) FindByIdentity(context.Context, domain.ArticleIdentity) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}
func (f *fakeClassificationRepo) GetByID(context.Context, string) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}
func (f *fakeClassificationRepo) List(context.Context, domain.ArticleFilter) (domain.ArticlePage, error) {
	return domain.ArticlePage{}, nil
}
func (f *fakeClassificationRepo) DeleteOlderThan(context.Context, domain.ArticleDeletion) (int64, error) {
	return 0, nil
}
func (f *fakeClassificationRepo) ClaimForScraping(context.Context, domain.ScrapeClaim) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}
func (f *fakeClassificationRepo) UpdateScrapeResult(context.Context, string, domain.ScrapeResult) error {
	return nil
}
func (f *fakeClassificationRepo) ReleaseStaleScrapeClaims(context.Context, time.Time) (int64, error) {
	return 0, nil
}
func (f *fakeClassificationRepo) ClaimForClassification(_ context.Context, claim domain.ClassificationClaim) (*domain.Article, error) {
	if f.article == nil || f.article.ClassificationStatus != domain.ClassificationStatusPending {
		return nil, repository.ErrNotFound
	}
	f.article.ClassificationStatus = domain.ClassificationStatusClassifying
	f.article.ClassificationClaimedAt = &claim.Now
	f.article.ClassificationAttempts++
	return f.article, nil
}
func (f *fakeClassificationRepo) UpdateClassification(_ context.Context, _ string, result domain.ClassificationResult) error {
	f.updates = append(f.updates, result)
	f.article.ClassificationStatus = result.Status
	f.article.ClassificationClaimedAt = nil
	return nil
}
func (f *fakeClassificationRepo) ReleaseStaleClassificationClaims(context.Context, time.Time) (int64, error) {
	f.released++
	return 0, nil
}

type fakeBackfillClassifier struct {
	result classifier.Result
	err    error
	items  *[]classifier.Item
}

func (f fakeBackfillClassifier) Classify(_ context.Context, items []classifier.Item) ([]classifier.Result, error) {
	if f.err != nil {
		return nil, f.err
	}
	if f.items != nil {
		*f.items = append(*f.items, items...)
	}
	return []classifier.Result{f.result}, nil
}
func (fakeBackfillClassifier) Metadata(context.Context) (classifier.Metadata, error) {
	return classifier.Metadata{}, nil
}
func (fakeBackfillClassifier) BatchSize() int { return 0 }

func TestClassificationBacklogStoresSuccessfulAndUnsortedResults(t *testing.T) {
	now := time.Date(2026, 8, 31, 10, 0, 0, 0, time.UTC)
	for _, test := range []struct {
		name   string
		result classifier.Result
		status domain.ClassificationStatus
	}{
		{
			"classified", classifier.Result{
				Topic: "politics", Confidence: 0.9, Filed: true, ModelVersion: "v2-001",
				CleanTitle: "Clean headline", CleanSummary: "Clean summary", CleanBody: "Clean body",
				DetectedLanguage: "en", LanguageConfidence: 0.99,
			}, domain.ClassificationStatusClassified,
		},
		{
			"unsorted", classifier.Result{
				Topic: "unsorted", Confidence: 0.4, ModelVersion: "v2-001",
				CleanTitle: "Clean headline", CleanSummary: "Clean summary", CleanBody: "Clean body",
				DetectedLanguage: "und", LanguageConfidence: 0,
			}, domain.ClassificationStatusUnsorted,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			repo := &fakeClassificationRepo{article: &domain.Article{
				ID: "article", SourceName: "Example Publisher", Title: "Headline",
				Summary: "Summary", Content: "Body",
				ClassificationStatus: domain.ClassificationStatusPending,
			}}
			var items []classifier.Item
			service := NewClassificationService(ClassificationDeps{
				Articles: repo, Classifier: fakeBackfillClassifier{result: test.result, items: &items},
				MaxAttempts: 3, Clock: func() time.Time { return now },
			})
			got, err := service.ProcessBacklog(t.Context(), 1)
			if err != nil || len(repo.updates) != 1 || repo.updates[0].Status != test.status {
				t.Fatalf("ProcessBacklog = %#v, %v; update = %#v", got, err, repo.updates)
			}
			update := repo.updates[0]
			if len(items) != 1 || items[0].Source != "Example Publisher" {
				t.Errorf("classifier input = %#v, want source name", items)
			}
			if update.CleanTitle != test.result.CleanTitle ||
				update.CleanSummary != test.result.CleanSummary ||
				update.CleanBody != test.result.CleanBody ||
				update.DetectedLanguage != test.result.DetectedLanguage ||
				update.LanguageConfidence != test.result.LanguageConfidence {
				t.Errorf("derived update = %+v", update)
			}
		})
	}
}

func TestClassificationBacklogRetriesThenExhaustsAttempts(t *testing.T) {
	now := time.Date(2026, 8, 31, 10, 0, 0, 0, time.UTC)
	repo := &fakeClassificationRepo{article: &domain.Article{ID: "article", ClassificationStatus: domain.ClassificationStatusPending, ClassificationAttempts: 2}}
	service := NewClassificationService(ClassificationDeps{Articles: repo, Classifier: fakeBackfillClassifier{err: errors.New("unavailable")}, MaxAttempts: 3, Clock: func() time.Time { return now }})
	got, err := service.ProcessBacklog(t.Context(), 1)
	if err != nil || got.Failed != 1 || repo.updates[0].Status != domain.ClassificationStatusFailed {
		t.Fatalf("ProcessBacklog = %#v, %v; update = %#v", got, err, repo.updates)
	}
}
