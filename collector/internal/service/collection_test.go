package service

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/collector/rss"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
	"github.com/riaz/newscollector/internal/processor"
	"github.com/riaz/newscollector/internal/repository"
)

// fakeRunRepo records the runs the service writes.
type fakeRunRepo struct {
	mu      sync.Mutex
	stored  []domain.CollectionRun
	err     error
	page    domain.CollectionRunPage
	getErr  error
	lastFlt domain.CollectionRunFilter
}

var _ repository.CollectionRunRepository = (*fakeRunRepo)(nil)

func (f *fakeRunRepo) Create(_ context.Context, run *domain.CollectionRun) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.err != nil {
		return f.err
	}
	f.stored = append(f.stored, *run)
	return nil
}

func (f *fakeRunRepo) GetByID(_ context.Context, id string) (*domain.CollectionRun, error) {
	if f.getErr != nil {
		return nil, f.getErr
	}
	for i := range f.stored {
		if f.stored[i].ID == id {
			return &f.stored[i], nil
		}
	}
	return nil, repository.ErrNotFound
}

func (f *fakeRunRepo) List(_ context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error) {
	f.lastFlt = filter
	return f.page, f.err
}

func (f *fakeRunRepo) only(t *testing.T) domain.CollectionRun {
	t.Helper()
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.stored) != 1 {
		t.Fatalf("stored %d runs, want exactly 1", len(f.stored))
	}
	return f.stored[0]
}

// fakeCacheRepo stands in for the feed cache.
type fakeCacheRepo struct {
	entry    *domain.FeedCacheEntry
	getErr   error
	saveErr  error
	saved    []domain.FeedCacheEntry
	getCalls int
}

var _ repository.FeedCacheRepository = (*fakeCacheRepo)(nil)

func (f *fakeCacheRepo) Get(_ context.Context, _ string) (*domain.FeedCacheEntry, error) {
	f.getCalls++
	if f.getErr != nil {
		return nil, f.getErr
	}
	if f.entry == nil {
		return nil, repository.ErrNotFound
	}
	return f.entry, nil
}

func (f *fakeCacheRepo) Save(_ context.Context, entry domain.FeedCacheEntry) error {
	if f.saveErr != nil {
		return f.saveErr
	}
	f.saved = append(f.saved, entry)
	return nil
}

// fakeLockRepo enforces one holder per resource, the way the primary key does.
type fakeLockRepo struct {
	mu       sync.Mutex
	held     map[string]domain.Lock
	err      error
	released []string
	relErr   error
}

var _ repository.LockRepository = (*fakeLockRepo)(nil)

func newFakeLocks() *fakeLockRepo { return &fakeLockRepo{held: make(map[string]domain.Lock)} }

func (f *fakeLockRepo) Acquire(_ context.Context, lock domain.Lock) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.err != nil {
		return false, f.err
	}
	if existing, ok := f.held[lock.Resource]; ok && existing.ExpiresAt.After(lock.AcquiredAt) {
		return false, nil
	}
	f.held[lock.Resource] = lock
	return true, nil
}

func (f *fakeLockRepo) Release(_ context.Context, resource, owner string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.relErr != nil {
		return f.relErr
	}
	if held, ok := f.held[resource]; !ok || held.Owner != owner {
		return repository.ErrNotFound
	}
	delete(f.held, resource)
	f.released = append(f.released, resource)
	return nil
}

// fakeFeedCollector returns a canned collection outcome.
type fakeFeedCollector struct {
	result   rss.Result
	err      error
	lastPrev rss.Validators
	calls    int
	mu       sync.Mutex
}

func (f *fakeFeedCollector) Collect(_ context.Context, _ *domain.Source, prev rss.Validators) (rss.Result, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	f.lastPrev = prev
	return f.result, f.err
}

// fakeProcessor returns a canned processing outcome.
type fakeProcessor struct {
	result processor.Result
	err    error
	items  int
	calls  int
	mu     sync.Mutex
}

