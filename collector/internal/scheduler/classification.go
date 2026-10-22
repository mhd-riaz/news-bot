package scheduler

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/riaz/newscollector/internal/service"
)

// ClassificationBacklog is the classification service behavior the scheduler needs.
type ClassificationBacklog interface {
	ProcessBacklog(context.Context, int) (service.ClassificationBacklogResult, error)
}

// ClassificationConfig controls classification backlog polling.
type ClassificationConfig struct {
	Interval  time.Duration
	BatchSize int
}

// ClassificationScheduler periodically processes pending classification work.
type ClassificationScheduler struct {
	backlog ClassificationBacklog
	cfg     ClassificationConfig
	logger  *slog.Logger
}

// NewClassification creates a scheduler for the classifier retry backlog.
func NewClassification(backlog ClassificationBacklog, cfg ClassificationConfig, logger *slog.Logger) *ClassificationScheduler {
	if logger == nil {
		logger = slog.Default()
	}
	return &ClassificationScheduler{backlog: backlog, cfg: cfg, logger: logger}
}

// Run processes the backlog until ctx is cancelled.
func (s *ClassificationScheduler) Run(ctx context.Context) error {
	if s.cfg.Interval <= 0 {
		return fmt.Errorf("scheduler: classification interval must be greater than zero, got %s", s.cfg.Interval)
	}
	if s.cfg.BatchSize < 1 {
		return fmt.Errorf("scheduler: classification batch size must be greater than zero, got %d", s.cfg.BatchSize)
	}
	ticker := time.NewTicker(s.cfg.Interval)
	defer ticker.Stop()
	for {
		s.tick(ctx)
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func (s *ClassificationScheduler) tick(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}
	started := time.Now()
	result, err := s.backlog.ProcessBacklog(ctx, s.cfg.BatchSize)
	if err != nil {
		if ctx.Err() == nil {
			s.logger.ErrorContext(ctx, "classification backlog unavailable", "error", err,
				"batch_size", s.cfg.BatchSize, "latency", time.Since(started))
		}
		return
	}
	if result.Claimed > 0 || result.StaleClaimsReleased > 0 {
		s.logger.InfoContext(ctx, "classification backlog processed",
			"batch_size", s.cfg.BatchSize, "latency", time.Since(started),
			"claimed", result.Claimed, "classified", result.Classified,
			"unsorted", result.Unsorted, "pending", result.Retrying, "failed", result.Failed,
			"attempts", result.Attempts, "max_backfill_lag", result.MaxBackfillLag,
			"stale_claims_released", result.StaleClaimsReleased)
	}
}
