package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"html"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
)

// ProcessingStatus is how far an article has travelled through the pipeline.
type ProcessingStatus string

// The stages an article passes through. Collection produces "collected";
// enrichment promotes an article to "enriched" once its stored text is the whole
// story, whether the feed supplied it or a fetch did. An article whose full text
// could not be obtained stays "collected", which is an honest description of
// what is held rather than a failure flag.
const (
	ProcessingStatusCollected ProcessingStatus = "collected"
	ProcessingStatusEnriched  ProcessingStatus = "enriched"
)

// Valid reports whether p is a status this package defines.
func (p ProcessingStatus) Valid() bool {
	return p == ProcessingStatusCollected || p == ProcessingStatusEnriched
}

// Bounds for a stored article. The text fields reuse the feed item's bounds,
// because an article is what a feed item becomes.
const (
	MaxArticleSummaryLength = MaxItemSummaryLength
	MaxArticleContentLength = MaxItemContentLength

	// maxClockSkew is how far ahead of the collection a publication date may be
	// before it is treated as wrong. Feeds regularly carry dates minutes into
	// the future from a mis-set server clock; a date days ahead would otherwise
	// pin the article to the top of every "latest" listing forever.
	maxClockSkew = time.Hour
)

// Article is one collected, normalised, deduplicated news item. Field names
// mirror the index plan in internal/mongodb, so a query planner change and a
// model change cannot drift apart silently.
type Article struct {
	ID string `bson:"_id"`

	// DedupID is the single unique key the database uses to settle a race
	// between two collectors inserting the same article at the same time.
	DedupID string `bson:"dedup_id"`

	SourceID string `bson:"source_id"`
	// SourceName is denormalised so a listing does not have to join.
	SourceName string `bson:"source_name"`
	FeedGUID   string `bson:"feed_guid,omitempty"`

	URL           string `bson:"url"`
	NormalizedURL string `bson:"normalized_url"`
	CanonicalURL  string `bson:"canonical_url,omitempty"`

	Title      string   `bson:"title"`
	Summary    string   `bson:"summary,omitempty"`
	Content    string   `bson:"content,omitempty"`
	Authors    []string `bson:"authors,omitempty"`
	Categories []string `bson:"categories,omitempty"`
	ImageURL   string   `bson:"image_url,omitempty"`

	// ContentHash identifies the text itself, which is what catches the same
	// story republished by one source under two URLs.
	ContentHash string `bson:"content_hash"`

	Language string `bson:"language"`
	Country  string `bson:"country"`
	State    string `bson:"state,omitempty"`
	City     string `bson:"city,omitempty"`

	PublishedAt time.Time `bson:"published_at"`
	CollectedAt time.Time `bson:"collected_at"`

	ProcessingStatus ProcessingStatus `bson:"processing_status"`

	// Enrichment state. ScrapeStatus records what the last full-text attempt
	// produced; NextScrapeAt is stored rather than derived so the backlog is a
	// single indexed comparison instead of a per-document backoff calculation.
	ScrapeStatus   ScrapeStatus `bson:"scrape_status"`
	ScrapeAttempts int          `bson:"scrape_attempts"`
	ScrapedAt      *time.Time   `bson:"scraped_at,omitempty"`
	NextScrapeAt   *time.Time   `bson:"next_scrape_at,omitempty"`

	ClassificationStatus    ClassificationStatus `bson:"classification_status"`
	ClassificationClaimedAt *time.Time           `bson:"classification_claimed_at,omitempty"`
	ClassificationAttempts  int                  `bson:"classification_attempts"`
	ClassifiedAt            *time.Time           `bson:"classified_at,omitempty"`
	Topic                   string               `bson:"topic,omitempty"`
	Confidence              float64              `bson:"confidence,omitempty"`
	ModelVersion            string               `bson:"model_version,omitempty"`
}

// ArticleIdentity is everything that can identify an article as one already
// stored. The repository tries the keys in the documented order: normalized URL,
// then canonical URL, then the publisher's own identifier within the source,
// then the content hash.
type ArticleIdentity struct {
	SourceID      string
	NormalizedURL string
	CanonicalURL  string
	FeedGUID      string
	ContentHash   string
}

