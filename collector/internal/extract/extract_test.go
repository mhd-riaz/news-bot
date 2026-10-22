package extract

import (
	"compress/gzip"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/riaz/newscollector/internal/domain"
)

// loadFixture reads one of the real article pages saved from the publishers.
// They are stored gzipped: the Deccan Herald page alone is 1.4 MB of markup.
func loadFixture(t *testing.T, name string) []byte {
	t.Helper()

	f, err := os.Open(filepath.Join("..", "..", "fixtures", "articles", name+".html.gz"))
	if err != nil {
		t.Fatalf("open fixture: %v", err)
	}
	defer f.Close()

	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatalf("gunzip fixture: %v", err)
	}
	defer gz.Close()

	body, err := readAll(gz)
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	return body
}

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	return u
}

// The word counts are measured from these exact fixtures. The bounds are loose
// because a library upgrade may legitimately shift a count by a few words; they
// are tight enough to catch an extractor that has stopped working.
func TestExtractRecoversTheStoryFromRealPages(t *testing.T) {
	tests := []struct {
		fixture  string
		pageURL  string
		minWords int
		wantBy   string
		contains string
	}{
		{
			// The Hindu embeds no structured data at all, so this page proves
			// the readability-style extractors carry the chain on their own.
			fixture:  "thehindu",
			pageURL:  "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
			minWords: 180,
			wantBy:   "readability",
			contains: "Ganesh",
		},
		{
			// Deccan Herald renders its body in the browser. Only the
			// structured data holds the story, and it holds all of it.
			fixture:  "deccanherald",
			pageURL:  "https://www.deccanherald.com/india/karnataka/bengaluru/130-lakes-4120304",
			minWords: 900,
			wantBy:   "json-ld",
			contains: "Pollution Control Board",
		},
		{
			// The Times of India sends no body in its feed at all, so every
			// word here is one the enrichment stage adds.
			fixture:  "timesofindia",
			pageURL:  "https://timesofindia.indiatimes.com/india/kerala-wakf-board/articleshow/133433996.cms",
			minWords: 350,
			contains: "Wakf",
		},
	}

	c := New(domain.MinScrapedWords)
	for _, tt := range tests {
		t.Run(tt.fixture, func(t *testing.T) {
			got, err := c.Extract(loadFixture(t, tt.fixture), "text/html", mustURL(t, tt.pageURL))
			if err != nil {
				t.Fatalf("Extract: %v", err)
			}
			if got.Words() < tt.minWords {
				t.Errorf("extracted %d words via %q, want at least %d",
					got.Words(), got.By, tt.minWords)
			}
			if !strings.Contains(got.Text, tt.contains) {
				t.Errorf("extracted text via %q does not mention %q", got.By, tt.contains)
			}
			if tt.wantBy != "" && got.By != tt.wantBy {
				t.Errorf("winner = %q, want %q (this publisher's page defeats the others)",
					got.By, tt.wantBy)
			}
		})
	}
}

func TestExtractRejectsABotWall(t *testing.T) {
	// Ars Technica answers 202 with a JavaScript challenge instead of the
	// article. It must be reported, not stored: the challenge text is short,
	// plausible prose, and would otherwise sit in the training set as an article.
	c := New(domain.MinScrapedWords)

	_, err := c.Extract(
		loadFixture(t, "arstechnica-botwall"),
		"text/html",
		mustURL(t, "https://arstechnica.com/science/2026/08/memories/"),
	)
	if !errors.Is(err, domain.ErrExtractionEmpty) {
		t.Errorf("err = %v, want ErrExtractionEmpty", err)
	}
}

func TestExtractPrefersTheLongestReading(t *testing.T) {
	// Every extractor runs and the longest body wins. Taking the first
	// non-empty answer instead would return whichever of these came first.
	deccan := loadFixture(t, "deccanherald")
	base := mustURL(t, "https://www.deccanherald.com/story")

	structured := Result{Text: Clean(JSONLD{}.Extract(deccan, base).Text)}
	traf := Result{Text: Clean(Trafilatura{}.Extract(deccan, base).Text)}
	read := Result{Text: Clean(Readability{}.Extract(deccan, base).Text)}

	if structured.Words() <= traf.Words() || structured.Words() <= read.Words() {
		t.Fatalf("fixture no longer discriminates: json-ld=%d trafilatura=%d readability=%d",
			structured.Words(), traf.Words(), read.Words())
	}

	got, err := New(domain.MinScrapedWords).Extract(deccan, "text/html", base)
	if err != nil {
		t.Fatalf("Extract: %v", err)
	}
	if got.Words() != structured.Words() {
		t.Errorf("chain kept %d words, want the longest reading of %d",
			got.Words(), structured.Words())
	}
}

