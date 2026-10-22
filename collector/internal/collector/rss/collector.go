// Package rss collects RSS, RDF and Atom feeds. It owns exactly two
// responsibilities: performing the conditional fetch through the guarded HTTP
// client, and turning whatever dialect came back into bounded domain feed
// items. Deduplication, sanitisation and persistence belong to the processing
// pipeline, so nothing here touches a database.
package rss

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"

	"github.com/mmcdole/gofeed"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
)

// ErrParse means the body was fetched but is not a feed this collector
// understands. It is a permanent failure for that body: retrying the same bytes
// cannot help, so the scheduler should treat it as a source health problem
// rather than a transient one.
var ErrParse = errors.New("rss: unparsable feed")

// DefaultMaxItems bounds how many entries one collection accepts. Feeds are
// occasionally published with tens of thousands of entries, and a collector
// that reads all of them holds the lot in memory.
const DefaultMaxItems = 500

// Fetcher is the part of the HTTP client this collector needs. Depending on the
// interface rather than the concrete client is what lets the tests run without
// a network.
type Fetcher interface {
	Fetch(ctx context.Context, req httpclient.Request) (*httpclient.Response, error)
}

// Validators are the HTTP cache validators kept from the previous collection of
// a source. Passing them makes the fetch conditional; leaving them empty makes
// it unconditional.
type Validators struct {
	ETag         string
	LastModified string
}

// Result is the outcome of one collection.
type Result struct {
	// NotModified is set when the publisher answered 304. Items is then empty
	// and the previous collection's items are still current.
	NotModified bool

	Items []domain.FeedItem

	// ItemsFound is how many entries the feed contained, before unusable ones
	// were dropped and before the item cap applied, so a source quietly losing
	// entries is visible rather than silent.
	ItemsFound   int
	ItemsSkipped int
	Truncated    bool

	// FeedType is the dialect gofeed detected, which may differ from the type
	// the source was registered with.
	FeedType string

	// Validators are what to store for the next conditional fetch.
	Validators Validators
}

// Collector fetches and parses one feed at a time. It holds no per-source
// state, so a single instance is shared across sources.
type Collector struct {
	fetcher  Fetcher
	maxItems int
}

// New wires a collector. A maxItems of zero or less means DefaultMaxItems.
func New(fetcher Fetcher, maxItems int) *Collector {
	if maxItems <= 0 {
		maxItems = DefaultMaxItems
	}
	return &Collector{fetcher: fetcher, maxItems: maxItems}
}

// Collect fetches a source's feed and returns its usable entries.
//
// An entry the feed publishes but this system cannot use — one with no link, or
// with a link that is not a fetchable web URL — is counted in ItemsSkipped and
// dropped. One malformed entry does not fail the whole collection, because a
// single bad row in an otherwise healthy feed should not stop the other fifty
// articles from being collected.
func (c *Collector) Collect(ctx context.Context, src *domain.Source, prev Validators) (Result, error) {
	if src == nil {
		return Result{}, errors.New("rss: nil source")
	}

	resp, err := c.fetcher.Fetch(ctx, httpclient.Request{
		URL:          src.FeedURL,
		ETag:         prev.ETag,
		LastModified: prev.LastModified,
	})
	if err != nil {
		return Result{}, err
	}

	validators := Validators{ETag: resp.ETag, LastModified: resp.LastModified}
	if resp.NotModified {
		return Result{NotModified: true, Validators: validators}, nil
	}

	feed, err := parse(resp.Body)
	if err != nil {
		return Result{}, err
	}

	result := Result{FeedType: feed.FeedType, Validators: validators, ItemsFound: len(feed.Items)}
	result.Items, result.ItemsSkipped, result.Truncated = c.convert(feed, baseURL(feed, resp.FinalURL, src.FeedURL))
	return result, nil
}

