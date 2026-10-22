// Package extract turns an article page into plain text.
//
// It runs several independent extractors and keeps the longest result rather
// than taking the first that returns anything, because no single one wins on
// every publisher. Measured on real pages: The Hindu embeds no structured data
// at all, so only the readability-style extractors find its 231-word story;
// Deccan Herald renders its body client-side, so those two return 48 words of
// navigation furniture while its JSON-LD holds all 1189. First-non-empty would
// silently take the wrong answer for one of them whichever order it tried.
package extract

import (
	"bytes"
	"fmt"
	"net/url"

	"golang.org/x/net/html/charset"

	"github.com/riaz/newscollector/internal/domain"
)

// Result is one extractor's reading of a page.
type Result struct {
	// Text is the article body as plain text, boilerplate removed.
	Text string

	// Title is the headline the extractor found, which may be empty. The feed
	// already supplied one, so this is only a cross-check.
	Title string

	// By names the extractor whose reading was kept. It is worth recording:
	// when a publisher changes its markup, which extractor stopped winning is
	// the first useful clue.
	By string
}

// Words reports the length of the extracted body.
func (r Result) Words() int { return domain.WordCount(r.Text) }

// Extractor reads an article body out of a parsed page. Implementations are
// expected to fail quietly — an extractor that finds nothing returns an empty
// Result, not an error, because the others may still succeed.
type Extractor interface {
	Name() string
	Extract(page []byte, base *url.URL) Result
}

// Chain runs every extractor and keeps the longest body.
type Chain struct {
	extractors []Extractor
	minWords   int
}

// New returns the default chain: structured data first, then the two
// readability-style libraries. The order is presentational only — every
// extractor runs and the longest result wins.
func New(minWords int) *Chain {
	if minWords <= 0 {
		minWords = domain.MinScrapedWords
	}
	return &Chain{
		extractors: []Extractor{JSONLD{}, Trafilatura{}, Readability{}},
		minWords:   minWords,
	}
}

// Extract reads the article out of page.
//
// contentType is the response header, used to decode the bytes before any
// extractor sees them. It is worth doing properly: the Times of India serves
// "text/html" with no charset at all, and a page mis-decoded here becomes
// mojibake in the training set rather than an obvious failure.
//
// It returns domain.ErrExtractionEmpty when nothing usable was found, which is
// how a bot-check page and a client-rendered page both end up reported rather
// than stored.
func (c *Chain) Extract(page []byte, contentType string, base *url.URL) (Result, error) {
	decoded, err := decodeCharset(page, contentType)
	if err != nil {
		return Result{}, fmt.Errorf("extract: decode page: %w", err)
	}

	var best Result
	for _, e := range c.extractors {
		got := e.Extract(decoded, base)
		got.Text = Clean(got.Text)
		got.By = e.Name()

		if got.Words() > best.Words() {
			best = got
		}
	}

	if best.Words() < c.minWords {
		return Result{}, fmt.Errorf("%w: best was %d words from %q",
			domain.ErrExtractionEmpty, best.Words(), best.By)
	}
	return best, nil
}

// decodeCharset converts a page to UTF-8, honouring the response's declared
// encoding and the document's own meta tag.
func decodeCharset(page []byte, contentType string) ([]byte, error) {
	r, err := charset.NewReader(bytes.NewReader(page), contentType)
	if err != nil {
		// An unknown encoding is not fatal: the bytes are more likely to be
		// UTF-8 already than to be unreadable.
		return page, nil
	}
	return readAll(r)
}
