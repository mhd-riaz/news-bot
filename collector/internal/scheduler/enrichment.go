package scheduler

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/riaz/newscollector/internal/service"
)

// Backlog is the part of the enrichment service the scheduler needs.
type Backlog interface {
	ProcessBacklog(ctx context.Context, limit int) (service.BacklogResult, error)
}

// EnrichmentConfig tunes the enrichment loop.
type EnrichmentConfig struct {
	// Interval is how often the backlog is looked at.
	Interval time.Duration

	// BatchSize bounds one tick's work.
	BatchSize int
}

// EnrichmentScheduler polls the full-text enrichment backlog on a timer.
//
// Unlike Scheduler, one tick is a single call: ProcessBacklog already claims
// and attempts its articles one at a time, pacing itself per host through the
// shared rate limiter, so there is no batch of goroutines here to fan out or
// wait for.
type EnrichmentScheduler struct {
	backlog Backlog
	cfg     EnrichmentConfig
	logger  *slog.Logger
}

// NewEnrichment wires the enrichment scheduler.
func NewEnrichment(backlog Backlog, cfg EnrichmentConfig, logger *slog.Logger) *EnrichmentScheduler {
	if logger == nil {
		logger = slog.Default()
	}
	return &EnrichmentScheduler{backlog: backlog, cfg: cfg, logger: logger}
}

// Run processes the backlog every Interval until ctx is cancelled.
//
// A tick is only started once the previous one has finished, so a batch that
// takes longer than the interval delays the next batch rather than stacking a
// second one on top of it.
func (s *EnrichmentScheduler) Run(ctx context.Context) error {
	if err := s.validate(); err != nil {
		return err
	}

	s.logger.Info("enrichment scheduler started", "interval", s.cfg.Interval, "batch_size", s.cfg.BatchSize)

	ticker := time.NewTicker(s.cfg.Interval)
	defer ticker.Stop()

	for {
		s.tick(ctx)

		select {
		case <-ctx.Done():
			s.logger.Info("enrichment scheduler stopped")
			return nil
		case <-ticker.C:
		}
	}
}

func (s *EnrichmentScheduler) validate() error {
	switch {
	case s.cfg.Interval <= 0:
		return fmt.Errorf("scheduler: enrichment interval must be greater than zero, got %s", s.cfg.Interval)
	case s.cfg.BatchSize < 1:
		return fmt.Errorf("scheduler: enrichment batch size must be greater than zero, got %d", s.cfg.BatchSize)
	default:
		return nil
	}
}

// tick processes one batch of the backlog.
func (s *EnrichmentScheduler) tick(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}

	res, err := s.backlog.ProcessBacklog(ctx, s.cfg.BatchSize)
	if err != nil {
		// A cancelled context during shutdown is not a fault worth reporting.
		if ctx.Err() == nil {
			s.logger.ErrorContext(ctx, "enrichment backlog failed", "error", err)
		}
		return
	}
	if res.Claimed == 0 {
		return
	}

	s.logger.InfoContext(ctx, "enrichment backlog processed",
		"claimed", res.Claimed, "succeeded", res.Succeeded, "no_new_content", res.NoNewContent,
		"retrying", res.Retrying, "terminal", res.Terminal)
}