// parse detects the dialect and translates it. gofeed's parser carries the
// per-dialect sub-parsers, so one is built per call rather than shared across
// concurrent collections.
func parse(body []byte) (*gofeed.Feed, error) {
	if len(bytes.TrimSpace(body)) == 0 {
		return nil, fmt.Errorf("%w: empty body", ErrParse)
	}

	feed, err := gofeed.NewParser().Parse(bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrParse, err)
	}
	return feed, nil
}

func (c *Collector) convert(feed *gofeed.Feed, base *url.URL) (items []domain.FeedItem, skipped int, truncated bool) {
	items = make([]domain.FeedItem, 0, min(len(feed.Items), c.maxItems))

	for _, entry := range feed.Items {
		if len(items) == c.maxItems {
			truncated = true
			break
		}
		if entry == nil {
			skipped++
			continue
		}

		item := convertItem(entry, base)
		item.Normalize()
		if err := item.Validate(); err != nil {
			skipped++
			continue
		}
		items = append(items, item)
	}

	if len(items) == 0 {
		return nil, skipped, truncated
	}
	return items, skipped, truncated
}

func convertItem(entry *gofeed.Item, base *url.URL) domain.FeedItem {
	item := domain.FeedItem{
		Title:       entry.Title,
		Link:        resolve(base, firstLink(entry)),
		GUID:        entry.GUID,
		Summary:     entry.Description,
		Content:     entry.Content,
		Categories:  entry.Categories,
		Authors:     authorNames(entry),
		ImageURL:    resolve(base, imageURL(entry)),
		PublishedAt: entry.PublishedParsed,
		UpdatedAt:   entry.UpdatedParsed,
	}

	// A feed that only dates its entries as "updated" — Atom's required field —
	// would otherwise arrive with no publication date at all.
	if item.PublishedAt == nil {
		item.PublishedAt = entry.UpdatedParsed
	}
	return item
}

// firstLink prefers the entry's canonical link and falls back to the first of
// its alternates, which is where some Atom feeds put the article URL.
func firstLink(entry *gofeed.Item) string {
	if strings.TrimSpace(entry.Link) != "" {
		return entry.Link
	}
	for _, link := range entry.Links {
		if strings.TrimSpace(link) != "" {
			return link
		}
	}
	return ""
}

func authorNames(entry *gofeed.Item) []string {
	names := make([]string, 0, len(entry.Authors))
	for _, author := range entry.Authors {
		if author == nil {
			continue
		}
		// Only the name is kept: an author email is personal data this system
		// has no use for.
		if name := strings.TrimSpace(author.Name); name != "" {
			names = append(names, name)
		}
	}
	return names
}

// imageURL takes the entry's own image, or the first enclosure that declares an
// image type. An enclosure with any other type is a podcast or a PDF.
func imageURL(entry *gofeed.Item) string {
	if entry.Image != nil && strings.TrimSpace(entry.Image.URL) != "" {
		return entry.Image.URL
	}
	for _, enc := range entry.Enclosures {
		if enc != nil && strings.HasPrefix(strings.ToLower(enc.Type), "image/") {
			return enc.URL
		}
	}
	return ""
}

// baseURL is what relative links in the feed resolve against: the feed's own
// declared home page when it has one, otherwise the URL the body came from.
func baseURL(feed *gofeed.Feed, finalURL, configuredURL string) *url.URL {
	for _, candidate := range []string{feed.Link, finalURL, configuredURL} {
		u, err := url.Parse(strings.TrimSpace(candidate))
		if err == nil && u.IsAbs() && u.Host != "" {
			return u
		}
	}
	return nil
}

// resolve turns a possibly relative link into an absolute one. A link that
// cannot be made absolute is returned empty, which the item's own rules then
// reject, rather than being stored as a fragment no reader can open.
func resolve(base *url.URL, raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}

	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	if !u.IsAbs() {
		if base == nil {
			return ""
		}
		u = base.ResolveReference(u)
	}
	return u.String()
}
