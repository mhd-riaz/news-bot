package domain

import (
	"fmt"
	"net/url"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
)

// SourceType is the feed dialect a source publishes.
type SourceType string

// The feed dialects Phase 1 collects. Anything else is rejected at the boundary.
const (
	SourceTypeRSS  SourceType = "rss"
	SourceTypeAtom SourceType = "atom"
)

// HealthStatus summarises how recent collection attempts against a source went.
type HealthStatus string

// Source health values. A newly created source is Unknown until it is collected.
const (
	HealthUnknown  HealthStatus = "unknown"
	HealthHealthy  HealthStatus = "healthy"
	HealthDegraded HealthStatus = "degraded"
	HealthFailing  HealthStatus = "failing"
)

// Field limits and defaults. They are deliberately conservative: a source is
// operator-supplied configuration, not user-generated content.
const (
	MaxNameLength    = 200
	MaxFeedURLLength = 2048
	MaxRegionLength  = 100

	MinPriority = 0
	MaxPriority = 100

	// MinFetchIntervalSeconds stops a source being configured to hammer a
	// publisher; MaxFetchIntervalSeconds keeps a typo from parking a feed for years.
	MinFetchIntervalSeconds = 60
	MaxFetchIntervalSeconds = 7 * 24 * 60 * 60

	DefaultPriority             = 50
	DefaultFetchIntervalSeconds = 900
)

// Source is a configured RSS or Atom feed, its region, its schedule and its
// health. Field names mirror the index plan in internal/mongodb, so a query
// planner change and a model change cannot drift apart silently.
type Source struct {
	ID       string     `bson:"_id"`
	Name     string     `bson:"name"`
	FeedURL  string     `bson:"feed_url"`
	Type     SourceType `bson:"type"`
	Enabled  bool       `bson:"enabled"`
	Priority int        `bson:"priority"`
	Language string     `bson:"language"`

	Country string `bson:"country"`
	State   string `bson:"state"`
	City    string `bson:"city"`

	// FetchIntervalSeconds is stored in seconds rather than as a time.Duration
	// so the value is readable in the shell instead of being nanoseconds.
	FetchIntervalSeconds int        `bson:"fetch_interval_seconds"`
	NextScheduledAt      time.Time  `bson:"next_scheduled_at"`
	LastCollectedAt      *time.Time `bson:"last_collected_at,omitempty"`

	HealthStatus        HealthStatus `bson:"health_status"`
	ConsecutiveFailures int          `bson:"consecutive_failures"`
	LastError           string       `bson:"last_error,omitempty"`

	CreatedAt time.Time `bson:"created_at"`
	UpdatedAt time.Time `bson:"updated_at"`
}

// FetchInterval expresses the configured interval as a duration.
func (s Source) FetchInterval() time.Duration {
	return time.Duration(s.FetchIntervalSeconds) * time.Second
}

// SourceInput is the operator-supplied part of a source. Optional fields are
// pointers so "absent" is distinguishable from a meaningful zero value such as
// priority 0 or enabled false.
type SourceInput struct {
	Name                 string
	FeedURL              string
	Type                 SourceType
	Language             string
	Country              string
	State                string
	City                 string
	Enabled              *bool
	Priority             *int
	FetchIntervalSeconds *int
}

// SourcePatch is a partial update. A nil field is left untouched.
type SourcePatch struct {
	Name                 *string
	FeedURL              *string
	Type                 *SourceType
	Language             *string
	Country              *string
	State                *string
	City                 *string
	Enabled              *bool
	Priority             *int
	FetchIntervalSeconds *int
}

// NewSource builds a validated source that is immediately due for collection.
// now is passed in rather than read from the clock so behaviour is deterministic.
func NewSource(in SourceInput, now time.Time) (*Source, error) {
	id, err := uuid.NewV7()
	if err != nil {
		return nil, fmt.Errorf("domain: generate source id: %w", err)
	}

	now = storedTime(now)
	s := &Source{
		ID:                   id.String(),
		Name:                 in.Name,
		FeedURL:              in.FeedURL,
		Type:                 in.Type,
		Language:             in.Language,
		Country:              in.Country,
		State:                in.State,
		City:                 in.City,
		Enabled:              true,
		Priority:             DefaultPriority,
		FetchIntervalSeconds: DefaultFetchIntervalSeconds,
		HealthStatus:         HealthUnknown,
		NextScheduledAt:      now,
		CreatedAt:            now,
		UpdatedAt:            now,
	}
	if in.Enabled != nil {
		s.Enabled = *in.Enabled
	}
	if in.Priority != nil {
		s.Priority = *in.Priority
	}
	if in.FetchIntervalSeconds != nil {
		s.FetchIntervalSeconds = *in.FetchIntervalSeconds
	}

	s.Normalize()
	if err := s.Validate(); err != nil {
		return nil, err
	}
	return s, nil
}

