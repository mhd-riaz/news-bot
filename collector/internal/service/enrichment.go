package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/extract"
	"github.com/riaz/newscollector/internal/httpclient"
	"github.com/riaz/newscollector/internal/ratelimit"
	"github.com/riaz/newscollector/internal/repository"
	"github.com/riaz/newscollector/internal/robots"
)

// Fetcher reads one URL. The service depends on the behaviour rather than the
// concrete client, so its tests need no network.
type Fetcher interface {
	Fetch(ctx context.Context, r httpclient.Request) (*httpclient.Response, error)
}

// RobotsChecker decides what a publisher permits for one URL.
type RobotsChecker interface {
	Allowed(ctx context.Context, rawURL string) (robots.Decision, error)
}

// ArticleExtractor reads the article body out of a fetched page.
type ArticleExtractor interface {
	Extract(page []byte, contentType string, base *url.URL) (extract.Result, error)
}

// EnrichmentDeps is everything an EnrichmentService needs.
//
// Limiter is a concrete *ratelimit.Limiter rather than an interface because
// exactly one instance must exist: the collector reaches the same hosts this
// service does, and a second limiter would only pace half the real traffic.
type EnrichmentDeps struct {
	Articles  repository.ArticleRepository
	Robots    RobotsChecker
	Limiter   *ratelimit.Limiter
	Fetcher   Fetcher
	Extractor ArticleExtractor

	// MaxAttempts bounds how many times one article is tried before it is
	// abandoned. It must agree with the value used to claim the backlog, or an
	// article could be marked permanently failed on an attempt the claim query
	// would in fact have offered again.
	MaxAttempts int

	// RetryBase is the wait after a first transient failure, doubling per
	// attempt as domain.ScrapeBackoff describes.
	RetryBase time.Duration

	// MaxArticleAge drops articles published before it from the backlog. Zero
	// means no bound, which a backfill wants; a steady-state run wants one, or
	// the backlog grows with every publisher that goes quiet for a week.
	MaxArticleAge time.Duration

	// ClaimTTL is how long a claim may stand before it is assumed abandoned. It
	// must comfortably outlast one attempt — fetch timeout plus extraction — or
	// ProcessBacklog would reclaim a fetch that is merely slow rather than dead.
	ClaimTTL time.Duration

	Clock  Clock
	Logger *slog.Logger
}

// EnrichmentService performs full-text enrichment: it takes articles a feed did
// not supply the whole story for, fetches them where a publisher permits it,
// and stores whatever is actually an improvement.
type EnrichmentService struct {
	deps EnrichmentDeps
}

// NewEnrichmentService wires the service. A nil clock defaults to time.Now, a
// nil logger to the default one, and zero durations to the domain package's
// defaults.
func NewEnrichmentService(deps EnrichmentDeps) *EnrichmentService {
	if deps.MaxAttempts <= 0 {
		deps.MaxAttempts = domain.DefaultMaxScrapeAttempts
	}
	if deps.RetryBase <= 0 {
		deps.RetryBase = domain.DefaultScrapeRetryBase
	}
	if deps.ClaimTTL <= 0 {
		deps.ClaimTTL = DefaultClaimTTL
	}
	if deps.Clock == nil {
		deps.Clock = time.Now
	}
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	return &EnrichmentService{deps: deps}
}

// DefaultClaimTTL is used when EnrichmentDeps.ClaimTTL is left zero.
const DefaultClaimTTL = 10 * time.Minute

// BacklogResult tallies one ProcessBacklog run.
type BacklogResult struct {
	Claimed      int
	Succeeded    int
	NoNewContent int

	// Retrying counts attempts that failed but will be offered again later.
	Retrying int

	// Terminal counts articles that will never be attempted again: gone,
	// blocked, disallowed by robots.txt, or out of attempts.
	Terminal int
}

