package extract

import (
	"bytes"
	"net/url"
	"strings"

	readability "codeberg.org/readeck/go-readability/v2"
	"github.com/markusmobius/go-trafilatura"
)

// Trafilatura wraps the Go port of the trafilatura extractor. It is the
// strongest general-purpose reader of the three on pages that serve their body
// in the markup.
type Trafilatura struct{}

func (Trafilatura) Name() string { return "trafilatura" }

func (Trafilatura) Extract(page []byte, base *url.URL) Result {
	res, err := trafilatura.Extract(bytes.NewReader(page), trafilatura.Options{
		OriginalURL:     base,
		IncludeImages:   false,
		IncludeLinks:    false,
		ExcludeComments: true,
		EnableFallback:  true,
		Focus:           trafilatura.Balanced,
	})
	if err != nil || res == nil {
		return Result{}
	}
	return Result{Text: res.ContentText, Title: res.Metadata.Title}
}

// Readability wraps the Go port of the algorithm behind Firefox's reader view.
// It disagrees with trafilatura often enough to be worth running: on The Hindu
// it recovers a little more of the story, and where one library is tripped by a
// page's markup the other frequently is not.
type Readability struct{}

func (Readability) Name() string { return "readability" }

func (Readability) Extract(page []byte, base *url.URL) Result {
	article, err := readability.FromReader(bytes.NewReader(page), base)
	if err != nil {
		return Result{}
	}

	var text strings.Builder
	if err := article.RenderText(&text); err != nil {
		return Result{}
	}
	return Result{Text: text.String(), Title: article.Title()}
}