// Apply merges a patch, then re-normalises and re-validates the whole source so
// a partial update can never leave a stored document in an invalid state.
func (s *Source) Apply(patch SourcePatch, now time.Time) error {
	assign(&s.Name, patch.Name)
	assign(&s.FeedURL, patch.FeedURL)
	assign(&s.Type, patch.Type)
	assign(&s.Language, patch.Language)
	assign(&s.Country, patch.Country)
	assign(&s.State, patch.State)
	assign(&s.City, patch.City)
	assign(&s.Enabled, patch.Enabled)
	assign(&s.Priority, patch.Priority)
	assign(&s.FetchIntervalSeconds, patch.FetchIntervalSeconds)

	s.UpdatedAt = storedTime(now)

	s.Normalize()
	return s.Validate()
}

// failuresBeforeFailing is how many consecutive failures a source is allowed
// before it is called failing rather than degraded. One failed poll is usually
// the publisher having a bad minute; three in a row is a broken feed.
const failuresBeforeFailing = 3

// MaxCollectionBackoff caps the retry interval of a failing source. It is the
// longest interval an operator may configure, so backoff can never park a feed
// for longer than a deliberate configuration could.
const MaxCollectionBackoff = time.Duration(MaxFetchIntervalSeconds) * time.Second

// RecordSuccess marks a completed collection: the source is healthy, its
// failure history is cleared, and its next poll is one interval away.
func (s *Source) RecordSuccess(now time.Time) {
	now = storedTime(now)

	s.HealthStatus = HealthHealthy
	s.ConsecutiveFailures = 0
	s.LastError = ""
	s.LastCollectedAt = &now
	s.NextScheduledAt = now.Add(s.FetchInterval())
	s.UpdatedAt = now
}

// RecordFailure marks a collection that produced nothing and backs the source
// off. reason must be a fixed, caller-safe phrase: it is served by the source
// API, so it must never carry a driver message or a host name.
//
// LastCollectedAt is deliberately left alone. It answers "when did this feed
// last give us articles", and a failed attempt is not an answer to that.
func (s *Source) RecordFailure(now time.Time, reason string) {
	now = storedTime(now)

	s.ConsecutiveFailures++
	if s.ConsecutiveFailures >= failuresBeforeFailing {
		s.HealthStatus = HealthFailing
	} else {
		s.HealthStatus = HealthDegraded
	}
	s.LastError = truncate(collapseSpace(reason), MaxRunErrorLength)
	s.NextScheduledAt = now.Add(backoff(s.FetchInterval(), s.ConsecutiveFailures))
	s.UpdatedAt = now
}

// backoff doubles the interval per consecutive failure, capped. A publisher
// that is down stops being polled every fifteen minutes for a week, which is
// both wasted work here and unwelcome traffic there.
func backoff(interval time.Duration, failures int) time.Duration {
	d := interval
	for i := 1; i < failures && d < MaxCollectionBackoff; i++ {
		d *= 2
	}
	return min(d, MaxCollectionBackoff)
}

// storedTime rounds to the millisecond precision BSON records, so the value the
// API returns after a write equals the one a later read returns.
func storedTime(t time.Time) time.Time {
	return t.UTC().Truncate(time.Millisecond)
}

func assign[T any](dst *T, src *T) {
	if src != nil {
		*dst = *src
	}
}

