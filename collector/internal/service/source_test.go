package service

import (
	"context"
	"errors"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

var fixedNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func fixedClock() time.Time { return fixedNow }

func ptr[T any](v T) *T { return &v }

// fakeSourceRepo is an in-memory stand-in for the MongoDB repository. It
// enforces the same unique feed URL constraint the uq_feed_url index does, so a
// service test exercises the real conflict path rather than a happy path only.
type fakeSourceRepo struct {
	mu       sync.Mutex
	byID     map[string]domain.Source
	failWith error
	// failOn injects a failure into one operation, so a test can fail the second
	// step of a multi-step use case while the first still succeeds.
	failOn map[string]error
}

func newFakeRepo() *fakeSourceRepo {
	return &fakeSourceRepo{byID: make(map[string]domain.Source), failOn: make(map[string]error)}
}

// fail reports the error this call should return, if any. The caller must hold mu.
func (f *fakeSourceRepo) fail(op string) error {
	if f.failWith != nil {
		return f.failWith
	}
	return f.failOn[op]
}

var _ repository.SourceRepository = (*fakeSourceRepo)(nil)

func (f *fakeSourceRepo) Create(_ context.Context, s *domain.Source) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("Create"); err != nil {
		return err
	}
	for _, existing := range f.byID {
		if existing.FeedURL == s.FeedURL {
			return repository.ErrDuplicate
		}
	}
	f.byID[s.ID] = *s
	return nil
}

func (f *fakeSourceRepo) GetByID(_ context.Context, id string) (*domain.Source, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("GetByID"); err != nil {
		return nil, err
	}
	s, ok := f.byID[id]
	if !ok {
		return nil, repository.ErrNotFound
	}
	return &s, nil
}

func (f *fakeSourceRepo) GetByFeedURL(_ context.Context, feedURL string) (*domain.Source, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("GetByFeedURL"); err != nil {
		return nil, err
	}
	for _, s := range f.byID {
		if s.FeedURL == feedURL {
			return &s, nil
		}
	}
	return nil, repository.ErrNotFound
}

func (f *fakeSourceRepo) List(_ context.Context, filter domain.SourceFilter) (domain.SourcePage, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("List"); err != nil {
		return domain.SourcePage{}, err
	}
	items := make([]domain.Source, 0, len(f.byID))
	for _, s := range f.byID {
		if filter.Enabled != nil && s.Enabled != *filter.Enabled {
			continue
		}
		if filter.Country != "" && s.Country != filter.Country {
			continue
		}
		items = append(items, s)
	}
	return domain.SourcePage{Items: items, Total: int64(len(items)), Limit: filter.Limit, Offset: filter.Offset}, nil
}

// ListDue mirrors the real query: enabled sources whose next collection has come
// round, most important first, capped at limit.
func (f *fakeSourceRepo) ListDue(_ context.Context, now time.Time, limit int) ([]domain.Source, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("ListDue"); err != nil {
		return nil, err
	}

	items := make([]domain.Source, 0, len(f.byID))
	for _, s := range f.byID {
		if s.Enabled && !s.NextScheduledAt.After(now) {
			items = append(items, s)
		}
	}
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].Priority != items[j].Priority {
			return items[i].Priority > items[j].Priority
		}
		return items[i].NextScheduledAt.Before(items[j].NextScheduledAt)
	})
	if len(items) > limit {
		items = items[:limit]
	}
	return items, nil
}

func (f *fakeSourceRepo) Update(_ context.Context, s *domain.Source) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("Update"); err != nil {
		return err
	}
	if _, ok := f.byID[s.ID]; !ok {
		return repository.ErrNotFound
	}
	for id, existing := range f.byID {
		if id != s.ID && existing.FeedURL == s.FeedURL {
			return repository.ErrDuplicate
		}
	}
	f.byID[s.ID] = *s
	return nil
}

// UpdateCollectionState mirrors the real field-scoped update: only what a
// collection owns is written, so a test can prove an operator's concurrent edit
// survives.
func (f *fakeSourceRepo) UpdateCollectionState(_ context.Context, s *domain.Source) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("UpdateCollectionState"); err != nil {
		return err
	}
	stored, ok := f.byID[s.ID]
	if !ok {
		return repository.ErrNotFound
	}

	stored.HealthStatus = s.HealthStatus
	stored.ConsecutiveFailures = s.ConsecutiveFailures
	stored.LastError = s.LastError
	stored.NextScheduledAt = s.NextScheduledAt
	stored.UpdatedAt = s.UpdatedAt
	if s.LastCollectedAt != nil {
		stored.LastCollectedAt = s.LastCollectedAt
	}

	f.byID[s.ID] = stored
	return nil
}

