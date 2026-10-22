package service

import (
	"context"
	"fmt"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// ReadEventService records what a reader did with the feed.
//
// Telemetry is write-only here: it is consumed offline by the training
// pipeline, never served back over HTTP.
type ReadEventService struct {
	repo repository.ReadEventRepository
	now  func() time.Time
}

// NewReadEventService wires the service. now is injected so a test can date
// events without sleeping.
func NewReadEventService(repo repository.ReadEventRepository, now func() time.Time) *ReadEventService {
	return &ReadEventService{repo: repo, now: now}
}

// Record validates a batch and stores it, reporting how many were written.
//
// One invalid event rejects the whole batch rather than being dropped. The only
// client is this application's own page, so an event that fails validation is
// this system's bug, and swallowing it would hide a telemetry defect behind
// data that merely looks thinner than expected.
func (s *ReadEventService) Record(ctx context.Context, inputs []domain.ReadEventInput) (int64, error) {
	var v domain.FieldErrors
	switch {
	case len(inputs) == 0:
		v.Add("events", "must contain at least one event")
	case len(inputs) > domain.MaxReadEventBatch:
		v.Add("events", fmt.Sprintf("must contain at most %d events", domain.MaxReadEventBatch))
	}
	if err := v.Err(); err != nil {
		return 0, err
	}

	now := s.now()
	events := make([]domain.ReadEvent, 0, len(inputs))
	for _, in := range inputs {
		event, err := domain.NewReadEvent(in, now)
		if err != nil {
			return 0, err
		}
		events = append(events, *event)
	}

	written, err := s.repo.CreateMany(ctx, events)
	if err != nil {
		return 0, translate(err)
	}
	return written, nil
}
