package mongo

import (
	"context"
	"errors"
	"fmt"

	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/repository"
)

// ReadEventRepository stores reader telemetry in the read_events collection.
type ReadEventRepository struct {
	coll *driver.Collection
}

// NewReadEventRepository binds the repository to the read_events collection.
func NewReadEventRepository(db *driver.Database) *ReadEventRepository {
	return &ReadEventRepository{coll: db.Collection(mongodb.CollectionReadEvents)}
}

var _ repository.ReadEventRepository = (*ReadEventRepository)(nil)

// CreateMany inserts a batch and reports how many documents were written.
//
// Unordered, so a rejected document does not abandon the rest of the flush, and
// a partial write is reported as the count rather than as a failure: telemetry
// is best-effort by nature and losing one event is not worth failing a request
// the reader never asked for.
func (r *ReadEventRepository) CreateMany(ctx context.Context, events []domain.ReadEvent) (int64, error) {
	if len(events) == 0 {
		return 0, nil
	}

	docs := make([]any, 0, len(events))
	for i := range events {
		docs = append(docs, events[i])
	}

	res, err := r.coll.InsertMany(ctx, docs, options.InsertMany().SetOrdered(false))
	inserted := int64(0)
	if res != nil {
		inserted = int64(len(res.InsertedIDs))
	}
	if err != nil {
		var bulk driver.BulkWriteException
		if errors.As(err, &bulk) && inserted > 0 {
			return inserted, nil
		}
		return inserted, fmt.Errorf("mongo: insert read events: %w", err)
	}
	return inserted, nil
}
