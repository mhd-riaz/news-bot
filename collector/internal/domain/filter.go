package domain

import "strings"

// Pagination bounds for listing. The maximum is a hard cap: a caller asking for
// more gets an error rather than a silently truncated page, so nobody builds on
// a page size the server will not honour.
const (
	DefaultListLimit = 50
	MaxListLimit     = 100
)

// SourceFilter narrows a source listing. Every field is optional; a nil or empty
// field is not applied. Values are validated against the same enums as the model,
// so a filter can never smuggle an arbitrary value into a query.
type SourceFilter struct {
	Enabled      *bool
	Type         *SourceType
	HealthStatus *HealthStatus
	Country      string
	State        string
	City         string

	Limit  int
	Offset int
}

// SourcePage is one page of a listing plus the total matching the filter, so a
// caller can render "showing 1-50 of 213" without a second request.
type SourcePage struct {
	Items  []Source
	Total  int64
	Limit  int
	Offset int
}

// Normalize applies the pagination defaults and canonicalises the region and
// enum fields the same way the model does.
func (f *SourceFilter) Normalize() {
	if f.Limit == 0 {
		f.Limit = DefaultListLimit
	}
	f.Country = strings.ToUpper(strings.TrimSpace(f.Country))
	f.State = strings.TrimSpace(f.State)
	f.City = strings.TrimSpace(f.City)

	if f.Type != nil {
		t := SourceType(strings.ToLower(strings.TrimSpace(string(*f.Type))))
		f.Type = &t
	}
	if f.HealthStatus != nil {
		h := HealthStatus(strings.ToLower(strings.TrimSpace(string(*f.HealthStatus))))
		f.HealthStatus = &h
	}
}

// Validate rejects out-of-range pagination and unknown enum values.
func (f SourceFilter) Validate() error {
	var v validator

	if f.Limit < 1 || f.Limit > MaxListLimit {
		v.add("limit", "must be between 1 and %d, got %d", MaxListLimit, f.Limit)
	}
	if f.Offset < 0 {
		v.add("offset", "must not be negative, got %d", f.Offset)
	}
	if f.Type != nil {
		switch *f.Type {
		case SourceTypeRSS, SourceTypeAtom:
		default:
			v.add("type", "must be one of rss, atom")
		}
	}
	if f.HealthStatus != nil {
		switch *f.HealthStatus {
		case HealthUnknown, HealthHealthy, HealthDegraded, HealthFailing:
		default:
			v.add("health_status", "must be one of unknown, healthy, degraded, failing")
		}
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

	return v.err()
}
