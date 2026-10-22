// Package scheduler drives collections on a timer. It owns when work happens
// and how much of it happens at once; what a collection actually does belongs
// to the collection service, and which collector wins a contested source is
// settled by that service's leases.
package scheduler

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

// Collector is the part of the collection service the scheduler needs.
type Collector interface {
	Due(ctx context.Context, limit int) ([]domain.Source, error)
	Collect(ctx context.Context, src *domain.Source) (*domain.CollectionRun, error)
}

// Config tunes the loop.
type Config struct {
	// Interval is how often due sources are looked for.
	Interval time.Duration

	// BatchSize bounds one tick's work, so a long outage that leaves every
	// source overdue is worked through over several ticks instead of all at once.
	BatchSize int

	// MaxConcurrent bounds how many collections run at the same time, and with
	// it how many outbound connections and MongoDB operations are in flight.
	MaxConcurrent int
}

// Scheduler polls for due sources and collects them.
type Scheduler struct {
	collector Collector
	cfg       Config
	logger    *slog.Logger
}

// New wires the scheduler.
func New(collector Collector, cfg Config, logger *slog.Logger) *Scheduler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Scheduler{collector: collector, cfg: cfg, logger: logger}
}

// Run collects due sources every Interval until ctx is cancelled.
//
// A tick is only started once the previous one has finished, so a batch that
// takes longer than the interval delays the next batch rather than stacking a
// second one on top of it. Run returns only after the in-flight collections of
// the current tick have finished, so shutdown never abandons a held lease.
func (s *Scheduler) Run(ctx context.Context) error {
	if err := s.validate(); err != nil {
		return err
	}

	s.logger.Info("scheduler started",
		"interval", s.cfg.Interval, "batch_size", s.cfg.BatchSize, "max_concurrent", s.cfg.MaxConcurrent)

	ticker := time.NewTicker(s.cfg.Interval)
	defer ticker.Stop()

	for {
		s.tick(ctx)

		select {
		case <-ctx.Done():
			s.logger.Info("scheduler stopped")
			return nil
		case <-ticker.C:
		}
	}
}

func (s *Scheduler) validate() error {
	switch {
	case s.cfg.Interval <= 0:
		return fmt.Errorf("scheduler: interval must be greater than zero, got %s", s.cfg.Interval)
	case s.cfg.BatchSize < 1:
		return fmt.Errorf("scheduler: batch size must be greater than zero, got %d", s.cfg.BatchSize)
	case s.cfg.MaxConcurrent < 1:
		return fmt.Errorf("scheduler: max concurrent must be greater than zero, got %d", s.cfg.MaxConcurrent)
	default:
		return nil
	}
}

// tick collects one batch of due sources and waits for it to finish.
func (s *Scheduler) tick(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}

	due, err := s.collector.Due(ctx, s.cfg.BatchSize)
	if err != nil {
		// A cancelled context during shutdown is not a fault worth reporting.
		if ctx.Err() == nil {
			s.logger.ErrorContext(ctx, "listing due sources failed", "error", err)
		}
		return
	}
	if len(due) == 0 {
		return
	}

	s.logger.InfoContext(ctx, "collecting due sources", "sources", len(due))

	slots := make(chan struct{}, s.cfg.MaxConcurrent)
	var wg sync.WaitGroup

	for i := range due {
		select {
		case <-ctx.Done():
			wg.Wait()
			return
		case slots <- struct{}{}:
		}

		wg.Add(1)
		go func(src *domain.Source) {
			defer wg.Done()
			defer func() { <-slots }()
			s.collect(ctx, src)
		}(&due[i])
	}

	wg.Wait()
}

// collect runs one collection and reports its outcome.
//
// A panic is contained here rather than being allowed to take the process down:
// this goroutine has no request to fail, and one malformed feed must not stop
// the API it shares a process with. The panic is logged and the source is left
// to be retried on its schedule.
func (s *Scheduler) collect(ctx context.Context, src *domain.Source) {
	defer func() {
		if r := recover(); r != nil {
			s.logger.ErrorContext(ctx, "collection panicked", "source_id", src.ID, "panic", r)
		}
	}()

	run, err := s.collector.Collect(ctx, src)
	switch {
	case errors.Is(err, service.ErrLocked):
		s.logger.DebugContext(ctx, "another collector holds this source", "source_id", src.ID)
	case err != nil:
		s.logger.ErrorContext(ctx, "collecting source failed", "source_id", src.ID, "error", err)
	default:
		s.logger.InfoContext(ctx, "collected source",
			"source_id", src.ID,
			"status", string(run.Status),
			"items_found", run.ItemsFound,
			"items_stored", run.ItemsStored,
			"items_duplicate", run.ItemsDuplicate,
			"duration_ms", run.DurationMS,
		)
	}
}
