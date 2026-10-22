package rss

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
)

// fixture reads an offline feed. Tests never contact a network service, so the
// fixtures are the only feeds this package is ever exercised against.
func fixture(t *testing.T, name string) []byte {
	t.Helper()
	body, err := os.ReadFile(filepath.Join("..", "..", "..", "fixtures", name))
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return body
}

// fakeFetcher stands in for the guarded HTTP client and records what it was asked for.
type fakeFetcher struct {
	resp *httpclient.Response
	err  error
	got  httpclient.Request
}

func (f *fakeFetcher) Fetch(_ context.Context, req httpclient.Request) (*httpclient.Response, error) {
	f.got = req
	if f.err != nil {
		return nil, f.err
	}
	return f.resp, nil
}

func bodyFetcher(body []byte) *fakeFetcher {
	return &fakeFetcher{resp: &httpclient.Response{StatusCode: 200, Body: body, FinalURL: "https://news.example.com/feed.xml"}}
}

func source(feedURL string, feedType domain.SourceType) *domain.Source {
	return &domain.Source{FeedURL: feedURL, Type: feedType}
}

func collect(t *testing.T, fetcher Fetcher, maxItems int) Result {
	t.Helper()
	res, err := New(fetcher, maxItems).Collect(t.Context(), source("https://news.example.com/feed.xml", domain.SourceTypeRSS), Validators{})
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}
	return res
}

func TestCollectRSS(t *testing.T) {
	res := collect(t, bodyFetcher(fixture(t, "rss.xml")), 0)

	if res.ItemsFound != 4 {
		t.Errorf("ItemsFound = %d, want 4", res.ItemsFound)
	}
	// The entry with no link and the one with a javascript: link are unusable.
	if len(res.Items) != 2 || res.ItemsSkipped != 2 {
		t.Fatalf("kept %d items and skipped %d, want 2 and 2", len(res.Items), res.ItemsSkipped)
	}

	first := res.Items[0]
	if first.Title != "Metro line extension cleared for Mysuru" {
		t.Errorf("Title = %q", first.Title)
	}
	if first.Link != "https://news.example.com/mysuru/metro-line-extension" {
		t.Errorf("Link = %q", first.Link)
	}
	if first.GUID != "mysuru-daily-10241" {
		t.Errorf("GUID = %q", first.GUID)
	}
	if !strings.Contains(first.Summary, "state cabinet approved") {
		t.Errorf("Summary = %q, want the CDATA content", first.Summary)
	}
	if len(first.Authors) != 1 || first.Authors[0] != "Anita Rao" {
		t.Errorf("Authors = %v, want the dc:creator", first.Authors)
	}
	if first.ImageURL != "https://cdn.example.com/img/metro.jpg" {
		t.Errorf("ImageURL = %q, want the image enclosure", first.ImageURL)
	}
	if first.PublishedAt == nil || first.PublishedAt.UTC().Format("2006-01-02T15:04:05Z") != "2025-08-12T02:45:00Z" {
		t.Errorf("PublishedAt = %v", first.PublishedAt)
	}

	second := res.Items[1]
	if second.Title != "Heavy rain forecast for the district" {
		t.Errorf("Title = %q, want the line breaks collapsed", second.Title)
	}
	// The feed's own <link> is the base a relative entry link resolves against.
	if second.Link != "https://news.example.com/mysuru/heavy-rain-forecast" {
		t.Errorf("Link = %q, want the relative link resolved", second.Link)
	}
	if len(second.Categories) != 1 {
		t.Errorf("Categories = %v, want the case-insensitive duplicate dropped", second.Categories)
	}
}

