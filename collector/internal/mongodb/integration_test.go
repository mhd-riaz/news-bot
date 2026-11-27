//go:build integration

package mongodb

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

// newTestClient connects to the MongoDB instance named by NEWS_TEST_MONGO_URI
// (default: the local Docker Compose one) using a database unique to this run.
func newTestClient(t *testing.T) *Client {
	t.Helper()

	uri := os.Getenv("NEWS_TEST_MONGO_URI")
	if uri == "" {
		uri = "mongodb://localhost:27017"
	}

	client, err := Connect(Settings{
		URI: uri,
		// Nanoseconds, not a formatted timestamp: two tests starting inside the
		// same second would otherwise share a database and each one's cleanup
		// would drop the other's data out from under it.
		Database:               fmt.Sprintf("news_it_%d", time.Now().UnixNano()),
		AppName:                "news-collector-tests",
		ConnectTimeout:         5 * time.Second,
		ServerSelectionTimeout: 5 * time.Second,
		OperationTimeout:       10 * time.Second,
		MaxPoolSize:            5,
	})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := client.Ping(ctx); err != nil {
		t.Fatalf("MongoDB is not reachable at %s: %v", uri, err)
	}

	t.Cleanup(func() {
		cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cleanupCancel()
		if err := client.Database().Drop(cleanupCtx); err != nil {
			t.Errorf("drop test database: %v", err)
		}
		if err := client.Close(cleanupCtx); err != nil {
			t.Errorf("close client: %v", err)
		}
	})

	return client
}

func TestMigrationCreatesCollectionsAndIndexes(t *testing.T) {
	client := newTestClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	created, err := EnsureCollections(ctx, client.Database())
	if err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if len(created) != len(Collections()) {
		t.Errorf("created %d collections, want %d", len(created), len(Collections()))
	}

	applied, err := EnsureIndexes(ctx, client.Database())
	if err != nil {
		t.Fatalf("EnsureIndexes: %v", err)
	}

	for _, ci := range IndexPlan() {
		if got := len(applied[ci.Collection]); got != len(ci.Models) {
			t.Errorf("%s: applied %d indexes, want %d", ci.Collection, got, len(ci.Models))
		}
	}
}

func TestMigrationIsIdempotent(t *testing.T) {
	client := newTestClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	for range 2 {
		if _, err := EnsureCollections(ctx, client.Database()); err != nil {
			t.Fatalf("EnsureCollections: %v", err)
		}
		if _, err := EnsureIndexes(ctx, client.Database()); err != nil {
			t.Fatalf("EnsureIndexes: %v", err)
		}
	}

	secondRun, err := EnsureCollections(ctx, client.Database())
	if err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if len(secondRun) != 0 {
		t.Errorf("a repeat migration must create nothing, got %v", secondRun)
	}
}

func TestNormalizedURLUniquenessIsEnforced(t *testing.T) {
	client := newTestClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if _, err := EnsureCollections(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if _, err := EnsureIndexes(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureIndexes: %v", err)
	}

	articles := client.Database().Collection(CollectionArticles)
	doc := bson.D{
		{Key: "dedup_id", Value: "dedup-1"},
		{Key: "normalized_url", Value: "https://example.test/story"},
	}

	if _, err := articles.InsertOne(ctx, doc); err != nil {
		t.Fatalf("first insert should succeed: %v", err)
	}

	duplicate := bson.D{
		{Key: "dedup_id", Value: "dedup-2"},
		{Key: "normalized_url", Value: "https://example.test/story"},
	}
	if _, err := articles.InsertOne(ctx, duplicate); err == nil {
		t.Fatal("the unique index must reject a duplicate normalized URL")
	}
}

// The Python server relies on these indexes: one invite per email, one reader per
// Google account (but many invites before first sign-in), and TTL-expired sessions.
func TestReaderIndexesAreEnforced(t *testing.T) {
	client := newTestClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if _, err := EnsureCollections(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if _, err := EnsureIndexes(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureIndexes: %v", err)
	}

	readers := client.Database().Collection(CollectionReaders)
	for i, doc := range []bson.D{
		{{Key: "_id", Value: "reader-1"}, {Key: "email", Value: "a@example.test"}, {Key: "invited", Value: true}},
		{{Key: "_id", Value: "reader-2"}, {Key: "email", Value: "b@example.test"}, {Key: "invited", Value: true}},
	} {
		if _, err := readers.InsertOne(ctx, doc); err != nil {
			t.Fatalf("invite %d without a Google account must be accepted: %v", i, err)
		}
	}
	if _, err := readers.InsertOne(ctx, bson.D{{Key: "_id", Value: "reader-3"}, {Key: "email", Value: "a@example.test"}}); err == nil {
		t.Fatal("the unique index must reject a second invite for one email")
	}
	if _, err := readers.UpdateByID(ctx, "reader-1", bson.D{{Key: "$set", Value: bson.D{{Key: "google_sub", Value: "sub-1"}}}}); err != nil {
		t.Fatalf("binding a Google account: %v", err)
	}
	if _, err := readers.UpdateByID(ctx, "reader-2", bson.D{{Key: "$set", Value: bson.D{{Key: "google_sub", Value: "sub-1"}}}}); err == nil {
		t.Fatal("the unique index must stop one Google account binding two readers")
	}

	cursor, err := client.Database().Collection(CollectionReaderSessions).Indexes().List(ctx)
	if err != nil {
		t.Fatalf("list session indexes: %v", err)
	}
	var specs []struct {
		Name               string `bson:"name"`
		ExpireAfterSeconds *int32 `bson:"expireAfterSeconds"`
	}
	if err := cursor.All(ctx, &specs); err != nil {
		t.Fatalf("decode session indexes: %v", err)
	}
	for _, spec := range specs {
		if spec.Name == "ttl_expires_at" && spec.ExpireAfterSeconds != nil && *spec.ExpireAfterSeconds == 0 {
			return
		}
	}
	t.Fatalf("reader_sessions has no TTL index on expires_at: %+v", specs)
}

func TestPingFailsAgainstUnreachableDeployment(t *testing.T) {
	client, err := Connect(Settings{
		URI:                    "mongodb://127.0.0.1:1",
		Database:               "news",
		ConnectTimeout:         time.Second,
		ServerSelectionTimeout: time.Second,
		OperationTimeout:       2 * time.Second,
		MaxPoolSize:            1,
	})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = client.Close(ctx)
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.Ping(ctx); err == nil {
		t.Fatal("ping must fail when no deployment is listening")
	}
}
