package service

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/mhd-riaz/news-bot/collector/internal/classifier"
	"github.com/mhd-riaz/news-bot/collector/internal/domain"
)

const targetModel = "v4-test-hybrid"

type fakeReclassifyRepo struct {
	articles []domain.Article
	updates  map[string]domain.Reclassification
	skipIDs  map[string]bool
	onUpdate func()
	limits   []int
	targets  []string
}

func newFakeReclassifyRepo(ids ...string) *fakeReclassifyRepo {
	repo := &fakeReclassifyRepo{updates: make(map[string]domain.Reclassification)}
	for _, id := range ids {
		repo.articles = append(repo.articles, domain.Article{
			ID: id, SourceName: "Publisher", Title: "Title " + id, Summary: "Summary " + id,
			Content: "Body " + id, ContentRev: 7,
		})
	}
	return repo
}

func (f *fakeReclassifyRepo) ListForReclassification(
	_ context.Context, afterID, target string, limit int,
) ([]domain.Article, error) {
	f.limits = append(f.limits, limit)
	f.targets = append(f.targets, target)
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

func (f *fakeReclassifyRepo) ReclassifyIfCurrent(
	_ context.Context, id string, revision int64, result domain.Reclassification,
) (bool, error) {
	if f.skipIDs[id] {
		return false, nil
	}
	for index, article := range f.articles {
		if article.ID != id {
			continue
		}
		if revision != article.ContentRev {
			return false, nil
		}
		f.articles = append(f.articles[:index], f.articles[index+1:]...)
		f.updates[id] = result
		if f.onUpdate != nil {
			f.onUpdate()
		}
		return true, nil
	}
	return false, nil
}

type fakeReclassifyClassifier struct {
	batchSize int
	version   string
	metaErr   error
	metaCalls int
	unfiled   map[string]bool
	declined  map[string]bool
	mutate    func([]classifier.Result) []classifier.Result
	calls     [][]classifier.Item
}

func (f *fakeReclassifyClassifier) Classify(
	_ context.Context, items []classifier.Item,
) ([]classifier.Result, error) {
	f.calls = append(f.calls, append([]classifier.Item(nil), items...))
	var declined []string
	for _, item := range items {
		if f.declined[item.ID] {
			declined = append(declined, item.ID)
		}
	}
	if len(declined) > 0 {
		return nil, &classifier.ItemError{IDs: declined}
	}
	results := make([]classifier.Result, len(items))
	for index, item := range items {
		results[index] = classifier.Result{
			ID: item.ID, Topic: "ai", Confidence: 0.8, Filed: !f.unfiled[item.ID],
			ModelVersion: targetModel, DetectedLanguage: "en",
		}
		if f.unfiled[item.ID] {
			results[index].Topic = "unsorted"
			results[index].Confidence = 0.3
		}
	}
	if f.mutate != nil {
		results = f.mutate(results)
	}
	return results, nil
}

func (f *fakeReclassifyClassifier) Metadata(context.Context) (classifier.Metadata, error) {
	f.metaCalls++
	if f.metaErr != nil {
		return classifier.Metadata{}, f.metaErr
	}
	version := f.version
	if version == "" {
		version = targetModel
	}
	return classifier.Metadata{ModelVersion: version}, nil
}

func (f *fakeReclassifyClassifier) BatchSize() int { return f.batchSize }

func TestReclassificationAbortsBeforeTouchingArticlesWithoutTargetVersion(t *testing.T) {
	for name, model := range map[string]*fakeReclassifyClassifier{
		"metadata fails": {batchSize: 50, metaErr: errors.New("sidecar down")},
		"blank version":  {batchSize: 50, version: "  "},
	} {
		t.Run(name, func(t *testing.T) {
			repo := newFakeReclassifyRepo("a")
			job := NewReclassificationService(ReclassificationDeps{Articles: repo, Classifier: model})
			result, err := job.Run(t.Context(), 10)
			if err == nil || result != (ReclassificationResult{}) {
				t.Fatalf("Run = %+v, %v; want an error and no work", result, err)
			}
			if len(repo.limits) != 0 || len(model.calls) != 0 || len(repo.updates) != 0 {
				t.Errorf("articles were touched: lists=%d classify=%d updates=%d",
					len(repo.limits), len(model.calls), len(repo.updates))
			}
		})
	}
}

func TestReclassificationRejectsInvalidSetup(t *testing.T) {
	for name, tc := range map[string]struct {
		deps  func(*fakeReclassifyRepo, *fakeReclassifyClassifier) ReclassificationDeps
		limit int
	}{
		"zero limit": {limit: 0, deps: func(r *fakeReclassifyRepo, c *fakeReclassifyClassifier) ReclassificationDeps {
			return ReclassificationDeps{Articles: r, Classifier: c}
		}},
		"negative delay": {limit: 10, deps: func(r *fakeReclassifyRepo, c *fakeReclassifyClassifier) ReclassificationDeps {
			return ReclassificationDeps{Articles: r, Classifier: c, BatchDelay: -time.Second}
		}},
		"missing classifier": {limit: 10, deps: func(r *fakeReclassifyRepo, _ *fakeReclassifyClassifier) ReclassificationDeps {
			return ReclassificationDeps{Articles: r}
		}},
		"classifier batch size": {limit: 10, deps: func(r *fakeReclassifyRepo, c *fakeReclassifyClassifier) ReclassificationDeps {
			c.batchSize = 0
			return ReclassificationDeps{Articles: r, Classifier: c}
		}},
	} {
		t.Run(name, func(t *testing.T) {
			repo := newFakeReclassifyRepo("a")
			model := &fakeReclassifyClassifier{batchSize: 50}
			_, err := NewReclassificationService(tc.deps(repo, model)).Run(t.Context(), tc.limit)
			if err == nil || len(repo.limits) != 0 || model.metaCalls != 0 {
				t.Fatalf("Run error = %v, lists = %d, metadata calls = %d", err, len(repo.limits), model.metaCalls)
			}
		})
	}
}

func TestReclassificationRunsBoundedResumableBatches(t *testing.T) {
	repo := newFakeReclassifyRepo("a", "b", "c", "d", "e")
	model := &fakeReclassifyClassifier{batchSize: 2}
	job := NewReclassificationService(ReclassificationDeps{
		Articles: repo, Classifier: model, BatchSize: 100,
		Clock: func() time.Time { return time.Date(2026, 11, 27, 9, 0, 0, 0, time.UTC) },
	})

	result, err := job.Run(t.Context(), 3)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if want := (ReclassificationResult{Batches: 2, Scanned: 3, Updated: 3, Classified: 3}); result != want {
		t.Fatalf("result = %+v, want %+v", result, want)
	}
	if fmt.Sprint(repo.limits) != "[2 1]" || repo.targets[0] != targetModel {
		t.Errorf("list limits/targets = %v / %v", repo.limits, repo.targets)
	}
	if len(repo.articles) != 2 || repo.articles[0].ID != "d" {
		t.Fatalf("limit was not respected; remaining = %+v", repo.articles)
	}
	if got := model.calls[0][0]; got.ID != "a" || got.Title != "Title a" || got.Summary != "Summary a" ||
		got.Body != "Body a" || got.Source != "Publisher" {
		t.Errorf("classifier input = %+v", got)
	}
	if got := repo.updates["a"]; got.ModelVersion != targetModel || got.At.IsZero() {
		t.Errorf("update = %+v", got)
	}

	result, err = job.Run(t.Context(), 10)
	if err != nil || result != (ReclassificationResult{Batches: 1, Scanned: 2, Updated: 2, Classified: 2}) {
		t.Fatalf("resumed Run = %+v, %v", result, err)
	}
}

func TestReclassificationBatchSizeIsBounded(t *testing.T) {
	ids := make([]string, 120)
	for index := range ids {
		ids[index] = fmt.Sprintf("id-%03d", index)
	}
	for name, tc := range map[string]struct {
		configured, sidecar, want int
	}{
		"unset configured size":        {configured: 0, sidecar: 100, want: MaxDerivedBackfillBatchSize},
		"configured above the maximum": {configured: 100, sidecar: 100, want: MaxDerivedBackfillBatchSize},
		"configured below sidecar":     {configured: 3, sidecar: 100, want: 3},
		"sidecar below configured":     {configured: 40, sidecar: 7, want: 7},
	} {
		t.Run(name, func(t *testing.T) {
			repo := newFakeReclassifyRepo(ids...)
			model := &fakeReclassifyClassifier{batchSize: tc.sidecar}
			job := NewReclassificationService(ReclassificationDeps{
				Articles: repo, Classifier: model, BatchSize: tc.configured,
			})
			if _, err := job.Run(t.Context(), 1000); err != nil {
				t.Fatalf("Run: %v", err)
			}
			for _, call := range model.calls {
				if len(call) > tc.want {
					t.Fatalf("batch of %d items exceeds bound %d", len(call), tc.want)
				}
			}
			if len(model.calls[0]) != tc.want {
				t.Errorf("first batch = %d items, want %d", len(model.calls[0]), tc.want)
			}
		})
	}
}

func TestReclassificationRejectsInconsistentClassifierResponses(t *testing.T) {
	for name, mutate := range map[string]func([]classifier.Result) []classifier.Result{
		"mismatched ID": func(results []classifier.Result) []classifier.Result {
			results[1].ID = "someone-else"
			return results
		},
		"missing result": func(results []classifier.Result) []classifier.Result { return results[:1] },
		"model version changed mid-run": func(results []classifier.Result) []classifier.Result {
			results[1].ModelVersion = "v5-swapped"
			return results
		},
	} {
		t.Run(name, func(t *testing.T) {
			repo := newFakeReclassifyRepo("a", "b")
			model := &fakeReclassifyClassifier{batchSize: 2, mutate: mutate}
			job := NewReclassificationService(ReclassificationDeps{Articles: repo, Classifier: model})
			result, err := job.Run(t.Context(), 10)
			if err == nil || result.Updated != 0 || len(repo.updates) != 0 {
				t.Fatalf("Run = %+v, %v; want an error and no writes for the batch", result, err)
			}
		})
	}
}

// TestReclassificationAdvancesPastConcurrentChanges proves that a concurrent writer cannot stall a run.
func TestReclassificationAdvancesPastConcurrentChanges(t *testing.T) {
	repo := newFakeReclassifyRepo("a", "b")
	repo.skipIDs = map[string]bool{"a": true}
	job := NewReclassificationService(ReclassificationDeps{
		Articles: repo, Classifier: &fakeReclassifyClassifier{batchSize: 1},
	})
	result, err := job.Run(t.Context(), 10)
	want := ReclassificationResult{Batches: 2, Scanned: 2, Updated: 1, Skipped: 1, Classified: 1}
	if err != nil || result != want {
		t.Fatalf("Run = %+v, %v; want %+v", result, err, want)
	}
	if _, ok := repo.updates["b"]; !ok {
		t.Fatal("run never advanced past the changed article")
	}
}

func TestReclassificationSkipsArticlesTheSidecarDeclines(t *testing.T) {
	for name, tc := range map[string]struct {
		declined  map[string]bool
		want      ReclassificationResult
		wantCalls []int
	}{
		"some declined": {
			declined:  map[string]bool{"b": true},
			want:      ReclassificationResult{Batches: 1, Scanned: 3, Updated: 2, Skipped: 1, Classified: 2},
			wantCalls: []int{3, 2},
		},
		"all declined": {
			declined:  map[string]bool{"a": true, "b": true, "c": true},
			want:      ReclassificationResult{Batches: 1, Scanned: 3, Skipped: 3},
			wantCalls: []int{3},
		},
	} {
		t.Run(name, func(t *testing.T) {
			repo := newFakeReclassifyRepo("a", "b", "c")
			model := &fakeReclassifyClassifier{batchSize: 3, declined: tc.declined}
			job := NewReclassificationService(ReclassificationDeps{Articles: repo, Classifier: model})
			result, err := job.Run(t.Context(), 10)
			if err != nil || result != tc.want {
				t.Fatalf("Run = %+v, %v; want %+v", result, err, tc.want)
			}
			var calls []int
			for _, call := range model.calls {
				calls = append(calls, len(call))
			}
			if fmt.Sprint(calls) != fmt.Sprint(tc.wantCalls) {
				t.Errorf("classifier batch sizes = %v, want %v", calls, tc.wantCalls)
			}
			for id := range tc.declined {
				if _, written := repo.updates[id]; written {
					t.Errorf("declined article %s was written", id)
				}
			}
		})
	}
}

func TestReclassificationCountsClassifiedAndUnsorted(t *testing.T) {
	repo := newFakeReclassifyRepo("a", "b", "c")
	model := &fakeReclassifyClassifier{batchSize: 3, unfiled: map[string]bool{"b": true}}
	job := NewReclassificationService(ReclassificationDeps{Articles: repo, Classifier: model})
	result, err := job.Run(t.Context(), 10)
	want := ReclassificationResult{Batches: 1, Scanned: 3, Updated: 3, Classified: 2, Unsorted: 1}
	if err != nil || result != want {
		t.Fatalf("Run = %+v, %v; want %+v", result, err, want)
	}
	if got := repo.updates["a"]; got.Status != domain.ClassificationStatusClassified || got.Topic != "ai" ||
		got.Confidence != 0.8 {
		t.Errorf("filed update = %+v", got)
	}
	if got := repo.updates["b"]; got.Status != domain.ClassificationStatusUnsorted || got.Topic != "unsorted" ||
		got.Confidence != 0.3 {
		t.Errorf("unfiled update = %+v", got)
	}
}

// TestReclassificationBatchDelay covers elapsed and canceled waits with isolated fake dependencies.
func TestReclassificationBatchDelay(t *testing.T) {
	for _, canceled := range []bool{false, true} {
		name := "elapsed"
		if canceled {
			name = "canceled"
		}
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			repo := newFakeReclassifyRepo("a", "b")
			delay := time.Nanosecond
			if canceled {
				repo.onUpdate = cancel
				delay = time.Hour
			}
			job := NewReclassificationService(ReclassificationDeps{
				Articles: repo, Classifier: &fakeReclassifyClassifier{batchSize: 1}, BatchDelay: delay,
			})
			result, err := job.Run(ctx, 10)
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