func (f *fakeProcessor) Process(_ context.Context, _ *domain.Source, items []domain.FeedItem) (processor.Result, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	f.items = len(items)
	return f.result, f.err
}

type collectionHarness struct {
	svc       *CollectionService
	sources   *fakeSourceRepo
	runs      *fakeRunRepo
	cache     *fakeCacheRepo
	locks     *fakeLockRepo
	collector *fakeFeedCollector
	processor *fakeProcessor
	source    *domain.Source
}

func newCollectionHarness(t *testing.T) *collectionHarness {
	t.Helper()

	src, err := domain.NewSource(domain.SourceInput{
		Name:     "Mysuru Daily",
		FeedURL:  "https://news.example.com/feed.xml",
		Type:     domain.SourceTypeRSS,
		Language: "en",
		Country:  "IN",
	}, fixedNow.Add(-time.Hour))
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	h := &collectionHarness{
		sources:   newFakeRepo(),
		runs:      &fakeRunRepo{},
		cache:     &fakeCacheRepo{},
		locks:     newFakeLocks(),
		collector: &fakeFeedCollector{},
		processor: &fakeProcessor{},
		source:    src,
	}
	h.sources.byID[src.ID] = *src

	h.svc = NewCollectionService(CollectionDeps{
		Sources:   h.sources,
		Runs:      h.runs,
		Cache:     h.cache,
		Locks:     h.locks,
		Collector: h.collector,
		Processor: h.processor,
		Owner:     "collector-under-test",
		LockTTL:   5 * time.Minute,
		Clock:     fixedClock,
		Logger:    slog.New(slog.NewJSONHandler(io.Discard, nil)),
	})
	return h
}

// stored returns the source as the service left it.
func (h *collectionHarness) stored(t *testing.T) domain.Source {
	t.Helper()
	h.sources.mu.Lock()
	defer h.sources.mu.Unlock()
	return h.sources.byID[h.source.ID]
}

func feedItems(n int) []domain.FeedItem {
	items := make([]domain.FeedItem, 0, n)
	for i := range n {
		items = append(items, domain.FeedItem{Title: "Story", Link: "https://news.example.com/" + string(rune('a'+i))})
	}
	return items
}

func TestCollectStoresArticlesAndMarksTheSourceHealthy(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.result = rss.Result{
		Items:      feedItems(3),
		ItemsFound: 3,
		FeedType:   "rss",
		Validators: rss.Validators{ETag: `W/"abc"`, LastModified: "Fri, 22 Aug 2026 10:00:00 GMT"},
	}
	h.processor.result = processor.Result{Items: 3, Stored: 2, Duplicates: 1}

	run, err := h.svc.Collect(t.Context(), h.source)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if run.Status != domain.RunStatusSuccess {
		t.Fatalf("status = %q, want success", run.Status)
	}
	if run.ItemsStored != 2 || run.ItemsDuplicate != 1 || run.ItemsFound != 3 {
		t.Errorf("counts = %+v, want the processor's totals carried onto the run", run)
	}
	if got := h.runs.only(t); got.ID != run.ID {
		t.Errorf("recorded run = %q, want the returned one %q", got.ID, run.ID)
	}

	src := h.stored(t)
	if src.HealthStatus != domain.HealthHealthy || src.ConsecutiveFailures != 0 {
		t.Errorf("source = %+v, want it healthy", src)
	}
	if want := fixedNow.Add(src.FetchInterval()); !src.NextScheduledAt.Equal(want) {
		t.Errorf("next scheduled = %v, want %v", src.NextScheduledAt, want)
	}
}

