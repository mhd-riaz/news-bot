package app

import (
	"time"

	driver "go.mongodb.org/mongo-driver/v2/mongo"

	"github.com/riaz/newscollector/internal/config"
	mongorepo "github.com/riaz/newscollector/internal/repository/mongo"
	"github.com/riaz/newscollector/internal/service"
)

// NewDerivedFieldBackfillService wires the resumable C1 backfill to MongoDB and
// the configured internal classifier.
func NewDerivedFieldBackfillService(
	cfg *config.Config, db *driver.Database, batchDelay time.Duration,
) (*service.DerivedFieldBackfillService, error) {
	classifier, err := NewClassifierClient(cfg)
	if err != nil {
		return nil, err
	}
	return service.NewDerivedFieldBackfillService(service.DerivedFieldBackfillDeps{
		Articles: mongorepo.NewArticleRepository(db), Classifier: classifier,
		BatchSize: cfg.Classifier.BatchSize, BatchDelay: batchDelay,
	}), nil
}