func (f *fakeSourceRepo) Delete(_ context.Context, id string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.fail("Delete"); err != nil {
		return err
	}
	if _, ok := f.byID[id]; !ok {
		return repository.ErrNotFound
	}
	delete(f.byID, id)
	return nil
}

func validInput() domain.SourceInput {
	return domain.SourceInput{
		Name:     "The Hindu — Bengaluru",
		FeedURL:  "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
		Type:     domain.SourceTypeRSS,
		Language: "en",
		Country:  "IN",
		State:    "Karnataka",
		City:     "Bengaluru",
	}
}

func newService(t *testing.T) (*SourceService, *fakeSourceRepo) {
	t.Helper()
	repo := newFakeRepo()
	return NewSourceService(repo, fixedClock), repo
}

func TestCreateStoresAValidSource(t *testing.T) {
	svc, repo := newService(t)

	src, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if src.ID == "" {
		t.Error("created source has no id")
	}
	if !src.CreatedAt.Equal(fixedNow) {
		t.Errorf("created_at = %v, want the injected clock %v", src.CreatedAt, fixedNow)
	}
	if len(repo.byID) != 1 {
		t.Errorf("repository holds %d sources, want 1", len(repo.byID))
	}
}

func TestCreateRejectsInvalidInputBeforeTouchingTheRepository(t *testing.T) {
	svc, repo := newService(t)
	in := validInput()
	in.FeedURL = "file:///etc/passwd"

	_, err := svc.Create(context.Background(), in)
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
	if len(repo.byID) != 0 {
		t.Errorf("repository holds %d sources, want the write to have been refused", len(repo.byID))
	}
}

func TestCreateReportsADuplicateFeedURLAsConflict(t *testing.T) {
	svc, _ := newService(t)
	if _, err := svc.Create(context.Background(), validInput()); err != nil {
		t.Fatalf("first Create: %v", err)
	}

	_, err := svc.Create(context.Background(), validInput())
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("error = %v, want ErrConflict", err)
	}
}

func TestGetReturnsNotFoundForAnUnknownID(t *testing.T) {
	svc, _ := newService(t)

	_, err := svc.Get(context.Background(), "0198f3d2-0000-7000-8000-000000000000")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

func TestGetRejectsAMalformedIDWithoutQueryingTheRepository(t *testing.T) {
	svc, repo := newService(t)
	repo.failWith = errors.New("the repository must not be reached")

	_, err := svc.Get(context.Background(), "not-a-uuid")
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

func TestUpdateAppliesAPartialChange(t *testing.T) {
	svc, _ := newService(t)
	created, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	updated, err := svc.Update(context.Background(), created.ID, domain.SourcePatch{Enabled: ptr(false)})
	if err != nil {
		t.Fatalf("Update: %v", err)
	}
	if updated.Enabled {
		t.Error("enabled = true, want false")
	}
	if updated.Name != created.Name {
		t.Errorf("name = %q, want it untouched", updated.Name)
	}
}

func TestUpdateRejectsAPatchThatWouldBreakTheModel(t *testing.T) {
	svc, repo := newService(t)
	created, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	_, err = svc.Update(context.Background(), created.ID, domain.SourcePatch{Priority: ptr(500)})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}

	stored := repo.byID[created.ID]
	if stored.Priority != domain.DefaultPriority {
		t.Errorf("stored priority = %d, want the rejected update not to have been persisted", stored.Priority)
	}
}

func TestUpdateReportsAColliderFeedURLAsConflict(t *testing.T) {
	svc, _ := newService(t)
	first, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	second := validInput()
	second.FeedURL = "https://www.deccanherald.com/rss/bengaluru.xml"
	if _, err := svc.Create(context.Background(), second); err != nil {
		t.Fatalf("Create: %v", err)
	}

	_, err = svc.Update(context.Background(), first.ID, domain.SourcePatch{FeedURL: ptr(second.FeedURL)})
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("error = %v, want ErrConflict", err)
	}
}

