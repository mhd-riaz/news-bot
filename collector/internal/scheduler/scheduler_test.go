package scheduler

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

func discardLogger() *slog.Logger { return slog.New(slog.NewJSONHandler(io.Discard, nil)) }

// fakeCollector stands in for the collection service.
type fakeCollector struct {
	mu sync.Mutex

	due     []domain.Source
	dueErr  error
	dueCall int

	collected  []string
	collectErr error
	// onCollect runs inside a collection, so a test can observe how many are in
	// flight at once or make one panic.
	onCollect func(src *domain.Source)

	inFlight atomic.Int32
	peak     atomic.Int32

	// done is closed once the expected number of collections has happened.
	done      chan struct{}
	expect    int
	closeOnce sync.Once
}

func (f *fakeCollector) Due(_ context.Context, limit int) ([]domain.Source, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.dueCall++
	if f.dueErr != nil {
		return nil, f.dueErr
	}
	if len(f.due) > limit {
		return f.due[:limit], nil
	}
	return f.due, nil
}

func (f *fakeCollector) Collect(_ context.Context, src *domain.Source) (*domain.CollectionRun, error) {
	now := f.inFlight.Add(1)
	for {
		peak := f.peak.Load()
		if now <= peak || f.peak.CompareAndSwap(peak, now) {
			break
		}
	}
	defer f.inFlight.Add(-1)

	// The attempt is recorded before the hook runs, so a hook that panics still
	// counts as an attempt.
	f.mu.Lock()
	f.collected = append(f.collected, src.ID)
	reached := len(f.collected)
	f.mu.Unlock()

	if f.done != nil && reached >= f.expect {
		f.closeOnce.Do(func() { close(f.done) })
	}

	if f.onCollect != nil {
		f.onCollect(src)
	}

	if f.collectErr != nil {
		return nil, f.collectErr
	}
	return &domain.CollectionRun{ID: "run-" + src.ID, SourceID: src.ID, Status: domain.RunStatusSuccess}, nil
}

func (f *fakeCollector) collectedIDs() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.collected...)
}

func sources(n int) []domain.Source {
	out := make([]domain.Source, 0, n)
	for i := range n {
		out = append(out, domain.Source{ID: string(rune('a' + i))})
	}
	return out
}

func testConfig() Config {
	return Config{Interval: time.Hour, BatchSize: 50, MaxConcurrent: 4}
}

// runOnce drives exactly one tick: the loop collects before it waits, so
// cancelling immediately still leaves one batch behind.
func runOnce(t *testing.T, c *fakeCollector, cfg Config) {
	t.Helper()

	ctx, cancel := context.WithCancel(t.Context())
	if c.done == nil {
		c.done = make(chan struct{})
		c.expect = 0
		close(c.done)
	}

	errCh := make(chan error, 1)
	go func() { errCh <- New(c, cfg, discardLogger()).Run(ctx) }()

	select {
	case <-c.done:
	case <-time.After(5 * time.Second):
		cancel()
		t.Fatal("the tick did not finish within five seconds")
	}
	cancel()

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return after cancellation")
	}
}

func TestTickCollectsEveryDueSource(t *testing.T) {
	c := &fakeCollector{due: sources(5), done: make(chan struct{}), expect: 5}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 5 {
		t.Fatalf("collected %d sources, want 5", got)
	}
}

func TestTickHonoursTheConcurrencyLimit(t *testing.T) {
	c := &fakeCollector{
		due:       sources(8),
		done:      make(chan struct{}),
		expect:    8,
		onCollect: func(*domain.Source) { time.Sleep(20 * time.Millisecond) },
	}

	cfg := testConfig()
	cfg.MaxConcurrent = 2
	runOnce(t, c, cfg)

	if peak := c.peak.Load(); peak > 2 {
		t.Fatalf("%d collections ran at once, want at most 2", peak)
	}
}

func TestTickAsksForNoMoreThanOneBatch(t *testing.T) {
	c := &fakeCollector{due: sources(10), done: make(chan struct{}), expect: 3}

	cfg := testConfig()
	cfg.BatchSize = 3
	runOnce(t, c, cfg)

	if got := len(c.collectedIDs()); got != 3 {
		t.Fatalf("collected %d sources, want the batch size of 3", got)
	}
}

// A source held by another collector is the normal outcome of two schedulers
// running, so the tick must carry on rather than abandon the batch.
func TestTickContinuesPastALockedSource(t *testing.T) {
	c := &fakeCollector{due: sources(3), collectErr: service.ErrLocked, done: make(chan struct{}), expect: 3}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 3 {
		t.Fatalf("attempted %d sources, want all 3", got)
	}
}

func TestTickContinuesPastAFailedCollection(t *testing.T) {
	c := &fakeCollector{due: sources(3), collectErr: errors.New("mongo: insert collection run: timeout"), done: make(chan struct{}), expect: 3}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 3 {
		t.Fatalf("attempted %d sources, want all 3", got)
	}
}

