package extract

import (
	"encoding/json"
	"net/url"
	"strings"

	"golang.org/x/net/html"
)

// JSONLD reads the body out of schema.org structured data.
//
// It is the only extractor that finds Deccan Herald's article, whose page
// renders its body in the browser: the story is in the ld+json block and
// nowhere in the served markup. Several publishers embed the full text there
// even when the visible page is behind ad furniture.
type JSONLD struct{}

func (JSONLD) Name() string { return "json-ld" }

// bodyKeys are the fields that may hold the article text, longest-wins between
// them. "description" is included last because some publishers put the whole
// story there and only a summary in articleBody.
var bodyKeys = []string{"articleBody", "text", "description"}

func (j JSONLD) Extract(page []byte, _ *url.URL) Result {
	var best Result

	for _, blob := range scriptsOfType(page, "application/ld+json") {
		var doc any
		if err := json.Unmarshal([]byte(blob), &doc); err != nil {
			// A publisher with one broken block usually has other good ones.
			continue
		}
		for _, node := range articleNodes(doc) {
			r := fromNode(node)
			if len(r.Text) > len(best.Text) {
				best = r
			}
		}
	}
	return best
}

// fromNode reads the longest body field out of one schema.org object.
func fromNode(node map[string]any) Result {
	var out Result
	for _, key := range bodyKeys {
		if s, ok := node[key].(string); ok && len(s) > len(out.Text) {
			out.Text = s
		}
	}
	if s, ok := node["headline"].(string); ok {
		out.Title = s
	}
	return out
}

// articleNodes walks the document for objects whose @type looks like an
// article. The structure varies wildly — a bare object, an array, or everything
// nested under @graph — so the whole tree is walked rather than guessing.
func articleNodes(v any) []map[string]any {
	var found []map[string]any

	switch t := v.(type) {
	case map[string]any:
		if isArticleType(t["@type"]) {
			found = append(found, t)
		}
		for _, child := range t {
			found = append(found, articleNodes(child)...)
		}
	case []any:
		for _, child := range t {
			found = append(found, articleNodes(child)...)
		}
	}
	return found
}

func isArticleType(v any) bool {
	switch t := v.(type) {
	case string:
		return strings.Contains(t, "Article")
	case []any:
		for _, item := range t {
			if isArticleType(item) {
				return true
			}
		}
	}
	return false
}

// scriptsOfType returns the contents of every <script> with the given type.
func scriptsOfType(page []byte, typ string) []string {
	z := html.NewTokenizer(strings.NewReader(string(page)))
	var out []string

	for {
		switch z.Next() {
		case html.ErrorToken:
			return out

		case html.StartTagToken:
			name, hasAttr := z.TagName()
			if string(name) != "script" || !hasAttr {
				continue
			}
			if !hasType(z, typ) {
				continue
			}
			// The tokenizer hands script contents back as a single text token.
			if z.Next() == html.TextToken {
				out = append(out, string(z.Text()))
			}
		}
	}
}

func hasType(z *html.Tokenizer, want string) bool {
	for {
		key, val, more := z.TagAttr()
		if string(key) == "type" && strings.EqualFold(strings.TrimSpace(string(val)), want) {
			return true
		}
		if !more {
			return false
		}
	}
}
