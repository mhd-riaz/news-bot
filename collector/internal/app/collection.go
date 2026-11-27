// Package app is the composition root: it assembles the application's
// components from configuration so every command builds them the same way. It
// is the one place that knows which concrete collector, processor and
// repositories a collection is made of.
package app

import (
	"fmt"
	"log/slog"

	"github.com/google/uuid"
	driver "go.mongodb.org/mongo-driver/v2/mongo"

	"github.com/mhd-riaz/news-bot/collector/internal/classifier"
	"github.com/mhd-riaz/news-bot/collector/internal/collector/rss"
	"github.com/mhd-riaz/news-bot/collector/internal/config"
	"github.com/mhd-riaz/news-bot/collector/internal/httpclient"
	"github.com/mhd-riaz/news-bot/collector/internal/processor"
	mongorepo "github.com/mhd-riaz/news-bot/collector/internal/repository/mongo"
	"github.com/mhd-riaz/news-bot/collector/internal/service"
)

// NewCollectionService wires a collection service against db.
//
// clock is passed through to the service; pass time.Now outside tests. The
// lease owner is a fresh identifier per call, so two processes — and two
// commands on the same machine — can never release each other's leases.
func NewCollectionService(cfg *config.Config, db *driver.Database, clock service.Clock, logger *slog.Logger) (*service.CollectionService, error) {
	owner, err := uuid.NewV7()
	if err != nil {
		return nil, fmt.Errorf("app: generate collector identity: %w", err)
	}

	client := httpclient.New(httpclient.Config{
		Timeout:              cfg.Collector.RequestTimeout,
		MaxResponseBytes:     cfg.Collector.MaxResponseBytes,
		MaxRedirects:         cfg.Collector.MaxRedirects,
		UserAgent:            cfg.Collector.UserAgent,
		AllowPrivateNetworks: cfg.Collector.AllowPrivateNetworks,
	})

	var model classifier.Client
	if cfg.Classifier.Enabled {
		model, err = NewClassifierClient(cfg)
		if err != nil {
			return nil, err
		}
	}

	return service.NewCollectionService(service.CollectionDeps{
		Sources:   mongorepo.NewSourceRepository(db),
		Runs:      mongorepo.NewCollectionRunRepository(db),
		Cache:     mongorepo.NewFeedCacheRepository(db),
		Locks:     mongorepo.NewLockRepository(db),
		Collector: rss.New(client, cfg.Collector.MaxItemsPerFeed),
		Processor: processor.New(mongorepo.NewArticleRepository(db), processor.Clock(clock), model),
		Owner:     owner.String(),
		LockTTL:   cfg.Scheduler.LockTTL,
		Clock:     clock,
		Logger:    logger,
	}), nil
}
