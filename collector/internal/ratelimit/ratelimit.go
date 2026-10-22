// Package ratelimit paces outbound requests per publisher and rests a host that
// is refusing them.
//
// The collector and the enrichment stage both reach the same handful of hosts,
// so a limiter owned by either one would only pace half the traffic. A single
// instance is shared between them; it is the reason a publisher sees a steady
// trickle rather than two independent bursts.
package ratelimit

import (
	"context"
	"errors"
	"sync"
	"time"
)

// ErrCircuitOpen means the host is being rested after refusing requests, and no
// request was made. It is a distinct error because it is not a failure of the
// article a caller was working on: nothing was tried, and trying again shortly
// is pointless.
var ErrCircuitOpen = errors.New("ratelimit: host is temporarily out of service")

// Defaults applied to any zero-valued Config field.
const (
	DefaultMinInterval      = 2 * time.Second
	DefaultFailureThreshold = 3
	DefaultOpenFor          = 15 * time.Minute
)

// Config tunes the limiter. The zero value is usable and yields the defaults.
type Config struct {
	// MinInterval is the smallest gap between two requests to one host. A
	// publisher that advertises a longer Crawl-delay is given it instead: the
	// interval is supplied per call, and the caller passes the larger of the two.
	MinInterval time.Duration

	// FailureThreshold is how many consecutive failures rest a host.
	FailureThreshold int

	// OpenFor is how long a rested host is left alone.
	OpenFor time.Duration

	// Now is injected so a test can drive the schedule without waiting.
	Now func() time.Time

	// Sleep is injected for the same reason. It must return early if the
	// context is cancelled.
	Sleep func(ctx context.Context, d time.Duration) error
}

func (c Config) withDefaults() Config {
	if c.MinInterval <= 0 {
		c.MinInterval = DefaultMinInterval
	}
	if c.FailureThreshold <= 0 {
		c.FailureThreshold = DefaultFailureThreshold
	}
	if c.OpenFor <= 0 {
		c.OpenFor = DefaultOpenFor
	}
	if c.Now == nil {
		c.Now = time.Now
	}
	if c.Sleep == nil {
		c.Sleep = sleep
	}
	return c
}

// hostState is one publisher's pacing and health.
type hostState struct {
	// next is the earliest instant a request may start. Holding the reservation
	// rather than the time of the last request is what makes concurrent callers
	// queue: each one moves the mark forward before it waits, so ten goroutines
	// arriving together are spaced out instead of all waiting the same interval
	// and then firing at once.
	next time.Time

	failures  int
	openUntil time.Time
}

// Limiter paces requests per host and rests hosts that refuse them. It is safe
// for concurrent use.
type Limiter struct {
	cfg Config

	mu    sync.Mutex
	hosts map[string]*hostState
}

// New returns a limiter. One instance should be shared by everything that makes
// outbound requests, or the pacing it applies is not the rate a publisher sees.
func New(cfg Config) *Limiter {
	return &Limiter{cfg: cfg.withDefaults(), hosts: make(map[string]*hostState)}
}

// Acquire blocks until a request to host may be made, and returns ErrCircuitOpen
// if the host is resting. minInterval overrides the configured gap when it is
// longer, which is how a publisher's advertised Crawl-delay is honoured.
func (l *Limiter) Acquire(ctx context.Context, host string, minInterval time.Duration) error {
	wait, err := l.reserve(host, minInterval)
	if err != nil {
		return err
	}
	if wait <= 0 {
		return ctx.Err()
	}
	return l.cfg.Sleep(ctx, wait)
}

// reserve claims the next slot for host and reports how long to wait for it.
// The waiting happens outside the lock so one slow host cannot stall the others.
func (l *Limiter) reserve(host string, minInterval time.Duration) (time.Duration, error) {
	if minInterval < l.cfg.MinInterval {
		minInterval = l.cfg.MinInterval
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	now := l.cfg.Now()
	st := l.hosts[host]
	if st == nil {
		st = &hostState{}
		l.hosts[host] = st
	}
	if now.Before(st.openUntil) {
		return 0, ErrCircuitOpen
	}

	start := now
	if st.next.After(start) {
		start = st.next
	}
	st.next = start.Add(minInterval)
	return start.Sub(now), nil
}

// Success reports that host answered, which closes the breaker.
func (l *Limiter) Success(host string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if st := l.hosts[host]; st != nil {
		st.failures = 0
	}
}

// Failure reports that host did not answer. Enough consecutive failures rest it:
// without that, a host having a bad hour would spend every queued article's
// attempt budget and mark them all permanently failed.
func (l *Limiter) Failure(host string) {
	l.mu.Lock()
	defer l.mu.Unlock()

	st := l.hosts[host]
	if st == nil {
		st = &hostState{}
		l.hosts[host] = st
	}
	st.failures++
	if st.failures >= l.cfg.FailureThreshold {
		st.openUntil = l.cfg.Now().Add(l.cfg.OpenFor)
		st.failures = 0
	}
}

// Rest puts host out of service for d, which is how a Retry-After is obeyed. A
// non-positive or absent duration falls back to the configured rest.
func (l *Limiter) Rest(host string, d time.Duration) {
	if d <= 0 {
		d = l.cfg.OpenFor
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	st := l.hosts[host]
	if st == nil {
		st = &hostState{}
		l.hosts[host] = st
	}
	st.openUntil = l.cfg.Now().Add(d)
	st.failures = 0
}

// Resting reports whether host is currently out of service, so a caller can skip
// a batch of its articles without reserving a slot for each one.
func (l *Limiter) Resting(host string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()

	st := l.hosts[host]
	return st != nil && l.cfg.Now().Before(st.openUntil)
}

// sleep waits for d unless the context ends first.
func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
