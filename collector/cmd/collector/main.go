// Command collector runs collections by hand. With -source it collects one
// feed immediately, whatever its schedule says; with no flag it collects every
// source currently due, which is what the scheduler does on a tick.
//
// It takes the same per-source leases the scheduler does, so running it against
// a live deployment cannot collide with the scheduled collection of the same
// source.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/riaz/newscollector/internal/app"
	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
	"github.com/riaz/newscollector/internal/service"
)

// version is overridden at build time with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	configPath := flag.String("config", defaultConfigPath(), "path to the YAML configuration file")
	envPath := flag.String("env", config.EnvFilePath(), "path to the dotenv file holding secrets")
	sourceID := flag.String("source", "", "collect only this source, ignoring its schedule")
	limit := flag.Int("limit", domain.DefaultListLimit, "how many due sources to collect when -source is not given")
	timeout := flag.Duration("timeout", 10*time.Minute, "overall time budget for the run")
	flag.Parse()

	if err := config.LoadEnvFile(*envPath); err != nil {
		return err
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		return err
	}

	logger, err := observability.NewLogger(cfg.Logging.Level, cfg.Logging.Format, os.Stdout)
	if err != nil {
		return err
	}
	logger = logger.With("service", cfg.App.Name, "command", "collector", "version", version)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()

	client, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name + "-collector",
		ConnectTimeout:         cfg.Mongo.ConnectTimeout,
		ServerSelectionTimeout: cfg.Mongo.ServerSelectionTimeout,
		OperationTimeout:       cfg.Mongo.OperationTimeout,
		MaxPoolSize:            cfg.Mongo.MaxPoolSize,
		MinPoolSize:            cfg.Mongo.MinPoolSize,
	})
	if err != nil {
		return err
	}
	defer func() {
		closeCtx, closeCancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
		defer closeCancel()
		if err := client.Close(closeCtx); err != nil {
			logger.Error("closing mongodb failed", "error", err)
		}
	}()

	// Unlike the API, a collection has nothing useful to do without the database.
	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("mongodb is not reachable at %s: %w", cfg.Mongo.RedactedURI(), err)
	}

	collector, err := app.NewCollectionService(cfg, client.Database(), time.Now, logger)
	if err != nil {
		return err
	}

	if *sourceID != "" {
		return collectOne(ctx, collector, logger, *sourceID)
	}
	return collectDue(ctx, collector, logger, *limit)
}

// collectOne collects a single named source.
func collectOne(ctx context.Context, collector *service.CollectionService, logger *slog.Logger, id string) error {
	run, err := collector.CollectByID(ctx, id)
	if err != nil {
		return describeError(id, err)
	}
	report(logger, run)
	return nil
}

// collectDue works through the sources whose next collection has come round.
// Sources are collected one at a time: this is an operator's foreground command,
// and the scheduler is what exists to collect in parallel.
func collectDue(ctx context.Context, collector *service.CollectionService, logger *slog.Logger, limit int) error {
	due, err := collector.Due(ctx, limit)
	if err != nil {
		return fmt.Errorf("list due sources: %w", err)
	}
	if len(due) == 0 {
		logger.Info("no sources are due")
		return nil
	}

	logger.Info("collecting due sources", "sources", len(due))

	var collected, skipped int
	for i := range due {
		run, err := collector.Collect(ctx, &due[i])
		switch {
		case errors.Is(err, service.ErrLocked):
			skipped++
			logger.Info("skipped: another collector holds this source", "source_id", due[i].ID)
		case err != nil:
			return describeError(due[i].ID, err)
		default:
			collected++
			report(logger, run)
		}
	}

	logger.Info("collection complete", "collected", collected, "skipped", skipped, "due", len(due))
	return nil
}

// report logs the outcome of one run. A failed collection is a recorded
// outcome, not a command failure: the run says why, and the exit code stays
// zero so a batch is not abandoned because one publisher is down.
func report(logger *slog.Logger, run *domain.CollectionRun) {
	logger.Info("collected source",
		"run_id", run.ID,
		"source_id", run.SourceID,
		"status", string(run.Status),
		"items_found", run.ItemsFound,
		"items_stored", run.ItemsStored,
		"items_duplicate", run.ItemsDuplicate,
		"items_invalid", run.ItemsInvalid,
		"duration_ms", run.DurationMS,
		"error", run.Error,
	)
}

func describeError(sourceID string, err error) error {
	switch {
	case errors.Is(err, service.ErrNotFound):
		return fmt.Errorf("no source with id %q", sourceID)
	case errors.Is(err, service.ErrSourceDisabled):
		return fmt.Errorf("source %s is disabled; enable it before collecting it", sourceID)
	default:
		return fmt.Errorf("collect source %s: %w", sourceID, err)
	}
}

func defaultConfigPath() string {
	if p := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); p != "" {
		return p
	}
	return config.DefaultPath
}
