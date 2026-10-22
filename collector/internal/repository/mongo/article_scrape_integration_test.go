//go:build integration

package mongo

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// longBody builds a body of exactly n words, so a fixture can sit either side
// of the threshold that decides whether an article needs fetching.
func longBody(n int) string {
	return strings.TrimSpace(strings.Repeat("reservoir ", n))
}

// pendingArticle stores an article that the collection stage left for
// enrichment: a teaser body, so NewArticle queues it rather than marking it
// finished.
func pendingArticle(t *testing.T, repo *ArticleRepository, link, guid string) *domain.Article {
	t.Helper()

	a := newArticle(t, link, guid, func(i *domain.FeedItem) {
		i.Content = "<p>A one-sentence teaser is all this feed sends.</p>"
	})
	if a.ScrapeStatus != domain.ScrapeStatusPending {
		t.Fatalf("fixture is %q, want %q", a.ScrapeStatus, domain.ScrapeStatusPending)
	}
	if err := repo.Create(testContext(t), a); err != nil {
		t.Fatalf("Create: %v", err)
	}
	return a
}

func defaultClaim(now time.Time) domain.ScrapeClaim {
	return domain.ScrapeClaim{Now: now, MaxAttempts: domain.DefaultMaxScrapeAttempts}
}

// dueAfter returns an instant at which a is certainly due. Taking it from the
// stored article rather than the wall clock keeps the claim from racing the
// timestamp NewArticle stamped a moment earlier.
func dueAfter(a *domain.Article) time.Time {
	return a.CollectedAt.Add(time.Second)
}

func TestClaimForScrapingTakesADueArticleAndCountsTheAttempt(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)

	got, err := repo.ClaimForScraping(ctx, defaultClaim(now))
	if err != nil {
		t.Fatalf("ClaimForScraping: %v", err)
	}
	if got.ID != a.ID {
		t.Errorf("claimed %q, want %q", got.ID, a.ID)
	}
	if got.ScrapeStatus != domain.ScrapeStatusScraping {
		t.Errorf("ScrapeStatus = %q, want %q", got.ScrapeStatus, domain.ScrapeStatusScraping)
	}
	// The counter must rise on the claim, not on the result: a worker that dies
	// mid-fetch has still spent an attempt.
	if got.ScrapeAttempts != 1 {
		t.Errorf("ScrapeAttempts = %d, want 1", got.ScrapeAttempts)
	}
	if got.ScrapedAt == nil {
		t.Error("ScrapedAt is nil, want the claim instant")
	}
}

func TestClaimForScrapingIsExclusive(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)

	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
		t.Fatalf("first claim: %v", err)
	}
	// The article is in flight, so a second worker must not be handed it.
	_, err := repo.ClaimForScraping(ctx, defaultClaim(now))
	if !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("second claim err = %v, want ErrNotFound", err)
	}
}

func TestClaimForScrapingSkipsArticlesThatNeedNoFetch(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	// A feed that ships the whole story is finished on arrival and must never
	// be fetched again.
	full := newArticle(t, "https://example.com/story/full", "story-full",
		func(i *domain.FeedItem) { i.Content = "<p>" + longBody(600) + "</p>" })
	if full.ScrapeStatus != domain.ScrapeStatusNotNeeded {
		t.Fatalf("fixture is %q, want %q", full.ScrapeStatus, domain.ScrapeStatusNotNeeded)
	}
	if err := repo.Create(ctx, full); err != nil {
		t.Fatalf("Create: %v", err)
	}

	_, err := repo.ClaimForScraping(ctx, defaultClaim(dueAfter(full)))
	if !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("claim err = %v, want ErrNotFound: a full-text feed is not backlog", err)
	}
}

func TestClaimForScrapingRespectsTheAttemptBudget(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)

	// Spend the budget, returning the article to the backlog each time.
	for i := 1; i <= domain.DefaultMaxScrapeAttempts; i++ {
		claimed, err := repo.ClaimForScraping(ctx, defaultClaim(now))
		if err != nil {
			t.Fatalf("claim %d: %v", i, err)
		}
		if claimed.ScrapeAttempts != i {
			t.Errorf("attempt %d recorded as %d", i, claimed.ScrapeAttempts)
		}
		due := now
		if err := repo.UpdateScrapeResult(ctx, a.ID, domain.ScrapeResult{
			Status: domain.ScrapeStatusFetchFailed,
			At:     now,
			NextAt: &due,
		}); err != nil {
			t.Fatalf("UpdateScrapeResult %d: %v", i, err)
		}
	}

	_, err := repo.ClaimForScraping(ctx, defaultClaim(now))
	if !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("claim after the budget err = %v, want ErrNotFound", err)
	}
}

func TestClaimForScrapingHonoursTheBackoffSchedule(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)

	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
		t.Fatalf("first claim: %v", err)
	}
	later := now.Add(15 * time.Minute)
	if err := repo.UpdateScrapeResult(ctx, a.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusFetchFailed,
		At:     now,
		NextAt: &later,
	}); err != nil {
		t.Fatalf("UpdateScrapeResult: %v", err)
	}

	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("claim before the backoff expires err = %v, want ErrNotFound", err)
	}
	if _, err := repo.ClaimForScraping(ctx, defaultClaim(later)); err != nil {
		t.Errorf("claim after the backoff expires: %v", err)
	}
}

func TestClaimForScrapingSkipsArticlesOlderThanTheBound(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")

	claim := defaultClaim(dueAfter(a))
	claim.PublishedAfter = a.PublishedAt.Add(time.Minute)

	_, err := repo.ClaimForScraping(ctx, claim)
	if !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("claim err = %v, want ErrNotFound for an article past the age bound", err)
	}
}

