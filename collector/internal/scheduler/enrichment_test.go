package scheduler

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/service"
)

// fakeBacklog is a Backlog whose ProcessBacklog call is entirely scripted, so
// a test can assert what the scheduler asked for without a real enrichment
// service, exactly as fakeCollector does for the collection scheduler.
type fakeBacklog struct {
	result service.BacklogResult
	err    error

	calls atomic.Int64
	limit atomic.Int64

	// done, when set, is closed once calls reaches expect. TestRunTicksRepeatedly
	// uses it to know the scheduler has ticked the number of times it wants
	// without polling.
	done   chan struct{}
	expect int64
}

func (f *fakeBacklog) ProcessBacklog(_ context.Context, limit int) (service.BacklogResult, error) {
	f.limit.Store(int64(limit))
	if n := f.calls.Add(1); f.done != nil && n == f.expect {
		close(f.done)
	}
	return f.result, f.err
}

func testEnrichmentConfig() EnrichmentConfig {
	return EnrichmentConfig{Interval: time.Hour, BatchSize: 50}
}

func TestEnrichmentTickProcessesABatch(t *testing.T) {
	b := &fakeBacklog{result: service.BacklogResult{Claimed: 3, Succeeded: 2, Retrying: 1}}
	s := NewEnrichment(b, testEnrichmentConfig(), discardLogger())

	s.tick(t.Context())

	if b.calls.Load() != 1 {
		t.Fatalf("ProcessBacklog was called %d times, want 1", b.calls.Load())
	}
	if b.limit.Load() != 50 {
		t.Errorf("limit = %d, want the configured batch size of 50", b.limit.Load())
	}
}

func TestEnrichmentTickSurvivesAFailure(t *testing.T) {
	b := &fakeBacklog{err: errors.New("mongo: no reachable servers")}
	s := NewEnrichment(b, testEnrichmentConfig(), discardLogger())

	// Must not panic, and must not stop the scheduler.
	s.tick(t.Context())
	if b.calls.Load() != 1 {
		t.Errorf("ProcessBacklog was called %d times, want 1", b.calls.Load())
	}
}

func TestEnrichmentTickDoesNothingOnAnAlreadyCancelledContext(t *testing.T) {
	b := &fakeBacklog{}
	s := NewEnrichment(b, testEnrichmentConfig(), discardLogger())

	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	s.tick(ctx)

	if b.calls.Load() != 0 {
		t.Error("a cancelled context still reached the backlog")
	}
}

func TestEnrichmentRunRejectsAnUnusableConfiguration(t *testing.T) {
	tests := []struct {
		name string
		cfg  EnrichmentConfig
	}{
		{"no interval", EnrichmentConfig{BatchSize: 1}},
		{"no batch", EnrichmentConfig{Interval: time.Second}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := NewEnrichment(&fakeBacklog{}, tt.cfg, discardLogger()).Run(t.Context()); err == nil {
				t.Fatal("Run accepted an unusable configuration")
			}
		})
	}
}

func TestEnrichmentRunTicksRepeatedly(t *testing.T) {
	b := &fakeBacklog{done: make(chan struct{}), expect: 3}

	cfg := testEnrichmentConfig()
	cfg.Interval = 5 * time.Millisecond

	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- NewEnrichment(b, cfg, discardLogger()).Run(ctx) }()

	select {
	case <-b.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the enrichment scheduler did not tick three times within five seconds")
	}
	cancel()
	<-errCh
}

func TestEnrichmentRunDoesNothingWhenAlreadyCancelled(t *testing.T) {
	b := &fakeBacklog{}

	ctx, cancel := context.WithCancel(t.Context())
	cancel()

	if err := NewEnrichment(b, testEnrichmentConfig(), discardLogger()).Run(ctx); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if b.calls.Load() != 0 {
		t.Errorf("the scheduler did work after cancellation: %d calls", b.calls.Load())
	}
}

func TestNewEnrichmentAcceptsANilLogger(t *testing.T) {
	// Must not panic when no logger is supplied.
	NewEnrichment(&fakeBacklog{}, testEnrichmentConfig(), nil)
}
