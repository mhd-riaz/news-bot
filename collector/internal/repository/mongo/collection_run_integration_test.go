//go:build integration

package mongo

import (
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func newRun(t *testing.T, sourceID string, status domain.RunStatus, startedAt time.Time) *domain.CollectionRun {
	t.Helper()
	run, err := domain.NewCollectionRun(domain.Source{ID: sourceID, Name: "Test Source"}, startedAt)
	if err != nil {
		t.Fatalf("NewCollectionRun: %v", err)
	}
	if status == domain.RunStatusFailed {
		run.Fail("the publisher answered HTTP 503", startedAt.Add(time.Second))
		return run
	}
	run.ItemsFound, run.ItemsStored = 5, 5
	run.Complete(startedAt.Add(time.Second), status == domain.RunStatusNotModified)
	return run
}

func TestCollectionRunRoundTrips(t *testing.T) {
	repo := NewCollectionRunRepository(newTestDatabase(t, "runs"))
	ctx := testContext(t)
	run := newRun(t, "0198f3d2-1111-7000-8000-000000000001", domain.RunStatusSuccess, time.Now().UTC())

	if err := repo.Create(ctx, run); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.GetByID(ctx, run.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.SourceID != run.SourceID || got.Status != domain.RunStatusSuccess {
		t.Errorf("read back %+v, want %+v", got, run)
	}
	if got.ItemsStored != 5 || got.DurationMS != 1000 {
		t.Errorf("counters round-tripped as stored=%d duration=%dms", got.ItemsStored, got.DurationMS)
	}
	if !got.StartedAt.Equal(run.StartedAt) {
		t.Errorf("started at = %v, want %v", got.StartedAt, run.StartedAt)
	}
}

func TestGetCollectionRunReportsMissing(t *testing.T) {
	repo := NewCollectionRunRepository(newTestDatabase(t, "runs"))

	_, err := repo.GetByID(testContext(t), "0198f3d2-2222-7000-8000-000000000009")

	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

func TestListCollectionRunsIsNewestFirstAndFiltered(t *testing.T) {
	repo := NewCollectionRunRepository(newTestDatabase(t, "runs"))
	ctx := testContext(t)

	base := time.Now().UTC().Truncate(time.Millisecond)
	sourceA := "0198f3d2-1111-7000-8000-00000000000a"
	sourceB := "0198f3d2-1111-7000-8000-00000000000b"

	// Three runs of A, oldest first, and one of B.
	for i := range 3 {
		status := domain.RunStatusSuccess
		if i == 1 {
			status = domain.RunStatusFailed
		}
		if err := repo.Create(ctx, newRun(t, sourceA, status, base.Add(time.Duration(i)*time.Minute))); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}
	if err := repo.Create(ctx, newRun(t, sourceB, domain.RunStatusSuccess, base)); err != nil {
		t.Fatalf("Create: %v", err)
	}

	page, err := repo.List(ctx, domain.CollectionRunFilter{SourceID: sourceA, Limit: 50})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if page.Total != 3 || len(page.Items) != 3 {
		t.Fatalf("page = %d of %d, want 3 of 3 for one source", len(page.Items), page.Total)
	}
	for i := 1; i < len(page.Items); i++ {
		if page.Items[i].StartedAt.After(page.Items[i-1].StartedAt) {
			t.Fatalf("runs are not newest first: %v then %v", page.Items[i-1].StartedAt, page.Items[i].StartedAt)
		}
	}

	failed := domain.RunStatusFailed
	page, err = repo.List(ctx, domain.CollectionRunFilter{Status: &failed, Limit: 50})
	if err != nil {
		t.Fatalf("List by status: %v", err)
	}
	if page.Total != 1 || page.Items[0].Error == "" {
		t.Fatalf("status filter returned %+v, want the single failed run with its reason", page.Items)
	}
}

func TestListCollectionRunsPaginates(t *testing.T) {
	repo := NewCollectionRunRepository(newTestDatabase(t, "runs"))
	ctx := testContext(t)
	base := time.Now().UTC()

	for i := range 5 {
		if err := repo.Create(ctx, newRun(t, "0198f3d2-1111-7000-8000-00000000000c",
			domain.RunStatusSuccess, base.Add(time.Duration(i)*time.Minute))); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}

	seen := make(map[string]struct{}, 5)
	for offset := 0; offset < 5; offset += 2 {
		page, err := repo.List(ctx, domain.CollectionRunFilter{Limit: 2, Offset: offset})
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		if page.Total != 5 {
			t.Fatalf("total = %d, want 5 on every page", page.Total)
		}
		for _, run := range page.Items {
			if _, dup := seen[run.ID]; dup {
				t.Fatalf("run %s appeared on two pages", run.ID)
			}
			seen[run.ID] = struct{}{}
		}
	}
	if len(seen) != 5 {
		t.Errorf("paging returned %d distinct runs, want 5", len(seen))
	}
}
