//go:build integration

package mongo

import (
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func TestFeedCacheRoundTripsAndReplaces(t *testing.T) {
	repo := NewFeedCacheRepository(newTestDatabase(t, "cache"))
	ctx := testContext(t)
	sourceID := "0198f3d2-1111-7000-8000-000000000001"
	now := time.Now().UTC()

	if _, err := repo.Get(ctx, sourceID); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("Get before any save = %v, want ErrNotFound", err)
	}

	if err := repo.Save(ctx, domain.NewFeedCacheEntry(sourceID, `W/"one"`, "Fri, 22 Aug 2026 10:00:00 GMT", now)); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if err := repo.Save(ctx, domain.NewFeedCacheEntry(sourceID, `W/"two"`, "", now.Add(time.Minute))); err != nil {
		t.Fatalf("second Save: %v", err)
	}

	got, err := repo.Get(ctx, sourceID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.ETag != `W/"two"` {
		t.Errorf("etag = %q, want the most recent one", got.ETag)
	}
	if got.LastModified != "" {
		t.Errorf("last modified = %q, want the previous value replaced rather than merged", got.LastModified)
	}
}

// uq_cache_source is what keeps one source to one cache document when two
// collectors finish at the same moment.
func TestFeedCacheKeepsOneDocumentPerSource(t *testing.T) {
	repo := NewFeedCacheRepository(newTestDatabase(t, "cache"))
	ctx := testContext(t)
	sourceID := "0198f3d2-1111-7000-8000-000000000002"
	now := time.Now().UTC()

	var wg sync.WaitGroup
	for i := range 8 {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			// A duplicate key here means another writer won, which is a valid
			// outcome rather than a fault.
			err := repo.Save(ctx, domain.NewFeedCacheEntry(sourceID, `W/"racer"`, "", now.Add(time.Duration(i)*time.Second)))
			if err != nil && !errors.Is(err, repository.ErrDuplicate) {
				t.Errorf("Save: %v", err)
			}
		}(i)
	}
	wg.Wait()

	if _, err := repo.Get(ctx, sourceID); err != nil {
		t.Fatalf("Get: %v", err)
	}
}
