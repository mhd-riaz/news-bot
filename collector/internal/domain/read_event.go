package domain

import (
	"fmt"
	"time"

	"github.com/google/uuid"
)

// ReadEventKind names what a reader did with a card or an article.
type ReadEventKind string

// The three things worth recording about a reader.
const (
	// ReadEventImpression is a card that entered the viewport. It is the only
	// source of negative examples a ranker will ever have: a click log records
	// what was chosen but never what was offered and passed over.
	ReadEventImpression ReadEventKind = "impression"

	// ReadEventClick is a reader opening the article.
	ReadEventClick ReadEventKind = "click"

	// ReadEventDwell is how long an article was actually on screen, which
	// separates a headline that was misleading from one that delivered.
	ReadEventDwell ReadEventKind = "dwell"
)

// Valid reports whether k is a kind this package defines.
func (k ReadEventKind) Valid() bool {
	return k == ReadEventImpression || k == ReadEventClick || k == ReadEventDwell
}

// PositionUnknown marks an event that did not arrive from a feed listing — a
// bookmarked link, or a URL someone shared. It is negative rather than zero so
// that correcting for position bias cannot mistake "not from a feed" for "top
// of the feed", which is the position with the strongest bias of all.
const PositionUnknown = -1

// Bounds on one reported event and on a batch of them.
const (
	// MaxReadEventBatch caps one flush. The browser batches a screenful at a
	// time, so this is generous; it exists to bound the work a single request
	// can ask for.
	MaxReadEventBatch = 200

	// MaxFeedPosition bounds how deep into a feed an event may claim to be.
	MaxFeedPosition = 10_000

	// MaxReadEventDwell caps a reported dwell. A tab left open overnight is not
	// engagement, and an unbounded value would dominate any average computed
	// over it.
	MaxReadEventDwell = time.Hour

	// MaxReadEventAge bounds how far back a flush may date its events. The
	// browser holds them only until the page is hidden or unloaded, so anything
	// older is a stale queue or a forged one.
	MaxReadEventAge = 6 * time.Hour
)

// ReadEvent is one recorded interaction.
//
// It is written by the browser and by the article route, and read only offline,
// so it carries no denormalised article fields: whatever Phase 8 needs about
// the article it joins from the article itself, which cannot then drift.
type ReadEvent struct {
	ID string `bson:"_id"`

	ArticleID string        `bson:"article_id"`
	Kind      ReadEventKind `bson:"kind"`

	// Position is where the card sat in the feed, zero-based, or
	// PositionUnknown. Without it a ranker learns that the top of the page is
	// good rather than that the article was.
	Position int `bson:"position_in_feed"`

	// DwellMillis is set only on a dwell event.
	DwellMillis int64 `bson:"dwell_ms,omitempty"`

	OccurredAt time.Time `bson:"occurred_at"`
	RecordedAt time.Time `bson:"recorded_at"`
}

// ReadEventInput is one event as the browser reports it.
//
// Age, not a timestamp, is what crosses the wire: an event is queued in the
// page and flushed later, and deriving the instant from the server's own clock
// minus a reported elapsed time keeps a wrong or hostile client clock out of
// the data entirely.
type ReadEventInput struct {
	ArticleID string
	Kind      ReadEventKind
	Position  int
	Dwell     time.Duration
	Age       time.Duration
}

// NewReadEvent validates one reported event and dates it against now.
func NewReadEvent(in ReadEventInput, now time.Time) (*ReadEvent, error) {
	if err := in.validate(); err != nil {
		return nil, err
	}

	id, err := uuid.NewV7()
	if err != nil {
		return nil, fmt.Errorf("domain: generate read event id: %w", err)
	}

	return &ReadEvent{
		ID:          id.String(),
		ArticleID:   in.ArticleID,
		Kind:        in.Kind,
		Position:    in.Position,
		DwellMillis: in.Dwell.Milliseconds(),
		OccurredAt:  storedTime(now.Add(-in.Age)),
		RecordedAt:  storedTime(now),
	}, nil
}

func (in ReadEventInput) validate() error {
	var v validator

	if _, err := uuid.Parse(in.ArticleID); err != nil {
		v.add("article_id", "must be a valid UUID")
	}
	if !in.Kind.Valid() {
		v.add("kind", "must be one of impression, click, dwell")
	}
	if in.Position < PositionUnknown || in.Position > MaxFeedPosition {
		v.add("position", "must be between %d and %d", PositionUnknown, MaxFeedPosition)
	}
	if in.Age < 0 || in.Age > MaxReadEventAge {
		v.add("age_ms", "must be between 0 and %d", MaxReadEventAge.Milliseconds())
	}

	// Dwell is carried only by a dwell event. Allowing it elsewhere would leave
	// two ways to express the same thing and no way to tell which was meant.
	switch {
	case in.Kind == ReadEventDwell && (in.Dwell <= 0 || in.Dwell > MaxReadEventDwell):
		v.add("dwell_ms", "must be between 1 and %d", MaxReadEventDwell.Milliseconds())
	case in.Kind != ReadEventDwell && in.Dwell != 0:
		v.add("dwell_ms", "is only valid on a dwell event")
	}

	return v.err()
}
