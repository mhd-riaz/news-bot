package service

import (
	"context"
	"errors"
	"net/url"
	"sync"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/extract"
	"github.com/riaz/newscollector/internal/httpclient"
	"github.com/riaz/newscollector/internal/ratelimit"
	"github.com/riaz/newscollector/internal/repository"
	"github.com/riaz/newscollector/internal/robots"
)

// --- fakes -------------------------------------------------------------

// fakeEnrichmentRepo is a queue of claimable articles, plus a record of every
// write, so a test can assert what the service told the database without a
// real one.
type fakeEnrichmentRepo struct {
	mu      sync.Mutex
	queue   []domain.Article
	updates map[string]domain.ScrapeResult
	// deleted marks an article whose UpdateScrapeResult must report
	// ErrNotFound, simulating a retention sweep racing the fetch.
	deleted map[string]bool

	releaseCalls  int
	releaseBefore time.Time
}

func newFakeEnrichmentRepo(articles ...domain.Article) *fakeEnrichmentRepo {
	return &fakeEnrichmentRepo{
		queue:   append([]domain.Article(nil), articles...),
		updates: map[string]domain.ScrapeResult{},
		deleted: map[string]bool{},
	}
}

func (f *fakeEnrichmentRepo) ClaimForScraping(context.Context, domain.ScrapeClaim) (*domain.Article, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.queue) == 0 {
		return nil, repository.ErrNotFound
	}
	a := f.queue[0]
	f.queue = f.queue[1:]
	a.ScrapeAttempts++
	return &a, nil
}

func (f *fakeEnrichmentRepo) UpdateScrapeResult(_ context.Context, id string, result domain.ScrapeResult) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.deleted[id] {
		return repository.ErrNotFound
	}
	f.updates[id] = result
	return nil
}

func (f *fakeEnrichmentRepo) ReleaseStaleScrapeClaims(_ context.Context, before time.Time) (int64, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.releaseCalls++
	f.releaseBefore = before
	return 0, nil
}

func (f *fakeEnrichmentRepo) Create(context.Context, *domain.Article) error { return nil }
func (f *fakeEnrichmentRepo) FindByIdentity(context.Context, domain.ArticleIdentity) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}
func (f *fakeEnrichmentRepo) GetByID(context.Context, string) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}
func (f *fakeEnrichmentRepo) List(context.Context, domain.ArticleFilter) (domain.ArticlePage, error) {
	return domain.ArticlePage{}, nil
}
func (f *fakeEnrichmentRepo) DeleteOlderThan(context.Context, domain.ArticleDeletion) (int64, error) {
	return 0, nil
}

func (f *fakeEnrichmentRepo) ClaimForClassification(context.Context, domain.ClassificationClaim) (*domain.Article, error) {
	return nil, repository.ErrNotFound
}

func (f *fakeEnrichmentRepo) UpdateClassification(context.Context, string, domain.ClassificationResult) error {
	return nil
}

func (f *fakeEnrichmentRepo) ReleaseStaleClassificationClaims(context.Context, time.Time) (int64, error) {
	return 0, nil
}

func (f *fakeEnrichmentRepo) resultFor(id string) (domain.ScrapeResult, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.updates[id]
	return r, ok
}

// fakeRobots returns one canned decision or error for every URL asked about,
// and records what was asked.
type fakeRobots struct {
	decision robots.Decision
	err      error
	asked    []string
}

func (f *fakeRobots) Allowed(_ context.Context, rawURL string) (robots.Decision, error) {
	f.asked = append(f.asked, rawURL)
	return f.decision, f.err
}

// fakeFetcher returns one canned response or error, and records the request it
// received.
type fakeFetcher struct {
	resp *httpclient.Response
	err  error
	last httpclient.Request
}

func (f *fakeFetcher) Fetch(_ context.Context, r httpclient.Request) (*httpclient.Response, error) {
	f.last = r
	return f.resp, f.err
}

// fakeExtractor returns one canned result or error, ignoring the page.
type fakeExtractor struct {
	result extract.Result
	err    error
}

func (f *fakeExtractor) Extract([]byte, string, *url.URL) (extract.Result, error) {
	return f.result, f.err
}

// --- test fixtures -------------------------------------------------------

func enrichArticle(mutate ...func(*domain.Article)) *domain.Article {
	a := &domain.Article{
		ID:      "018f3f7e-1c2a-7f24-9a3f-8f9f2a0a5c11",
		URL:     "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
		Content: "A one-sentence teaser.",
	}
	for _, m := range mutate {
		m(a)
	}
	return a
}