func TestCleanUnescapesMarkupCarriedInsideStructuredData(t *testing.T) {
	// Structured data holds the body as an escaped HTML string, so the text
	// arrives looking like this and has to survive two rounds of decoding.
	in := `&lt;p&gt;Every month, the &lt;a href="/tags/kspcb"&gt;Board&lt;/a&gt; tests water quality.&lt;/p&gt;`

	got := Clean(in)
	if strings.ContainsAny(got, "<>") {
		t.Errorf("Clean left markup behind: %q", got)
	}
	if !strings.Contains(got, "Board tests water quality") {
		t.Errorf("Clean = %q, want the sentence intact", got)
	}
}

func TestCleanSeparatesBlockElements(t *testing.T) {
	// Without this, the last word of one paragraph and the first of the next
	// are stored as a single token.
	got := Clean("<p>uploaded on the website.</p><p>A bench of the court said</p>")
	if strings.Contains(got, "website.A") {
		t.Errorf("Clean ran two paragraphs together: %q", got)
	}
}

func TestCleanDropsScriptAndStyleContent(t *testing.T) {
	got := Clean(`<div><script>var x = "tracking";</script><style>.a{color:red}</style><p>The story.</p></div>`)
	if strings.Contains(got, "tracking") || strings.Contains(got, "color:red") {
		t.Errorf("Clean kept code in the article body: %q", got)
	}
	if !strings.Contains(got, "The story.") {
		t.Errorf("Clean = %q, want the story kept", got)
	}
}

func TestCleanRemovesPageFurniture(t *testing.T) {
	tests := []struct {
		name, in, unwanted string
	}{
		{"advertisement", "The story. ADVERTISEMENT More story.", "ADVERTISEMENT"},
		{"publication stamp", "The story. Published - August 23, 2026 09:22 am IST", "Published -"},
		{"photo credit", "The story. | Photo Credit: AP", "Photo Credit"},
		{"app promo", "The story. Download the TOI app.", "Download the"},
		{"social prompt", "The story. Follow us on WhatsApp", "Follow us on"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Clean(tt.in)
			if strings.Contains(got, tt.unwanted) {
				t.Errorf("Clean = %q, still contains %q", got, tt.unwanted)
			}
			if !strings.Contains(got, "The story.") {
				t.Errorf("Clean = %q, want the story kept", got)
			}
		})
	}
}

func TestCleanNormalisesSpacing(t *testing.T) {
	got := Clean("  The   story\n\n\n\nwent   on.  ")
	if got != "The story\nwent on." {
		t.Errorf("Clean = %q", got)
	}
}

func TestDecodeCharsetHandlesADeclaredEncoding(t *testing.T) {
	// The Times of India sends "text/html" with no charset, so the document's
	// own meta tag is the only declaration there is.
	page := []byte(`<html><head><meta charset="utf-8"></head><body><p>Kerala Wakf Board — 40,000 properties</p></body></html>`)

	got, err := decodeCharset(page, "text/html")
	if err != nil {
		t.Fatalf("decodeCharset: %v", err)
	}
	if !strings.Contains(string(got), "—") {
		t.Errorf("em dash did not survive decoding: %q", got)
	}
}

func TestExtractorsReturnEmptyRatherThanFailing(t *testing.T) {
	// One extractor giving up must not stop the others being consulted.
	junk := []byte("not markup at all")
	base := mustURL(t, "https://example.com/story")

	for _, e := range []Extractor{JSONLD{}, Trafilatura{}, Readability{}} {
		if got := e.Extract(junk, base); got.Words() > 5 {
			t.Errorf("%s invented %d words from junk", e.Name(), got.Words())
		}
	}
}