func TestCollectReplaysStoredValidatorsAndKeepsTheNewOnes(t *testing.T) {
	h := newCollectionHarness(t)
	h.cache.entry = &domain.FeedCacheEntry{SourceID: h.source.ID, ETag: `W/"old"`, LastModified: "Thu, 21 Aug 2026 10:00:00 GMT"}
	h.collector.result = rss.Result{Validators: rss.Validators{ETag: `W/"new"`}}

	if _, err := h.svc.Collect(t.Context(), h.source); err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if h.collector.lastPrev.ETag != `W/"old"` || h.collector.lastPrev.LastModified == "" {
		t.Errorf("replayed validators = %+v, want the stored ones", h.collector.lastPrev)
	}
	if len(h.cache.saved) != 1 || h.cache.saved[0].ETag != `W/"new"` {
		t.Errorf("saved validators = %+v, want the publisher's new ETag", h.cache.saved)
	}
}

func TestCollectRecordsNotModifiedWithoutProcessing(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.result = rss.Result{NotModified: true, Validators: rss.Validators{ETag: `W/"same"`}}

	run, err := h.svc.Collect(t.Context(), h.source)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if run.Status != domain.RunStatusNotModified {
		t.Fatalf("status = %q, want not_modified", run.Status)
	}
	if h.processor.calls != 0 {
		t.Errorf("processor ran %d times, want 0: there was nothing to process", h.processor.calls)
	}
	if src := h.stored(t); src.HealthStatus != domain.HealthHealthy {
		t.Errorf("health = %q, want a 304 to count as a healthy poll", src.HealthStatus)
	}
}

func TestCollectReportsAPartialCollection(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.result = rss.Result{Items: feedItems(2), ItemsFound: 5, ItemsSkipped: 3}
	h.processor.result = processor.Result{Items: 2, Stored: 1, Invalid: 1}

	run, err := h.svc.Collect(t.Context(), h.source)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if run.Status != domain.RunStatusPartial {
		t.Fatalf("status = %q, want partial", run.Status)
	}
	if run.ItemsSkipped != 3 || run.ItemsInvalid != 1 {
		t.Errorf("run = %+v, want the dropped entries counted", run)
	}
	if src := h.stored(t); src.HealthStatus != domain.HealthHealthy {
		t.Errorf("health = %q, want a partial collection to still count as reaching the publisher", src.HealthStatus)
	}
}

// A publisher that is down is a recorded failure, not a caller error: the run
// is the record, and the source backs off.
func TestCollectRecordsAFailureAndBacksTheSourceOff(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.err = &httpclient.StatusError{StatusCode: 503}

	run, err := h.svc.Collect(t.Context(), h.source)
	if err != nil {
		t.Fatalf("Collect returned an error for a failed feed: %v", err)
	}

	if run.Status != domain.RunStatusFailed {
		t.Fatalf("status = %q, want failed", run.Status)
	}
	if run.Error != "the publisher answered HTTP 503" {
		t.Errorf("reason = %q, want the classified phrase", run.Error)
	}

	src := h.stored(t)
	if src.HealthStatus != domain.HealthDegraded || src.ConsecutiveFailures != 1 {
		t.Errorf("source = %+v, want it degraded after one failure", src)
	}
	if !src.NextScheduledAt.After(fixedNow) {
		t.Errorf("next scheduled = %v, want it pushed out from %v", src.NextScheduledAt, fixedNow)
	}
}

