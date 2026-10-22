package robots

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
)

// fakeFetcher serves canned robots.txt files and counts requests, so a test can
// prove the cache and the request collapsing actually spare the publisher.
type fakeFetcher struct {
	mu     sync.Mutex
	bodies map[string]string
	status map[string]int
	err    map[string]error
	calls  atomic.Int64
	accept string
}

func (f *fakeFetcher) Fetch(_ context.Context, r httpclient.Request) (*httpclient.Response, error) {
	f.calls.Add(1)

	f.mu.Lock()
	defer f.mu.Unlock()
	f.accept = r.Accept

	if err, ok := f.err[r.URL]; ok {
		return nil, err
	}
	if code, ok := f.status[r.URL]; ok {
		return nil, &httpclient.StatusError{StatusCode: code}
	}
	body, ok := f.bodies[r.URL]
	if !ok {
		return nil, &httpclient.StatusError{StatusCode: 404}
	}
	return &httpclient.Response{StatusCode: 200, Body: []byte(body), FinalURL: r.URL}, nil
}

func newFake() *fakeFetcher {
	return &fakeFetcher{
		bodies: map[string]string{},
		status: map[string]int{},
		err:    map[string]error{},
	}
}

type testClock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *testClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *testClock) Advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

func newChecker(f *fakeFetcher, c *testClock) *Checker {
	return New(f, Config{Now: c.Now})
}

func newClock() *testClock {
	return &testClock{now: time.Date(2026, 8, 23, 10, 0, 0, 0, time.UTC)}
}

func TestAllowedReadsTheWildcardGroup(t *testing.T) {
	f := newFake()
	f.bodies["https://www.thehindu.com/robots.txt"] = `
User-agent: *
Disallow: /todays-paper/
Disallow: /search/
`
	c := newChecker(f, newClock())

	tests := []struct {
		url  string
		want bool
	}{
		{"https://www.thehindu.com/news/cities/mumbai/article71380097.ece", true},
		{"https://www.thehindu.com/todays-paper/something", false},
		{"https://www.thehindu.com/search/?q=x", false},
	}
	for _, tt := range tests {
		got, err := c.Allowed(context.Background(), tt.url)
		if err != nil {
			t.Fatalf("Allowed(%s): %v", tt.url, err)
		}
		if got.Allowed != tt.want {
			t.Errorf("Allowed(%s) = %v, want %v", tt.url, got.Allowed, tt.want)
		}
	}
}

func TestAllowedStripsTrackingParametersBeforeTesting(t *testing.T) {
	f := newFake()
	// Al Jazeera's shape: the article path is fine, the feed's tracking
	// parameter is not. The raw feed link would be refused; the article is not.
	f.bodies["https://www.aljazeera.com/robots.txt"] = `
User-agent: *
Disallow: /*?traffic_source=
`
	c := newChecker(f, newClock())

	got, err := c.Allowed(context.Background(),
		"https://www.aljazeera.com/news/2026/8/23/story?traffic_source=rss")
	if err != nil {
		t.Fatalf("Allowed: %v", err)
	}
	if !got.Allowed {
		t.Error("Allowed = false; the tracking parameter should have been stripped before the test")
	}
}

func TestAllowedRefusesADefaultDenyPublisher(t *testing.T) {
	f := newFake()
	// The Register's shape: named search engines are welcome, everyone else is
	// not. Matching only the wildcard group would read this as permission.
	f.bodies["https://www.theregister.com/robots.txt"] = `
User-agent: Googlebot
Allow: /

User-agent: Bingbot
Allow: /

User-agent: *
Disallow: /
`
	c := newChecker(f, newClock())

	got, err := c.Allowed(context.Background(), "https://www.theregister.com/2026/08/22/story/")
	if err != nil {
		t.Fatalf("Allowed: %v", err)
	}
	if got.Allowed {
		t.Error("Allowed = true for a default-deny publisher")
	}
}

func TestAllowedReportsTheCrawlDelay(t *testing.T) {
	f := newFake()
	f.bodies["https://slow.example/robots.txt"] = `
User-agent: *
Crawl-delay: 10
Disallow: /private/
`
	c := newChecker(f, newClock())

	got, err := c.Allowed(context.Background(), "https://slow.example/story")
	if err != nil {
		t.Fatalf("Allowed: %v", err)
	}
	if got.CrawlDelay != 10*time.Second {
		t.Errorf("CrawlDelay = %v, want 10s", got.CrawlDelay)
	}
}

func TestMissingRobotsFilePermitsEverything(t *testing.T) {
	f := newFake()
	f.status["https://nofile.example/robots.txt"] = 404
	c := newChecker(f, newClock())

	got, err := c.Allowed(context.Background(), "https://nofile.example/story")
	if err != nil {
		t.Fatalf("Allowed: %v", err)
	}
	if !got.Allowed {
		t.Error("Allowed = false; a publisher that published no rules has refused nothing")
	}
}

