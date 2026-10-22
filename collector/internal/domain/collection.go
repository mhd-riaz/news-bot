package domain

import (
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

// RunStatus is the outcome of one collection attempt.
type RunStatus string

// The outcomes a collection can have. partial is deliberately separate from
// success: the collection stored what it could, but the feed also lost entries
// or was cut short, and a source quietly shedding entries on every poll is
// worth being able to find.
const (
	RunStatusSuccess     RunStatus = "success"
	RunStatusNotModified RunStatus = "not_modified"
	RunStatusPartial     RunStatus = "partial"
	RunStatusFailed      RunStatus = "failed"
)

// MaxRunErrorLength bounds the stored failure reason. The reason is a fixed
// phrase chosen by the caller rather than a raw error, and the bound is what
// stops a future one from growing a run document without limit.
const MaxRunErrorLength = 300

// CollectionRun is the audit record of one collection attempt against one
// source. It is written whether the attempt succeeded or failed, because a
// source that has stopped answering is only visible in the record of the
// attempts that got nothing.
//
// Field names mirror the index plan in internal/mongodb.
type CollectionRun struct {
	ID       string `bson:"_id"`
	SourceID string `bson:"source_id"`
	// SourceName is denormalised so listing runs does not have to join.
	SourceName string `bson:"source_name"`

	Status      RunStatus `bson:"status"`
	StartedAt   time.Time `bson:"started_at"`
	CompletedAt time.Time `bson:"completed_at"`
	DurationMS  int64     `bson:"duration_ms"`

	// FeedType is the dialect the collector detected, which may differ from the
	// type the source was registered with.
	FeedType string `bson:"feed_type,omitempty"`

	ItemsFound     int `bson:"items_found"`
	ItemsStored    int `bson:"items_stored"`
	ItemsDuplicate int `bson:"items_duplicate"`
	ItemsInvalid   int `bson:"items_invalid"`
	ItemsSkipped   int `bson:"items_skipped"`

	// Truncated means the feed carried more entries than one collection accepts.
	Truncated bool `bson:"truncated"`

	// Error is a fixed, caller-safe phrase. It is served by the API, so it must
	// never carry a driver message, a host name or any other internal detail.
	Error string `bson:"error,omitempty"`
}

// NewCollectionRun opens a run against src. The run is finished by Complete or
// Fail; until then it carries no outcome.
func NewCollectionRun(src Source, startedAt time.Time) (*CollectionRun, error) {
	id, err := uuid.NewV7()
	if err != nil {
		return nil, fmt.Errorf("domain: generate collection run id: %w", err)
	}
	return &CollectionRun{
		ID:         id.String(),
		SourceID:   src.ID,
		SourceName: truncate(collapseSpace(src.Name), MaxNameLength),
		StartedAt:  storedTime(startedAt),
	}, nil
}

// Complete closes a run that reached the publisher. notModified reports whether
// the publisher answered 304, which is a successful poll that transferred
// nothing rather than a collection that found nothing.
func (r *CollectionRun) Complete(now time.Time, notModified bool) {
	switch {
	case notModified:
		r.Status = RunStatusNotModified
	case r.ItemsSkipped > 0 || r.ItemsInvalid > 0 || r.Truncated:
		r.Status = RunStatusPartial
	default:
		r.Status = RunStatusSuccess
	}
	r.finish(now)
}

// Fail closes a run that did not produce articles. reason must be a fixed
// phrase safe to serve to an API caller.
func (r *CollectionRun) Fail(reason string, now time.Time) {
	r.Status = RunStatusFailed
	r.Error = truncate(collapseSpace(reason), MaxRunErrorLength)
	r.finish(now)
}

// finish records when the attempt ended and how long it took. A clock that
// jumps backwards yields zero rather than a negative duration.
func (r *CollectionRun) finish(now time.Time) {
	r.CompletedAt = storedTime(now)
	if d := r.CompletedAt.Sub(r.StartedAt); d > 0 {
		r.DurationMS = d.Milliseconds()
	}
}

// CollectionRunFilter narrows a run listing. Every field is optional; a nil or
// empty field is not applied.
type CollectionRunFilter struct {
	SourceID string
	Status   *RunStatus

	Limit  int
	Offset int
}

// CollectionRunPage is one page of a listing plus the total matching the filter.
type CollectionRunPage struct {
	Items  []CollectionRun
	Total  int64
	Limit  int
	Offset int
}

// Normalize applies the pagination defaults and canonicalises the enum field.
func (f *CollectionRunFilter) Normalize() {
	if f.Limit == 0 {
		f.Limit = DefaultListLimit
	}
	f.SourceID = strings.TrimSpace(f.SourceID)
	if f.Status != nil {
		s := RunStatus(strings.ToLower(strings.TrimSpace(string(*f.Status))))
		f.Status = &s
	}
}

// Validate rejects out-of-range pagination, an unknown status and a source
// identifier that is not a UUID, before any of them reaches a query.
func (f CollectionRunFilter) Validate() error {
	var v validator

	if f.Limit < 1 || f.Limit > MaxListLimit {
		v.add("limit", "must be between 1 and %d, got %d", MaxListLimit, f.Limit)
	}
	if f.Offset < 0 {
		v.add("offset", "must not be negative, got %d", f.Offset)
	}
	if f.SourceID != "" {
		if _, err := uuid.Parse(f.SourceID); err != nil {
			v.add("source_id", "must be a valid UUID")
		}
	}
	if f.Status != nil {
		switch *f.Status {
		case RunStatusSuccess, RunStatusNotModified, RunStatusPartial, RunStatusFailed:
		default:
			v.add("status", "must be one of success, not_modified, partial, failed")
		}
	}

	return v.err()
}
