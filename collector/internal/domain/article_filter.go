package domain

import (
	"encoding/base64"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

// ArticleSort selects which timeline a listing walks.
type ArticleSort string

// The orders a listing may be read in. Both are newest first: an article feed
// has no other useful order, and each is served by its own compound index.
const (
	// SortPublishedAt orders by when the publisher dated the article.
	SortPublishedAt ArticleSort = "published_at"

	// SortCollectedAt orders by when this system stored it, which is what a
	// caller polling for new arrivals wants — a publisher back-dating an
	// article cannot make it skip past a reader who has already paged by it.
	SortCollectedAt ArticleSort = "collected_at"
)

// ArticleFilter narrows an article listing. Every field is optional; a nil or
// empty field is not applied.
type ArticleFilter struct {
	SourceID string
	Language string
	Country  string
	State    string
	City     string
	Topic    string

	// PublishedFrom and PublishedTo bound published_at, whichever order the
	// listing is read in.
	PublishedFrom *time.Time
	PublishedTo   *time.Time

	Sort   ArticleSort
	Cursor *ArticleCursor
	Limit  int
}

// ArticleDeletion selects the articles a retention sweep removes.
//
// OlderThan is required and has no default: articles accumulate without bound,
// but a deletion whose bound could be omitted would empty the collection on a
// mistyped parameter. The optional source narrows the sweep to one feed, by id
// or by the name denormalised onto every article.
type ArticleDeletion struct {
	OlderThan  time.Time
	SourceID   string
	SourceName string
}

// Normalize canonicalises the fields the same way the article model does, so a
// name given here matches the name stored on the article.
func (d *ArticleDeletion) Normalize() {
	d.OlderThan = d.OlderThan.UTC()
	d.SourceID = strings.TrimSpace(d.SourceID)
	d.SourceName = collapseSpace(d.SourceName)
}

// Validate rejects a sweep with no bound, an identifier that is not a UUID and
// a name no article could carry.
func (d ArticleDeletion) Validate() error {
	var v validator

	if d.OlderThan.IsZero() {
		v.add("delete_older_than", "is required")
	}
	if d.SourceID != "" {
		if _, err := uuid.Parse(d.SourceID); err != nil {
			v.add("source_id", "must be a valid UUID")
		}
	}
	if len(d.SourceName) > MaxNameLength {
		v.add("source_name", "must be at most %d characters", MaxNameLength)
	}

	return v.err()
}

// ArticlePage is one page of a listing.
//
// It carries no total. Articles accumulate without bound, and counting a
// filtered set of them on every page is the same walk the cursor exists to
// avoid; a caller learns there is more from HasMore instead.
type ArticlePage struct {
	Items      []Article
	Limit      int
	NextCursor string
	HasMore    bool
}

// ArticleCursor is the position of the last article on a page: the value of the
// sort field, and the identifier that breaks a tie between two articles sharing
// it.
type ArticleCursor struct {
	Value time.Time
	ID    string
}

// SortValue returns the field this article is ordered by under sort.
func (a Article) SortValue(sort ArticleSort) time.Time {
	if sort == SortCollectedAt {
		return a.CollectedAt
	}
	return a.PublishedAt
}

// CursorFor returns the token that resumes this listing after a.
func (f ArticleFilter) CursorFor(a Article) string {
	return ArticleCursor{Value: a.SortValue(f.Sort), ID: a.ID}.Encode()
}

// Encode renders the cursor as an opaque token. Milliseconds match the
// precision BSON stores, so a decoded cursor names exactly the article it was
// taken from.
func (c ArticleCursor) Encode() string {
	raw := strconv.FormatInt(c.Value.UnixMilli(), 10) + "." + c.ID
	return base64.RawURLEncoding.EncodeToString([]byte(raw))
}

// ParseArticleCursor decodes a token produced by Encode.
//
// Both halves are parsed and validated before they can reach a query: a cursor
// is caller-supplied input like any other, and a tampered one must be a
// rejected request rather than a silent reset to the first page.
func ParseArticleCursor(raw string) (*ArticleCursor, error) {
	var v validator

	decoded, err := base64.RawURLEncoding.DecodeString(strings.TrimSpace(raw))
	if err != nil {
		v.add("cursor", "must be a cursor returned by a previous page")
		return nil, v.err()
	}

	value, id, found := strings.Cut(string(decoded), ".")
	millis, convErr := strconv.ParseInt(value, 10, 64)
	if _, uuidErr := uuid.Parse(id); !found || convErr != nil || uuidErr != nil {
		v.add("cursor", "must be a cursor returned by a previous page")
		return nil, v.err()
	}

	return &ArticleCursor{Value: time.UnixMilli(millis).UTC(), ID: id}, nil
}

// Normalize applies the defaults and canonicalises the fields that have a
// canonical form, the same way the article model does.
func (f *ArticleFilter) Normalize() {
	if f.Limit == 0 {
		f.Limit = DefaultListLimit
	}
	if f.Sort == "" {
		f.Sort = SortPublishedAt
	}

	f.Sort = ArticleSort(strings.ToLower(strings.TrimSpace(string(f.Sort))))
	f.SourceID = strings.TrimSpace(f.SourceID)
	f.Language = strings.ToLower(strings.TrimSpace(f.Language))
	f.Country = strings.ToUpper(strings.TrimSpace(f.Country))
	f.State = strings.TrimSpace(f.State)
	f.City = strings.TrimSpace(f.City)
	f.Topic = strings.ToLower(strings.TrimSpace(f.Topic))
}

// Validate rejects out-of-range pagination, unknown enum values, an identifier
// that is not a UUID and a date range that cannot contain anything.
func (f ArticleFilter) Validate() error {
	var v validator

	if f.Limit < 1 || f.Limit > MaxListLimit {
		v.add("limit", "must be between 1 and %d, got %d", MaxListLimit, f.Limit)
	}
	switch f.Sort {
	case SortPublishedAt, SortCollectedAt:
	default:
		v.add("sort", "must be one of published_at, collected_at")
	}

	if f.SourceID != "" {
		if _, err := uuid.Parse(f.SourceID); err != nil {
			v.add("source_id", "must be a valid UUID")
		}
	}
	if f.Language != "" && !isAlpha(f.Language, 2) {
		v.add("language", "must be a two-letter ISO 639-1 code")
	}
	if f.Country != "" && !isAlpha(f.Country, 2) {
		v.add("country", "must be a two-letter ISO 3166-1 alpha-2 code")
	}
	if len(f.State) > MaxRegionLength {
		v.add("state", "must be at most %d characters", MaxRegionLength)
	}
	if len(f.City) > MaxRegionLength {
		v.add("city", "must be at most %d characters", MaxRegionLength)
	}
	if len(f.Topic) > MaxRegionLength {
		v.add("topic", "must be at most %d characters", MaxRegionLength)
	}

	if f.PublishedFrom != nil && f.PublishedTo != nil && f.PublishedFrom.After(*f.PublishedTo) {
		v.add("published_from", "must not be later than published_to")
	}

	return v.err()
}
