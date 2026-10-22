// Command migrate creates the application's MongoDB collections and indexes.
// The API does the same thing at startup; this exists for a local run and for
// migrating without restarting anything. It is idempotent.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/riaz/newscollector/internal/bootstrap"
	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	configPath := flag.String("config", defaultConfigPath(), "path to the YAML configuration file")
	envPath := flag.String("env", config.EnvFilePath(), "path to the dotenv file holding secrets")
	timeout := flag.Duration("timeout", 2*time.Minute, "overall time budget for the migration")
	flag.Parse()

	if err := config.LoadEnvFile(*envPath); err != nil {
		return err
	}

	cfg, err := config.Load(*configPath, config.SkipAuthValidation)
	if err != nil {
		return err
	}

	logger, err := observability.NewLogger(cfg.Logging.Level, cfg.Logging.Format, os.Stdout)
	if err != nil {
		return err
	}
	logger = logger.With("command", "migrate", "database", cfg.Mongo.Database)

	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()

	client, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name + "-migrate",
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

	// Unlike the API, a migration has nothing useful to do without the database.
	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("cannot reach mongodb at %s: %w", cfg.Mongo.RedactedURI(), err)
	}

	if err := bootstrap.Migrate(ctx, client.Database(), logger); err != nil {
		return err
	}

	logger.Info("migration complete")
	return nil
}
func defaultConfigPath() string {
	if p := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); p != "" {
		return p
	}
	return config.DefaultPath
}