func newTestLimiter() *ratelimit.Limiter {
	// A real limiter with an effectively-zero interval: these tests assert
	// classification and wiring, not pacing, which internal/ratelimit already
	// covers on its own.
	return ratelimit.New(ratelimit.Config{MinInterval: time.Microsecond})
}

func allowedDecision() robots.Decision { return robots.Decision{Allowed: true} }

// --- ScrapeArticle ---------------------------------------------------------

func TestScrapeArticleSucceeds(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, ContentType: "text/html",
			FinalURL: "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
		}},
		Extractor: &fakeExtractor{result: extract.Result{Text: longWords(300), By: "readability"}},
	})

	content, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if err != nil {
		t.Fatalf("ScrapeArticle: %v", err)
	}
	if domain.WordCount(content) != 300 {
		t.Errorf("got %d words, want 300", domain.WordCount(content))
	}
}

func TestScrapeArticleRefusedByRobotsRule(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: robots.Decision{Allowed: false}},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{err: errors.New("must not be called")},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrRobotsDisallowed) {
		t.Errorf("err = %v, want ErrRobotsDisallowed", err)
	}
}

func TestScrapeArticlePropagatesAnUnreadableRobotsFile(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{err: robots.ErrUnreadable},
		Limiter: newTestLimiter(),
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, robots.ErrUnreadable) {
		t.Errorf("err = %v, want ErrUnreadable", err)
	}
}

func TestScrapeArticleSkipsARestingHostWithoutAnyLookup(t *testing.T) {
	robotsChecker := &fakeRobots{decision: allowedDecision()}
	fetcher := &fakeFetcher{err: errors.New("must not be called")}
	limiter := newTestLimiter()
	limiter.Rest("www.thehindu.com", time.Hour)

	svc := NewEnrichmentService(EnrichmentDeps{Robots: robotsChecker, Limiter: limiter, Fetcher: fetcher})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, ratelimit.ErrCircuitOpen) {
		t.Fatalf("err = %v, want ErrCircuitOpen", err)
	}
	if len(robotsChecker.asked) != 0 {
		t.Error("robots.txt was consulted for a resting host")
	}
}

func TestScrapeArticleMapsA404ToGone(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{err: &httpclient.StatusError{StatusCode: 404}},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrArticleGone) {
		t.Errorf("err = %v, want ErrArticleGone", err)
	}
}

func TestScrapeArticleMapsA403ToBlocked(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{err: &httpclient.StatusError{StatusCode: 403}},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrScrapeBlocked) {
		t.Errorf("err = %v, want ErrScrapeBlocked", err)
	}
}

func TestScrapeArticleTreatsA429AsTransient(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{err: &httpclient.StatusError{StatusCode: 429}},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if errors.Is(err, domain.ErrArticleGone) || errors.Is(err, domain.ErrScrapeBlocked) {
		t.Errorf("a 429 was classified as terminal: %v", err)
	}
	var statusErr *httpclient.StatusError
	if !errors.As(err, &statusErr) || statusErr.StatusCode != 429 {
		t.Errorf("err = %v, want the raw 429 status error", err)
	}
}

func TestScrapeArticleDetectsARedirectToTheHomepage(t *testing.T) {
	// An expired article commonly redirects to the section front page rather
	// than answering 404.
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://www.thehindu.com/",
		}},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrArticleGone) {
		t.Errorf("err = %v, want ErrArticleGone", err)
	}
}

func TestScrapeArticleDetectsARedirectOffSite(t *testing.T) {
	// A paywall commonly redirects to a login host rather than answering 403.
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://login.thehindu.com/subscribe",
		}},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrScrapeBlocked) {
		t.Errorf("err = %v, want ErrScrapeBlocked", err)
	}
}

func TestScrapeArticlePropagatesAnExtractionFailure(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
		}},
		Extractor: &fakeExtractor{err: domain.ErrExtractionEmpty},
	})

	_, err := svc.ScrapeArticle(context.Background(), enrichArticle())
	if !errors.Is(err, domain.ErrExtractionEmpty) {
		t.Errorf("err = %v, want ErrExtractionEmpty", err)
	}
}