// The stored reason is served by the API, so it must never quote the underlying
// error — which may name an internal host or a driver.
func TestFailureReasonsAreFixedPhrases(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want string
	}{
		{"blocked address", httpclient.ErrBlockedAddress, "the feed resolves to an address this collector refuses to contact"},
		{"invalid url", httpclient.ErrInvalidURL, "the feed URL cannot be fetched as written"},
		{"redirect loop", httpclient.ErrTooManyRedirects, "the feed redirected too many times"},
		{"oversized body", httpclient.ErrResponseTooLarge, "the feed response is larger than this collector accepts"},
		{"unparsable feed", rss.ErrParse, "the feed could not be parsed as RSS, RDF or Atom"},
		{"status", &httpclient.StatusError{StatusCode: 404}, "the publisher answered HTTP 404"},
		{"deadline", context.DeadlineExceeded, "the collection ran out of time"},
		{"network timeout", &net.DNSError{IsTimeout: true}, "the publisher did not answer in time"},
		{"storage", repository.ErrDuplicate, "the collected articles could not be stored"},
		{"unknown", errors.New("dial tcp 10.0.0.5:27017: connect: connection refused"), "the collection failed"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newCollectionHarness(t)
			h.collector.err = tt.err

			run, err := h.svc.Collect(t.Context(), h.source)
			if err != nil {
				t.Fatalf("Collect: %v", err)
			}

			if run.Error != tt.want {
				t.Fatalf("reason = %q, want %q", run.Error, tt.want)
			}
			if strings.Contains(run.Error, "10.0.0.5") || strings.Contains(run.Error, "dial tcp") {
				t.Error("the raw error leaked into a field the API serves")
			}
		})
	}
}

func TestCollectSkipsASourceAnotherCollectorHolds(t *testing.T) {
	h := newCollectionHarness(t)
	h.locks.held[domain.SourceLockResource(h.source.ID)] = domain.NewLock(
		domain.SourceLockResource(h.source.ID), "another-collector", fixedNow, time.Minute)

	_, err := h.svc.Collect(t.Context(), h.source)

	if !errors.Is(err, ErrLocked) {
		t.Fatalf("error = %v, want ErrLocked", err)
	}
	if h.collector.calls != 0 {
		t.Errorf("the feed was fetched %d times, want 0 while another collector holds it", h.collector.calls)
	}
	if len(h.runs.stored) != 0 {
		t.Errorf("recorded %d runs, want none: nothing was attempted", len(h.runs.stored))
	}
}

func TestCollectReleasesTheLeaseWhateverHappens(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.err = rss.ErrParse

	if _, err := h.svc.Collect(t.Context(), h.source); err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if len(h.locks.held) != 0 {
		t.Fatalf("leases still held: %+v", h.locks.held)
	}
	if len(h.locks.released) != 1 {
		t.Errorf("released %d leases, want 1", len(h.locks.released))
	}
}

// The lease must come back even when the collection's own context is gone,
// or a cancelled shutdown would park the source until the TTL expires.
func TestCollectReleasesTheLeaseAfterCancellation(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.err = context.Canceled

	ctx, cancel := context.WithCancel(t.Context())
	cancel()

	if _, err := h.svc.Collect(ctx, h.source); err != nil {
		t.Fatalf("Collect: %v", err)
	}
	if len(h.locks.held) != 0 {
		t.Errorf("leases still held after a cancelled collection: %+v", h.locks.held)
	}
}

// A cache that cannot be read costs one conditional request, not a collection.
func TestCollectSurvivesAnUnreadableCache(t *testing.T) {
	h := newCollectionHarness(t)
	h.cache.getErr = errors.New("mongo: find feed cache entry: timeout")
	h.cache.saveErr = errors.New("mongo: save feed cache entry: timeout")
	h.collector.result = rss.Result{Items: feedItems(1), ItemsFound: 1, Validators: rss.Validators{ETag: `W/"x"`}}
	h.processor.result = processor.Result{Items: 1, Stored: 1}

	run, err := h.svc.Collect(t.Context(), h.source)
	if err != nil {
		t.Fatalf("Collect: %v", err)
	}

	if run.Status != domain.RunStatusSuccess {
		t.Errorf("status = %q, want the articles to have been stored regardless", run.Status)
	}
	if h.collector.lastPrev != (rss.Validators{}) {
		t.Errorf("replayed validators = %+v, want an unconditional fetch", h.collector.lastPrev)
	}
}

// A database that cannot record the attempt is this system failing, not the
// publisher, and the caller must hear about it.
func TestCollectFailsWhenTheRunCannotBeRecorded(t *testing.T) {
	h := newCollectionHarness(t)
	h.runs.err = errors.New("mongo: insert collection run: timeout")

	_, err := h.svc.Collect(t.Context(), h.source)

	if err == nil {
		t.Fatal("Collect returned no error although the run could not be recorded")
	}
	if len(h.locks.held) != 0 {
		t.Errorf("leases still held: %+v", h.locks.held)
	}
}