// Identity returns the keys this article would be recognised by.
func (a *Article) Identity() ArticleIdentity {
	return ArticleIdentity{
		SourceID:      a.SourceID,
		NormalizedURL: a.NormalizedURL,
		CanonicalURL:  a.CanonicalURL,
		FeedGUID:      a.FeedGUID,
		ContentHash:   a.ContentHash,
	}
}

// NewArticle turns one feed item, collected from src, into a storable article.
// now is passed in rather than read from the clock so behaviour is deterministic.
func NewArticle(src Source, item FeedItem, now time.Time) (*Article, error) {
	item.Normalize()
	if err := item.Validate(); err != nil {
		return nil, err
	}

	id, err := uuid.NewV7()
	if err != nil {
		return nil, fmt.Errorf("domain: generate article id: %w", err)
	}

	collected := storedTime(now)
	a := &Article{
		ID:         id.String(),
		SourceID:   src.ID,
		SourceName: src.Name,
		FeedGUID:   item.GUID,

		URL:           item.Link,
		NormalizedURL: NormalizeURL(item.Link),
		CanonicalURL:  canonicalFromGUID(item.GUID),

		Title:      item.Title,
		Summary:    plainText(item.Summary),
		Content:    plainText(item.Content),
		Authors:    item.Authors,
		Categories: item.Categories,
		ImageURL:   item.ImageURL,

		// The region and the language come from the source: a feed item does
		// not carry where it is about, which is the whole point of registering
		// feeds by region.
		Language: src.Language,
		Country:  src.Country,
		State:    src.State,
		City:     src.City,

		CollectedAt:      collected,
		PublishedAt:      publicationTime(item.PublishedAt, collected),
		ProcessingStatus: ProcessingStatusCollected,

		ClassificationStatus: ClassificationStatusPending,
	}

	if a.Summary == "" {
		a.Summary = truncate(a.Content, MaxItemSummaryLength)
	}
	// ContentHash is computed once, from what the feed gave, and never
	// recomputed. It is a deduplication key: re-deriving it after enrichment
	// would stop an already-stored article matching itself.
	a.ContentHash = contentHash(a.Title, a.Content, a.Summary)
	a.DedupID = dedupID(a.CanonicalURL, a.NormalizedURL)

	if NeedsScrape(a) {
		a.ScrapeStatus = ScrapeStatusPending
		a.NextScrapeAt = &collected
	} else {
		a.ScrapeStatus = ScrapeStatusNotNeeded
		a.ProcessingStatus = ProcessingStatusEnriched
	}

	a.Normalize()
	if err := a.Validate(); err != nil {
		return nil, err
	}
	return a, nil
}

// Normalize applies the same canonical forms the source model uses, so an
// article and the feed it came from cannot disagree about the case of a country
// code, and re-applies every length bound.
func (a *Article) Normalize() {
	a.Title = truncate(collapseSpace(a.Title), MaxItemTitleLength)
	a.Summary = truncate(strings.TrimSpace(a.Summary), MaxArticleSummaryLength)
	a.Content = truncate(strings.TrimSpace(a.Content), MaxArticleContentLength)
	a.SourceName = truncate(collapseSpace(a.SourceName), MaxNameLength)

	a.Authors = normalizeList(a.Authors, MaxItemAuthorLength, MaxItemAuthors)
	a.Categories = normalizeList(a.Categories, MaxItemCategoryLength, MaxItemCategories)

	a.Language = strings.ToLower(strings.TrimSpace(a.Language))
	a.Country = strings.ToUpper(strings.TrimSpace(a.Country))
	a.State = strings.TrimSpace(a.State)
	a.City = strings.TrimSpace(a.City)
	a.Topic = strings.ToLower(strings.TrimSpace(a.Topic))

	a.PublishedAt = storedTime(a.PublishedAt)
	a.CollectedAt = storedTime(a.CollectedAt)
}

