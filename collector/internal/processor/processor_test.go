package processor

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

var fixedNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func fixedClock() time.Time { return fixedNow }

// fakeArticleRepo enforces the same unique keys the articles indexes do, so the
// duplicate paths a test exercises are the ones production takes.
type fakeArticleRepo struct {
	stored []domain.Article

	// createErr and findErr inject a repository failure.
	createErr error
	findErr   error

	// createHook runs before a successful insert, so a test can simulate another
	// collector winning the race between the lookup and the write.
	createHook func()

	creates int
}

type fakeClassifier struct {
	results   []classifier.Result
	err       error
	items     []classifier.Item
	calls     [][]classifier.Item
	batchSize int
}

func (f *fakeClassifier) Classify(_ context.Context, items []classifier.Item) ([]classifier.Result, error) {
	f.items = append([]classifier.Item(nil), items...)
	f.calls = append(f.calls, f.items)
	if f.err != nil {
		return nil, f.err
	}
	if f.results != nil {
		return f.results, nil
	}
	// Without fixed results, echo one classified result per item so a chunked
	// batch of any size can be verified without the caller wiring up each chunk.
	results := make([]classifier.Result, len(items))
	for index, item := range items {
		results[index] = classifier.Result{
			ID: item.ID, Topic: "politics", Confidence: 0.9, Filed: true, ModelVersion: "v2-001",
			CleanTitle: item.Title, CleanSummary: item.Summary, CleanBody: item.Body,
			DetectedLanguage: "en", LanguageConfidence: 0.99,
		}
	}
	return results, nil
}

func (f *fakeClassifier) Metadata(context.Context) (classifier.Metadata, error) {
	return classifier.Metadata{}, nil
}

func (f *fakeClassifier) BatchSize() int { return f.batchSize }

var _ repository.ArticleRepository = (*fakeArticleRepo)(nil)

func (f *fakeArticleRepo) Create(_ context.Context, a *domain.Article) error {
	if f.createErr != nil {
		return f.createErr
	}
	if f.createHook != nil {
		f.createHook()
	}
	f.creates++

	for _, existing := range f.stored {
		if existing.DedupID == a.DedupID || existing.NormalizedURL == a.NormalizedURL ||
			(existing.SourceID == a.SourceID && existing.FeedGUID != "" && existing.FeedGUID == a.FeedGUID) {
			return repository.ErrDuplicate
		}
	}
	f.stored = append(f.stored, *a)
	return nil
}

func (f *fakeArticleRepo) FindByIdentity(_ context.Context, id domain.ArticleIdentity) (*domain.Article, error) {
	if f.findErr != nil {
		return nil, f.findErr
	}
	for i, a := range f.stored {
		switch {
		case a.NormalizedURL == id.NormalizedURL,
			id.CanonicalURL != "" && a.CanonicalURL == id.CanonicalURL,
			id.FeedGUID != "" && a.SourceID == id.SourceID && a.FeedGUID == id.FeedGUID,
			id.ContentHash != "" && a.SourceID == id.SourceID && a.ContentHash == id.ContentHash:
			return &f.stored[i], nil
		}
	}
	return nil, repository.ErrNotFound
}

// The reading half of the contract is not what this package does; it is
// implemented only so the fake satisfies the interface.
func (f *fakeArticleRepo) GetByID(_ context.Context, id string) (*domain.Article, error) {
	for i := range f.stored {
		if f.stored[i].ID == id {
			return &f.stored[i], nil
		}
	}
	return nil, repository.ErrNotFound
}

func (f *fakeArticleRepo) List(_ context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error) {
	return domain.ArticlePage{Items: f.stored, Limit: filter.Limit}, nil
}

func (f *fakeArticleRepo) DeleteOlderThan(context.Context, domain.ArticleDeletion) (int64, error) {
	return 0, nil
}

// The enrichment stage runs after this package's, so these exist only to
// satisfy the interface.
func (f *fakeArticleRepo) ClaimForScraping(context.Context, domain.ScrapeClaim) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}

func (f *fakeArticleRepo) UpdateScrapeResult(context.Context, string, domain.ScrapeResult) error {
	return nil
}

func (f *fakeArticleRepo) ReleaseStaleScrapeClaims(context.Context, time.Time) (int64, error) {
	return 0, nil
}

func (f *fakeArticleRepo) ClaimForClassification(context.Context, domain.ClassificationClaim) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}

func (f *fakeArticleRepo) UpdateClassification(context.Context, string, domain.ClassificationResult) error {
	return nil
}

func (f *fakeArticleRepo) ReleaseStaleClassificationClaims(context.Context, time.Time) (int64, error) {
	return 0, nil
}

func testSource() *domain.Source {
	return &domain.Source{
		ID:       "018f3f7e-1c2a-7f24-9a3f-8f9f2a0a5c11",
		Name:     "Mysuru Daily",
		FeedURL:  "https://news.example.com/feed.xml",
		Type:     domain.SourceTypeRSS,
		Language: "en",
		Country:  "IN",
		State:    "Karnataka",
		City:     "Mysuru",
	}
}

