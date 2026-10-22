//go:build integration

package mongo

import (
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func newTestRepo(t *testing.T) *SourceRepository {
	t.Helper()
	return NewSourceRepository(newTestDatabase(t, "src"))
}

func newSource(t *testing.T, feedURL string, mutate ...func(*domain.SourceInput)) *domain.Source {
	t.Helper()
	in := domain.SourceInput{
		Name:     "Test Source",
		FeedURL:  feedURL,
		Type:     domain.SourceTypeRSS,
		Language: "en",
		Country:  "IN",
		State:    "Karnataka",
		City:     "Bengaluru",
	}
	for _, m := range mutate {
		m(&in)
	}
	src, err := domain.NewSource(in, time.Now().UTC())
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	return src
}

func TestListDueReturnsOverdueSourcesByPriority(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	now := time.Now().UTC()

	// Overdue, low priority.
	low := newSource(t, "https://example.com/low.rss", func(in *domain.SourceInput) {
		in.Priority = ptrTo(10)
	})
	low.NextScheduledAt = now.Add(-time.Hour)

	// Overdue, high priority: must come first.
	high := newSource(t, "https://example.com/high.rss", func(in *domain.SourceInput) {
		in.Priority = ptrTo(90)
	})
	high.NextScheduledAt = now.Add(-time.Minute)

	// Not due yet, and a disabled one that is overdue: neither may be returned.
	future := newSource(t, "https://example.com/future.rss")
	future.NextScheduledAt = now.Add(time.Hour)

	disabled := newSource(t, "https://example.com/disabled.rss", func(in *domain.SourceInput) {
		in.Enabled = ptrTo(false)
	})
	disabled.NextScheduledAt = now.Add(-time.Hour)

	for _, src := range []*domain.Source{low, high, future, disabled} {
		if err := repo.Create(ctx, src); err != nil {
			t.Fatalf("Create %s: %v", src.FeedURL, err)
		}
	}

	due, err := repo.ListDue(ctx, now, 10)
	if err != nil {
		t.Fatalf("ListDue: %v", err)
	}

	if len(due) != 2 {
		t.Fatalf("due = %d sources, want only the two enabled and overdue ones", len(due))
	}
	if due[0].ID != high.ID || due[1].ID != low.ID {
		t.Errorf("order = %q then %q, want the higher priority first", due[0].Name, due[1].Name)
	}
}

func TestListDueRespectsTheLimit(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	now := time.Now().UTC()

	for i := range 5 {
		src := newSource(t, "https://example.com/"+string(rune('a'+i))+".rss")
		src.NextScheduledAt = now.Add(-time.Hour)
		if err := repo.Create(ctx, src); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}

	due, err := repo.ListDue(ctx, now, 2)
	if err != nil {
		t.Fatalf("ListDue: %v", err)
	}
	if len(due) != 2 {
		t.Fatalf("due = %d sources, want the limit of 2", len(due))
	}
}

func ptrTo[T any](v T) *T { return &v }

// A collection must write back its own fields without carrying the rest of the
// document it loaded before the fetch.
func TestUpdateCollectionStateLeavesOperatorFieldsAlone(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	now := time.Now().UTC()

	src := newSource(t, "https://example.com/state.rss")
	if err := repo.Create(ctx, src); err != nil {
		t.Fatalf("Create: %v", err)
	}

	// The operator disables the feed while a collection is in flight.
	edited, err := repo.GetByID(ctx, src.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if err := edited.Apply(domain.SourcePatch{Enabled: ptrTo(false)}, now); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if err := repo.Update(ctx, edited); err != nil {
		t.Fatalf("Update: %v", err)
	}

	// The collector still holds the copy it loaded before that edit.
	src.RecordSuccess(now.Add(time.Second))
	if err := repo.UpdateCollectionState(ctx, src); err != nil {
		t.Fatalf("UpdateCollectionState: %v", err)
	}

	got, err := repo.GetByID(ctx, src.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Enabled {
		t.Error("the collection re-enabled a source the operator had disabled")
	}
	if got.HealthStatus != domain.HealthHealthy || got.LastCollectedAt == nil {
		t.Errorf("source = %+v, want the collection's own fields written", got)
	}
}

func TestUpdateCollectionStateReportsAMissingSource(t *testing.T) {
	repo := newTestRepo(t)
	src := newSource(t, "https://example.com/gone.rss")

	err := repo.UpdateCollectionState(testContext(t), src)

	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

func TestCreateAndReadBack(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	src := newSource(t, "https://example.com/one.rss")

	if err := repo.Create(ctx, src); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.GetByID(ctx, src.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.ID != src.ID || got.FeedURL != src.FeedURL {
		t.Errorf("read back %+v, want %+v", got, src)
	}
	if got.Country != "IN" || got.Language != "en" {
		t.Errorf("region round-tripped as %q/%q", got.Country, got.Language)
	}
	// Round-tripping the interval must not turn seconds into nanoseconds.
	if got.FetchIntervalSeconds != domain.DefaultFetchIntervalSeconds {
		t.Errorf("fetch_interval_seconds = %d, want %d", got.FetchIntervalSeconds, domain.DefaultFetchIntervalSeconds)
	}
	if got.NextScheduledAt.IsZero() || got.CreatedAt.IsZero() {
		t.Error("timestamps did not survive the round trip")
	}
	// The value the API returned on the write must equal the one a read returns,
	// which only holds if the domain already rounded to BSON's precision.
	if !got.CreatedAt.Equal(src.CreatedAt) {
		t.Errorf("created_at read back as %v, want the written %v", got.CreatedAt, src.CreatedAt)
	}
	if !got.UpdatedAt.Equal(src.UpdatedAt) {
		t.Errorf("updated_at read back as %v, want the written %v", got.UpdatedAt, src.UpdatedAt)
	}
	if !got.NextScheduledAt.Equal(src.NextScheduledAt) {
		t.Errorf("next_scheduled_at read back as %v, want the written %v", got.NextScheduledAt, src.NextScheduledAt)
	}
}

// The unique index, not a prior read, must be what rejects a duplicate.
func TestCreateRejectsADuplicateFeedURL(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)

	if err := repo.Create(ctx, newSource(t, "https://example.com/dup.rss")); err != nil {
		t.Fatalf("first Create: %v", err)
	}

	err := repo.Create(ctx, newSource(t, "https://example.com/dup.rss"))
	if !errors.Is(err, repository.ErrDuplicate) {
		t.Fatalf("error = %v, want repository.ErrDuplicate", err)
	}
}

func TestGetByIDReturnsNotFound(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)

	_, err := repo.GetByID(ctx, "0198f3d2-0000-7000-8000-00000000dead")
	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("error = %v, want repository.ErrNotFound", err)
	}
}

func TestGetByFeedURL(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	src := newSource(t, "https://example.com/lookup.rss")
	if err := repo.Create(ctx, src); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.GetByFeedURL(ctx, src.FeedURL)
	if err != nil {
		t.Fatalf("GetByFeedURL: %v", err)
	}
	if got.ID != src.ID {
		t.Errorf("id = %q, want %q", got.ID, src.ID)
	}

	if _, err := repo.GetByFeedURL(ctx, "https://example.com/absent.rss"); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("error = %v, want repository.ErrNotFound", err)
	}
}

func TestUpdateReplacesTheStoredDocument(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	src := newSource(t, "https://example.com/update.rss")
	if err := repo.Create(ctx, src); err != nil {
		t.Fatalf("Create: %v", err)
	}

	src.Enabled = false
	src.Priority = 90
	src.LastError = ""
	if err := repo.Update(ctx, src); err != nil {
		t.Fatalf("Update: %v", err)
	}

	got, err := repo.GetByID(ctx, src.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Enabled || got.Priority != 90 {
		t.Errorf("stored %+v, want the replacement applied", got)
	}
}

func TestUpdateReportsAnUnknownID(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	src := newSource(t, "https://example.com/ghost.rss")

	if err := repo.Update(ctx, src); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("error = %v, want repository.ErrNotFound", err)
	}
}

func TestUpdateReportsAColliderFeedURL(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	first := newSource(t, "https://example.com/a.rss")
	second := newSource(t, "https://example.com/b.rss")
	if err := repo.Create(ctx, first); err != nil {
		t.Fatalf("Create: %v", err)
	}
	if err := repo.Create(ctx, second); err != nil {
		t.Fatalf("Create: %v", err)
	}

	first.FeedURL = second.FeedURL
	if err := repo.Update(ctx, first); !errors.Is(err, repository.ErrDuplicate) {
		t.Fatalf("error = %v, want repository.ErrDuplicate", err)
	}
}

func TestDelete(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)
	src := newSource(t, "https://example.com/delete.rss")
	if err := repo.Create(ctx, src); err != nil {
		t.Fatalf("Create: %v", err)
	}

	if err := repo.Delete(ctx, src.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if err := repo.Delete(ctx, src.ID); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("second Delete returned %v, want repository.ErrNotFound", err)
	}
}

