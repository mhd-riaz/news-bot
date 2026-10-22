// Package mongo implements the repository contracts on top of MongoDB. It is
// the only place in the application that turns domain concepts into queries, and
// the only place that translates driver errors into repository sentinels.
package mongo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/repository"
)

// SourceRepository stores configured feeds in the sources collection.
type SourceRepository struct {
	coll *driver.Collection
}

// NewSourceRepository binds the repository to the sources collection. The name
// comes from the shared constant so the migration and the queries cannot drift.
func NewSourceRepository(db *driver.Database) *SourceRepository {
	return &SourceRepository{coll: db.Collection(mongodb.CollectionSources)}
}

var _ repository.SourceRepository = (*SourceRepository)(nil)

// Create inserts a source. The uq_feed_url unique index, not a prior read, is
// what rejects a duplicate, so two concurrent creates cannot both succeed.
func (r *SourceRepository) Create(ctx context.Context, s *domain.Source) error {
	if _, err := r.coll.InsertOne(ctx, s); err != nil {
		if driver.IsDuplicateKeyError(err) {
			return repository.ErrDuplicate
		}
		return fmt.Errorf("mongo: insert source: %w", err)
	}
	return nil
}

// GetByID returns one source by identifier.
func (r *SourceRepository) GetByID(ctx context.Context, id string) (*domain.Source, error) {
	return r.findOne(ctx, bson.D{{Key: "_id", Value: id}})
}

// GetByFeedURL returns the source registered for a feed URL.
func (r *SourceRepository) GetByFeedURL(ctx context.Context, feedURL string) (*domain.Source, error) {
	return r.findOne(ctx, bson.D{{Key: "feed_url", Value: feedURL}})
}

func (r *SourceRepository) findOne(ctx context.Context, filter bson.D) (*domain.Source, error) {
	var s domain.Source
	if err := r.coll.FindOne(ctx, filter).Decode(&s); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: find source: %w", err)
	}
	return &s, nil
}

// List returns a page of sources and the total number matching the filter.
//
// Results are ordered by _id, which is a UUIDv7 and therefore chronological by
// creation. That makes the order both deterministic — a requirement for correct
// offset pagination — and served by the built-in _id index.
func (r *SourceRepository) List(ctx context.Context, filter domain.SourceFilter) (domain.SourcePage, error) {
	query := sourceQuery(filter)

	total, err := r.coll.CountDocuments(ctx, query)
	if err != nil {
		return domain.SourcePage{}, fmt.Errorf("mongo: count sources: %w", err)
	}

	opts := options.Find().
		SetSort(bson.D{{Key: "_id", Value: 1}}).
		SetSkip(int64(filter.Offset)).
		SetLimit(int64(filter.Limit))

	cursor, err := r.coll.Find(ctx, query, opts)
	if err != nil {
		return domain.SourcePage{}, fmt.Errorf("mongo: find sources: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	items := make([]domain.Source, 0, filter.Limit)
	if err := cursor.All(ctx, &items); err != nil {
		return domain.SourcePage{}, fmt.Errorf("mongo: decode sources: %w", err)
	}

	return domain.SourcePage{
		Items:  items,
		Total:  total,
		Limit:  filter.Limit,
		Offset: filter.Offset,
	}, nil
}

// ListDue returns the enabled sources whose next collection has come round,
// most important first.
//
// The sort is priority descending then due-time ascending, which is exactly
// ix_due_by_priority, so a backlog is worked in the order an operator asked for
// rather than in insertion order. The limit is what keeps one tick's work
// bounded when a long outage has left every source overdue at once.
func (r *SourceRepository) ListDue(ctx context.Context, now time.Time, limit int) ([]domain.Source, error) {
	query := bson.D{
		{Key: "enabled", Value: true},
		{Key: "next_scheduled_at", Value: bson.D{{Key: "$lte", Value: now}}},
	}
	opts := options.Find().
		SetSort(bson.D{{Key: "priority", Value: -1}, {Key: "next_scheduled_at", Value: 1}}).
		SetLimit(int64(limit))

	cursor, err := r.coll.Find(ctx, query, opts)
	if err != nil {
		return nil, fmt.Errorf("mongo: find due sources: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	items := make([]domain.Source, 0, limit)
	if err := cursor.All(ctx, &items); err != nil {
		return nil, fmt.Errorf("mongo: decode due sources: %w", err)
	}
	return items, nil
}

// Update replaces a stored source in full. Replacement rather than a field-wise
// $set means the document can never end up in a state the domain never validated.
func (r *SourceRepository) Update(ctx context.Context, s *domain.Source) error {
	res, err := r.coll.ReplaceOne(ctx, bson.D{{Key: "_id", Value: s.ID}}, s)
	if err != nil {
		if driver.IsDuplicateKeyError(err) {
			return repository.ErrDuplicate
		}
		return fmt.Errorf("mongo: replace source: %w", err)
	}
	if res.MatchedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}

// UpdateCollectionState writes back only what a collection decides.
//
// A full replacement would carry the source as it looked when the collection
// started, so an operator who disabled the feed or changed its interval during
// those seconds would find the change quietly undone. last_collected_at is only
// written when there is one, so a failed attempt against a never-collected
// source does not record a null.
func (r *SourceRepository) UpdateCollectionState(ctx context.Context, s *domain.Source) error {
	fields := bson.D{
		{Key: "health_status", Value: string(s.HealthStatus)},
		{Key: "consecutive_failures", Value: s.ConsecutiveFailures},
		{Key: "last_error", Value: s.LastError},
		{Key: "next_scheduled_at", Value: s.NextScheduledAt},
		{Key: "updated_at", Value: s.UpdatedAt},
	}
	if s.LastCollectedAt != nil {
		fields = append(fields, bson.E{Key: "last_collected_at", Value: *s.LastCollectedAt})
	}

	res, err := r.coll.UpdateOne(ctx,
		bson.D{{Key: "_id", Value: s.ID}},
		bson.D{{Key: "$set", Value: fields}},
	)
	if err != nil {
		return fmt.Errorf("mongo: update source collection state: %w", err)
	}
	if res.MatchedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}

// Delete removes a source by identifier.
func (r *SourceRepository) Delete(ctx context.Context, id string) error {
	res, err := r.coll.DeleteOne(ctx, bson.D{{Key: "_id", Value: id}})
	if err != nil {
		return fmt.Errorf("mongo: delete source: %w", err)
	}
	if res.DeletedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}

// sourceQuery builds the filter document field by field from typed values.
// Nothing the caller supplied is ever spliced in as a document, so a crafted
// payload cannot inject a query operator.
func sourceQuery(f domain.SourceFilter) bson.D {
	query := bson.D{}

	if f.Enabled != nil {
		query = append(query, bson.E{Key: "enabled", Value: *f.Enabled})
	}
	if f.Type != nil {
		query = append(query, bson.E{Key: "type", Value: string(*f.Type)})
	}
	if f.HealthStatus != nil {
		query = append(query, bson.E{Key: "health_status", Value: string(*f.HealthStatus)})
	}
	if f.Country != "" {
		query = append(query, bson.E{Key: "country", Value: f.Country})
	}
	if f.State != "" {
		query = append(query, bson.E{Key: "state", Value: f.State})
	}
	if f.City != "" {
		query = append(query, bson.E{Key: "city", Value: f.City})
	}

	return query
}