func TestCollectByIDRejectsAnIdentifierThatIsNotAUUID(t *testing.T) {
	h := newCollectionHarness(t)

	_, err := h.svc.CollectByID(t.Context(), "../../etc/passwd")

	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
	if h.sources.byID == nil || h.collector.calls != 0 {
		t.Error("a malformed identifier reached the repository")
	}
}

func TestCollectByIDReportsAnUnknownSource(t *testing.T) {
	h := newCollectionHarness(t)

	_, err := h.svc.CollectByID(t.Context(), "0198f3d2-9999-7000-8000-000000000009")

	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

// Disabled has to mean the same thing everywhere: a feed switched off must not
// still be collectable by naming it.
func TestCollectByIDRefusesADisabledSource(t *testing.T) {
	h := newCollectionHarness(t)

	disabled := *h.source
	disabled.Enabled = false
	h.sources.mu.Lock()
	h.sources.byID[disabled.ID] = disabled
	h.sources.mu.Unlock()

	_, err := h.svc.CollectByID(t.Context(), disabled.ID)

	if !errors.Is(err, ErrSourceDisabled) {
		t.Fatalf("error = %v, want ErrSourceDisabled", err)
	}
	if h.collector.calls != 0 {
		t.Errorf("the feed was fetched %d times, want 0", h.collector.calls)
	}
	if len(h.locks.held) != 0 {
		t.Errorf("a lease was taken for a source that was never collected: %+v", h.locks.held)
	}
}

func TestDueReturnsOnlySourcesWhoseTimeHasCome(t *testing.T) {
	h := newCollectionHarness(t)

	later := *h.source
	later.ID = "0198f3d2-1111-7000-8000-000000000002"
	later.NextScheduledAt = fixedNow.Add(time.Hour)
	h.sources.byID[later.ID] = later

	due, err := h.svc.Due(t.Context(), 10)
	if err != nil {
		t.Fatalf("Due: %v", err)
	}

	if len(due) != 1 || due[0].ID != h.source.ID {
		t.Fatalf("due = %+v, want only the overdue source", due)
	}
}

func TestDueRejectsANonPositiveLimit(t *testing.T) {
	h := newCollectionHarness(t)

	if _, err := h.svc.Due(t.Context(), 0); err == nil {
		t.Fatal("Due accepted a limit of zero")
	}
}

func TestListRunsValidatesTheFilter(t *testing.T) {
	h := newCollectionHarness(t)

	_, err := h.svc.ListRuns(t.Context(), domain.CollectionRunFilter{Limit: domain.MaxListLimit + 1})

	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

func TestListRunsAppliesTheDefaultPageSize(t *testing.T) {
	h := newCollectionHarness(t)

	if _, err := h.svc.ListRuns(t.Context(), domain.CollectionRunFilter{}); err != nil {
		t.Fatalf("ListRuns: %v", err)
	}
	if h.runs.lastFlt.Limit != domain.DefaultListLimit {
		t.Errorf("limit = %d, want the default %d", h.runs.lastFlt.Limit, domain.DefaultListLimit)
	}
}

func TestGetRunTranslatesAMissingRun(t *testing.T) {
	h := newCollectionHarness(t)

	_, err := h.svc.GetRun(t.Context(), "0198f3d2-2222-7000-8000-000000000009")

	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}

func TestGetRunRejectsAnIdentifierThatIsNotAUUID(t *testing.T) {
	h := newCollectionHarness(t)

	_, err := h.svc.GetRun(t.Context(), "1 OR 1=1")

	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want a validation error", err)
	}
}

func TestListRunsReportsAStorageFailure(t *testing.T) {
	h := newCollectionHarness(t)
	h.runs.err = errors.New("mongo: count collection runs: timeout")

	if _, err := h.svc.ListRuns(t.Context(), domain.CollectionRunFilter{}); err == nil {
		t.Fatal("ListRuns hid a storage failure")
	}
}

// A lease that cannot be given back means exclusivity lapsed. It is logged, but
// it must not turn a completed collection into a failure.
func TestCollectSurvivesALeaseThatCannotBeReleased(t *testing.T) {
	tests := []struct {
		name   string
		relErr error
	}{
		{"the lease had already expired", repository.ErrNotFound},
		{"the lock store is unreachable", errors.New("mongo: release lock: timeout")},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newCollectionHarness(t)
			h.collector.result = rss.Result{Items: feedItems(1), ItemsFound: 1}
			h.processor.result = processor.Result{Items: 1, Stored: 1}
			h.locks.relErr = tt.relErr

			run, err := h.svc.Collect(t.Context(), h.source)
			if err != nil {
				t.Fatalf("Collect: %v", err)
			}
			if run.Status != domain.RunStatusSuccess {
				t.Errorf("status = %q, want the collection to stand", run.Status)
			}
		})
	}
}