// Normalize trims and case-folds the fields that have a canonical form, so
// "  EN " and "en" cannot become two different values in the same index.
func (s *Source) Normalize() {
	s.Name = strings.TrimSpace(s.Name)
	s.FeedURL = strings.TrimSpace(s.FeedURL)
	s.Type = SourceType(strings.ToLower(strings.TrimSpace(string(s.Type))))
	s.Language = strings.ToLower(strings.TrimSpace(s.Language))
	s.Country = strings.ToUpper(strings.TrimSpace(s.Country))
	s.State = strings.TrimSpace(s.State)
	s.City = strings.TrimSpace(s.City)
	s.HealthStatus = HealthStatus(strings.ToLower(strings.TrimSpace(string(s.HealthStatus))))
	if s.HealthStatus == "" {
		s.HealthStatus = HealthUnknown
	}
}

// ValidateID rejects an identifier that is not a UUID, before it is ever used
// to build a query.
func ValidateID(id string) error {
	var v validator
	if _, err := uuid.Parse(id); err != nil {
		v.add("id", "must be a valid UUID")
	}
	return v.err()
}

// Validate reports every broken rule at once.
func (s *Source) Validate() error {
	var v validator

	if _, err := uuid.Parse(s.ID); err != nil {
		v.add("id", "must be a valid UUID")
	}
	if s.Name == "" {
		v.add("name", "must not be empty")
	} else if len(s.Name) > MaxNameLength {
		v.add("name", "must be at most %d characters, got %d", MaxNameLength, len(s.Name))
	}

	validateFeedURL(&v, s.FeedURL)

	switch s.Type {
	case SourceTypeRSS, SourceTypeAtom:
	default:
		v.add("type", "must be one of rss, atom")
	}

	switch s.HealthStatus {
	case HealthUnknown, HealthHealthy, HealthDegraded, HealthFailing:
	default:
		v.add("health_status", "must be one of unknown, healthy, degraded, failing")
	}

	if s.Priority < MinPriority || s.Priority > MaxPriority {
		v.add("priority", "must be between %d and %d, got %d", MinPriority, MaxPriority, s.Priority)
	}
	if s.FetchIntervalSeconds < MinFetchIntervalSeconds || s.FetchIntervalSeconds > MaxFetchIntervalSeconds {
		v.add("fetch_interval_seconds", "must be between %d and %d, got %d",
			MinFetchIntervalSeconds, MaxFetchIntervalSeconds, s.FetchIntervalSeconds)
	}
	if s.ConsecutiveFailures < 0 {
		v.add("consecutive_failures", "must not be negative")
	}

	if !isAlpha(s.Language, 2) {
		v.add("language", "must be a two-letter ISO 639-1 code")
	}
	if !isAlpha(s.Country, 2) {
		v.add("country", "must be a two-letter ISO 3166-1 alpha-2 code")
	}
	if len(s.State) > MaxRegionLength {
		v.add("state", "must be at most %d characters", MaxRegionLength)
	}
	if len(s.City) > MaxRegionLength {
		v.add("city", "must be at most %d characters", MaxRegionLength)
	}

	return v.err()
}

// validateFeedURL checks the shape of a feed URL. The network-level SSRF guard
// (DNS resolution and private-range blocking) lives in internal/httpclient,
// because it can only be applied at connection time; this rejects the URLs that
// never need resolving in the first place.
func validateFeedURL(v *validator, raw string) {
	if raw == "" {
		v.add("feed_url", "must not be empty")
		return
	}
	if len(raw) > MaxFeedURLLength {
		v.add("feed_url", "must be at most %d characters, got %d", MaxFeedURLLength, len(raw))
		return
	}
	if strings.ContainsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) {
		v.add("feed_url", "must not contain whitespace or control characters")
		return
	}

	u, err := url.Parse(raw)
	if err != nil {
		v.add("feed_url", "must be a valid absolute URL")
		return
	}
	switch strings.ToLower(u.Scheme) {
	case "http", "https":
	default:
		v.add("feed_url", "must use the http or https scheme")
	}
	if u.Host == "" {
		v.add("feed_url", "must include a host")
	}
	// Credentials in the URL would be persisted and echoed back by the API.
	if u.User != nil {
		v.add("feed_url", "must not embed credentials")
	}
}

// isAlpha reports whether s is exactly n ASCII letters.
func isAlpha(s string, n int) bool {
	if len(s) != n {
		return false
	}
	for _, r := range s {
		if r > unicode.MaxASCII || !unicode.IsLetter(r) {
			return false
		}
	}
	return true
}
