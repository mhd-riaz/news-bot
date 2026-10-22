package domain

import (
	"net/url"
	"strings"
	"time"
	"unicode"
)

// Bounds for a feed item. A feed is remote, third-party input, so every string
// that reaches the database is capped here rather than trusted to be sane.
const (
	MaxItemTitleLength    = 500
	MaxItemLinkLength     = 2048
	MaxItemGUIDLength     = 512
	MaxItemSummaryLength  = 5000
	MaxItemContentLength  = 200_000
	MaxItemAuthorLength   = 200
	MaxItemCategoryLength = 100

	MaxItemAuthors    = 10
	MaxItemCategories = 25
)

// FeedItem is one entry exactly as a feed published it, after the collector has
// trimmed and bounded it. Deduplication, HTML sanitisation and enrichment
// belong to the processing pipeline in Milestone 4; this type deliberately
// carries the publisher's values rather than a normalised article.
type FeedItem struct {
	Title      string
	Link       string
	GUID       string
	Summary    string
	Content    string
	Authors    []string
	Categories []string
	ImageURL   string

	PublishedAt *time.Time
	UpdatedAt   *time.Time
}

// Normalize trims, collapses runs of whitespace in the short single-line fields
// and enforces every length and count bound. It is total: any input leaves the
// call in a storable shape, so the collector never has to reject an item merely
// for being verbose.
func (i *FeedItem) Normalize() {
	i.Title = truncate(collapseSpace(i.Title), MaxItemTitleLength)
	i.Link = truncate(strings.TrimSpace(i.Link), MaxItemLinkLength)
	i.GUID = truncate(collapseSpace(i.GUID), MaxItemGUIDLength)
	i.ImageURL = truncate(strings.TrimSpace(i.ImageURL), MaxItemLinkLength)

	i.Summary = truncate(strings.TrimSpace(i.Summary), MaxItemSummaryLength)
	i.Content = truncate(strings.TrimSpace(i.Content), MaxItemContentLength)

	i.Authors = normalizeList(i.Authors, MaxItemAuthorLength, MaxItemAuthors)
	i.Categories = normalizeList(i.Categories, MaxItemCategoryLength, MaxItemCategories)

	i.PublishedAt = normalizeTimestamp(i.PublishedAt)
	i.UpdatedAt = normalizeTimestamp(i.UpdatedAt)
}

// Validate reports why an item cannot be collected. The link is the one
// non-negotiable field: it is the first key in the deduplication order, and an
// article nobody can open is of no use to a reader either.
func (i *FeedItem) Validate() error {
	var v validator

	switch {
	case i.Link == "":
		v.add("link", "must not be empty")
	case !isFetchableURL(i.Link):
		v.add("link", "must be an absolute http or https URL without credentials")
	}
	if i.ImageURL != "" && !isFetchableURL(i.ImageURL) {
		v.add("image_url", "must be an absolute http or https URL without credentials")
	}

	return v.err()
}

// isFetchableURL reports whether raw is an absolute web URL a reader could
// follow. Credentials are rejected because storing them would echo a password
// back through the article API.
func isFetchableURL(raw string) bool {
	if strings.ContainsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) {
		return false
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.User != nil {
		return false
	}
	switch strings.ToLower(u.Scheme) {
	case "http", "https":
		return true
	default:
		return false
	}
}

// normalizeList trims each entry, drops the empty and the duplicated ones, and
// keeps at most max of them.
func normalizeList(values []string, maxLength, max int) []string {
	if len(values) == 0 {
		return nil
	}

	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, min(len(values), max))
	for _, v := range values {
		v = truncate(collapseSpace(v), maxLength)
		if v == "" {
			continue
		}
		key := strings.ToLower(v)
		if _, dup := seen[key]; dup {
			continue
		}
		seen[key] = struct{}{}

		out = append(out, v)
		if len(out) == max {
			break
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// normalizeTimestamp drops a zero time and matches the millisecond precision
// BSON stores, so a value read back equals the one written.
func normalizeTimestamp(t *time.Time) *time.Time {
	if t == nil || t.IsZero() {
		return nil
	}
	rounded := storedTime(*t)
	return &rounded
}

// collapseSpace trims the ends and reduces every internal run of whitespace to a
// single space, so a title split across three lines of XML is one line of text.
func collapseSpace(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

// truncate cuts to at most max bytes on a rune boundary, so a cut never leaves
// invalid UTF-8 behind.
func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	cut := max
	for cut > 0 && !utf8Start(s[cut]) {
		cut--
	}
	return strings.TrimRight(s[:cut], " ")
}

// utf8Start reports whether b begins a UTF-8 encoded rune.
func utf8Start(b byte) bool { return b&0xC0 != 0x80 }