func TestCollectReportsAnUnavailableLockStore(t *testing.T) {
	h := newCollectionHarness(t)
	h.locks.err = errors.New("mongo: acquire lock: timeout")

	if _, err := h.svc.Collect(t.Context(), h.source); err == nil {
		t.Fatal("Collect hid a lock store failure")
	}
}

func TestCollectRejectsANilSource(t *testing.T) {
	h := newCollectionHarness(t)

	if _, err := h.svc.Collect(t.Context(), nil); err == nil {
		t.Fatal("Collect accepted a nil source")
	}
}

// A collection takes seconds, and an operator may disable the feed during them.
// Writing the whole source back afterwards would quietly undo that.
func TestCollectDoesNotOverwriteAConcurrentEdit(t *testing.T) {
	h := newCollectionHarness(t)
	h.collector.result = rss.Result{Items: feedItems(1), ItemsFound: 1}
	h.processor.result = processor.Result{Items: 1, Stored: 1}

	// The operator's edit lands while the collector holds its in-memory copy.
	h.collector.result.FeedType = "rss"
	edited := *h.source
	edited.Enabled = false
	edited.Name = "Renamed By An Operator"
	h.sources.mu.Lock()
	h.sources.byID[edited.ID] = edited
	h.sources.mu.Unlock()

	if _, err := h.svc.Collect(t.Context(), h.source); err != nil {
		t.Fatalf("Collect: %v", err)
	}

	src := h.stored(t)
	if src.Enabled || src.Name != "Renamed By An Operator" {
		t.Fatalf("source = %+v, want the operator's edit intact", src)
	}
	if src.HealthStatus != domain.HealthHealthy {
		t.Errorf("health = %q, want the collection's own fields still written", src.HealthStatus)
	}
}

func TestCollectFailsWhenTheSourceCannotBeUpdated(t *testing.T) {
	h := newCollectionHarness(t)
	h.sources.failOn["UpdateCollectionState"] = errors.New("mongo: update source: timeout")

	if _, err := h.svc.Collect(t.Context(), h.source); err == nil {
		t.Fatal("Collect hid a failed source update")
	}
}

// The zero clock and logger must not leave a service that panics on first use.
func TestNewCollectionServiceFillsInItsDefaults(t *testing.T) {
	h := newCollectionHarness(t)

	svc := NewCollectionService(CollectionDeps{
		Sources:   h.sources,
		Runs:      h.runs,
		Cache:     h.cache,
		Locks:     h.locks,
		Collector: h.collector,
		Processor: h.processor,
		Owner:     "defaults",
		LockTTL:   time.Minute,
	})

	if _, err := svc.Collect(t.Context(), h.source); err != nil {
		t.Fatalf("Collect: %v", err)
	}
}