func item(title, link, guid string) domain.FeedItem {
	published := fixedNow.Add(-2 * time.Hour)
	return domain.FeedItem{Title: title, Link: link, GUID: guid, Summary: "A summary.", PublishedAt: &published}
}

func TestProcessStoresNewArticles(t *testing.T) {
	repo := &fakeArticleRepo{}

	res, err := New(repo, fixedClock).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
		item("Two", "https://news.example.com/2", "g-2"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}

	if res != (Result{Items: 2, Stored: 2, Unclassified: 2}) {
		t.Fatalf("Result = %+v, want 2 items stored", res)
	}
	if len(repo.stored) != 2 {
		t.Fatalf("stored %d articles, want 2", len(repo.stored))
	}
	if repo.stored[0].SourceName != "Mysuru Daily" || repo.stored[0].City != "Mysuru" {
		t.Errorf("the source's attribution and region were not carried: %+v", repo.stored[0])
	}
}

func TestProcessClassifiesBeforeStoring(t *testing.T) {
	repo := &fakeArticleRepo{}
	model := &fakeClassifier{results: []classifier.Result{{
		ID: "", Topic: "politics", Confidence: 0.9, Filed: true, ModelVersion: "v2-001",
		CleanTitle: "One", CleanSummary: "Clean summary", CleanBody: "Clean body",
		DetectedLanguage: "en", LanguageConfidence: 0.99,
	}}}
	result, err := New(repo, fixedClock, model).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}
	if len(model.items) != 1 || len(repo.stored) != 1 || repo.stored[0].ClassificationStatus != domain.ClassificationStatusClassified || repo.stored[0].Topic != "politics" {
		t.Fatalf("classification/store state = items:%#v stored:%#v", model.items, repo.stored)
	}
	if result.Unclassified != 0 || result.Classified != 1 || !result.ClassifierAvailable {
		t.Errorf("classification result = %+v, want one available classified result", result)
	}
	if model.items[0].Source != "Mysuru Daily" {
		t.Errorf("classifier source = %q, want publisher name", model.items[0].Source)
	}
	stored := repo.stored[0]
	if stored.CleanTitle != "One" || stored.CleanSummary != "Clean summary" ||
		stored.CleanBody != "Clean body" || stored.DetectedLanguage != "en" ||
		stored.LanguageConfidence != 0.99 {
		t.Errorf("stored derived fields = %+v", stored)
	}
}

func TestProcessStoresPendingArticlesWhenClassifierFails(t *testing.T) {
	repo := &fakeArticleRepo{}
	model := &fakeClassifier{err: errors.New("classifier unavailable")}
	result, err := New(repo, fixedClock, model).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}
	if len(repo.stored) != 1 || repo.stored[0].ClassificationStatus != domain.ClassificationStatusPending {
		t.Fatalf("stored state = %#v, want pending article", repo.stored)
	}
	if result.Unclassified != 1 {
		t.Errorf("Unclassified = %d, want 1", result.Unclassified)
	}
}

func TestProcessClassifiesLargeBatchesInChunksOfTheConfiguredSize(t *testing.T) {
	repo := &fakeArticleRepo{}
	model := &fakeClassifier{batchSize: 2}
	result, err := New(repo, fixedClock, model).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
		item("Two", "https://news.example.com/2", "g-2"),
		item("Three", "https://news.example.com/3", "g-3"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}
	if len(model.calls) != 2 || len(model.calls[0]) != 2 || len(model.calls[1]) != 1 {
		t.Fatalf("calls = %#v, want a batch of 2 items and then a batch of 1", model.calls)
	}
	if result.Classified != 3 || result.Unclassified != 0 || !result.ClassifierAvailable {
		t.Errorf("classification result = %+v, want all 3 items classified across chunks", result)
	}
}

func TestProcessSkipsArticlesAlreadyStored(t *testing.T) {
	repo := &fakeArticleRepo{}
	p := New(repo, fixedClock)
	items := []domain.FeedItem{item("One", "https://news.example.com/1", "g-1")}

	if _, err := p.Process(t.Context(), testSource(), items); err != nil {
		t.Fatalf("first Process: %v", err)
	}

	// The same feed, polled again: the entry is unchanged and must not be stored twice.
	res, err := p.Process(t.Context(), testSource(), items)
	if err != nil {
		t.Fatalf("second Process: %v", err)
	}
	if res != (Result{Items: 1, Duplicates: 1, Unclassified: 1}) {
		t.Fatalf("Result = %+v, want the item counted as a duplicate", res)
	}
	if len(repo.stored) != 1 {
		t.Errorf("stored %d articles, want 1", len(repo.stored))
	}
}

