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

// FeedCacheRepository stores per-source HTTP validators in the
// feed_cache_metadata collection.
type FeedCacheRepository struct {
	coll *driver.Collection
}

// NewFeedCacheRepository binds the repository to the feed_cache_metadata collection.
func NewFeedCacheRepository(db *driver.Database) *FeedCacheRepository {
	return &FeedCacheRepository{coll: db.Collection(mongodb.CollectionFeedCache)}
}

var _ repository.FeedCacheRepository = (*FeedCacheRepository)(nil)

// Get returns the validators stored for a source.
func (r *FeedCacheRepository) Get(ctx context.Context, sourceID string) (*domain.FeedCacheEntry, error) {
	var entry domain.FeedCacheEntry
	if err := r.coll.FindOne(ctx, bson.D{{Key: "source_id", Value: sourceID}}).Decode(&entry); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: find feed cache entry: %w", err)
	}
	return &entry, nil
}

// Save stores the validators for a source, replacing whatever was held before.
//
// The upsert is keyed on source_id, which uq_cache_source keeps unique, so two
// collectors finishing the same source at once end up with one document rather
// than two. The loser of that race sees a duplicate key, which means the other
// one's validators are already stored and there is nothing left to do.
func (r *FeedCacheRepository) Save(ctx context.Context, entry domain.FeedCacheEntry) error {
	update := bson.D{{Key: "$set", Value: bson.D{
		{Key: "source_id", Value: entry.SourceID},
		{Key: "etag", Value: entry.ETag},
		{Key: "last_modified", Value: entry.LastModified},
		{Key: "updated_at", Value: entry.UpdatedAt},
	}}}

	_, err := r.coll.UpdateOne(ctx,
		bson.D{{Key: "source_id", Value: entry.SourceID}},
		update,
		options.UpdateOne().SetUpsert(true),
	)
	if err != nil {
		if driver.IsDuplicateKeyError(err) {
			return repository.ErrDuplicate
		}
		return fmt.Errorf("mongo: save feed cache entry: %w", err)
	}
	return nil
}