// A panic in one collection must not take down the process the API shares.
func TestTickContainsAPanic(t *testing.T) {
	c := &fakeCollector{
		due:    sources(2),
		done:   make(chan struct{}),
		expect: 2,
		onCollect: func(src *domain.Source) {
			if src.ID == "a" {
				panic("a publisher did something unexpected")
			}
		},
	}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 2 {
		t.Fatalf("attempted %d sources, want both despite the panic", got)
	}
}

func TestTickDoesNothingWhenNothingIsDue(t *testing.T) {
	c := &fakeCollector{}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 0 {
		t.Fatalf("collected %d sources, want none", got)
	}
}

func TestTickSurvivesAnUnavailableDatabase(t *testing.T) {
	c := &fakeCollector{dueErr: errors.New("mongo: find due sources: timeout")}

	runOnce(t, c, testConfig())

	if got := len(c.collectedIDs()); got != 0 {
		t.Fatalf("collected %d sources, want none", got)
	}
}

// Run must not return until the collections it started have finished, or
// shutdown would close MongoDB underneath them and abandon their leases.
func TestRunWaitsForInFlightCollections(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	var finished atomic.Bool

	c := &fakeCollector{
		due: sources(1),
		onCollect: func(*domain.Source) {
			close(started)
			<-release
			finished.Store(true)
		},
	}

	ctx, cancel := context.WithCancel(t.Context())
	errCh := make(chan error, 1)
	go func() { errCh <- New(c, testConfig(), discardLogger()).Run(ctx) }()

	<-started
	cancel()

	select {
	case <-errCh:
		t.Fatal("Run returned while a collection was still in flight")
	case <-time.After(50 * time.Millisecond):
	}

	close(release)
	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return after the collection finished")
	}
	if !finished.Load() {
		t.Error("the in-flight collection was abandoned")
	}
}

func TestRunRejectsAnUnusableConfiguration(t *testing.T) {
	tests := []struct {
		name string
		cfg  Config
	}{
		{"no interval", Config{BatchSize: 1, MaxConcurrent: 1}},
		{"no batch", Config{Interval: time.Second, MaxConcurrent: 1}},
		{"no concurrency", Config{Interval: time.Second, BatchSize: 1}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := New(&fakeCollector{}, tt.cfg, discardLogger()).Run(t.Context()); err == nil {
				t.Fatal("Run accepted an unusable configuration")
			}
		})
	}
}

func TestRunTicksRepeatedly(t *testing.T) {
	c := &fakeCollector{due: sources(1), done: make(chan struct{}), expect: 3}

	cfg := testConfig()
	cfg.Interval = 5 * time.Millisecond

	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- New(c, cfg, discardLogger()).Run(ctx) }()

	select {
	case <-c.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the scheduler did not tick three times within five seconds")
	}
	cancel()
	<-errCh
}

// A context that is already gone must not start any work.
func TestRunDoesNothingWhenAlreadyCancelled(t *testing.T) {
	c := &fakeCollector{due: sources(3)}

	ctx, cancel := context.WithCancel(t.Context())
	cancel()

	if err := New(c, testConfig(), discardLogger()).Run(ctx); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if c.dueCall != 0 || len(c.collectedIDs()) != 0 {
		t.Errorf("the scheduler did work after cancellation: %d lookups, %d collections", c.dueCall, len(c.collectedIDs()))
	}
}

// Cancelling mid-batch must stop the queue rather than start every remaining
// source, while still waiting for what is already running. The batch is large
// so that the scheduler would have to lose the cancellation race twenty times
// over for this to report a false failure.
func TestTickStopsQueueingWhenCancelledMidBatch(t *testing.T) {
	const batch = 20

	var cancel context.CancelFunc
	c := &fakeCollector{due: sources(batch)}
	c.onCollect = func(*domain.Source) { cancel() }

	cfg := testConfig()
	cfg.MaxConcurrent = 1

	var ctx context.Context
	ctx, cancel = context.WithCancel(t.Context())
	defer cancel()

	if err := New(c, cfg, discardLogger()).Run(ctx); err != nil {
		t.Fatalf("Run: %v", err)
	}

	if got := len(c.collectedIDs()); got == 0 || got == batch {
		t.Fatalf("collected %d of %d sources, want the batch cut short after cancellation", got, batch)
	}
}

// A nil logger must not leave a scheduler that panics on its first log line.
func TestNewAcceptsANilLogger(t *testing.T) {
	previous := slog.Default()
	slog.SetDefault(discardLogger())
	t.Cleanup(func() { slog.SetDefault(previous) })

	c := &fakeCollector{due: sources(1), done: make(chan struct{}), expect: 1}

	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- New(c, testConfig(), nil).Run(ctx) }()

	select {
	case <-c.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the tick did not finish within five seconds")
	}
	cancel()
	<-errCh
}