func TestForbiddenRobotsFileIsARefusal(t *testing.T) {
	f := newFake()
	// NDTV's shape: the edge answers 403 to everything, robots.txt included.
	// The robotstxt library would read this as "allow all"; it is the opposite.
	f.status["https://www.ndtv.com/robots.txt"] = 403
	c := newChecker(f, newClock())

	_, err := c.Allowed(context.Background(), "https://www.ndtv.com/india-news/story-123")
	if !errors.Is(err, domain.ErrRobotsDisallowed) {
		t.Errorf("err = %v, want ErrRobotsDisallowed", err)
	}
}

func TestUnreadableRobotsFileFailsClosed(t *testing.T) {
	f := newFake()
	f.status["https://broken.example/robots.txt"] = 503
	f.err["https://timeout.example/robots.txt"] = errors.New("dial tcp: i/o timeout")
	c := newChecker(f, newClock())

	for _, host := range []string{"broken.example", "timeout.example"} {
		_, err := c.Allowed(context.Background(), "https://"+host+"/story")
		if !errors.Is(err, ErrUnreadable) {
			t.Errorf("%s: err = %v, want ErrUnreadable", host, err)
		}
	}
}

func TestRulesAreCachedPerHostUntilTheyExpire(t *testing.T) {
	f := newFake()
	f.bodies["https://example.com/robots.txt"] = "User-agent: *\nDisallow: /admin/\n"
	clock := newClock()
	c := New(f, Config{Now: clock.Now, TTL: time.Hour})

	for range 5 {
		if _, err := c.Allowed(context.Background(), "https://example.com/story"); err != nil {
			t.Fatalf("Allowed: %v", err)
		}
	}
	if n := f.calls.Load(); n != 1 {
		t.Errorf("fetched robots.txt %d times, want 1", n)
	}

	clock.Advance(time.Hour + time.Minute)
	if _, err := c.Allowed(context.Background(), "https://example.com/story"); err != nil {
		t.Fatalf("Allowed after expiry: %v", err)
	}
	if n := f.calls.Load(); n != 2 {
		t.Errorf("fetched %d times after expiry, want 2", n)
	}
}

func TestARefusalIsCachedToo(t *testing.T) {
	f := newFake()
	f.status["https://www.ndtv.com/robots.txt"] = 403
	c := newChecker(f, newClock())

	// Re-asking a host that just refused, once per article, would be its own
	// small denial of service.
	for range 4 {
		if _, err := c.Allowed(context.Background(), "https://www.ndtv.com/story"); err == nil {
			t.Fatal("Allowed returned no error for a refusing host")
		}
	}
	if n := f.calls.Load(); n != 1 {
		t.Errorf("fetched robots.txt %d times, want 1", n)
	}
}

func TestConcurrentMissesAskThePublisherOnce(t *testing.T) {
	f := newFake()
	f.bodies["https://example.com/robots.txt"] = "User-agent: *\nAllow: /\n"
	c := newChecker(f, newClock())

	var wg sync.WaitGroup
	wg.Add(20)
	for range 20 {
		go func() {
			defer wg.Done()
			_, _ = c.Allowed(context.Background(), "https://example.com/story")
		}()
	}
	wg.Wait()

	if n := f.calls.Load(); n != 1 {
		t.Errorf("twenty cold-cache callers fetched robots.txt %d times, want 1", n)
	}
}

func TestRobotsIsRequestedAsText(t *testing.T) {
	f := newFake()
	f.bodies["https://example.com/robots.txt"] = "User-agent: *\nAllow: /\n"
	c := newChecker(f, newClock())

	if _, err := c.Allowed(context.Background(), "https://example.com/story"); err != nil {
		t.Fatalf("Allowed: %v", err)
	}
	if f.accept != httpclient.AcceptText {
		t.Errorf("Accept = %q, want %q", f.accept, httpclient.AcceptText)
	}
}

func TestAllowedRejectsAUnusableURL(t *testing.T) {
	c := newChecker(newFake(), newClock())

	if _, err := c.Allowed(context.Background(), "/relative/path"); err == nil {
		t.Error("a URL with no host was accepted")
	}
}

func TestHost(t *testing.T) {
	tests := []struct{ in, want string }{
		{"https://www.thehindu.com/news/article.ece", "www.thehindu.com"},
		{"https://WWW.NDTV.COM/story#publisher=newsstand", "www.ndtv.com"},
		{"https://example.com/a?utm_source=rss", "example.com"},
		{"nonsense", ""},
	}
	for _, tt := range tests {
		if got := Host(tt.in); got != tt.want {
			t.Errorf("Host(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}
