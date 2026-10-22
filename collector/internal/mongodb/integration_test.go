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
