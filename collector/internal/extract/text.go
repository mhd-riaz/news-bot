package extract

import (
	"bytes"
	"io"
	"regexp"
	"strings"

	"golang.org/x/net/html"
)

// maxPageBytes bounds what is read out of a decoding reader. The HTTP client
// already caps the response; this guards the decoded form, which can be larger
// than the bytes that arrived.
const maxPageBytes = 32 << 20

func readAll(r io.Reader) ([]byte, error) {
	return io.ReadAll(io.LimitReader(r, maxPageBytes))
}

// boilerplate are fragments that belong to the page furniture rather than the
// story. Every one was seen in a real extraction from the configured sources.
//
// The list is deliberately short and specific. Aggressive cleaning is worse
// than none: it removes real sentences, and the damage is invisible until a
// model is already trained on the result.
var boilerplate = []*regexp.Regexp{
	regexp.MustCompile(`(?i)\bADVERTISEMENT\b`),
	regexp.MustCompile(`(?i)\bPublished\s*[-–—]\s*\w+\s+\d{1,2},\s*\d{4}[^.\n]*\b(?:IST|GMT|UTC|EST|EDT)\b`),
	regexp.MustCompile(`(?i)\|\s*Photo Credit:[^\n.]*`),
	regexp.MustCompile(`(?i)\bLast Updated\s*:[^\n]*\b(?:IST|GMT|UTC)\b`),
	regexp.MustCompile(`(?i)\bDownload the [A-Za-z0-9 ]{1,25} app\.`),
	regexp.MustCompile(`(?i)\bFollow us on [A-Za-z ]{1,30}\b`),
	regexp.MustCompile(`(?i)\bGet the latest [^.\n]{1,80}\.`),
}

// Clean turns an extractor's output into the plain text an article is stored
// as: no markup, no entities, no page furniture, and ordinary spacing.
//
// It accepts markup as well as text because the extractors disagree about what
// they return — structured data in particular carries escaped HTML inside a
// JSON string, so the body arrives as "&lt;p&gt;Every month...". That needs two
// passes: the first turns the entities back into tags, the second removes them.
// The pass count is bounded because text may legitimately contain an angle
// bracket, and stripping until nothing changes would never finish on it.
func Clean(s string) string {
	if s == "" {
		return ""
	}
	for range 2 {
		if !strings.ContainsAny(s, "<&") {
			break
		}
		s = htmlToText(s)
	}
	for _, re := range boilerplate {
		s = re.ReplaceAllString(s, " ")
	}
	return collapse(s)
}

// htmlToText drops every tag and unescapes what is left. Block-level elements
// become newlines so two paragraphs do not run into one another as a single
// word, which is how "website.A bench of" happens.
func htmlToText(s string) string {
	z := html.NewTokenizer(strings.NewReader(s))
	var b strings.Builder

	for {
		switch z.Next() {
		case html.ErrorToken:
			return b.String()

		case html.TextToken:
			b.Write(z.Text())

		case html.StartTagToken, html.EndTagToken, html.SelfClosingTagToken:
			name, _ := z.TagName()
			switch string(name) {
			case "script", "style", "noscript":
				// Skip the element's contents entirely rather than reading
				// code into the article body.
				if z.Token().Type == html.StartTagToken {
					skipTo(z, string(name))
				}
			case "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
				"tr", "section", "article", "blockquote", "figcaption":
				b.WriteByte('\n')
			}
		}
	}
}

// skipTo discards tokens until the named element closes.
func skipTo(z *html.Tokenizer, name string) {
	depth := 1
	for depth > 0 {
		switch z.Next() {
		case html.ErrorToken:
			return
		case html.StartTagToken:
			if n, _ := z.TagName(); string(n) == name {
				depth++
			}
		case html.EndTagToken:
			if n, _ := z.TagName(); string(n) == name {
				depth--
			}
		}
	}
}

// collapse normalises whitespace: runs of spaces become one, runs of blank
// lines become one, and the result is trimmed.
func collapse(s string) string {
	var b bytes.Buffer
	b.Grow(len(s))

	var space, newline bool
	for _, r := range s {
		switch {
		case r == '\n' || r == '\r':
			newline = true
		case r == ' ' || r == '\t' || r == '\v' || r == '\f' || r == '\u00a0':
			space = true
		default:
			if b.Len() > 0 {
				if newline {
					b.WriteByte('\n')
				} else if space {
					b.WriteByte(' ')
				}
			}
			space, newline = false, false
			b.WriteRune(r)
		}
	}
	return b.String()
}
