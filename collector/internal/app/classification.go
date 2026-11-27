package app

import (
	"fmt"
	"log/slog"

	driver "go.mongodb.org/mongo-driver/v2/mongo"

	"github.com/mhd-riaz/news-bot/collector/internal/classifier"
	"github.com/mhd-riaz/news-bot/collector/internal/config"
	mongorepo "github.com/mhd-riaz/news-bot/collector/internal/repository/mongo"
	"github.com/mhd-riaz/news-bot/collector/internal/service"
)

// NewClassificationService wires the retry worker to the internal classifier.
func NewClassificationService(cfg *config.Config, db *driver.Database, clock service.Clock, logger *slog.Logger) (*service.ClassificationService, error) {
	client, err := NewClassifierClient(cfg)
	if err != nil {
		return nil, err
	}
	return service.NewClassificationService(service.ClassificationDeps{
		Articles: mongorepo.NewArticleRepository(db), Classifier: client,
		MaxAttempts: cfg.Classifier.MaxAttempts, ClaimTTL: cfg.Classifier.ClaimTTL,
		Clock: clock, Logger: logger,
	}), nil
}

// NewClassifierClient configures the trusted internal classifier client.
func NewClassifierClient(cfg *config.Config) (classifier.Client, error) {
	client, err := classifier.NewHTTPClient(
		cfg.Classifier.Endpoint, cfg.Classifier.Timeout, cfg.Classifier.BatchSize, cfg.Classifier.APIKey,
	)
	if err != nil {
		return nil, fmt.Errorf("app: configure classifier client: %w", err)
	}
	return client, nil
}
