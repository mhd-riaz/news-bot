package domain

import (
	"errors"
	"strings"
	"testing"
	"time"
)

var collectedAt = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func testSource() Source {
	return Source{
		ID:       "018f3f7e-1c2a-7f24-9a3f-8f9f2a0a5c11",
		Name:     "Mysuru Daily",
		FeedURL:  "https://news.example.com/feed.xml",
		Type:     SourceTypeRSS,
		Language: "en",
		Country:  "IN",
		State:    "Karnataka",
		City:     "Mysuru",
	}
}

func testItem(mutate ...func(*FeedItem)) FeedItem {
	published := time.Date(2026, 8, 22, 8, 0, 0, 0, time.UTC)
	item := FeedItem{
		Title:       "Metro line extension cleared",
		Link:        "https://news.example.com/mysuru/metro",
		GUID:        "mysuru-daily-10241",
		Summary:     "<p>The cabinet approved it.</p>",
		Content:     "<p>The cabinet approved the extension on <b>Monday</b>.</p>",
		Authors:     []string{"Anita Rao"},
		Categories:  []string{"Transport"},
		PublishedAt: &published,
	}
	for _, m := range mutate {
		m(&item)
	}
	return item
}

func newTestArticle(t *testing.T, mutate ...func(*FeedItem)) *Article {
	t.Helper()
	a, err := NewArticle(testSource(), testItem(mutate...), collectedAt)
	if err != nil {
		t.Fatalf("NewArticle: %v", err)
	}
	return a
}

func TestNewArticleCarriesTheSourceRegion(t *testing.T) {
	a := newTestArticle(t)

	if a.SourceID != testSource().ID || a.SourceName != "Mysuru Daily" {
		t.Errorf("source attribution = %q / %q", a.SourceID, a.SourceName)
	}
	if a.Language != "en" || a.Country != "IN" || a.State != "Karnataka" || a.City != "Mysuru" {
		t.Errorf("region = %q/%q/%q/%q, want the source's", a.Language, a.Country, a.State, a.City)
	}
	if a.ProcessingStatus != ProcessingStatusCollected {
		t.Errorf("ProcessingStatus = %q", a.ProcessingStatus)
	}
	if !a.CollectedAt.Equal(collectedAt) {
		t.Errorf("CollectedAt = %s, want the injected time", a.CollectedAt)
	}
	if a.ClassificationStatus != ClassificationStatusPending {
		t.Errorf("ClassificationStatus = %q, want pending", a.ClassificationStatus)
	}
}

func TestNewArticleStripsMarkup(t *testing.T) {
	a := newTestArticle(t)

	if !strings.Contains(a.Content, "The cabinet approved the extension on Monday") {
		t.Errorf("Content = %q, want the text with its tags removed", a.Content)
	}
	if strings.ContainsAny(a.Content+a.Summary, "<>") {
		t.Errorf("markup survived: summary %q, content %q", a.Summary, a.Content)
	}
}

func TestNewArticleFallsBackToTheContentForASummary(t *testing.T) {
	a := newTestArticle(t, func(i *FeedItem) { i.Summary = "" })

	if a.Summary == "" || !strings.Contains(a.Summary, "cabinet approved") {
		t.Errorf("Summary = %q, want a fallback drawn from the content", a.Summary)
	}
}

func TestNewArticlePublicationTime(t *testing.T) {
	future := collectedAt.Add(48 * time.Hour)
	slightlyAhead := collectedAt.Add(10 * time.Minute)

	tests := []struct {
		name      string
		published *time.Time
		want      time.Time
	}{
		{name: "absent", published: nil, want: collectedAt},
		{name: "zero", published: &time.Time{}, want: collectedAt},
		{name: "far future", published: &future, want: collectedAt},
		{name: "within the clock skew", published: &slightlyAhead, want: slightlyAhead},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestArticle(t, func(i *FeedItem) { i.PublishedAt = tc.published })
			if !a.PublishedAt.Equal(tc.want) {
				t.Errorf("PublishedAt = %s, want %s", a.PublishedAt, tc.want)
			}
		})
	}
}

