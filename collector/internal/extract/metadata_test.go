package extract

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
)

// TestParsePageDateRequiresTimezone rejects ambiguous dates rather than silently assigning UTC.
func TestParsePageDateRequiresTimezone(t *testing.T) {
	for _, value := range []string{"2026-08-31T09:15:00", "2026-08-31 09:15:00", "2026-08-31", "", "invalid"} {
		t.Run(value, func(t *testing.T) {
			if got := parsePageDate(value); got != nil {
				t.Errorf("parsePageDate(%q) = %v, want nil", value, got)
			}
		})
	}
	want := time.Date(2026, 8, 31, 3, 45, 0, 0, time.UTC)
	if got := parsePageDate(" 2026-08-31T09:15:00+05:30 "); got == nil || !got.Equal(want) {
		t.Errorf("explicit offset = %v, want %v", got, want)
	}
}

// TestExtractSyntheticArticles exercises real extractors without redistributing publisher content.
func TestExtractSyntheticArticles(t *testing.T) {
	body := strings.Repeat("Engineers measured reservoir levels, checked every sensor, and published the readings for residents. ", 30)
	for _, structured := range []bool{false, true} {
		name := "html"
		pageBody := body
		script := ""
		if structured {
			name = "structured"
			pageBody = "A short teaser."
			script = `<script type="application/ld+json">{"@type":"NewsArticle","articleBody":"` + body + `"}</script>`
		}
		t.Run(name, func(t *testing.T) {
			page := []byte(`<html><head><title>Reservoir monitoring report</title>` + script +
				`</head><body><article><h1>Reservoir monitoring report</h1><p>` + pageBody + `</p></article></body></html>`)
			got, err := New(150).Extract(page, "text/html", mustURL(t, "https://example.com/news/story"))
			if err != nil || got.Words() < 150 || !strings.Contains(got.Text, "Engineers measured reservoir levels") {
				t.Fatalf("synthetic extraction = %d words by %q, %v", got.Words(), got.By, err)
			}
			if structured && got.By != "json-ld" {
				t.Errorf("long structured body lost to shorter extractor %q", got.By)
			}
		})
	}
}

// TestExtractShortPageRetainsMetadata keeps validated metadata but still rejects insufficient body text.
func TestExtractShortPageRetainsMetadata(t *testing.T) {
	page := []byte(`<html><head>
		<meta property="article:published_time" content="2026-08-31T09:15:00+05:30">
		<meta property="og:image" content="/image.jpg">
		</head><body><article><p>A short teaser.</p></article></body></html>`)
	got, err := New(150).Extract(page, "text/html", mustURL(t, "https://example.com/story"))
	if !errors.Is(err, domain.ErrExtractionEmpty) || got.PublishedAt == nil ||
		got.ImageURL != "https://example.com/image.jpg" {
		t.Fatalf("short-page extraction = %+v, %v", got, err)
	}
}
