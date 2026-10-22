package mongo

import (
	"context"
	"errors"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/repository"
)

// CollectionRunRepository stores collection attempts in the collection_runs
// collection.
type CollectionRunRepository struct {
	coll *driver.Collection
}

// NewCollectionRunRepository binds the repository to the collection_runs collection.
func NewCollectionRunRepository(db *driver.Database) *CollectionRunRepository {
	return &CollectionRunRepository{coll: db.Collection(mongodb.CollectionCollectionRuns)}
}

var _ repository.CollectionRunRepository = (*CollectionRunRepository)(nil)

// Create inserts a finished run.
func (r *CollectionRunRepository) Create(ctx context.Context, run *domain.CollectionRun) error {
	if _, err := r.coll.InsertOne(ctx, run); err != nil {
		if driver.IsDuplicateKeyError(err) {
			return repository.ErrDuplicate
		}
		return fmt.Errorf("mongo: insert collection run: %w", err)
	}
	return nil
}

// GetByID returns one run by identifier.
func (r *CollectionRunRepository) GetByID(ctx context.Context, id string) (*domain.CollectionRun, error) {
	var run domain.CollectionRun
	if err := r.coll.FindOne(ctx, bson.D{{Key: "_id", Value: id}}).Decode(&run); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: find collection run: %w", err)
	}
	return &run, nil
}

// List returns a page of runs, newest first.
//
// The sort is started_at descending with _id as the tiebreaker, which matches
// ix_source_started, ix_started and ix_status_started, and makes the order
// total rather than merely mostly-ordered — a requirement for offset paging to
// return each run exactly once.
func (r *CollectionRunRepository) List(ctx context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error) {
	query := collectionRunQuery(filter)

	total, err := r.coll.CountDocuments(ctx, query)
	if err != nil {
		return domain.CollectionRunPage{}, fmt.Errorf("mongo: count collection runs: %w", err)
	}

	opts := options.Find().
		SetSort(bson.D{{Key: "started_at", Value: -1}, {Key: "_id", Value: -1}}).
		SetSkip(int64(filter.Offset)).
		SetLimit(int64(filter.Limit))

	cursor, err := r.coll.Find(ctx, query, opts)
	if err != nil {
		return domain.CollectionRunPage{}, fmt.Errorf("mongo: find collection runs: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	items := make([]domain.CollectionRun, 0, filter.Limit)
	if err := cursor.All(ctx, &items); err != nil {
		return domain.CollectionRunPage{}, fmt.Errorf("mongo: decode collection runs: %w", err)
	}

	return domain.CollectionRunPage{
		Items:  items,
		Total:  total,
		Limit:  filter.Limit,
		Offset: filter.Offset,
	}, nil
}

// collectionRunQuery builds the filter document field by field from typed,
// already-validated values, so no part of a request is ever spliced into a
// query document as an operator.
func collectionRunQuery(f domain.CollectionRunFilter) bson.D {
	query := bson.D{}

	if f.SourceID != "" {
		query = append(query, bson.E{Key: "source_id", Value: f.SourceID})
	}
	if f.Status != nil {
		query = append(query, bson.E{Key: "status", Value: string(*f.Status)})
	}

	return query
}