func TestNewArticleRejectsAnUnusableItem(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*FeedItem)
	}{
		{name: "no link", mutate: func(i *FeedItem) { i.Link = "" }},
		{name: "unusable link", mutate: func(i *FeedItem) { i.Link = "javascript:alert(1)" }},
		{name: "no title", mutate: func(i *FeedItem) { i.Title = "  " }},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewArticle(testSource(), testItem(tc.mutate), collectedAt)
			if err == nil {
				t.Fatal("expected a validation error")
			}
			if !errors.Is(err, ErrValidation) {
				t.Errorf("error = %v, want it to wrap ErrValidation", err)
			}
		})
	}
}

func TestArticleClassificationValidation(t *testing.T) {
	classifiedAt := collectedAt.Add(time.Minute)
	valid := newTestArticle(t)
	valid.ClassificationStatus = ClassificationStatusClassified
	valid.ClassifiedAt = &classifiedAt
	valid.Topic = "Politics"
	valid.Confidence = 0.8
	valid.ModelVersion = "v2-001"
	valid.Normalize()
	if err := valid.Validate(); err != nil {
		t.Fatalf("classified article validation: %v", err)
	}
	if valid.Topic != "politics" {
		t.Errorf("Topic = %q, want politics", valid.Topic)
	}

	invalid := newTestArticle(t)
	invalid.ClassificationStatus = ClassificationStatusUnsorted
	invalid.Topic = "politics"
	if err := invalid.Validate(); err == nil {
		t.Fatal("expected invalid unsorted classification")
	}
}

func TestArticleIdentity(t *testing.T) {
	permalink := newTestArticle(t, func(i *FeedItem) { i.GUID = "https://news.example.com/mysuru/metro?utm_source=x" })

	if permalink.CanonicalURL != "https://news.example.com/mysuru/metro" {
		t.Errorf("CanonicalURL = %q, want the URL-shaped GUID normalised", permalink.CanonicalURL)
	}

	opaque := newTestArticle(t)
	if opaque.CanonicalURL != "" {
		t.Errorf("CanonicalURL = %q, want empty for an opaque GUID", opaque.CanonicalURL)
	}
	if opaque.FeedGUID != "mysuru-daily-10241" {
		t.Errorf("FeedGUID = %q", opaque.FeedGUID)
	}

	// A permalink is the stronger identity, so it decides the dedup key: the
	// same article served under two links still collapses to one.
	other := newTestArticle(t, func(i *FeedItem) {
		i.Link = "https://news.example.com/mysuru/metro-line-extension"
		i.GUID = "https://news.example.com/mysuru/metro?utm_source=x"
	})
	if other.DedupID != permalink.DedupID {
		t.Error("two links sharing a permalink must share a dedup id")
	}
	if other.NormalizedURL == permalink.NormalizedURL {
		t.Error("the test articles should differ by link")
	}
}

func TestDedupIDFallsBackToTheLink(t *testing.T) {
	a := newTestArticle(t)
	b := newTestArticle(t, func(i *FeedItem) { i.Link = a.URL + "?utm_campaign=newsletter" })

	if a.DedupID != b.DedupID {
		t.Error("links differing only by a tracking parameter must share a dedup id")
	}
}

func TestContentHashIgnoresCaseAndWhitespace(t *testing.T) {
	a := newTestArticle(t)
	b := newTestArticle(t, func(i *FeedItem) {
		i.Title = "METRO   LINE\nEXTENSION cleared"
		i.Link = "https://news.example.com/other"
	})

	if a.ContentHash != b.ContentHash {
		t.Error("a re-cased, re-wrapped title must hash the same")
	}

	c := newTestArticle(t, func(i *FeedItem) { i.Title = "A different headline entirely" })
	if a.ContentHash == c.ContentHash {
		t.Error("different text must hash differently")
	}
}