func TestScrapeArticleRefusesToRegress(t *testing.T) {
	// Deccan Herald's shape: the feed already holds the whole story, and the
	// page itself yields only navigation furniture.
	svc := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://www.deccanherald.com/story",
		}},
		Extractor: &fakeExtractor{result: extract.Result{Text: longWords(40)}},
	})

	a := enrichArticle(func(a *domain.Article) {
		a.URL = "https://www.deccanherald.com/story"
		a.Content = longWords(1189)
	})
	_, err := svc.ScrapeArticle(context.Background(), a)
	if !errors.Is(err, domain.ErrNoNewContent) {
		t.Errorf("err = %v, want ErrNoNewContent", err)
	}
}

func TestScrapeArticleUpdatesTheLimiterOnSuccessAndFailure(t *testing.T) {
	limiter := newTestLimiter()

	fail := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: limiter,
		Fetcher: &fakeFetcher{err: &httpclient.StatusError{StatusCode: 503}},
	})
	for range 3 {
		_, _ = fail.ScrapeArticle(context.Background(), enrichArticle())
	}
	if !limiter.Resting("www.thehindu.com") {
		t.Fatal("three consecutive failures did not rest the host")
	}

	// A success elsewhere must not be confused with this host by name alone.
	succeed := NewEnrichmentService(EnrichmentDeps{
		Robots:  &fakeRobots{decision: allowedDecision()},
		Limiter: limiter,
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://www.bbc.co.uk/news/story",
		}},
		Extractor: &fakeExtractor{result: extract.Result{Text: longWords(200)}},
	})
	other := enrichArticle(func(a *domain.Article) { a.URL = "https://www.bbc.co.uk/news/story" })
	if _, err := succeed.ScrapeArticle(context.Background(), other); err != nil {
		t.Fatalf("ScrapeArticle for a different host: %v", err)
	}
	if limiter.Resting("www.bbc.co.uk") {
		t.Error("an unrelated host was rested by another host's failures")
	}
}

func TestScrapeArticleRejectsAnArticleWithNoHost(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{Limiter: newTestLimiter()})
	a := enrichArticle(func(a *domain.Article) { a.URL = "not a url" })

	if _, err := svc.ScrapeArticle(context.Background(), a); err == nil {
		t.Error("a hostless URL was accepted")
	}
}

// --- ProcessBacklog ---------------------------------------------------------

func TestProcessBacklogStopsWhenTheBacklogIsEmpty(t *testing.T) {
	repo := newFakeEnrichmentRepo()
	svc := NewEnrichmentService(EnrichmentDeps{Articles: repo, Limiter: newTestLimiter()})

	res, err := svc.ProcessBacklog(context.Background(), 10)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Claimed != 0 {
		t.Errorf("Claimed = %d, want 0", res.Claimed)
	}
}

func TestProcessBacklogRecordsASuccess(t *testing.T) {
	repo := newFakeEnrichmentRepo(*enrichArticle())
	svc := NewEnrichmentService(EnrichmentDeps{
		Articles: repo,
		Robots:   &fakeRobots{decision: allowedDecision()},
		Limiter:  newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, FinalURL: "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
		}},
		Extractor: &fakeExtractor{result: extract.Result{Text: longWords(250)}},
	})

	res, err := svc.ProcessBacklog(context.Background(), 10)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Claimed != 1 || res.Succeeded != 1 {
		t.Errorf("result = %+v, want Claimed=1 Succeeded=1", res)
	}

	got, ok := repo.resultFor(enrichArticle().ID)
	if !ok {
		t.Fatal("no update was written")
	}
	if got.Status != domain.ScrapeStatusSuccess {
		t.Errorf("Status = %q, want success", got.Status)
	}
	if domain.WordCount(got.Content) != 250 {
		t.Errorf("stored %d words, want 250", domain.WordCount(got.Content))
	}
	if got.NextAt != nil {
		t.Error("a terminal success carried a retry time")
	}
}

func TestProcessBacklogSchedulesARetryOnATransientFailure(t *testing.T) {
	// The claim already raised the counter to 1, so this is the article's
	// first attempt, well inside a budget of 3: it must come back.
	repo := newFakeEnrichmentRepo(*enrichArticle())
	svc := NewEnrichmentService(EnrichmentDeps{
		Articles:  repo,
		Robots:    &fakeRobots{decision: allowedDecision()},
		Limiter:   newTestLimiter(),
		Fetcher:   &fakeFetcher{err: &httpclient.StatusError{StatusCode: 503}},
		RetryBase: 15 * time.Minute,
	})

	res, err := svc.ProcessBacklog(context.Background(), 10)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Retrying != 1 || res.Terminal != 0 {
		t.Errorf("result = %+v, want Retrying=1 Terminal=0", res)
	}

	got, _ := repo.resultFor(enrichArticle().ID)
	if got.Status != domain.ScrapeStatusFetchFailed {
		t.Errorf("Status = %q, want fetch_failed", got.Status)
	}
	if got.NextAt == nil {
		t.Fatal("a retryable failure carried no retry time")
	}
	if wait := got.NextAt.Sub(got.At); wait != 15*time.Minute {
		t.Errorf("scheduled after %s, want the configured base of 15m", wait)
	}
}

