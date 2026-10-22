// Command seed applies a declarative list of sources to the database. The API
// does the same thing at startup; this exists for a local run, and for applying
// an edited file without restarting anything. It is idempotent: running it
// twice creates nothing the second time.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/riaz/newscollector/internal/bootstrap"
	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
	mongorepo "github.com/riaz/newscollector/internal/repository/mongo"
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
	sourcesPath := flag.String("sources", "", "path or https URL of the YAML seed file; defaults to bootstrap.sources_path")
	dryRun := flag.Bool("dry-run", false, "validate the seed file without writing to the database")
	flag.Parse()

	if err := config.LoadEnvFile(*envPath); err != nil {
		return err
	}

	cfg, err := config.Load(*configPath, config.SkipAuthValidation)
	if err != nil {
		return err
	}
	if *sourcesPath == "" {
		*sourcesPath = cfg.Bootstrap.SourcesPath
	}
	if *sourcesPath == "" {
		return errors.New("no seed file: pass -sources, or set bootstrap.sources_path")
	}

	logger, err := observability.NewLogger(cfg.Logging.Level, cfg.Logging.Format, os.Stdout)
	if err != nil {
		return err
	}
	logger = logger.With("service", cfg.App.Name, "command", "seed", "version", version)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Validating everything before the first write stops a typo halfway down the
	// file from leaving the database half-seeded.
	inputs, err := bootstrap.LoadSources(ctx, *sourcesPath)
	if err != nil {
		return err
	}
	if *dryRun {
		logger.Info("seed file is valid", "path", *sourcesPath, "sources", len(inputs))
		return nil
	}

	client, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name,
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
		closeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
		defer cancel()
		if err := client.Close(closeCtx); err != nil {
			logger.Error("closing mongodb failed", "error", err)
		}
	}()

	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("mongodb is not reachable at %s: %w", cfg.Mongo.RedactedURI(), err)
	}

	svc := service.NewSourceService(mongorepo.NewSourceRepository(client.Database()), time.Now)
	return bootstrap.SyncSources(ctx, svc, inputs, logger)
}

// defaultConfigPath lets the container point at a mounted config without flags.
func defaultConfigPath() string {
	if p := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); p != "" {
		return p
	}
	return config.DefaultPath
}
