// Command reader serves recommendations and articles without any MongoDB write path.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/handler"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/observability"
	"github.com/riaz/newscollector/internal/recommendation"
	mongorepo "github.com/riaz/newscollector/internal/repository/mongo"
	"github.com/riaz/newscollector/internal/service"
	"github.com/riaz/newscollector/internal/web"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "reader: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	path := flag.String("config", "configs/reader.yaml", "reader configuration")
	env := flag.String("env", config.EnvFilePath(), "dotenv file, never logged")
	recommender := flag.String("recommender", "", "private ranking service URL (default localhost:8001)")
	flag.Parse()
	if err := config.LoadEnvFile(*env); err != nil {
		return err
	}
	if *recommender == "" {
		*recommender = os.Getenv("NEWS_RECOMMENDER_ENDPOINT")
		if *recommender == "" {
			*recommender = "http://127.0.0.1:8001"
		}
	}
	cfg, err := config.Load(*path)
	if err != nil {
		return err
	}
	logger, err := observability.NewLogger(cfg.Logging.Level, cfg.Logging.Format, os.Stdout)
	if err != nil {
		return err
	}
	client, err := mongodb.Connect(mongodb.Settings{
		URI: cfg.Mongo.URI, Database: cfg.Mongo.Database, AppName: cfg.App.Name,
		ConnectTimeout: cfg.Mongo.ConnectTimeout, ServerSelectionTimeout: cfg.Mongo.ServerSelectionTimeout,
		OperationTimeout: cfg.Mongo.OperationTimeout, MaxPoolSize: cfg.Mongo.MaxPoolSize,
		MinPoolSize:     cfg.Mongo.MinPoolSize,
		MaxConnIdleTime: cfg.Mongo.MaxConnIdleTime,
	})
	if err != nil {
		return err
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := client.Close(ctx); err != nil {
			logger.Error("closing reader database", "error", err)
		}
	}()
	repository := mongorepo.NewArticleRepository(client.Database())
	ranker, err := recommendation.New(*recommender, os.Getenv("NEWS_RECOMMENDER_API_KEY"), repository)
	if err != nil {
		return err
	}
	articles := service.NewArticleService(repository)
	site, err := web.New(articles, nil, cfg.Web.PageSize, logger)
	if err != nil {
		return err
	}
	auth := (*handler.Authenticator)(nil)
	if cfg.Auth.Enabled {
		auth = handler.NewAuthenticator(handler.AuthCredentials{
			APIKeyHeader: cfg.Auth.APIKeyHeader, APIKeys: cfg.Auth.APIKeys,
			BasicUsername: cfg.Auth.BasicUsername, BasicPassword: cfg.Auth.BasicPassword,
		})
	}
	mux := readerRoutes(site.Routes(), ranker, articles, auth, client, logger)
	server := &http.Server{
		Addr: cfg.Server.Address(), Handler: mux,
		ReadHeaderTimeout: cfg.Server.ReadHeaderTimeout, ReadTimeout: cfg.Server.ReadTimeout,
		WriteTimeout: cfg.Server.WriteTimeout, IdleTimeout: cfg.Server.IdleTimeout,
		MaxHeaderBytes: cfg.Server.MaxHeaderBytes,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	stopped := make(chan error, 1)
	go func() {
		logger.Info("read-only story reader listening", "address", server.Addr)
		stopped <- server.ListenAndServe()
	}()
	var serveErr error
	select {
	case serveErr = <-stopped:
		if errors.Is(serveErr, http.ErrServerClosed) {
			serveErr = nil
		}
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.Server.ShutdownTimeout)
	defer cancel()
	return errors.Join(serveErr, server.Shutdown(shutdownCtx))
}

func readerRoutes(pages http.Handler, ranker *recommendation.Service, articles *service.ArticleService,
	auth *handler.Authenticator, mongo handler.Pinger, logger *slog.Logger) http.Handler {
	api := http.NewServeMux()
	recommendations := handler.NewRecommendation(ranker, logger)
	articleHandler := handler.NewArticle(articles, logger)
	api.HandleFunc("GET /api/v1/recommendations/meta", recommendations.Metadata)
	api.HandleFunc("POST /api/v1/recommendations", recommendations.Recommend)
	api.HandleFunc("GET /api/v1/articles", articleHandler.List)
	api.HandleFunc("GET /api/v1/articles/{id}", articleHandler.Get)
	api.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "read-only reader: route not found", http.StatusNotFound)
	})
	mux := http.NewServeMux()
	health := handler.NewHealth(mongo, 2*time.Second, "stories", logger)
	mux.HandleFunc("GET /health/live", health.Live)
	mux.HandleFunc("GET /health/ready", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if _, err := ranker.Metadata(ctx); err != nil {
			logger.WarnContext(ctx, "recommender not ready", "error", err)
			http.Error(w, "recommender unavailable", http.StatusServiceUnavailable)
			return
		}
		health.Ready(w, r)
	})
	mux.Handle("/api/v1/", auth.Require(api))
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/stories", http.StatusTemporaryRedirect)
	})
	// The legacy telemetry route is intentionally unreachable in this command.
	mux.HandleFunc("POST /read-events", func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "telemetry is disabled in the read-only reader", http.StatusMethodNotAllowed)
	})
	mux.Handle("/", auth.Require(pages))
	return observability.Chain(mux, observability.RequestID, observability.Recover(logger), observability.AccessLog(logger))
}
