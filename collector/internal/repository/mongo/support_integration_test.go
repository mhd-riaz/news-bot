//go:build integration

package mongo

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	driver "go.mongodb.org/mongo-driver/v2/mongo"

	"github.com/riaz/newscollector/internal/mongodb"
)

// newTestDatabase connects to the MongoDB instance named by NEWS_TEST_MONGO_URI
// (default: the local Docker Compose one) using a database unique to this run,
// and applies the real migration so the tests exercise the production indexes.
// The database is dropped when the test ends.
func newTestDatabase(t *testing.T, prefix string) *driver.Database {
	t.Helper()

	uri := os.Getenv("NEWS_TEST_MONGO_URI")
	if uri == "" {
		uri = "mongodb://localhost:27017"
	}

	client, err := mongodb.Connect(mongodb.Settings{
		URI: uri,
		// Nanoseconds keep the name unique per test without the '.' that a
		// fractional-second timestamp would introduce; MongoDB forbids it.
		Database:               fmt.Sprintf("news_it_%s_%d", prefix, time.Now().UnixNano()),
		AppName:                "news-collector-tests",
		ConnectTimeout:         5 * time.Second,
		ServerSelectionTimeout: 5 * time.Second,
		OperationTimeout:       10 * time.Second,
		MaxPoolSize:            5,
	})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := client.Ping(ctx); err != nil {
		t.Fatalf("MongoDB is not reachable at %s: %v", uri, err)
	}
	if _, err := mongodb.EnsureCollections(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureCollections: %v", err)
	}
	if _, err := mongodb.EnsureIndexes(ctx, client.Database()); err != nil {
		t.Fatalf("EnsureIndexes: %v", err)
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

	return client.Database()
}

func testContext(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	t.Cleanup(cancel)
	return ctx
}
