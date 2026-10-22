//go:build integration

package mongodb

import (
	"context"
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

// indexNames returns the indexes present on a collection.
func indexNames(t *testing.T, db *mongo.Database, collection string) map[string]struct{} {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	cursor, err := db.Collection(collection).Indexes().List(ctx)
	if err != nil {
		t.Fatalf("list indexes: %v", err)
	}
	var specs []struct {
		Name string `bson:"name"`
	}
	if err := cursor.All(ctx, &specs); err != nil {
		t.Fatalf("decode indexes: %v", err)
	}

	names := make(map[string]struct{}, len(specs))
	for _, s := range specs {
		names[s.Name] = struct{}{}
	}
	return names
}

// An index that gained a field cannot be recreated under its old name, so the
// migration has to retire the superseded one first. This reproduces the upgrade
// an existing deployment goes through.
func TestMigrationReplacesASupersededIndex(t *testing.T) {
	db := newTestClient(t).Database()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if _, err := EnsureCollections(ctx, db); err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}

	// The shape a pre-Milestone-6 database is in: the old two-key index.
	_, err := db.Collection(CollectionArticles).Indexes().CreateOne(ctx, mongo.IndexModel{
		Keys:    bson.D{{Key: "source_id", Value: 1}, {Key: "published_at", Value: -1}},
		Options: options.Index().SetName("ix_source_published"),
	})
	if err != nil {
		t.Fatalf("create the superseded index: %v", err)
	}

	dropped, err := DropObsoleteIndexes(ctx, db)
	if err != nil {
		t.Fatalf("DropObsoleteIndexes: %v", err)
	}
	if len(dropped[CollectionArticles]) == 0 {
		t.Fatalf("dropped = %v, want the superseded index reported", dropped)
	}

	if _, err := EnsureIndexes(ctx, db); err != nil {
		t.Fatalf("EnsureIndexes after the drop: %v", err)
	}

	names := indexNames(t, db, CollectionArticles)
	if _, stale := names["ix_source_published"]; stale {
		t.Error("the superseded index is still there")
	}
	if _, ok := names["ix_source_published_cursor"]; !ok {
		t.Errorf("the replacement index was not created: %v", names)
	}
}

// A fresh database has none of the obsolete indexes, and a second run has none
// left, so both must be no-ops rather than errors.
func TestDroppingObsoleteIndexesIsSafeToRepeat(t *testing.T) {
	db := newTestClient(t).Database()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if _, err := DropObsoleteIndexes(ctx, db); err != nil {
		t.Fatalf("DropObsoleteIndexes on an empty database: %v", err)
	}
	if _, err := EnsureCollections(ctx, db); err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if _, err := EnsureIndexes(ctx, db); err != nil {
		t.Fatalf("EnsureIndexes: %v", err)
	}

	dropped, err := DropObsoleteIndexes(ctx, db)
	if err != nil {
		t.Fatalf("second DropObsoleteIndexes: %v", err)
	}
	if len(dropped) != 0 {
		t.Errorf("dropped = %v, want nothing on a database that never had them", dropped)
	}

	// The plan must still apply cleanly afterwards.
	if _, err := EnsureIndexes(ctx, db); err != nil {
		t.Fatalf("EnsureIndexes after a repeat drop: %v", err)
	}
}