// ProcessBacklog claims and attempts up to limit articles, and reports what
// happened. It returns once the backlog is exhausted, limit is reached, or ctx
// ends; a claim finding nothing left is the ordinary end of a run, not an error.
func (s *EnrichmentService) ProcessBacklog(ctx context.Context, limit int) (BacklogResult, error) {
	if limit < 1 {
		return BacklogResult{}, fmt.Errorf("service: backlog limit must be greater than zero, got %d", limit)
	}

	var res BacklogResult
	claim := domain.ScrapeClaim{MaxAttempts: s.deps.MaxAttempts}

	// A worker that died mid-fetch leaves its claim behind at "scraping" forever
	// unless something returns it to the backlog; this is that something. It runs
	// once per batch rather than once per article, since it is a sweep over
	// every claim, not a check of one.
	if _, err := s.deps.Articles.ReleaseStaleScrapeClaims(ctx, s.deps.Clock().Add(-s.deps.ClaimTTL)); err != nil {
		s.deps.Logger.WarnContext(ctx, "enrichment: release stale claims", "error", err)
	}

	for i := 0; i < limit; i++ {
		if err := ctx.Err(); err != nil {
			return res, err
		}

		claim.Now = s.deps.Clock()
		if s.deps.MaxArticleAge > 0 {
			claim.PublishedAfter = claim.Now.Add(-s.deps.MaxArticleAge)
		}

		a, err := s.deps.Articles.ClaimForScraping(ctx, claim)
		if errors.Is(err, repository.ErrNotFound) {
			break
		}
		if err != nil {
			return res, fmt.Errorf("enrichment: claim article: %w", err)
		}
		res.Claimed++

		content, scrapeErr := s.ScrapeArticle(ctx, a)
		result := s.resultFor(a, content, scrapeErr)

		if err := s.deps.Articles.UpdateScrapeResult(ctx, a.ID, result); err != nil {
			if errors.Is(err, repository.ErrNotFound) {
				// A retention sweep may have removed the article while the
				// fetch was in flight; there is nothing left to update.
				continue
			}
			return res, fmt.Errorf("enrichment: update scrape result for %s: %w", a.ID, err)
		}

		switch {
		case result.Status == domain.ScrapeStatusSuccess:
			res.Succeeded++
		case result.Status == domain.ScrapeStatusNoNewContent:
			res.NoNewContent++
		case result.NextAt != nil:
			res.Retrying++
		default:
			res.Terminal++
		}

		s.deps.Logger.InfoContext(ctx, "enrichment: attempt finished",
			"article_id", a.ID, "attempt", a.ScrapeAttempts, "status", result.Status)
	}

	return res, nil
}

// ScrapeArticle performs one attempt at fetching a's full text.
//
// It makes no database write: the caller decides what a returned error means
// for the article's stored state, which keeps this function testable with a
// fake HTTP client and nothing else, and reusable outside ProcessBacklog.
//
// A non-nil error is always one of the domain sentinels — ErrRobotsDisallowed,
// ErrScrapeBlocked, ErrArticleGone, ErrExtractionEmpty, ErrNoNewContent — or a
// transient transport problem that is none of those. The caller tells the two
// apart with errors.Is, exactly as it would classify any other Go error.
func (s *EnrichmentService) ScrapeArticle(ctx context.Context, a *domain.Article) (string, error) {
	host := robots.Host(a.URL)
	if host == "" {
		return "", fmt.Errorf("enrichment: %q has no host to fetch from", a.URL)
	}

	// Checked before robots.txt is even consulted: a host resting after
	// consecutive failures should not pay for a robots.txt lookup either, cached
	// or not.
	if s.deps.Limiter.Resting(host) {
		return "", ratelimit.ErrCircuitOpen
	}

	decision, err := s.deps.Robots.Allowed(ctx, a.URL)
	if err != nil {
		return "", err
	}
	if !decision.Allowed {
		return "", domain.ErrRobotsDisallowed
	}

	if err := s.deps.Limiter.Acquire(ctx, host, decision.CrawlDelay); err != nil {
		return "", err
	}

	resp, err := s.deps.Fetcher.Fetch(ctx, httpclient.Request{
		URL:    domain.FetchURL(a.URL),
		Accept: httpclient.AcceptHTML,
	})
	if err != nil {
		s.deps.Limiter.Failure(host)
		return "", classifyFetchError(err)
	}
	s.deps.Limiter.Success(host)

	if err := checkRedirect(a.URL, resp.FinalURL); err != nil {
		return "", err
	}

	base, parseErr := url.Parse(resp.FinalURL)
	if parseErr != nil {
		base, _ = url.Parse(a.URL)
	}

	result, err := s.deps.Extractor.Extract(resp.Body, resp.ContentType, base)
	if err != nil {
		return "", err
	}
	if !domain.BetterContent(a.Content, result.Text) {
		return "", domain.ErrNoNewContent
	}
	return result.Text, nil
}

