//go:build integration

package mongo

import (
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func TestLockIsExclusiveWhileItLasts(t *testing.T) {
	repo := NewLockRepository(newTestDatabase(t, "locks"))
	ctx := testContext(t)
	resource := domain.SourceLockResource("0198f3d2-1111-7000-8000-000000000001")
	now := time.Now().UTC()

	acquired, err := repo.Acquire(ctx, domain.NewLock(resource, "collector-a", now, time.Minute))
	if err != nil || !acquired {
		t.Fatalf("first Acquire = %v, %v; want it granted", acquired, err)
	}

	acquired, err = repo.Acquire(ctx, domain.NewLock(resource, "collector-b", now, time.Minute))
	if err != nil {
		t.Fatalf("second Acquire: %v", err)
	}
	if acquired {
		t.Fatal("two collectors hold the same source at once")
	}
}

func TestLockCanBeTakenOverOnceItExpires(t *testing.T) {
	repo := NewLockRepository(newTestDatabase(t, "locks"))
	ctx := testContext(t)
	resource := domain.SourceLockResource("0198f3d2-1111-7000-8000-000000000002")
	now := time.Now().UTC()

	if _, err := repo.Acquire(ctx, domain.NewLock(resource, "crashed-collector", now, time.Second)); err != nil {
		t.Fatalf("Acquire: %v", err)
	}

	// A collector that crashed never released its lease; a later one must be
	// able to take the source over without waiting for the TTL reaper.
	acquired, err := repo.Acquire(ctx, domain.NewLock(resource, "next-collector", now.Add(2*time.Second), time.Minute))
	if err != nil {
		t.Fatalf("Acquire after expiry: %v", err)
	}
	if !acquired {
		t.Fatal("an expired lease was not taken over")
	}
}

func TestReleaseFreesTheResource(t *testing.T) {
	repo := NewLockRepository(newTestDatabase(t, "locks"))
	ctx := testContext(t)
	resource := domain.SourceLockResource("0198f3d2-1111-7000-8000-000000000003")
	now := time.Now().UTC()

	if _, err := repo.Acquire(ctx, domain.NewLock(resource, "collector-a", now, time.Minute)); err != nil {
		t.Fatalf("Acquire: %v", err)
	}
	if err := repo.Release(ctx, resource, "collector-a"); err != nil {
		t.Fatalf("Release: %v", err)
	}

	acquired, err := repo.Acquire(ctx, domain.NewLock(resource, "collector-b", now, time.Minute))
	if err != nil || !acquired {
		t.Fatalf("Acquire after release = %v, %v; want it granted", acquired, err)
	}
}

// A collector whose lease expired and was taken over must not be able to
// release the new holder's lease.
func TestReleaseRefusesAnotherOwnersLease(t *testing.T) {
	repo := NewLockRepository(newTestDatabase(t, "locks"))
	ctx := testContext(t)
	resource := domain.SourceLockResource("0198f3d2-1111-7000-8000-000000000004")
	now := time.Now().UTC()

	if _, err := repo.Acquire(ctx, domain.NewLock(resource, "current-holder", now, time.Minute)); err != nil {
		t.Fatalf("Acquire: %v", err)
	}

	err := repo.Release(ctx, resource, "previous-holder")

	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("Release by a stale owner = %v, want ErrNotFound", err)
	}
	acquired, err := repo.Acquire(ctx, domain.NewLock(resource, "somebody-else", now, time.Minute))
	if err != nil {
		t.Fatalf("Acquire: %v", err)
	}
	if acquired {
		t.Fatal("the current holder's lease was dropped by the previous one")
	}
}

// The point of the lease: whatever the contention, exactly one collector wins.
func TestOnlyOneCollectorWinsAContestedSource(t *testing.T) {
	repo := NewLockRepository(newTestDatabase(t, "locks"))
	ctx := testContext(t)
	resource := domain.SourceLockResource("0198f3d2-1111-7000-8000-000000000005")
	now := time.Now().UTC()

	var winners atomic.Int32
	var wg sync.WaitGroup
	for i := range 16 {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			acquired, err := repo.Acquire(ctx, domain.NewLock(resource, string(rune('a'+i)), now, time.Minute))
			if err != nil {
				t.Errorf("Acquire: %v", err)
				return
			}
			if acquired {
				winners.Add(1)
			}
		}(i)
	}
	wg.Wait()

	if got := winners.Load(); got != 1 {
		t.Fatalf("%d collectors acquired the same lease, want exactly 1", got)
	}
}
