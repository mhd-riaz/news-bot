package mongodb

import (
	"context"
	"errors"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

// namespaceExistsCode is the MongoDB error returned when a collection already exists.
const namespaceExistsCode = 48

// indexNotFoundCode is returned by dropIndexes for an index that is not there,
// which is the normal case on a database that never had the superseded one.
const indexNotFoundCode = 27

// namespaceNotFoundCode is returned when the collection itself is not there yet.
const namespaceNotFoundCode = 26

// CollectionIndexes binds a collection to the indexes it requires.
type CollectionIndexes struct {
	Collection string
	Models     []mongo.IndexModel
}

// IndexPlan is the full set of indexes the application depends on.
//
// The unique indexes on articles are the database-level enforcement of the
// deduplication order: normalized URL, then canonical URL, then source plus feed
// GUID. content_hash is the final fallback lookup and is deliberately not unique,
// because two sources may legitimately syndicate byte-identical content.
func IndexPlan() []CollectionIndexes {
	return []CollectionIndexes{
		{
			Collection: CollectionSources,
			Models: []mongo.IndexModel{
				{
					Keys:    bson.D{{Key: "feed_url", Value: 1}},
					Options: options.Index().SetName("uq_feed_url").SetUnique(true),
				},
				{
					Keys:    bson.D{{Key: "enabled", Value: 1}, {Key: "next_scheduled_at", Value: 1}},
					Options: options.Index().SetName("ix_due_for_collection"),
				},
				{
					Keys: bson.D{
						{Key: "enabled", Value: 1},
						{Key: "priority", Value: -1},
						{Key: "next_scheduled_at", Value: 1},
					},
					Options: options.Index().SetName("ix_due_by_priority"),
				},
				{
					Keys:    bson.D{{Key: "health_status", Value: 1}, {Key: "consecutive_failures", Value: -1}},
					Options: options.Index().SetName("ix_health"),
				},
				{
					Keys: bson.D{
						{Key: "country", Value: 1},
						{Key: "state", Value: 1},
						{Key: "city", Value: 1},
					},
					Options: options.Index().SetName("ix_region"),
				},
				{
					Keys:    bson.D{{Key: "type", Value: 1}, {Key: "enabled", Value: 1}},
					Options: options.Index().SetName("ix_type_enabled"),
				},
			},
		},
		{
			Collection: CollectionArticles,
			Models: []mongo.IndexModel{
				{
					Keys:    bson.D{{Key: "dedup_id", Value: 1}},
					Options: options.Index().SetName("uq_dedup_id").SetUnique(true),
				},
				{
					Keys:    bson.D{{Key: "normalized_url", Value: 1}},
					Options: options.Index().SetName("uq_normalized_url").SetUnique(true),
				},
				{
					Keys: bson.D{{Key: "source_id", Value: 1}, {Key: "feed_guid", Value: 1}},
					Options: options.Index().
						SetName("uq_source_feed_guid").
						SetUnique(true).
						SetPartialFilterExpression(bson.D{{Key: "feed_guid", Value: bson.D{{Key: "$gt", Value: ""}}}}),
				},
				{
					Keys: bson.D{{Key: "canonical_url", Value: 1}},
					Options: options.Index().
						SetName("ix_canonical_url").
						SetPartialFilterExpression(bson.D{{Key: "canonical_url", Value: bson.D{{Key: "$gt", Value: ""}}}}),
				},
				{
					Keys:    bson.D{{Key: "content_hash", Value: 1}},
					Options: options.Index().SetName("ix_content_hash"),
				},
				{
					Keys: bson.D{
						{Key: "source_id", Value: 1},
						{Key: "published_at", Value: -1},
						{Key: "_id", Value: -1},
					},
					Options: options.Index().SetName("ix_source_published_cursor"),
				},
				{
					Keys:    bson.D{{Key: "published_at", Value: -1}, {Key: "_id", Value: -1}},
					Options: options.Index().SetName("ix_published_cursor"),
				},
				{
					Keys:    bson.D{{Key: "collected_at", Value: -1}, {Key: "_id", Value: -1}},
					Options: options.Index().SetName("ix_collected_cursor"),
				},
				{
					Keys: bson.D{
						{Key: "language", Value: 1},
						{Key: "published_at", Value: -1},
						{Key: "_id", Value: -1},
					},
					Options: options.Index().SetName("ix_language_published_cursor"),
				},
				// Region is the axis this whole system is organised around, so
				// filtering by it must not be a collection scan. The prefix
				// order matches how a caller narrows: country, then state,
				// then city.
				//
				// Every listing index ends in published_at and _id because that
				// is the order a page is read in; without the _id the database
				// cannot order two articles sharing a timestamp from the index
				// alone and has to sort the whole filtered set to find one page.
				{
					Keys: bson.D{
						{Key: "country", Value: 1},
						{Key: "state", Value: 1},
						{Key: "city", Value: 1},
						{Key: "published_at", Value: -1},
						{Key: "_id", Value: -1},
					},
					Options: options.Index().SetName("ix_region_published_cursor"),
				},
				{
					Keys:    bson.D{{Key: "processing_status", Value: 1}, {Key: "collected_at", Value: -1}},
					Options: options.Index().SetName("ix_status_collected"),
				},
				// The enrichment backlog. Both the claim and the stale-claim
				// sweep filter on scrape_status first, and the claim then takes
				// the oldest due article, so the ascending next_scrape_at both
				// narrows the match and supplies the sort.
				{
					Keys:    bson.D{{Key: "scrape_status", Value: 1}, {Key: "next_scrape_at", Value: 1}},
					Options: options.Index().SetName("ix_scrape_backlog"),
				},
				{
					Keys:    bson.D{{Key: "classification_status", Value: 1}, {Key: "collected_at", Value: 1}},
					Options: options.Index().SetName("ix_classification_backlog"),
				},
				{
					Keys:    bson.D{{Key: "updated_at", Value: 1}, {Key: "_id", Value: 1}},
					Options: options.Index().SetName("ix_updated_cursor"),
				},
				{
					Keys: bson.D{
						{Key: "date_verified", Value: 1},
						{Key: "detected_language", Value: 1},
						{Key: "published_at", Value: -1},
					},
					Options: options.Index().SetName("ix_verified_language_published"),
				},
				{
					Keys: bson.D{
						{Key: "topic", Value: 1},
						{Key: "published_at", Value: -1},
						{Key: "_id", Value: -1},
					},
					Options: options.Index().SetName("ix_topic_published_cursor"),
				},
			},
		},
		{
			Collection: CollectionCollectionRuns,
			Models: []mongo.IndexModel{
				{
					Keys:    bson.D{{Key: "source_id", Value: 1}, {Key: "started_at", Value: -1}},
					Options: options.Index().SetName("ix_source_started"),
				},
				{
					Keys:    bson.D{{Key: "started_at", Value: -1}},
					Options: options.Index().SetName("ix_started"),
				},
				{
					Keys:    bson.D{{Key: "status", Value: 1}, {Key: "started_at", Value: -1}},
					Options: options.Index().SetName("ix_status_started"),
				},
			},
		},
		{
			Collection: CollectionFeedCache,
			Models: []mongo.IndexModel{
				{
					Keys:    bson.D{{Key: "source_id", Value: 1}},
					Options: options.Index().SetName("uq_cache_source").SetUnique(true),
				},
			},
		},
		{
			Collection: CollectionLocks,
			Models: []mongo.IndexModel{
				// TTL(0) lets MongoDB reap leases whose expiry has passed, so a
				// crashed collector cannot hold a source lock forever.
				{
					Keys:    bson.D{{Key: "expires_at", Value: 1}},
					Options: options.Index().SetName("ttl_expires_at").SetExpireAfterSeconds(0),
				},
				{
					Keys:    bson.D{{Key: "resource", Value: 1}, {Key: "expires_at", Value: 1}},
					Options: options.Index().SetName("ix_resource_expiry"),
				},
			},
		},
		{
			Collection: CollectionReadEvents,
			Models: []mongo.IndexModel{
				// Read events are written by the browser and read offline, in
				// two shapes only: the whole log in time order, which is how a
				// ranker is trained on a temporal split, and one article's
				// history, which is how a single card is explained.
				{
					Keys:    bson.D{{Key: "occurred_at", Value: -1}, {Key: "_id", Value: -1}},
					Options: options.Index().SetName("ix_occurred_cursor"),
				},
				{
					Keys:    bson.D{{Key: "article_id", Value: 1}, {Key: "occurred_at", Value: -1}},
					Options: options.Index().SetName("ix_article_occurred"),
				},
				{
					Keys:    bson.D{{Key: "kind", Value: 1}, {Key: "occurred_at", Value: -1}},
					Options: options.Index().SetName("ix_kind_occurred"),
				},
			},
		},
	}
}

// ObsoleteIndexes names, per collection, the indexes a previous version of the
// plan created and this one has replaced.
//
// MongoDB refuses to recreate an existing index name with different keys, so an
// index that gains a field has to be retired under its old name rather than
// edited in place. Listing them here keeps that history explicit and auditable
// instead of hiding it in a conditional inside the migration.
func ObsoleteIndexes() map[string][]string {
	return map[string][]string{
		// Superseded by their *_cursor forms, which carry the _id tiebreaker a
		// paged listing sorts on.
		CollectionArticles: {
			"ix_source_published",
			"ix_language_published",
			"ix_region_published",
		},
	}
}

// EnsureCollections creates any missing collection and returns the names it
// created. It is safe to run repeatedly.
func EnsureCollections(ctx context.Context, db *mongo.Database) ([]string, error) {
	existing, err := db.ListCollectionNames(ctx, bson.D{})
	if err != nil {
		return nil, fmt.Errorf("mongodb: list collections: %w", err)
	}

	present := make(map[string]struct{}, len(existing))
	for _, name := range existing {
		present[name] = struct{}{}
	}

	var created []string
	for _, name := range Collections() {
		if _, ok := present[name]; ok {
			continue
		}
		if err := db.CreateCollection(ctx, name); err != nil {
			if isNamespaceExists(err) {
				continue
			}
			return created, fmt.Errorf("mongodb: create collection %q: %w", name, err)
		}
		created = append(created, name)
	}
	return created, nil
}

// DropObsoleteIndexes removes the superseded indexes and returns the names it
// dropped per collection. An index that is not there — a fresh database, or a
// second run — is not an error, so this is safe to run before every migration.
//
// What is present is read first and only those are dropped, so the returned
// list, and the migration's log line, name what actually changed rather than
// what was merely attempted.
func DropObsoleteIndexes(ctx context.Context, db *mongo.Database) (map[string][]string, error) {
	dropped := make(map[string][]string)

	for collection, names := range ObsoleteIndexes() {
		present, err := existingIndexNames(ctx, db, collection)
		if err != nil {
			return dropped, err
		}

		for _, name := range names {
			if _, ok := present[name]; !ok {
				continue
			}
			// Still tolerate a missing index: another migration may have been
			// running at the same time and dropped it first.
			if err := db.Collection(collection).Indexes().DropOne(ctx, name); err != nil && !isIndexNotFound(err) {
				return dropped, fmt.Errorf("mongodb: drop index %q on %q: %w", name, collection, err)
			}
			dropped[collection] = append(dropped[collection], name)
		}
	}
	return dropped, nil
}

// existingIndexNames lists the indexes on a collection. A collection that does
// not exist yet simply has none.
func existingIndexNames(ctx context.Context, db *mongo.Database, collection string) (map[string]struct{}, error) {
	cursor, err := db.Collection(collection).Indexes().List(ctx)
	if err != nil {
		if isIndexNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("mongodb: list indexes on %q: %w", collection, err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	var specs []struct {
		Name string `bson:"name"`
	}
	if err := cursor.All(ctx, &specs); err != nil {
		return nil, fmt.Errorf("mongodb: decode indexes on %q: %w", collection, err)
	}

	names := make(map[string]struct{}, len(specs))
	for _, spec := range specs {
		names[spec.Name] = struct{}{}
	}
	return names, nil
}

// EnsureIndexes applies the index plan. createIndexes is idempotent for an
// unchanged specification, so reruns are no-ops.
func EnsureIndexes(ctx context.Context, db *mongo.Database) (map[string][]string, error) {
	applied := make(map[string][]string, len(IndexPlan()))

	for _, ci := range IndexPlan() {
		names, err := db.Collection(ci.Collection).Indexes().CreateMany(ctx, ci.Models)
		if err != nil {
			return applied, fmt.Errorf("mongodb: create indexes on %q: %w", ci.Collection, err)
		}
		applied[ci.Collection] = names
	}
	return applied, nil
}

func isNamespaceExists(err error) bool {
	var cmdErr mongo.CommandError
	return errors.As(err, &cmdErr) && cmdErr.Code == namespaceExistsCode
}

// isIndexNotFound also covers a collection that does not exist yet, which the
// server reports the same way when asked to drop an index from it.
func isIndexNotFound(err error) bool {
	var cmdErr mongo.CommandError
	return errors.As(err, &cmdErr) && (cmdErr.Code == indexNotFoundCode || cmdErr.Code == namespaceNotFoundCode)
}