func TestUpdateScrapeResultStoresTextAndPromotesTheArticle(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)
	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
		t.Fatalf("ClaimForScraping: %v", err)
	}

	body := longBody(240)
	if err := repo.UpdateScrapeResult(ctx, a.ID, domain.ScrapeResult{
		Status:  domain.ScrapeStatusSuccess,
		Content: body,
		At:      now,
	}); err != nil {
		t.Fatalf("UpdateScrapeResult: %v", err)
	}

	got, err := repo.GetByID(ctx, a.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Content != body {
		t.Errorf("Content was not stored (%d words)", domain.WordCount(got.Content))
	}
	if got.ScrapeStatus != domain.ScrapeStatusSuccess {
		t.Errorf("ScrapeStatus = %q, want %q", got.ScrapeStatus, domain.ScrapeStatusSuccess)
	}
	if got.ProcessingStatus != domain.ProcessingStatusEnriched {
		t.Errorf("ProcessingStatus = %q, want %q", got.ProcessingStatus, domain.ProcessingStatusEnriched)
	}
	// Frozen: the hash identifies the feed's text and is a deduplication key.
	if got.ContentHash != a.ContentHash {
		t.Errorf("ContentHash changed: %q -> %q", a.ContentHash, got.ContentHash)
	}
	// A terminal article carries no next attempt, which is what keeps it out of
	// every future backlog query.
	if got.NextScrapeAt != nil {
		t.Errorf("NextScrapeAt = %v, want nil for a terminal status", got.NextScrapeAt)
	}
	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now.Add(24*time.Hour))); !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("a finished article was offered again: %v", err)
	}
}

func TestUpdateScrapeResultLeavesStoredTextAloneOnFailure(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)
	before := a.Content

	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
		t.Fatalf("ClaimForScraping: %v", err)
	}
	due := now.Add(time.Hour)
	if err := repo.UpdateScrapeResult(ctx, a.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusFetchFailed,
		At:     now,
		NextAt: &due,
	}); err != nil {
		t.Fatalf("UpdateScrapeResult: %v", err)
	}

	got, err := repo.GetByID(ctx, a.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Content != before {
		t.Errorf("a failed attempt overwrote the stored text: %q -> %q", before, got.Content)
	}
	if got.ProcessingStatus != domain.ProcessingStatusCollected {
		t.Errorf("ProcessingStatus = %q, want %q after a failure",
			got.ProcessingStatus, domain.ProcessingStatusCollected)
	}
}

func TestUpdateScrapeResultReportsADeletedArticle(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	// The retention sweep may legitimately remove an article while its fetch is
	// in flight, and the caller has to be able to tell that from a real failure.
	err := repo.UpdateScrapeResult(ctx, "018f3f7e-1c2a-7f24-9a3f-000000000000", domain.ScrapeResult{
		Status: domain.ScrapeStatusSuccess,
		At:     time.Now().UTC(),
	})
	if !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

func TestReleaseStaleScrapeClaimsRecoversFromACrashedWorker(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	a := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	now := dueAfter(a)

	claimed, err := repo.ClaimForScraping(ctx, defaultClaim(now))
	if err != nil {
		t.Fatalf("ClaimForScraping: %v", err)
	}

	// A claim younger than the bound belongs to a worker that is still running.
	freed, err := repo.ReleaseStaleScrapeClaims(ctx, now.Add(-time.Minute))
	if err != nil {
		t.Fatalf("ReleaseStaleScrapeClaims: %v", err)
	}
	if freed != 0 {
		t.Errorf("freed %d live claims, want 0", freed)
	}

	cutoff := now.Add(time.Minute)
	freed, err = repo.ReleaseStaleScrapeClaims(ctx, cutoff)
	if err != nil {
		t.Fatalf("ReleaseStaleScrapeClaims: %v", err)
	}
	if freed != 1 {
		t.Fatalf("freed %d abandoned claims, want 1", freed)
	}

	again, err := repo.ClaimForScraping(ctx, defaultClaim(cutoff))
	if err != nil {
		t.Fatalf("claim after release: %v", err)
	}
	if again.ID != claimed.ID {
		t.Errorf("claimed %q, want the released %q", again.ID, claimed.ID)
	}
	// The attempt the dead worker spent is still counted, so an article that
	// kills its worker cannot be retried forever.
	if again.ScrapeAttempts != 2 {
		t.Errorf("ScrapeAttempts = %d, want 2", again.ScrapeAttempts)
	}
}

func TestClaimForScrapingTakesTheOldestDueArticleFirst(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	first := pendingArticle(t, repo, "https://example.com/story/1", "story-1")
	second := pendingArticle(t, repo, "https://example.com/story/2", "story-2")
	now := dueAfter(second)

	// Push the first article's next attempt behind the second's.
	older := now.Add(-time.Hour)
	if err := repo.UpdateScrapeResult(ctx, second.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusFetchFailed,
		At:     older,
		NextAt: &older,
	}); err != nil {
		t.Fatalf("UpdateScrapeResult: %v", err)
	}

	got, err := repo.ClaimForScraping(ctx, defaultClaim(now))
	if err != nil {
		t.Fatalf("ClaimForScraping: %v", err)
	}
	if got.ID != second.ID {
		t.Errorf("claimed %q, want the longest-waiting %q (other: %q)", got.ID, second.ID, first.ID)
	}
}
