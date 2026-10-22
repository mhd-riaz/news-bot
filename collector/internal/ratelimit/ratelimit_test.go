package ratelimit

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

// testClock is a hand-driven clock. Sleeping advances it, so a test can exercise
// a fifteen-minute rest without waiting for one.
type testClock struct {
	mu   sync.Mutex
	now  time.Time
	naps []time.Duration
}

func newTestClock() *testClock {
	return &testClock{now: time.Date(2026, 8, 23, 10, 0, 0, 0, time.UTC)}
}

func (c *testClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *testClock) Sleep(ctx context.Context, d time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.naps = append(c.naps, d)
	c.now = c.now.Add(d)
	return nil
}

func (c *testClock) Advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

func (c *testClock) Naps() []time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]time.Duration(nil), c.naps...)
}

func newTestLimiter(c *testClock, cfg Config) *Limiter {
	cfg.Now = c.Now
	cfg.Sleep = c.Sleep
	return New(cfg)
}

func TestAcquireDoesNotDelayTheFirstRequestToAHost(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: 2 * time.Second})

	if err := l.Acquire(context.Background(), "thehindu.com", 0); err != nil {
		t.Fatalf("Acquire: %v", err)
	}
	if naps := c.Naps(); len(naps) != 0 {
		t.Errorf("the first request waited %v, want none", naps)
	}
}

func TestAcquireSpacesRequestsToOneHost(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: 2 * time.Second})
	ctx := context.Background()

	for i := range 3 {
		if err := l.Acquire(ctx, "thehindu.com", 0); err != nil {
			t.Fatalf("Acquire %d: %v", i, err)
		}
	}

	// Each caller after the first reserves the slot the previous one left, so
	// the gap is the interval every time rather than a burst.
	want := []time.Duration{2 * time.Second, 2 * time.Second}
	got := c.Naps()
	if len(got) != len(want) {
		t.Fatalf("waits = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("wait %d = %v, want %v", i, got[i], want[i])
		}
	}
}

func TestAcquireDoesNotSpaceDifferentHosts(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: 2 * time.Second})
	ctx := context.Background()

	// Pacing is per publisher: fifteen hosts should not queue behind each other.
	for _, host := range []string{"thehindu.com", "bbc.co.uk", "techcrunch.com"} {
		if err := l.Acquire(ctx, host, 0); err != nil {
			t.Fatalf("Acquire %s: %v", host, err)
		}
	}
	if naps := c.Naps(); len(naps) != 0 {
		t.Errorf("distinct hosts waited %v, want none", naps)
	}
}

func TestAcquireHonoursALongerCrawlDelay(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: 2 * time.Second})
	ctx := context.Background()

	if err := l.Acquire(ctx, "slow.example", 10*time.Second); err != nil {
		t.Fatalf("first Acquire: %v", err)
	}
	if err := l.Acquire(ctx, "slow.example", 10*time.Second); err != nil {
		t.Fatalf("second Acquire: %v", err)
	}

	naps := c.Naps()
	if len(naps) != 1 || naps[0] != 10*time.Second {
		t.Errorf("waits = %v, want one 10s wait", naps)
	}
}

func TestAcquireIgnoresACrawlDelayShorterThanTheConfiguredGap(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: 2 * time.Second})
	ctx := context.Background()

	// A publisher asking to be hit harder than the configured pace does not get it.
	_ = l.Acquire(ctx, "fast.example", 100*time.Millisecond)
	_ = l.Acquire(ctx, "fast.example", 100*time.Millisecond)

	naps := c.Naps()
	if len(naps) != 1 || naps[0] != 2*time.Second {
		t.Errorf("waits = %v, want one 2s wait", naps)
	}
}

