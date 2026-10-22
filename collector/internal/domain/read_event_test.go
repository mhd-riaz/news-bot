package domain

import (
	"errors"
	"testing"
	"time"
)

func TestNewReadEventDatesTheEventFromTheServerClock(t *testing.T) {
	now := time.Date(2026, 8, 23, 12, 0, 0, 0, time.UTC)

	event, err := NewReadEvent(ReadEventInput{
		ArticleID: "0198f3d2-3333-7000-8000-000000000001",
		Kind:      ReadEventImpression,
		Position:  4,
		Age:       90 * time.Second,
	}, now)
	if err != nil {
		t.Fatalf("NewReadEvent: %v", err)
	}

	if want := now.Add(-90 * time.Second); !event.OccurredAt.Equal(want) {
		t.Errorf("OccurredAt = %s, want %s", event.OccurredAt, want)
	}
	if !event.RecordedAt.Equal(now) {
		t.Errorf("RecordedAt = %s, want %s", event.RecordedAt, now)
	}
	if event.ID == "" {
		t.Error("ID is empty")
	}
}

func TestNewReadEventRejects(t *testing.T) {
	const article = "0198f3d2-3333-7000-8000-000000000001"
	now := time.Now()

	cases := []struct {
		name string
		in   ReadEventInput
	}{
		{"an article id that is not a UUID", ReadEventInput{ArticleID: "../../etc/passwd", Kind: ReadEventClick}},
		{"an unknown kind", ReadEventInput{ArticleID: article, Kind: "scrolled"}},
		{"a position below the unknown marker", ReadEventInput{ArticleID: article, Kind: ReadEventClick, Position: -2}},
		{"a position past the cap", ReadEventInput{ArticleID: article, Kind: ReadEventClick, Position: MaxFeedPosition + 1}},
		{"an age in the future", ReadEventInput{ArticleID: article, Kind: ReadEventClick, Age: -time.Second}},
		{"an age older than the queue can hold", ReadEventInput{ArticleID: article, Kind: ReadEventClick, Age: MaxReadEventAge + time.Second}},
		{"a dwell on a click", ReadEventInput{ArticleID: article, Kind: ReadEventClick, Dwell: time.Second}},
		{"a dwell event with no dwell", ReadEventInput{ArticleID: article, Kind: ReadEventDwell}},
		{"a dwell past the cap", ReadEventInput{ArticleID: article, Kind: ReadEventDwell, Dwell: MaxReadEventDwell + time.Second}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := NewReadEvent(tc.in, now); !errors.Is(err, ErrValidation) {
				t.Fatalf("error = %v, want ErrValidation", err)
			}
		})
	}
}

// A position of zero is the top of the feed, which carries the strongest
// position bias of all, so it must stay distinguishable from "not from a feed".
func TestReadEventKeepsPositionZeroDistinctFromUnknown(t *testing.T) {
	const article = "0198f3d2-3333-7000-8000-000000000001"
	now := time.Now()

	top, err := NewReadEvent(ReadEventInput{ArticleID: article, Kind: ReadEventClick, Position: 0}, now)
	if err != nil {
		t.Fatalf("NewReadEvent(top): %v", err)
	}
	direct, err := NewReadEvent(ReadEventInput{ArticleID: article, Kind: ReadEventClick, Position: PositionUnknown}, now)
	if err != nil {
		t.Fatalf("NewReadEvent(direct): %v", err)
	}

	if top.Position == direct.Position {
		t.Fatalf("position %d is used for both the top of the feed and an unknown slot", top.Position)
	}
}
