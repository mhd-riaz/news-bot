package domain

import (
	"strings"
	"testing"
	"time"
)

// words builds a body of exactly n words. Extraction quality is judged in words,
// so the fixtures are sized in words rather than bytes.
func words(n int) string {
	return strings.TrimSpace(strings.Repeat("lake ", n))
}

// The word counts below are measured, not invented: they come from fetching one
// real article from each publisher and running both extractors over it. They are
// pinned here so a change to the thresholds has to face the evidence.
const (
	deccanFeedWords    = 1189 // feed ships the whole story
	deccanScrapedWords = 48   // ...but the page renders its body client-side
	mitReviewFeedWords = 1534
	registerFeedWords  = 662
	ndtvFeedWords      = 26 // content is the summary, repeated
	guardianFeedWords  = 96
	hinduScrapedWords  = 231
	toiScrapedWords    = 439
	vergeScrapedWords  = 395
	vergeFeedWords     = 139
)

func TestNeedsScrape(t *testing.T) {
	tests := []struct {
		name    string
		article Article
		want    bool
	}{
		{
			// The case that matters most: Deccan Herald publishes the article in
			// the feed, so fetching the page again would only risk replacing it.
			name:    "deccan herald ships full text in the feed",
			article: Article{Content: words(deccanFeedWords), Summary: words(300)},
			want:    false,
		},
		{
			name:    "mit technology review ships full text",
			article: Article{Content: words(mitReviewFeedWords), Summary: words(40)},
			want:    false,
		},
		{
			name:    "the register ships full text",
			article: Article{Content: words(registerFeedWords), Summary: words(40)},
			want:    false,
		},
		{
			name:    "times of india sends no body at all",
			article: Article{Content: "", Summary: ""},
			want:    true,
		},
		{
			name:    "the hindu sends a one-sentence teaser",
			article: Article{Content: "", Summary: words(30)},
			want:    true,
		},
		{
			name: "ndtv repeats the summary as the content",
			article: Article{
				Content: words(ndtvFeedWords),
				Summary: words(ndtvFeedWords),
			},
			want: true,
		},
		{
			name: "content that merely restates the summary with different spacing",
			article: Article{
				Content: "PM  launched   the commemoration.",
				Summary: "PM launched the commemoration.",
			},
			want: true,
		},
		{
			// The page holds 427 words; the feed sent 96. Fetching is worth it,
			// and BetterContent is what makes a wrong guess harmless.
			name:    "the guardian sends a dek worth improving on",
			article: Article{Content: words(guardianFeedWords), Summary: words(20)},
			want:    true,
		},
		{
			name:    "the verge sends an excerpt worth improving on",
			article: Article{Content: words(vergeFeedWords), Summary: words(20)},
			want:    true,
		},
		{
			name:    "one word short of the threshold is scraped",
			article: Article{Content: words(FullTextWords - 1)},
			want:    true,
		},
		{
			name:    "exactly the threshold is kept",
			article: Article{Content: words(FullTextWords)},
			want:    false,
		},
		{
			name:    "nil article is never scraped",
			article: Article{},
			want:    true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			a := tt.article
			if got := NeedsScrape(&a); got != tt.want {
				t.Errorf("NeedsScrape() = %v, want %v (content=%d words, summary=%d words)",
					got, tt.want, WordCount(a.Content), WordCount(a.Summary))
			}
		})
	}

	if NeedsScrape(nil) {
		t.Error("NeedsScrape(nil) = true, want false")
	}
}

func TestBetterContentRefusesToRegress(t *testing.T) {
	tests := []struct {
		name                string
		existing, candidate string
		want                bool
	}{
		{
			// Deccan Herald again: the page yields 48 words of navigation
			// furniture. Overwriting 1189 good words with that is the one
			// outcome enrichment must never produce.
			name:      "client-rendered page must not replace a full feed article",
			existing:  words(deccanFeedWords),
			candidate: words(deccanScrapedWords),
			want:      false,
		},
		{
			name:      "the hindu article replaces an empty body",
			existing:  "",
			candidate: words(hinduScrapedWords),
			want:      true,
		},
		{
			name:      "times of india article replaces an empty body",
			existing:  "",
			candidate: words(toiScrapedWords),
			want:      true,
		},
		{
			name:      "the verge article replaces the shorter feed excerpt",
			existing:  words(vergeFeedWords),
			candidate: words(vergeScrapedWords),
			want:      true,
		},
		{
			name:      "a bot-check page is too short to be an article",
			existing:  "",
			candidate: words(MinScrapedWords - 1),
			want:      false,
		},
		{
			name:      "identical text is not an improvement",
			existing:  words(200),
			candidate: words(200),
			want:      false,
		},
		{
			name:      "an empty extraction never wins",
			existing:  words(200),
			candidate: "",
			want:      false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := BetterContent(tt.existing, tt.candidate); got != tt.want {
				t.Errorf("BetterContent(%d words, %d words) = %v, want %v",
					WordCount(tt.existing), WordCount(tt.candidate), got, tt.want)
			}
		})
	}
}

