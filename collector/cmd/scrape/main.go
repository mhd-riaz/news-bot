// Command scrape runs full-text enrichment by hand: it works through the
// backlog of articles whose feed sent only a teaser, fetching each one's own
// page where its publisher permits it.
//
// It shares nothing in flight with the scheduled enrichment loop other than
// the database: an article is claimed atomically before it is fetched, so
// running this alongside a live deployment cannot duplicate work.
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
	limit := flag.Int("limit", 0, "how many articles to attempt (0 uses scraper.batch_size)")
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
	logger = logger.With("service", cfg.App.Name, "command", "scrape", "version", version)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()

	client, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name + "-scrape",
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

	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("mongodb is not reachable at %s: %w", cfg.Mongo.RedactedURI(), err)
	}

	batch := *limit
	if batch <= 0 {
		batch = cfg.Scraper.BatchSize
	}

	enrichment := app.NewEnrichmentService(cfg, client.Database(), time.Now, logger)
	res, err := enrichment.ProcessBacklog(ctx, batch)
	if err != nil {
		return fmt.Errorf("process backlog: %w", err)
	}

	logger.Info("enrichment run complete",
		"claimed", res.Claimed,
		"succeeded", res.Succeeded,
		"no_new_content", res.NoNewContent,
		"retrying", res.Retrying,
		"terminal", res.Terminal,
	)
	return nil
}

func defaultConfigPath() string {
	if p := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); p != "" {
		return p
	}
	return config.DefaultPath
}