// Validate reports every broken rule at once.
func (a *Article) Validate() error {
	var v validator

	if _, err := uuid.Parse(a.ID); err != nil {
		v.add("id", "must be a valid UUID")
	}
	if _, err := uuid.Parse(a.SourceID); err != nil {
		v.add("source_id", "must be a valid UUID")
	}
	if a.DedupID == "" {
		v.add("dedup_id", "must not be empty")
	}
	if a.ContentHash == "" {
		v.add("content_hash", "must not be empty")
	}

	if !isFetchableURL(a.URL) {
		v.add("url", "must be an absolute http or https URL")
	}
	if a.NormalizedURL == "" {
		v.add("normalized_url", "must not be empty")
	}
	// A headline is what every listing shows; an article without one is not
	// worth storing.
	if a.Title == "" {
		v.add("title", "must not be empty")
	}

	if !isAlpha(a.Language, 2) {
		v.add("language", "must be a two-letter ISO 639-1 code")
	}
	if !isAlpha(a.Country, 2) {
		v.add("country", "must be a two-letter ISO 3166-1 alpha-2 code")
	}

	if a.PublishedAt.IsZero() {
		v.add("published_at", "must not be zero")
	}
	if a.CollectedAt.IsZero() {
		v.add("collected_at", "must not be zero")
	}
	if !a.ProcessingStatus.Valid() {
		v.add("processing_status", "must be %s or %s",
			ProcessingStatusCollected, ProcessingStatusEnriched)
	}
	if !a.ScrapeStatus.Valid() {
		v.add("scrape_status", "must be a known scrape status")
	}
	if a.ScrapeAttempts < 0 {
		v.add("scrape_attempts", "must not be negative")
	}
	if !a.ClassificationStatus.Valid() {
		v.add("classification_status", "must be a known classification status")
	}
	if a.ClassificationAttempts < 0 {
		v.add("classification_attempts", "must not be negative")
	}
	if a.ClassificationStatus == ClassificationStatusClassifying && a.ClassificationClaimedAt == nil {
		v.add("classification_claimed_at", "must be set while classifying")
	}
	if a.ClassificationStatus == ClassificationStatusClassified || a.ClassificationStatus == ClassificationStatusUnsorted {
		if a.Topic == "" {
			v.add("topic", "must be set after successful classification")
		}
		if a.ClassificationStatus == ClassificationStatusUnsorted && a.Topic != "unsorted" {
			v.add("topic", "must be unsorted when classification is unsorted")
		}
		if a.ClassifiedAt == nil {
			v.add("classified_at", "must be set after successful classification")
		}
		if a.ModelVersion == "" {
			v.add("model_version", "must be set after successful classification")
		}
		if a.Confidence < 0 || a.Confidence > 1 {
			v.add("confidence", "must be between 0 and 1 after successful classification")
		}
	}

	return v.err()
}

// publicationTime falls back to the collection time when the feed gave no date
// or gave one that cannot be true.
func publicationTime(published *time.Time, collected time.Time) time.Time {
	if published == nil || published.IsZero() || published.After(collected.Add(maxClockSkew)) {
		return collected
	}
	return *published
}

// canonicalFromGUID returns the publisher's own permalink when its identifier is
// one. RSS permalink GUIDs and Atom ids are frequently URLs, and a publisher
// keeps that identifier stable even when it changes the link an article is
// served under, which makes it a stronger identity than the link itself.
func canonicalFromGUID(guid string) string {
	if guid == "" || !isFetchableURL(guid) {
		return ""
	}
	return NormalizeURL(guid)
}

// dedupID is the primary identity, hashed to a fixed width so the unique index
// on it stays small regardless of how long a publisher's URLs are.
func dedupID(canonicalURL, normalizedURL string) string {
	if canonicalURL != "" {
		return hashOf("canonical", canonicalURL)
	}
	return hashOf("url", normalizedURL)
}

// contentHash identifies the text of an article. Case and whitespace are
// flattened first, so a publisher re-titling a story in title case does not
// produce a second article.
func contentHash(title, content, summary string) string {
	body := content
	if body == "" {
		body = summary
	}
	return hashOf("content", strings.ToLower(collapseSpace(title)), strings.ToLower(collapseSpace(body)))
}