func TestListFiltersAndPaginates(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)

	seed := []struct {
		url     string
		enabled bool
		country string
		typ     domain.SourceType
	}{
		{"https://example.com/1.rss", true, "IN", domain.SourceTypeRSS},
		{"https://example.com/2.rss", true, "IN", domain.SourceTypeAtom},
		{"https://example.com/3.rss", false, "IN", domain.SourceTypeRSS},
		{"https://example.com/4.rss", true, "US", domain.SourceTypeRSS},
	}
	for _, s := range seed {
		src := newSource(t, s.url, func(in *domain.SourceInput) {
			in.Enabled = &s.enabled
			in.Country = s.country
			in.Type = s.typ
		})
		if err := repo.Create(ctx, src); err != nil {
			t.Fatalf("Create %s: %v", s.url, err)
		}
	}

	enabled := true
	rss := domain.SourceTypeRSS
	tests := []struct {
		name      string
		filter    domain.SourceFilter
		wantTotal int64
	}{
		{"no filter", domain.SourceFilter{Limit: 10}, 4},
		{"enabled only", domain.SourceFilter{Limit: 10, Enabled: &enabled}, 3},
		{"country", domain.SourceFilter{Limit: 10, Country: "IN"}, 3},
		{"type", domain.SourceFilter{Limit: 10, Type: &rss}, 3},
		{"enabled and country", domain.SourceFilter{Limit: 10, Enabled: &enabled, Country: "IN"}, 2},
		{"no match", domain.SourceFilter{Limit: 10, Country: "FR"}, 0},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			page, err := repo.List(ctx, tc.filter)
			if err != nil {
				t.Fatalf("List: %v", err)
			}
			if page.Total != tc.wantTotal {
				t.Errorf("total = %d, want %d", page.Total, tc.wantTotal)
			}
			if int64(len(page.Items)) != tc.wantTotal {
				t.Errorf("items = %d, want %d", len(page.Items), tc.wantTotal)
			}
		})
	}

	// Paging must be stable: the two pages together must cover every source once.
	seen := make(map[string]bool)
	for offset := 0; offset < 4; offset += 2 {
		page, err := repo.List(ctx, domain.SourceFilter{Limit: 2, Offset: offset})
		if err != nil {
			t.Fatalf("List offset %d: %v", offset, err)
		}
		if len(page.Items) != 2 {
			t.Fatalf("page at offset %d holds %d items, want 2", offset, len(page.Items))
		}
		for _, item := range page.Items {
			if seen[item.ID] {
				t.Errorf("source %q appeared on more than one page", item.ID)
			}
			seen[item.ID] = true
		}
	}
	if len(seen) != 4 {
		t.Errorf("paging covered %d sources, want 4", len(seen))
	}
}

func TestListReturnsAnEmptyPageRatherThanNil(t *testing.T) {
	repo := newTestRepo(t)
	ctx := testContext(t)

	page, err := repo.List(ctx, domain.SourceFilter{Limit: 10})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if page.Items == nil {
		t.Error("items = nil, want an empty slice")
	}
	if page.Total != 0 {
		t.Errorf("total = %d, want 0", page.Total)
	}
}
