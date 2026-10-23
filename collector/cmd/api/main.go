// Command api serves the HTTP interface of the news collection system.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/riaz/newscollector/internal/app"
	"github.com/riaz/newscollector/internal/bootstrap"
	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/handler"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
	mongorepo "github.com/riaz/newscollector/internal/repository/mongo"
	"github.com/riaz/newscollector/internal/scheduler"
	"github.com/riaz/newscollector/internal/service"
	"github.com/riaz/newscollector/internal/web"
)

// version is overridden at build time with -ldflags "-X main.version=...".
var version = "dev"

// readinessCheckTimeout bounds the dependency probe inside /health/ready.
const readinessCheckTimeout = 2 * time.Second

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	configPath := flag.String("config", defaultConfigPath(), "path to the YAML configuration file")
	envPath := flag.String("env", config.EnvFilePath(), "path to the dotenv file holding secrets")
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
	logger = logger.With(
		"service", cfg.App.Name,
		"environment", cfg.App.Environment,
		"version", version,
	)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	mongoClient, err := mongodb.Connect(mongodb.Settings{
		URI:                    cfg.Mongo.URI,
		Database:               cfg.Mongo.Database,
		AppName:                cfg.App.Name,
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

	// A database outage must not stop the process from starting: liveness stays
	// green and readiness reports 503 until MongoDB comes back. The bootstrap
	// below is the exception — it has nothing to reconcile against an absent
	// database, so it fails and lets the restart policy retry.
	pingCtx, cancelPing := context.WithTimeout(ctx, cfg.Mongo.ServerSelectionTimeout)
	if err := mongoClient.Ping(pingCtx); err != nil {
		logger.Warn("mongodb unreachable at startup; readiness will report not ready",
			"uri", cfg.Mongo.RedactedURI(), "error", err)
	} else {
		logger.Info("connected to mongodb", "uri", cfg.Mongo.RedactedURI(), "database", cfg.Mongo.Database)
	}
	cancelPing()

	sourceService := service.NewSourceService(mongorepo.NewSourceRepository(mongoClient.Database()), time.Now)
	articleService := service.NewArticleService(mongorepo.NewArticleRepository(mongoClient.Database()))
	readEventService := service.NewReadEventService(mongorepo.NewReadEventRepository(mongoClient.Database()), time.Now)

	// Reconciling here rather than in a one-shot container is what makes a
	// redeploy actually pick up an edited source list: a container that has
	// already exited successfully may simply not be recreated. Failing is
	// deliberate — the restart policy retries, and serving against an
	// unmigrated database would be worse than a restart.
	bootstrapCtx, cancelBootstrap := context.WithTimeout(ctx, cfg.Bootstrap.Timeout)
	err = bootstrap.Run(bootstrapCtx, bootstrap.Options{
		Database:    mongoClient.Database(),
		Migrate:     cfg.Bootstrap.Migrate,
		SourcesPath: cfg.Bootstrap.SourcesPath,
		Sources:     sourceService,
		Logger:      logger,
	})
	cancelBootstrap()
	if err != nil {
		return fmt.Errorf("startup bootstrap: %w", err)
	}

	collectionService, err := app.NewCollectionService(cfg, mongoClient.Database(), time.Now, logger)
	if err != nil {
		return err
	}
	enrichmentService := app.NewEnrichmentService(cfg, mongoClient.Database(), time.Now, logger)
	var classificationService *service.ClassificationService
	var topicCache *classifier.MetadataCache
	var classifierClient classifier.Client
	if cfg.Classifier.Enabled {
		classificationService, err = app.NewClassificationService(cfg, mongoClient.Database(), time.Now, logger)
		if err != nil {
			return err
		}
		classifierClient, err = app.NewClassifierClient(cfg)
		if err != nil {
			return err
		}
		topicCache = classifier.NewMetadataCache()
	}

	var authenticator *handler.Authenticator
	if cfg.Auth.Enabled {
		authenticator = handler.NewAuthenticator(handler.AuthCredentials{
			APIKeyHeader:  cfg.Auth.APIKeyHeader,
			APIKeys:       cfg.Auth.APIKeys,
			BasicUsername: cfg.Auth.BasicUsername,
			BasicPassword: cfg.Auth.BasicPassword,
		})
		logger.Info("api authentication enabled",
			"api_key_header", cfg.Auth.APIKeyHeader,
			"api_keys", len(cfg.Auth.APIKeys),
			"basic_auth", cfg.Auth.BasicUsername != "")
	} else {
		logger.Warn("api authentication is disabled; every endpoint is open to anyone who can reach the port")
	}

	// The reader-facing site is what makes read events accumulate, and read
	// events are the one input a later ranker cannot be given retroactively.
	var pages http.Handler
	if cfg.Web.Enabled {
		// Passed only when non-nil: a nil *MetadataCache handed to a variadic
		// interface parameter would still be a non-nil TopicSource.
		var topicSources []classifier.TopicSource
		if topicCache != nil {
			topicSources = append(topicSources, topicCache)
		}
		site, err := web.New(articleService, readEventService, cfg.Web.PageSize, logger, topicSources...)
		if err != nil {
			return err
		}
		pages = site.Routes()
		logger.Info("reader pages enabled", "page_size", cfg.Web.PageSize)
	}

	srv := &http.Server{
		Addr: cfg.Server.Address(),
		Handler: handler.NewRouter(
			handler.NewHealth(mongoClient, readinessCheckTimeout, version, logger),
			handler.NewSource(sourceService, logger),
			handler.NewCollectionRun(collectionService, logger),
			handler.NewArticle(articleService, logger),
			pages,
			authenticator,
			logger,
		),
		ReadHeaderTimeout: cfg.Server.ReadHeaderTimeout,
		ReadTimeout:       cfg.Server.ReadTimeout,
		WriteTimeout:      cfg.Server.WriteTimeout,
		IdleTimeout:       cfg.Server.IdleTimeout,
		MaxHeaderBytes:    cfg.Server.MaxHeaderBytes,
	}

	// The scheduler shares the process with the API. Per-source leases are what
	// make that safe with more than one replica running.
	schedulerStopped := make(chan struct{})
	if cfg.Scheduler.Enabled {
		sch := scheduler.New(collectionService, scheduler.Config{
			Interval:      cfg.Scheduler.Interval,
			BatchSize:     cfg.Scheduler.BatchSize,
			MaxConcurrent: cfg.Scheduler.MaxConcurrent,
		}, logger)

		go func() {
			defer close(schedulerStopped)
			if err := sch.Run(ctx); err != nil {
				logger.Error("scheduler stopped early", "error", err)
			}
		}()
	} else {
		close(schedulerStopped)
		logger.Warn("scheduler is disabled; feeds will only be collected by the collector command")
	}

	// Enrichment shares the process the same way collection does: it reaches for
	// its own claim on an article before fetching it, so a second instance of
	// this same command cannot duplicate the work.
	enrichmentStopped := make(chan struct{})
	if cfg.Scraper.Enabled {
		esch := scheduler.NewEnrichment(enrichmentService, scheduler.EnrichmentConfig{
			Interval:  cfg.Scraper.Interval,
			BatchSize: cfg.Scraper.BatchSize,
		}, logger)

		go func() {
			defer close(enrichmentStopped)
			if err := esch.Run(ctx); err != nil {
				logger.Error("enrichment scheduler stopped early", "error", err)
			}
		}()
	} else {
		close(enrichmentStopped)
		logger.Warn("enrichment scheduler is disabled; articles will only be scraped by the scrape command")
	}

	classificationStopped := make(chan struct{})
	if classificationService != nil {
		classificationScheduler := scheduler.NewClassification(classificationService, scheduler.ClassificationConfig{
			Interval: cfg.Scheduler.Interval, BatchSize: cfg.Classifier.BatchSize,
		}, logger)
		go func() {
			defer close(classificationStopped)
			if err := classificationScheduler.Run(ctx); err != nil {
				logger.Error("classification scheduler stopped early", "error", err)
			}
		}()
	} else {
		close(classificationStopped)
	}

	metadataStopped := make(chan struct{})
	if topicCache != nil {
		go func() {
			defer close(metadataStopped)
			topicCache.Run(ctx, classifierClient, cfg.Classifier.MetadataRefreshInterval, logger)
		}()
	} else {
		close(metadataStopped)
	}

	serverErr := make(chan error, 1)
	go func() {
		logger.Info("http server listening", "address", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serverErr <- err
			return
		}
		serverErr <- nil
	}()

	var runErr error
	select {
	case err := <-serverErr:
		runErr = err
	case <-ctx.Done():
		logger.Info("shutdown signal received", "timeout", cfg.Server.ShutdownTimeout)
	}

	// Detach from the cancelled signal context so in-flight requests get their
	// full grace period.
	shutdownCtx, cancelShutdown := context.WithTimeout(context.WithoutCancel(ctx), cfg.Server.ShutdownTimeout)
	defer cancelShutdown()

	shutdownErr := srv.Shutdown(shutdownCtx)
	if shutdownErr != nil {
		logger.Error("graceful shutdown failed", "error", shutdownErr)
	}

	// The scheduler stops with the signal context. Waiting for it lets a
	// collection in flight finish and give its lease back before the MongoDB
	// connection it needs is closed — but only within the same grace period the
	// HTTP server gets, so a slow publisher cannot hold shutdown open.
	stop()
	select {
	case <-schedulerStopped:
	case <-shutdownCtx.Done():
		logger.Warn("scheduler did not stop within the shutdown timeout; " +
			"any lease it still holds will expire on its own")
	}
	select {
	case <-enrichmentStopped:
	case <-shutdownCtx.Done():
		logger.Warn("enrichment scheduler did not stop within the shutdown timeout; " +
			"any claim it still holds is released automatically once it goes stale")
	}
	select {
	case <-classificationStopped:
	case <-shutdownCtx.Done():
		logger.Warn("classification scheduler did not stop within the shutdown timeout; any claim it still holds will be recovered")
	}
	select {
	case <-metadataStopped:
	case <-shutdownCtx.Done():
		logger.Warn("classifier metadata refresh did not stop within the shutdown timeout")
	}

	if err := mongoClient.Close(shutdownCtx); err != nil {
		logger.Error("closing mongodb failed", "error", err)
	}

	logger.Info("shutdown complete")
	return errors.Join(runErr, shutdownErr)
}

// defaultConfigPath lets the container point at a mounted config without flags.
func defaultConfigPath() string {
	if p := os.Getenv(config.EnvPrefix + "CONFIG_PATH"); p != "" {
		return p
	}
	return config.DefaultPath
}