func TestProcessBacklogAbandonsAnArticleThatHasSpentItsBudget(t *testing.T) {
	// Two prior attempts are already recorded; the claim raises this to the
	// third and last one the budget allows.
	seed := *enrichArticle()
	seed.ScrapeAttempts = 2
	repo := newFakeEnrichmentRepo(seed)

	svc := NewEnrichmentService(EnrichmentDeps{
		Articles:    repo,
		Robots:      &fakeRobots{decision: allowedDecision()},
		Limiter:     newTestLimiter(),
		Fetcher:     &fakeFetcher{err: &httpclient.StatusError{StatusCode: 503}},
		MaxAttempts: 3,
	})

	res, err := svc.ProcessBacklog(context.Background(), 10)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Terminal != 1 || res.Retrying != 0 {
		t.Errorf("result = %+v, want Terminal=1 Retrying=0", res)
	}

	got, _ := repo.resultFor(seed.ID)
	if got.Status != domain.ScrapeStatusFailed {
		t.Errorf("Status = %q, want failed", got.Status)
	}
	if got.NextAt != nil {
		t.Error("an exhausted article carried a retry time")
	}
}

func TestProcessBacklogRespectsTheLimit(t *testing.T) {
	a1 := enrichArticle(func(a *domain.Article) { a.ID = "1"; a.URL = "https://a.example/1" })
	a2 := enrichArticle(func(a *domain.Article) { a.ID = "2"; a.URL = "https://a.example/2" })
	repo := newFakeEnrichmentRepo(*a1, *a2)

	svc := NewEnrichmentService(EnrichmentDeps{
		Articles: repo,
		Robots:   &fakeRobots{decision: robots.Decision{Allowed: false}},
		Limiter:  newTestLimiter(),
	})

	res, err := svc.ProcessBacklog(context.Background(), 1)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Claimed != 1 {
		t.Errorf("Claimed = %d, want 1", res.Claimed)
	}
}

func TestProcessBacklogSkipsAnArticleDeletedDuringTheFetch(t *testing.T) {
	repo := newFakeEnrichmentRepo(*enrichArticle())
	repo.deleted[enrichArticle().ID] = true

	svc := NewEnrichmentService(EnrichmentDeps{
		Articles: repo,
		Robots:   &fakeRobots{decision: robots.Decision{Allowed: false}},
		Limiter:  newTestLimiter(),
	})

	res, err := svc.ProcessBacklog(context.Background(), 10)
	if err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}
	if res.Claimed != 1 {
		t.Errorf("Claimed = %d, want 1", res.Claimed)
	}
	if res.Terminal != 0 && res.Retrying != 0 {
		t.Errorf("a deleted article was still counted: %+v", res)
	}
}

func TestProcessBacklogReleasesStaleClaimsBeforeDrawingFromTheBacklog(t *testing.T) {
	repo := newFakeEnrichmentRepo()
	svc := NewEnrichmentService(EnrichmentDeps{
		Articles: repo,
		Limiter:  newTestLimiter(),
		ClaimTTL: 10 * time.Minute,
	})

	if _, err := svc.ProcessBacklog(context.Background(), 5); err != nil {
		t.Fatalf("ProcessBacklog: %v", err)
	}

	repo.mu.Lock()
	defer repo.mu.Unlock()
	if repo.releaseCalls != 1 {
		t.Errorf("ReleaseStaleScrapeClaims was called %d times, want 1", repo.releaseCalls)
	}
}

func TestProcessBacklogRejectsANonPositiveLimit(t *testing.T) {
	svc := NewEnrichmentService(EnrichmentDeps{
		Articles: newFakeEnrichmentRepo(),
		Limiter:  newTestLimiter(),
	})
	if _, err := svc.ProcessBacklog(context.Background(), 0); err == nil {
		t.Error("a zero limit was accepted")
	}
}

// longWords builds a body of exactly n words.
func longWords(n int) string {
	s := ""
	for i := 0; i < n; i++ {
		if i > 0 {
			s += " "
		}
		s += "word"
	}
	return s
}
