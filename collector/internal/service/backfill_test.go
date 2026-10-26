package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
)

type fakeDerivedBackfillRepo struct {
	articles []domain.Article
	updates  map[string]domain.ArticleDerivedFields
	skipIDs  map[string]bool
	onUpdate func()
}

func (f *fakeDerivedBackfillRepo) ListMissingDerivedFields(
	_ context.Context, afterID string, limit int,
) ([]domain.Article, error) {
	var articles []domain.Article
	for _, article := range f.articles {
		if article.ID > afterID {
			articles = append(articles, article)
			if len(articles) == limit {
				break
			}
		}
	}
	return articles, nil
}

func (f *fakeDerivedBackfillRepo) BackfillDerivedFieldsIfMissing(
	_ context.Context, id string, _ int64, fields domain.ArticleDerivedFields,
) (bool, error) {
	if f.skipIDs[id] {
		return false, nil
	}
	for index, article := range f.articles {
		if article.ID == id {
			f.articles = append(f.articles[:index], f.articles[index+1:]...)
			f.updates[id] = fields
			if f.onUpdate != nil {
				f.onUpdate()
			}
			return true, nil
		}
	}
	return false, nil
}

type fakeDerivedBackfillClassifier struct {
	batchSize int
	err       error
	calls     [][]classifier.Item
}

func (f *fakeDerivedBackfillClassifier) Classify(
	_ context.Context, items []classifier.Item,
) ([]classifier.Result, error) {
	f.calls = append(f.calls, append([]classifier.Item(nil), items...))
	if f.err != nil {
		return nil, f.err
	}
	results := make([]classifier.Result, len(items))
	for index, item := range items {
		results[index] = classifier.Result{
			ID: item.ID, Topic: "politics", CleanTitle: "clean " + item.Title,
			CleanSummary: "clean summary", CleanBody: "clean body",
			DetectedLanguage: "en", LanguageConfidence: 0.99,
		}
	}
	return results, nil
}

func (*fakeDerivedBackfillClassifier) Metadata(context.Context) (classifier.Metadata, error) {
	return classifier.Metadata{}, nil
}

func (f *fakeDerivedBackfillClassifier) BatchSize() int { return f.batchSize }

func TestDerivedFieldBackfillRunsBoundedResumableBatches(t *testing.T) {
	now := time.Date(2026, 8, 31, 10, 0, 0, 0, time.UTC)
	repo := &fakeDerivedBackfillRepo{
		articles: []domain.Article{
			{ID: "fallback", SourceName: "Publisher", Title: "First", PublishedAt: now, CollectedAt: now},
			{ID: "feed", SourceName: "Publisher", Title: "Second", PublishedAt: now.Add(-time.Hour), CollectedAt: now},
			{ID: "third", SourceName: "Publisher", Title: "Third", PublishedAt: now, CollectedAt: now, PublishedAtSource: domain.PublicationDateSourcePage},
		},
		updates: make(map[string]domain.ArticleDerivedFields),
	}
	model := &fakeDerivedBackfillClassifier{batchSize: 2}
	backfill := NewDerivedFieldBackfillService(DerivedFieldBackfillDeps{
		Articles: repo, Classifier: model, BatchSize: 100,
	})

	result, err := backfill.Run(t.Context(), 10)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if result != (DerivedFieldBackfillResult{Batches: 2, Scanned: 3, Updated: 3}) {
		t.Fatalf("result = %+v", result)
	}
	if len(model.calls) != 2 || len(model.calls[0]) != 2 || len(model.calls[1]) != 1 {
		t.Fatalf("classifier calls = %#v", model.calls)
	}
	if model.calls[0][0].Source != "Publisher" {
		t.Errorf("classifier input source = %q", model.calls[0][0].Source)
	}
	if got := repo.updates["fallback"]; got.PublishedAtSource != domain.PublicationDateSourceCollectedFallback ||
		got.DateVerified {
		t.Errorf("fallback date fields = %+v", got)
	}
	if got := repo.updates["feed"]; got.PublishedAtSource != domain.PublicationDateSourceFeed ||
		!got.DateVerified || got.CleanTitle != "clean Second" || got.DetectedLanguage != "en" {
		t.Errorf("feed derived fields = %+v", got)
	}
	if got := repo.updates["third"]; got.PublishedAtSource != domain.PublicationDateSourcePage || !got.DateVerified {
		t.Errorf("existing page provenance = %+v", got)
	}
}

func TestDerivedFieldBackfillDoesNotWriteWhenClassificationFails(t *testing.T) {
	repo := &fakeDerivedBackfillRepo{
		articles: []domain.Article{{ID: "article", Title: "A headline"}},
		updates:  make(map[string]domain.ArticleDerivedFields),
	}
	backfill := NewDerivedFieldBackfillService(DerivedFieldBackfillDeps{
		Articles: repo, Classifier: &fakeDerivedBackfillClassifier{
			batchSize: 50, err: errors.New("classifier unavailable"),
		},
	})
	result, err := backfill.Run(t.Context(), 50)
	if err == nil || result.Updated != 0 || len(repo.updates) != 0 {
		t.Fatalf("Run = %+v, %v; want no updates and an error", result, err)
	}
}

// TestDerivedFieldBackfillAdvancesPastSkippedSnapshots proves that a concurrent writer cannot stall a run.
func TestDerivedFieldBackfillAdvancesPastSkippedSnapshots(t *testing.T) {
	repo := &fakeDerivedBackfillRepo{
		articles: []domain.Article{{ID: "a"}, {ID: "b"}},
		updates:  make(map[string]domain.ArticleDerivedFields),
		skipIDs:  map[string]bool{"a": true},
	}
	backfill := NewDerivedFieldBackfillService(DerivedFieldBackfillDeps{
		Articles: repo, Classifier: &fakeDerivedBackfillClassifier{batchSize: 1},
	})
	result, err := backfill.Run(t.Context(), 10)
	if err != nil || result != (DerivedFieldBackfillResult{Batches: 2, Scanned: 2, Updated: 1, Skipped: 1}) {
		t.Fatalf("Run = %+v, %v", result, err)
	}
	if _, ok := repo.updates["b"]; !ok {
		t.Fatal("run never advanced past the skipped snapshot")
	}
}

// TestDerivedFieldBackfillBatchDelay covers elapsed and canceled waits with isolated fake dependencies.
func TestDerivedFieldBackfillBatchDelay(t *testing.T) {
	for _, canceled := range []bool{false, true} {
		name := "elapsed"
		if canceled {
			name = "canceled"
		}
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			repo := &fakeDerivedBackfillRepo{
				articles: []domain.Article{{ID: "a"}, {ID: "b"}},
				updates:  make(map[string]domain.ArticleDerivedFields),
			}
			delay := time.Nanosecond
			if canceled {
				repo.onUpdate = cancel
				delay = time.Hour
			}
			backfill := NewDerivedFieldBackfillService(DerivedFieldBackfillDeps{
				Articles: repo, Classifier: &fakeDerivedBackfillClassifier{batchSize: 1},
				BatchDelay: delay,
			})
			result, err := backfill.Run(ctx, 10)
			if canceled {
				if !errors.Is(err, context.Canceled) || result.Updated != 1 {
					t.Fatalf("canceled Run = %+v, %v", result, err)
				}
			} else if err != nil || result.Updated != 2 {
				t.Fatalf("Run = %+v, %v", result, err)
			}
		})
	}
}