func TestCollectAtom(t *testing.T) {
	res := collect(t, bodyFetcher(fixture(t, "atom.xml")), 0)

	if res.FeedType != "atom" {
		t.Errorf("FeedType = %q, want atom", res.FeedType)
	}
	if len(res.Items) != 2 {
		t.Fatalf("kept %d items, want 2", len(res.Items))
	}

	first := res.Items[0]
	if first.Link != "https://atom.example.org/2025/08/fishing-ban-lifted" {
		t.Errorf("Link = %q, want the alternate link", first.Link)
	}
	// Atom entries here carry only <updated>, which must stand in as the date.
	if first.PublishedAt == nil || !first.PublishedAt.Equal(*first.UpdatedAt) {
		t.Errorf("PublishedAt = %v, UpdatedAt = %v: want updated used as the fallback", first.PublishedAt, first.UpdatedAt)
	}
	if len(first.Authors) != 1 || first.Authors[0] != "Suhas Kamath" {
		t.Errorf("Authors = %v", first.Authors)
	}
	if strings.Contains(strings.Join(first.Authors, " "), "@") {
		t.Error("an author email must not be collected")
	}
	if res.Items[1].Link != "https://atom.example.org/2025/08/port-record-cargo" {
		t.Errorf("Link = %q, want the relative link resolved", res.Items[1].Link)
	}
}

func TestCollectRDF(t *testing.T) {
	res := collect(t, bodyFetcher(fixture(t, "rdf.xml")), 0)

	if len(res.Items) != 1 {
		t.Fatalf("kept %d items, want 1", len(res.Items))
	}
	if res.Items[0].Link != "https://rdf.example.net/story/water-levels-rise" {
		t.Errorf("Link = %q", res.Items[0].Link)
	}
	if res.Items[0].PublishedAt == nil {
		t.Error("PublishedAt is nil, want the dc:date")
	}
}

func TestCollectRejectsBodiesThatAreNotFeeds(t *testing.T) {
	tests := []struct {
		name string
		body []byte
	}{
		{name: "malformed xml", body: fixture(t, "malformed.xml")},
		{name: "html landing page", body: fixture(t, "not-a-feed.html")},
		{name: "empty body", body: nil},
		{name: "whitespace only", body: []byte("   \n\t ")},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := New(bodyFetcher(tc.body), 0).
				Collect(t.Context(), source("https://news.example.com/feed.xml", domain.SourceTypeRSS), Validators{})
			if !errors.Is(err, ErrParse) {
				t.Fatalf("Collect error = %v, want ErrParse", err)
			}
		})
	}
}

func TestCollectPassesValidatorsThroughAndReportsNotModified(t *testing.T) {
	fetcher := &fakeFetcher{resp: &httpclient.Response{
		StatusCode:   304,
		NotModified:  true,
		ETag:         `"v1"`,
		LastModified: "Tue, 12 Aug 2025 04:00:00 GMT",
	}}

	res, err := New(fetcher, 0).Collect(t.Context(),
		source("https://news.example.com/feed.xml", domain.SourceTypeRSS),
		Validators{ETag: `"v1"`, LastModified: "Tue, 12 Aug 2025 04:00:00 GMT"})
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if fetcher.got.ETag != `"v1"` || fetcher.got.LastModified != "Tue, 12 Aug 2025 04:00:00 GMT" {
		t.Errorf("the fetch was not made conditional: %+v", fetcher.got)
	}
	if !res.NotModified || len(res.Items) != 0 {
		t.Errorf("NotModified = %v with %d items", res.NotModified, len(res.Items))
	}
	if res.Validators.ETag != `"v1"` {
		t.Errorf("Validators = %+v, want the current ones carried forward", res.Validators)
	}
}

func TestCollectCapsItems(t *testing.T) {
	res := collect(t, bodyFetcher(fixture(t, "rss.xml")), 1)

	if len(res.Items) != 1 || !res.Truncated {
		t.Fatalf("kept %d items, Truncated = %v, want 1 and true", len(res.Items), res.Truncated)
	}
	if res.ItemsFound != 4 {
		t.Errorf("ItemsFound = %d: the cap must not hide how many the feed published", res.ItemsFound)
	}
}

func TestCollectReturnsTheFetchError(t *testing.T) {
	fetcher := &fakeFetcher{err: httpclient.ErrBlockedAddress}

	_, err := New(fetcher, 0).Collect(t.Context(), source("http://169.254.169.254/feed.xml", domain.SourceTypeRSS), Validators{})
	if !errors.Is(err, httpclient.ErrBlockedAddress) {
		t.Fatalf("Collect error = %v, want the fetch error unchanged", err)
	}
}