func TestScrapeStatusRetryable(t *testing.T) {
	retryable := []ScrapeStatus{
		ScrapeStatusPending, ScrapeStatusFetchFailed, ScrapeStatusExtractFailed,
	}
	terminal := []ScrapeStatus{
		ScrapeStatusNotNeeded, ScrapeStatusSuccess, ScrapeStatusNoNewContent,
		ScrapeStatusRobotsDisallowed, ScrapeStatusBlocked, ScrapeStatusGone,
		ScrapeStatusFailed,
	}

	for _, s := range retryable {
		if !s.Retryable() {
			t.Errorf("%s.Retryable() = false, want true", s)
		}
	}
	for _, s := range terminal {
		if s.Retryable() {
			t.Errorf("%s.Retryable() = true, want false: a run would fetch it forever", s)
		}
	}
}

func TestScrapeStatusHasFullText(t *testing.T) {
	// This is the filter a consumer uses to ask for article bodies, so it must
	// admit the feeds that never needed a fetch as well as the ones that got one.
	for _, s := range []ScrapeStatus{ScrapeStatusSuccess, ScrapeStatusNotNeeded} {
		if !s.HasFullText() {
			t.Errorf("%s.HasFullText() = false, want true", s)
		}
	}
	for _, s := range []ScrapeStatus{
		ScrapeStatusPending, ScrapeStatusBlocked, ScrapeStatusFailed,
		ScrapeStatusNoNewContent, ScrapeStatusRobotsDisallowed,
	} {
		if s.HasFullText() {
			t.Errorf("%s.HasFullText() = true, want false", s)
		}
	}
}

func TestScrapeStatusValid(t *testing.T) {
	if ScrapeStatus("nonsense").Valid() {
		t.Error("an unknown status reported itself valid")
	}
	if !ScrapeStatusSuccess.Valid() {
		t.Error("success reported itself invalid")
	}
}

func TestScrapeBackoffDoublesAndCaps(t *testing.T) {
	base := 15 * time.Minute
	tests := []struct {
		attempts int
		want     time.Duration
	}{
		{0, base},
		{1, base},
		{2, 30 * time.Minute},
		{3, 60 * time.Minute},
		{4, 2 * time.Hour},
		{9, MaxScrapeBackoff},
	}
	for _, tt := range tests {
		if got := ScrapeBackoff(base, tt.attempts); got != tt.want {
			t.Errorf("ScrapeBackoff(%s, %d) = %s, want %s", base, tt.attempts, got, tt.want)
		}
	}

	if got := ScrapeBackoff(0, 1); got != DefaultScrapeRetryBase {
		t.Errorf("ScrapeBackoff with no base = %s, want the default %s", got, DefaultScrapeRetryBase)
	}
}

func TestNewArticleMarksFullTextFeedsAsEnriched(t *testing.T) {
	// A feed that ships the whole story is finished the moment it is collected:
	// it must not join the scrape backlog.
	body := "<p>" + words(deccanFeedWords) + "</p>"
	a := newTestArticle(t, func(i *FeedItem) { i.Content = body })

	if a.ScrapeStatus != ScrapeStatusNotNeeded {
		t.Errorf("ScrapeStatus = %q, want %q", a.ScrapeStatus, ScrapeStatusNotNeeded)
	}
	if a.ProcessingStatus != ProcessingStatusEnriched {
		t.Errorf("ProcessingStatus = %q, want %q", a.ProcessingStatus, ProcessingStatusEnriched)
	}
	if a.NextScrapeAt != nil {
		t.Errorf("NextScrapeAt = %v, want nil: the article is not in the backlog", a.NextScrapeAt)
	}
	if !a.ScrapeStatus.HasFullText() {
		t.Error("HasFullText() = false, want true for a full-text feed")
	}
}

func TestNewArticleQueuesTeaserFeedsForScraping(t *testing.T) {
	a := newTestArticle(t, func(i *FeedItem) {
		i.Content = ""
		i.Summary = "<p>The five injured persons were reported to be in stable condition.</p>"
	})

	if a.ScrapeStatus != ScrapeStatusPending {
		t.Errorf("ScrapeStatus = %q, want %q", a.ScrapeStatus, ScrapeStatusPending)
	}
	if a.ProcessingStatus != ProcessingStatusCollected {
		t.Errorf("ProcessingStatus = %q, want %q until the text is fetched",
			a.ProcessingStatus, ProcessingStatusCollected)
	}
	if a.NextScrapeAt == nil || !a.NextScrapeAt.Equal(a.CollectedAt) {
		t.Errorf("NextScrapeAt = %v, want the collection time so it is due at once", a.NextScrapeAt)
	}
	if a.ScrapeAttempts != 0 {
		t.Errorf("ScrapeAttempts = %d, want 0", a.ScrapeAttempts)
	}
}

func TestNewArticleFreezesContentHashAgainstTheFeedText(t *testing.T) {
	// ContentHash is a deduplication key. Enrichment replaces Content later, and
	// the hash must not follow it: a re-derived hash would stop an already
	// stored article matching itself.
	a := newTestArticle(t)
	before := a.ContentHash

	a.Content = words(hinduScrapedWords)
	a.ScrapeStatus = ScrapeStatusSuccess
	a.Normalize()

	if a.ContentHash != before {
		t.Errorf("ContentHash changed after enrichment: %q -> %q", before, a.ContentHash)
	}
}
