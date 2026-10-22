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
}

func (f fakeBackfillClassifier) Classify(context.Context, []classifier.Item) ([]classifier.Result, error) {
	if f.err != nil {
		return nil, f.err
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
		{"classified", classifier.Result{Topic: "politics", Confidence: 0.9, Filed: true, ModelVersion: "v2-001"}, domain.ClassificationStatusClassified},
		{"unsorted", classifier.Result{Topic: "unsorted", Confidence: 0.4, ModelVersion: "v2-001"}, domain.ClassificationStatusUnsorted},
	} {
		t.Run(test.name, func(t *testing.T) {
			repo := &fakeClassificationRepo{article: &domain.Article{ID: "article", ClassificationStatus: domain.ClassificationStatusPending}}
			service := NewClassificationService(ClassificationDeps{Articles: repo, Classifier: fakeBackfillClassifier{result: test.result}, MaxAttempts: 3, Clock: func() time.Time { return now }})
			got, err := service.ProcessBacklog(t.Context(), 1)
			if err != nil || len(repo.updates) != 1 || repo.updates[0].Status != test.status {
				t.Fatalf("ProcessBacklog = %#v, %v; update = %#v", got, err, repo.updates)
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