func TestNormalizeURL(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{name: "already canonical", raw: "https://news.example.com/a", want: "https://news.example.com/a"},
		{name: "upper-case host", raw: "HTTPS://News.Example.COM/a", want: "https://news.example.com/a"},
		{name: "www prefix", raw: "https://www.news.example.com/a", want: "https://news.example.com/a"},
		{name: "default port", raw: "https://news.example.com:443/a", want: "https://news.example.com/a"},
		{name: "non-default port kept", raw: "https://news.example.com:8443/a", want: "https://news.example.com:8443/a"},
		{name: "fragment", raw: "https://news.example.com/a#section", want: "https://news.example.com/a"},
		{name: "trailing slash", raw: "https://news.example.com/a/", want: "https://news.example.com/a"},
		{name: "root path kept", raw: "https://news.example.com/", want: "https://news.example.com/"},
		{
			name: "tracking parameters",
			raw:  "https://news.example.com/a?utm_source=twitter&utm_medium=social&id=7&fbclid=xyz",
			want: "https://news.example.com/a?id=7",
		},
		{
			name: "query order",
			raw:  "https://news.example.com/a?b=2&a=1",
			want: "https://news.example.com/a?a=1&b=2",
		},
		{
			name: "only tracking parameters",
			raw:  "https://news.example.com/a?utm_source=twitter",
			want: "https://news.example.com/a",
		},
		{name: "credentials dropped", raw: "https://u:p@news.example.com/a", want: "https://news.example.com/a"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := NormalizeURL(tc.raw); got != tc.want {
				t.Errorf("NormalizeURL(%q) = %q, want %q", tc.raw, got, tc.want)
			}
		})
	}
}

func TestPlainText(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{name: "tags become word boundaries", raw: "<p>one</p><p>two</p>", want: "one two"},
		{name: "entities are decoded", raw: "Rain &amp; wind", want: "Rain & wind"},
		{name: "escaped markup stays text", raw: "&lt;script&gt;alert(1)&lt;/script&gt;", want: "<script>alert(1)</script>"},
		{name: "a bare less-than is text", raw: "5 < 6 is true", want: "5 < 6 is true"},
		{name: "attributes go with the tag", raw: `<a href="https://x/">link</a>`, want: "link"},
		{name: "whitespace collapses", raw: "  a\n\n\tb  ", want: "a b"},
		{name: "empty", raw: "", want: ""},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := plainText(tc.raw); got != tc.want {
				t.Errorf("plainText(%q) = %q, want %q", tc.raw, got, tc.want)
			}
		})
	}
}

func TestArticleValidate(t *testing.T) {
	tests := []struct {
		name      string
		mutate    func(*Article)
		wantField string
	}{
		{name: "valid", mutate: func(*Article) {}},
		{name: "bad id", mutate: func(a *Article) { a.ID = "not-a-uuid" }, wantField: "id"},
		{name: "bad source id", mutate: func(a *Article) { a.SourceID = "17" }, wantField: "source_id"},
		{name: "no title", mutate: func(a *Article) { a.Title = "" }, wantField: "title"},
		{name: "no url", mutate: func(a *Article) { a.URL = "" }, wantField: "url"},
		{name: "no normalized url", mutate: func(a *Article) { a.NormalizedURL = "" }, wantField: "normalized_url"},
		{name: "no dedup id", mutate: func(a *Article) { a.DedupID = "" }, wantField: "dedup_id"},
		{name: "no content hash", mutate: func(a *Article) { a.ContentHash = "" }, wantField: "content_hash"},
		{name: "bad language", mutate: func(a *Article) { a.Language = "eng" }, wantField: "language"},
		{name: "bad country", mutate: func(a *Article) { a.Country = "IND" }, wantField: "country"},
		{name: "zero published", mutate: func(a *Article) { a.PublishedAt = time.Time{} }, wantField: "published_at"},
		{name: "zero collected", mutate: func(a *Article) { a.CollectedAt = time.Time{} }, wantField: "collected_at"},
		{name: "unknown status", mutate: func(a *Article) { a.ProcessingStatus = "done" }, wantField: "processing_status"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestArticle(t)
			tc.mutate(a)

			err := a.Validate()
			if tc.wantField == "" {
				if err != nil {
					t.Fatalf("Validate = %v, want no error", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tc.wantField) {
				t.Fatalf("Validate = %v, want a %s violation", err, tc.wantField)
			}
		})
	}
}
