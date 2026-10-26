// Command backfill fills C1 fields on legacy articles without changing their
// existing topics or raw article text. Re-running it safely resumes at the
// first article that still lacks content_rev.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/riaz/newscollector/internal/app"
	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
)

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
	limit := flag.Int("limit", 1000, "maximum number of legacy articles to backfill")
	delay := flag.Duration("delay", time.Second, "pause between classifier batches")
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
	logger = logger.With("service", cfg.App.Name, "command", "backfill", "version", version)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()

	client, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name + "-backfill",
		ConnectTimeout:         cfg.Mongo.ConnectTimeout,
		ServerSelectionTimeout: cfg.Mongo.ServerSelectionTimeout,
		OperationTimeout:       cfg.Mongo.OperationTimeout,
		MaxConnIdleTime:        cfg.Mongo.MaxConnIdleTime,
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

	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("mongodb is not reachable at %s: %w", cfg.Mongo.RedactedURI(), err)
	}
	backfill, err := app.NewDerivedFieldBackfillService(cfg, client.Database(), *delay)
	if err != nil {
		return err
	}
	result, err := backfill.Run(ctx, *limit)
	if err != nil {
		return fmt.Errorf("run C1 backfill: %w", err)
	}
	logger.Info("C1 backfill complete",
		"batches", result.Batches,
		"scanned", result.Scanned,
		"updated", result.Updated,
		"skipped", result.Skipped,
	)
	return nil
}

func defaultConfigPath() string {
	if path := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); path != "" {
		return path
	}
	return config.DefaultPath
}