// hashOf hashes a labelled tuple. The label and the separator keep two
// different kinds of key from ever colliding on the same digest.
func hashOf(kind string, parts ...string) string {
	h := sha256.New()
	h.Write([]byte(kind))
	for _, p := range parts {
		h.Write([]byte{0})
		h.Write([]byte(p))
	}
	return hex.EncodeToString(h.Sum(nil))
}

// trackingParams are query parameters that identify a campaign or a referrer
// rather than the article, so two links that differ only in these are the same
// article arriving by two routes.
var trackingParams = map[string]struct{}{
	"utm_source": {}, "utm_medium": {}, "utm_campaign": {}, "utm_term": {},
	"utm_content": {}, "utm_id": {}, "utm_name": {}, "utm_reader": {},
	"gclid": {}, "dclid": {}, "fbclid": {}, "msclkid": {}, "yclid": {},
	"igshid": {}, "mc_cid": {}, "mc_eid": {}, "_ga": {}, "ref_src": {},
}

// NormalizeURL reduces a link to the form two publishers' links for the same
// article agree on: lower-case scheme and host, no default port, no "www.", no
// fragment, no tracking parameters, the remaining parameters in a stable order
// and no trailing slash. An unparsable URL is returned trimmed but unchanged,
// so a link is never silently replaced with something that does not resolve.
func NormalizeURL(raw string) string {
	raw = strings.TrimSpace(raw)

	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return raw
	}

	u.Scheme = strings.ToLower(u.Scheme)
	u.Host = strings.ToLower(u.Host)
	u.User = nil
	u.Fragment = ""
	u.RawFragment = ""

	if port := u.Port(); (u.Scheme == "http" && port == "80") || (u.Scheme == "https" && port == "443") {
		u.Host = u.Hostname()
	}
	u.Host = strings.TrimPrefix(u.Host, "www.")

	if u.RawQuery != "" {
		u.RawQuery = normalizeQuery(u.Query())
	}
	if u.Path != "/" {
		u.Path = strings.TrimRight(u.Path, "/")
	}

	return u.String()
}

// normalizeQuery drops the tracking parameters and re-encodes what is left in a
// stable order, so ?a=1&b=2 and ?b=2&a=1 hash the same.
func normalizeQuery(values url.Values) string {
	for name := range values {
		if _, tracking := trackingParams[strings.ToLower(name)]; tracking {
			delete(values, name)
		}
	}
	if len(values) == 0 {
		return ""
	}
	// url.Values.Encode already sorts by key; the values under one key are
	// sorted here so repeated parameters are stable too.
	for _, v := range values {
		sort.Strings(v)
	}
	return values.Encode()
}

// plainText turns a feed's HTML into the text an article carries. Tags are
// removed before entities are decoded, so an escaped tag in the source cannot
// reappear as a real one. The result is text, not sanitised HTML: nothing in
// this system renders it as markup.
func plainText(s string) string {
	if s == "" {
		return ""
	}

	var b strings.Builder
	b.Grow(len(s))

	for len(s) > 0 {
		start := strings.IndexByte(s, '<')
		if start < 0 {
			b.WriteString(s)
			break
		}
		// A '<' that does not begin a tag is ordinary text, as in "5 < 6".
		if !startsTag(s[start+1:]) {
			b.WriteString(s[:start+1])
			s = s[start+1:]
			continue
		}

		b.WriteString(s[:start])
		end := strings.IndexByte(s[start:], '>')
		if end < 0 {
			break // an unterminated tag takes the rest of the text with it
		}
		// A removed tag is a word boundary: "<p>one</p><p>two</p>" must not
		// become "onetwo".
		b.WriteByte(' ')
		s = s[start+end+1:]
	}

	return collapseSpace(html.UnescapeString(b.String()))
}

func startsTag(rest string) bool {
	if rest == "" {
		return false
	}
	switch c := rest[0]; {
	case c == '/', c == '!', c == '?':
		return true
	default:
		return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
	}
}