func TestProcessDeduplicatesWithinOneBatch(t *testing.T) {
	const permalink = "https://news.example.com/1"

	tests := []struct {
		name  string
		batch []domain.FeedItem
	}{
		{
			name: "same link, one carrying a tracking parameter",
			batch: []domain.FeedItem{
				item("One", "https://news.example.com/1", "g-1"),
				item("One", "https://news.example.com/1?utm_source=twitter", "g-2"),
			},
		},
		{
			name: "different links sharing the publisher's permalink",
			batch: []domain.FeedItem{
				item("One", "https://news.example.com/1", permalink),
				item("One, updated", "https://news.example.com/1-amp", permalink),
			},
		},
		{
			name: "different links sharing the publisher's identifier",
			batch: []domain.FeedItem{
				item("One", "https://news.example.com/1", "g-1"),
				item("One, updated", "https://news.example.com/1-amp", "g-1"),
			},
		},
		{
			name: "same text republished under another link",
			batch: []domain.FeedItem{
				item("One", "https://news.example.com/1", "g-1"),
				item("One", "https://news.example.com/1-amp", "g-2"),
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			repo := &fakeArticleRepo{}

			res, err := New(repo, fixedClock).Process(t.Context(), testSource(), tc.batch)
			if err != nil {
				t.Fatalf("Process: %v", err)
			}
			if res.Stored != 1 || res.Duplicates != 1 {
				t.Fatalf("Result = %+v, want 1 stored and 1 duplicate", res)
			}
		})
	}
}

// The content hash is the last key tried, and it only settles a duplicate within
// one source: two sources syndicating the same story are two articles.
func TestProcessKeepsTheSameStoryFromTwoSources(t *testing.T) {
	repo := &fakeArticleRepo{}
	p := New(repo, fixedClock)

	other := testSource()
	other.ID = "018f3f7e-1c2a-7f24-9a3f-8f9f2a0a5c99"
	other.Name = "Deccan Bulletin"

	batch := []domain.FeedItem{item("One", "https://news.example.com/1", "g-1")}
	syndicated := []domain.FeedItem{item("One", "https://bulletin.example.net/1", "b-1")}

	if _, err := p.Process(t.Context(), testSource(), batch); err != nil {
		t.Fatalf("Process: %v", err)
	}
	res, err := p.Process(t.Context(), other, syndicated)
	if err != nil {
		t.Fatalf("Process: %v", err)
	}

	if res.Stored != 1 {
		t.Fatalf("Result = %+v, want the syndicated copy stored", res)
	}
}

func TestProcessCountsUnusableItemsWithoutFailingTheBatch(t *testing.T) {
	repo := &fakeArticleRepo{}

	res, err := New(repo, fixedClock).Process(t.Context(), testSource(), []domain.FeedItem{
		item("No link", "", "g-1"),
		item("", "https://news.example.com/2", "g-2"),
		item("Fine", "https://news.example.com/3", "g-3"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}

	if res != (Result{Items: 3, Stored: 1, Invalid: 2, Unclassified: 1}) {
		t.Fatalf("Result = %+v, want 1 stored and 2 invalid", res)
	}
}

// Between the lookup and the insert another collector may store the same
// article. The unique index rejects the second write, and that is a duplicate,
// not a failure.
func TestProcessTreatsALostRaceAsADuplicate(t *testing.T) {
	repo := &fakeArticleRepo{}
	repo.createHook = func() {
		if len(repo.stored) == 0 {
			rival, err := domain.NewArticle(*testSource(), item("One", "https://news.example.com/1", "g-1"), fixedNow)
			if err != nil {
				t.Fatalf("build the rival article: %v", err)
			}
			repo.stored = append(repo.stored, *rival)
		}
	}

	res, err := New(repo, fixedClock).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
	})
	if err != nil {
		t.Fatalf("Process: %v", err)
	}
	if res != (Result{Items: 1, Duplicates: 1, Unclassified: 1}) {
		t.Fatalf("Result = %+v, want the lost race counted as a duplicate", res)
	}
}

func TestProcessStopsOnARepositoryFailure(t *testing.T) {
	boom := errors.New("mongo is down")

	tests := []struct {
		name string
		repo *fakeArticleRepo
	}{
		{name: "lookup fails", repo: &fakeArticleRepo{findErr: boom}},
		{name: "insert fails", repo: &fakeArticleRepo{createErr: boom}},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			res, err := New(tc.repo, fixedClock).Process(t.Context(), testSource(), []domain.FeedItem{
				item("One", "https://news.example.com/1", "g-1"),
				item("Two", "https://news.example.com/2", "g-2"),
			})
			if !errors.Is(err, boom) {
				t.Fatalf("Process error = %v, want it to wrap the repository failure", err)
			}
			// The counts so far travel with the error so a run record can still
			// report what got through.
			if res.Items != 2 || res.Stored != 0 {
				t.Errorf("Result = %+v", res)
			}
		})
	}
}

func TestProcessRejectsANilSource(t *testing.T) {
	if _, err := New(&fakeArticleRepo{}, fixedClock).Process(t.Context(), nil, nil); err == nil {
		t.Fatal("expected an error for a nil source")
	}
}

func TestNewDefaultsTheClock(t *testing.T) {
	repo := &fakeArticleRepo{}

	if _, err := New(repo, nil).Process(t.Context(), testSource(), []domain.FeedItem{
		item("One", "https://news.example.com/1", "g-1"),
	}); err != nil {
		t.Fatalf("Process: %v", err)
	}
	if repo.stored[0].CollectedAt.IsZero() {
		t.Error("a nil clock must fall back to the wall clock")
	}
}
