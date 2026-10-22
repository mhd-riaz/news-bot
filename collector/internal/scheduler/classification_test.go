package scheduler

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/service"
)

type fakeClassificationBacklog struct {
	calls int
	limit int
	err   error
}

func (f *fakeClassificationBacklog) ProcessBacklog(_ context.Context, limit int) (service.ClassificationBacklogResult, error) {
	f.calls++
	f.limit = limit
	return service.ClassificationBacklogResult{Claimed: 1}, f.err
}

func TestClassificationTickProcessesABatchAndSurvivesFailures(t *testing.T) {
	backlog := &fakeClassificationBacklog{}
	scheduler := NewClassification(backlog, ClassificationConfig{Interval: time.Hour, BatchSize: 4}, discardLogger())
	scheduler.tick(t.Context())
	if backlog.calls != 1 || backlog.limit != 4 {
		t.Fatalf("backlog calls/limit = %d/%d, want 1/4", backlog.calls, backlog.limit)
	}
	backlog.err = errors.New("unavailable")
	scheduler.tick(t.Context())
	if backlog.calls != 2 {
		t.Errorf("backlog calls = %d, want 2", backlog.calls)
	}
}

func TestClassificationRunRejectsInvalidConfig(t *testing.T) {
	for _, cfg := range []ClassificationConfig{{BatchSize: 1}, {Interval: time.Second}} {
		if err := NewClassification(&fakeClassificationBacklog{}, cfg, discardLogger()).Run(t.Context()); err == nil {
			t.Fatal("Run accepted invalid classification scheduler config")
		}
	}
}