// classifyFetchError turns a fetch failure into the sentinel that describes it.
// Any status this switch does not name — 429, 5xx, and anything unexpected —
// falls through unchanged and is treated as transient.
func classifyFetchError(err error) error {
	var statusErr *httpclient.StatusError
	if !errors.As(err, &statusErr) {
		return err
	}
	switch statusErr.StatusCode {
	case 404, 410:
		return domain.ErrArticleGone
	case 401, 403:
		return domain.ErrScrapeBlocked
	default:
		return err
	}
}

// checkRedirect catches the two shapes of soft failure a 200 status can still
// hide behind. Neither is rare: an expired article commonly redirects to the
// section front page rather than answering 404, and a paywall commonly
// redirects to a login host rather than answering 403.
func checkRedirect(requested, final string) error {
	if final == "" {
		return nil
	}
	ru, err1 := url.Parse(requested)
	fu, err2 := url.Parse(final)
	if err1 != nil || err2 != nil || ru.Host == "" || fu.Host == "" {
		return nil
	}
	if trimWWW(ru.Host) != trimWWW(fu.Host) {
		return domain.ErrScrapeBlocked
	}
	if fu.Path == "" || fu.Path == "/" {
		return domain.ErrArticleGone
	}
	return nil
}

func trimWWW(host string) string {
	if len(host) > 4 && host[:4] == "www." {
		return host[4:]
	}
	return host
}

// resultFor turns one attempt's outcome into the write the repository makes.
func (s *EnrichmentService) resultFor(a *domain.Article, content string, scrapeErr error) domain.ScrapeResult {
	now := s.deps.Clock()

	if scrapeErr == nil {
		return domain.ScrapeResult{Status: domain.ScrapeStatusSuccess, Content: content, At: now}
	}

	status, retryable := s.classify(a, scrapeErr)
	result := domain.ScrapeResult{Status: status, At: now}
	if retryable {
		next := now.Add(domain.ScrapeBackoff(s.deps.RetryBase, a.ScrapeAttempts))
		result.NextAt = &next
	}
	return result
}

// classify maps a ScrapeArticle error onto a status and whether it is worth
// offering again.
//
// a.ScrapeAttempts is the shared counter the claim already raised, not a count
// specific to any one failure kind. Comparing it to domain.MaxExtractAttempts
// is therefore an approximation — an extraction failure following an earlier
// fetch failure is capped a little tighter than the constant's name alone
// suggests — but it is the same counter the claim query itself relies on, and
// a second counter would track something the database does not.
func (s *EnrichmentService) classify(a *domain.Article, err error) (domain.ScrapeStatus, bool) {
	switch {
	case errors.Is(err, domain.ErrRobotsDisallowed):
		return domain.ScrapeStatusRobotsDisallowed, false
	case errors.Is(err, domain.ErrScrapeBlocked):
		return domain.ScrapeStatusBlocked, false
	case errors.Is(err, domain.ErrArticleGone):
		return domain.ScrapeStatusGone, false
	case errors.Is(err, domain.ErrNoNewContent):
		return domain.ScrapeStatusNoNewContent, false
	case errors.Is(err, domain.ErrExtractionEmpty):
		if a.ScrapeAttempts >= domain.MaxExtractAttempts {
			return domain.ScrapeStatusFailed, false
		}
		return domain.ScrapeStatusExtractFailed, true
	default:
		// Network failures, 5xx, 429, and ratelimit.ErrCircuitOpen: none of
		// them says anything about the article, only about the moment.
		if a.ScrapeAttempts >= s.deps.MaxAttempts {
			return domain.ScrapeStatusFailed, false
		}
		return domain.ScrapeStatusFetchFailed, true
	}
}