func TestUpdateReturnsNotFoundForAnUnknownID(t *testing.T) {
	svc, _ := newService(t)

	_, err := svc.Update(context.Background(), "0198f3d2-0000-7000-8000-000000000000", domain.SourcePatch{})
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

func TestDelete(t *testing.T) {
	svc, repo := newService(t)
	created, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	if err := svc.Delete(context.Background(), created.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if len(repo.byID) != 0 {
		t.Errorf("repository holds %d sources, want 0", len(repo.byID))
	}

	if err := svc.Delete(context.Background(), created.ID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("second Delete returned %v, want ErrNotFound", err)
	}
}

func TestListAppliesPaginationDefaults(t *testing.T) {
	svc, _ := newService(t)
	if _, err := svc.Create(context.Background(), validInput()); err != nil {
		t.Fatalf("Create: %v", err)
	}

	page, err := svc.List(context.Background(), domain.SourceFilter{})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if page.Limit != domain.DefaultListLimit {
		t.Errorf("limit = %d, want the default %d", page.Limit, domain.DefaultListLimit)
	}
	if page.Total != 1 {
		t.Errorf("total = %d, want 1", page.Total)
	}
}

func TestListRejectsAnOversizedLimit(t *testing.T) {
	svc, _ := newService(t)

	_, err := svc.List(context.Background(), domain.SourceFilter{Limit: domain.MaxListLimit + 1})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

func TestEnsureCreatesThenUpdatesTheSameFeed(t *testing.T) {
	svc, repo := newService(t)

	first, created, err := svc.Ensure(context.Background(), validInput())
	if err != nil {
		t.Fatalf("first Ensure: %v", err)
	}
	if !created {
		t.Error("created = false on the first Ensure, want true")
	}

	in := validInput()
	in.Name = "The Hindu — Bengaluru (city desk)"
	in.Priority = ptr(80)

	second, created, err := svc.Ensure(context.Background(), in)
	if err != nil {
		t.Fatalf("second Ensure: %v", err)
	}
	if created {
		t.Error("created = true on the second Ensure, want false")
	}
	if second.ID != first.ID {
		t.Errorf("id = %q, want the existing %q so seeding is idempotent", second.ID, first.ID)
	}
	if second.Name != in.Name || second.Priority != 80 {
		t.Errorf("source = %q/%d, want the seeded values applied", second.Name, second.Priority)
	}
	if len(repo.byID) != 1 {
		t.Errorf("repository holds %d sources, want reseeding not to duplicate", len(repo.byID))
	}
}

func TestEnsureLeavesUnsetFieldsAlone(t *testing.T) {
	svc, _ := newService(t)
	created, _, err := svc.Ensure(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	if _, err := svc.Update(context.Background(), created.ID, domain.SourcePatch{Priority: ptr(95)}); err != nil {
		t.Fatalf("Update: %v", err)
	}

	// Reseeding without a priority must not reset the hand-tuned value.
	reseeded, _, err := svc.Ensure(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	if reseeded.Priority != 95 {
		t.Errorf("priority = %d, want the operator's 95 preserved", reseeded.Priority)
	}
}

func TestRepositoryFailuresTravelUnchanged(t *testing.T) {
	svc, repo := newService(t)
	boom := errors.New("connection reset by peer")
	repo.failWith = boom

	_, err := svc.Create(context.Background(), validInput())
	if !errors.Is(err, boom) {
		t.Fatalf("error = %v, want the underlying failure to reach the caller for logging", err)
	}
	if errors.Is(err, ErrNotFound) || errors.Is(err, ErrConflict) {
		t.Error("an infrastructure failure was misreported as a domain outcome")
	}
}

func TestNewSourceServiceDefaultsTheClock(t *testing.T) {
	svc := NewSourceService(newFakeRepo(), nil)

	src, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if src.CreatedAt.IsZero() {
		t.Error("created_at is zero, want the default clock to have been used")
	}
}

func TestConflictMessageDoesNotLeakInternals(t *testing.T) {
	svc, _ := newService(t)
	if _, err := svc.Create(context.Background(), validInput()); err != nil {
		t.Fatalf("Create: %v", err)
	}

	_, err := svc.Create(context.Background(), validInput())
	if err == nil {
		t.Fatal("want a conflict")
	}
	if strings.Contains(err.Error(), "index") || strings.Contains(err.Error(), "mongo") {
		t.Errorf("conflict message %q leaks storage detail", err.Error())
	}
}

func TestDeleteRejectsAMalformedIDWithoutQueryingTheRepository(t *testing.T) {
	svc, repo := newService(t)
	repo.failWith = errors.New("the repository must not be reached")

	if err := svc.Delete(context.Background(), "not-a-uuid"); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

func TestUpdateRejectsAMalformedIDWithoutQueryingTheRepository(t *testing.T) {
	svc, repo := newService(t)
	repo.failWith = errors.New("the repository must not be reached")

	_, err := svc.Update(context.Background(), "not-a-uuid", domain.SourcePatch{})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

// Every read and write must surface an infrastructure failure rather than
// swallowing it or reporting it as a domain outcome.
func TestOperationsSurfaceRepositoryFailures(t *testing.T) {
	boom := errors.New("connection reset by peer")
	id := "0198f3d2-0000-7000-8000-000000000000"

	tests := []struct {
		name string
		op   string
		call func(*SourceService) error
	}{
		{"get", "GetByID", func(s *SourceService) error {
			_, err := s.Get(context.Background(), id)
			return err
		}},
		{"list", "List", func(s *SourceService) error {
			_, err := s.List(context.Background(), domain.SourceFilter{})
			return err
		}},
		{"update", "GetByID", func(s *SourceService) error {
			_, err := s.Update(context.Background(), id, domain.SourcePatch{})
			return err
		}},
		{"delete", "Delete", func(s *SourceService) error {
			return s.Delete(context.Background(), id)
		}},
		{"ensure", "Create", func(s *SourceService) error {
			_, _, err := s.Ensure(context.Background(), validInput())
			return err
		}},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			svc, repo := newService(t)
			repo.failOn[tc.op] = boom

			err := tc.call(svc)
			if !errors.Is(err, boom) {
				t.Fatalf("error = %v, want the underlying failure to reach the caller", err)
			}
			if errors.Is(err, ErrNotFound) || errors.Is(err, ErrConflict) {
				t.Error("an infrastructure failure was misreported as a domain outcome")
			}
		})
	}
}

func TestEnsureRejectsInvalidInput(t *testing.T) {
	svc, repo := newService(t)
	in := validInput()
	in.Country = "IND"

	_, _, err := svc.Ensure(context.Background(), in)
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
	if len(repo.byID) != 0 {
		t.Error("an invalid entry was written")
	}
}

// Losing the create race and then failing to load the winner must surface, not
// be silently reported as a successful seed.
func TestEnsureSurfacesAFailedLookupAfterLosingTheRace(t *testing.T) {
	svc, repo := newService(t)
	if _, err := svc.Create(context.Background(), validInput()); err != nil {
		t.Fatalf("Create: %v", err)
	}
	boom := errors.New("connection reset by peer")
	repo.failOn["GetByFeedURL"] = boom

	_, _, err := svc.Ensure(context.Background(), validInput())
	if !errors.Is(err, boom) {
		t.Fatalf("error = %v, want the lookup failure surfaced", err)
	}
}

func TestEnsureSurfacesAFailedUpdateOfTheExistingSource(t *testing.T) {
	svc, repo := newService(t)
	if _, err := svc.Create(context.Background(), validInput()); err != nil {
		t.Fatalf("Create: %v", err)
	}
	boom := errors.New("connection reset by peer")
	repo.failOn["Update"] = boom

	_, _, err := svc.Ensure(context.Background(), validInput())
	if !errors.Is(err, boom) {
		t.Fatalf("error = %v, want the update failure surfaced", err)
	}
}

// A source stored before a rule tightened must not be silently re-persisted in
// its now-invalid form by a re-seed.
func TestEnsureRevalidatesTheExistingSource(t *testing.T) {
	svc, repo := newService(t)
	created, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	stored := repo.byID[created.ID]
	stored.Priority = 9000
	repo.byID[created.ID] = stored

	_, _, err = svc.Ensure(context.Background(), validInput())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want the stored source to be revalidated", err)
	}
}

// A duplicate reported by a read or a delete is a conflict, not an internal error.
func TestDuplicateFromAnyOperationBecomesConflict(t *testing.T) {
	svc, repo := newService(t)
	repo.failOn["Delete"] = repository.ErrDuplicate

	err := svc.Delete(context.Background(), "0198f3d2-0000-7000-8000-000000000000")
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("error = %v, want ErrConflict", err)
	}
}

func TestSuccessfulOperationsTranslateToNil(t *testing.T) {
	svc, _ := newService(t)
	created, err := svc.Create(context.Background(), validInput())
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if err := svc.Delete(context.Background(), created.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
}