func TestConsecutiveFailuresRestTheHost(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{
		MinInterval:      time.Second,
		FailureThreshold: 3,
		OpenFor:          15 * time.Minute,
	})
	ctx := context.Background()

	l.Failure("ndtv.com")
	l.Failure("ndtv.com")
	if l.Resting("ndtv.com") {
		t.Fatal("host rested before the threshold was reached")
	}

	l.Failure("ndtv.com")
	if !l.Resting("ndtv.com") {
		t.Fatal("host did not rest after reaching the threshold")
	}
	if err := l.Acquire(ctx, "ndtv.com", 0); !errors.Is(err, ErrCircuitOpen) {
		t.Errorf("Acquire err = %v, want ErrCircuitOpen", err)
	}

	c.Advance(15 * time.Minute)
	if l.Resting("ndtv.com") {
		t.Error("host still resting after the rest expired")
	}
	if err := l.Acquire(ctx, "ndtv.com", 0); err != nil {
		t.Errorf("Acquire after the rest expired: %v", err)
	}
}

func TestSuccessClearsTheFailureRun(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{FailureThreshold: 3})

	// Only a consecutive run rests a host: an intermittent failure among
	// successes is the normal weather of the open internet.
	l.Failure("bbc.co.uk")
	l.Failure("bbc.co.uk")
	l.Success("bbc.co.uk")
	l.Failure("bbc.co.uk")
	l.Failure("bbc.co.uk")

	if l.Resting("bbc.co.uk") {
		t.Error("host rested on a broken run of failures")
	}
}

func TestRestObeysAnExplicitRetryAfter(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{OpenFor: 15 * time.Minute})
	ctx := context.Background()

	l.Rest("timesofindia.indiatimes.com", 30*time.Second)
	if err := l.Acquire(ctx, "timesofindia.indiatimes.com", 0); !errors.Is(err, ErrCircuitOpen) {
		t.Fatalf("Acquire err = %v, want ErrCircuitOpen", err)
	}

	c.Advance(30 * time.Second)
	if err := l.Acquire(ctx, "timesofindia.indiatimes.com", 0); err != nil {
		t.Errorf("Acquire after Retry-After elapsed: %v", err)
	}
}

func TestRestWithoutADurationFallsBackToTheConfiguredRest(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{OpenFor: 5 * time.Minute})

	l.Rest("example.com", 0)

	c.Advance(4 * time.Minute)
	if !l.Resting("example.com") {
		t.Error("host stopped resting early")
	}
	c.Advance(time.Minute)
	if l.Resting("example.com") {
		t.Error("host still resting after the configured rest")
	}
}

func TestAcquireStopsWhenTheContextIsCancelled(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: time.Hour})

	ctx, cancel := context.WithCancel(context.Background())
	if err := l.Acquire(ctx, "thehindu.com", 0); err != nil {
		t.Fatalf("first Acquire: %v", err)
	}
	cancel()

	// A shutdown must not have to wait out the pacing interval.
	if err := l.Acquire(ctx, "thehindu.com", 0); !errors.Is(err, context.Canceled) {
		t.Errorf("Acquire err = %v, want context.Canceled", err)
	}
}

func TestConcurrentAcquireReservesDistinctSlots(t *testing.T) {
	c := newTestClock()
	l := newTestLimiter(c, Config{MinInterval: time.Second})

	// Reserving under the lock is what stops concurrent callers all reading the
	// same mark and then firing together.
	const callers = 8
	var wg sync.WaitGroup
	wg.Add(callers)
	for range callers {
		go func() {
			defer wg.Done()
			_ = l.Acquire(context.Background(), "thehindu.com", 0)
		}()
	}
	wg.Wait()

	naps := c.Naps()
	if len(naps) != callers-1 {
		t.Fatalf("%d callers produced %d waits, want %d", callers, len(naps), callers-1)
	}
	for i, d := range naps {
		if d <= 0 {
			t.Errorf("wait %d = %v, want a positive gap", i, d)
		}
	}
}

func TestZeroConfigIsUsable(t *testing.T) {
	l := New(Config{})
	if l.cfg.MinInterval != DefaultMinInterval ||
		l.cfg.FailureThreshold != DefaultFailureThreshold ||
		l.cfg.OpenFor != DefaultOpenFor {
		t.Errorf("defaults not applied: %+v", l.cfg)
	}
	if l.cfg.Now == nil || l.cfg.Sleep == nil {
		t.Error("clock or sleep left nil")
	}
}
