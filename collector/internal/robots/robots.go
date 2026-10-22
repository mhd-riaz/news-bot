// Package robots decides whether a publisher permits this collector to fetch a
// URL, and how fast.
//
// It deliberately does not use the robotstxt library's own status handling.
// That treats every 4xx as "allow everything", including 401 and 403 — so a
// publisher whose edge refuses this client outright would be read as inviting
// it in. The rules below fail closed instead: a refusal is a refusal, and a
// robots.txt that cannot be read is not permission.
package robots

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/temoto/robotstxt"
	"golang.org/x/sync/singleflight"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
)

// ErrUnreadable means the publisher's rules could not be retrieved, so nothing
// may be fetched from it. It is separate from an ordinary denial because it may
// clear on its own, and a caller may want to retry the article later.
var ErrUnreadable = errors.New("robots: rules could not be read")

// Defaults applied to any zero-valued Config field.
const (
	DefaultTTL = 24 * time.Hour

	// DefaultAgent is the product token matched against the User-agent lines.
	// It is the bare token, not the full User-Agent header: robots.txt groups
	// are keyed on the product name, so sending the version and URL here would
	// silently match nothing but the wildcard group.
	DefaultAgent = "news-collector"

	// maxRobotsBytes caps the file. Some publishers ship robots.txt files of
	// several thousand lines; far beyond this is not a rules file.
	maxRobotsBytes = 512 << 10
)

// Fetcher is the subset of the HTTP client this package needs, so a test can
// supply rules without a server.
type Fetcher interface {
	Fetch(ctx context.Context, r httpclient.Request) (*httpclient.Response, error)
}

// Config tunes the checker. The zero value is usable and yields the defaults.
type Config struct {
	// Agent is the product token matched against User-agent lines.
	Agent string

	// TTL is how long one publisher's rules are reused. They are cached rather
	// than fetched per article because a run works through many articles from
	// the same handful of hosts, but not forever: a publisher may change its
	// mind, and this is how long it takes to be noticed.
	TTL time.Duration

	// Now is injected so a test can expire the cache without waiting.
	Now func() time.Time
}

func (c Config) withDefaults() Config {
	if c.Agent == "" {
		c.Agent = DefaultAgent
	}
	if c.TTL <= 0 {
		c.TTL = DefaultTTL
	}
	if c.Now == nil {
		c.Now = time.Now
	}
	return c
}

// Decision is what a publisher permits for one URL.
type Decision struct {
	// Allowed reports whether the URL may be fetched.
	Allowed bool

	// CrawlDelay is the gap the publisher asks for between requests. Zero means
	// it named none, and the caller's own pacing applies.
	CrawlDelay time.Duration
}

// entry is one publisher's cached rules. A nil data means the host refused or
// could not be read, which is remembered too: re-asking a host that just
// answered 403 on every article would be its own small denial of service.
type entry struct {
	data      *robotstxt.RobotsData
	err       error
	expiresAt time.Time
}

// Checker answers whether a URL may be fetched. It is safe for concurrent use.
type Checker struct {
	cfg    Config
	client Fetcher

	mu    sync.Mutex
	cache map[string]entry

	// group collapses concurrent misses for one host into a single fetch, so
	// starting fifty workers against a cold cache asks each publisher once.
	group singleflight.Group
}

// New returns a checker that reads rules through client.
func New(client Fetcher, cfg Config) *Checker {
	return &Checker{cfg: cfg.withDefaults(), client: client, cache: make(map[string]entry)}
}

// Allowed reports what the publisher permits for rawURL.
//
// The URL is cleaned before it is tested, because the tracking parameters a
// feed attaches are exactly what some publishers disallow: the same article is
// forbidden with "?traffic_source=rss" and allowed without it.
func (c *Checker) Allowed(ctx context.Context, rawURL string) (Decision, error) {
	u, err := url.Parse(domain.FetchURL(rawURL))
	if err != nil {
		return Decision{}, fmt.Errorf("robots: parse url: %w", err)
	}
	if u.Host == "" {
		return Decision{}, fmt.Errorf("robots: %q has no host", rawURL)
	}

	data, err := c.rulesFor(ctx, u.Scheme, u.Host)
	if err != nil {
		return Decision{}, err
	}

	path := u.EscapedPath()
	if path == "" {
		path = "/"
	}
	if u.RawQuery != "" {
		path += "?" + u.RawQuery
	}

	group := data.FindGroup(c.cfg.Agent)
	return Decision{
		Allowed:    data.TestAgent(path, c.cfg.Agent),
		CrawlDelay: group.CrawlDelay,
	}, nil
}

// rulesFor returns a host's rules, fetching them at most once per TTL and at
// most once at a time.
func (c *Checker) rulesFor(ctx context.Context, scheme, host string) (*robotstxt.RobotsData, error) {
	if e, ok := c.cached(host); ok {
		return e.data, e.err
	}

	v, err, _ := c.group.Do(host, func() (any, error) {
		// A second caller may have populated the cache while this one queued.
		if e, ok := c.cached(host); ok {
			return e, nil
		}

		data, fetchErr := c.fetch(ctx, scheme, host)
		e := entry{
			data:      data,
			err:       fetchErr,
			expiresAt: c.cfg.Now().Add(c.cfg.TTL),
		}

		c.mu.Lock()
		c.cache[host] = e
		c.mu.Unlock()
		return e, nil
	})
	if err != nil {
		return nil, err
	}

	e := v.(entry)
	return e.data, e.err
}

func (c *Checker) cached(host string) (entry, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	e, ok := c.cache[host]
	if !ok || !c.cfg.Now().Before(e.expiresAt) {
		return entry{}, false
	}
	return e, true
}

// fetch reads and parses one publisher's robots.txt.
//
// The status mapping is the whole point of this function:
//   - 2xx parses, and an unparsable body is treated as no rules rather than as
//     a refusal, since a publisher with a broken file has not refused anything.
//   - 404 and 410 mean the publisher published no rules, which permits everything.
//   - 401 and 403 mean this client is not welcome. The library would call these
//     "allow all"; they are the opposite.
//   - anything else, including 5xx and a transport failure, leaves the rules
//     unknown, and unknown is not permission.
func (c *Checker) fetch(ctx context.Context, scheme, host string) (*robotstxt.RobotsData, error) {
	if scheme == "" {
		scheme = "https"
	}
	robotsURL := scheme + "://" + host + "/robots.txt"

	resp, err := c.client.Fetch(ctx, httpclient.Request{URL: robotsURL, Accept: httpclient.AcceptText})
	if err != nil {
		var statusErr *httpclient.StatusError
		if errors.As(err, &statusErr) {
			return statusFallback(statusErr.StatusCode, host)
		}
		return nil, fmt.Errorf("%w: %s: %w", ErrUnreadable, host, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return statusFallback(resp.StatusCode, host)
	}
	if len(resp.Body) > maxRobotsBytes {
		return nil, fmt.Errorf("%w: %s: rules file is %d bytes", ErrUnreadable, host, len(resp.Body))
	}

	data, err := robotstxt.FromBytes(resp.Body)
	if err != nil {
		// A malformed file is a publisher's mistake, not a refusal. robotstxt
		// still returns the rules it understood, so prefer those to nothing.
		if data == nil {
			return robotstxt.FromString("")
		}
	}
	return data, nil
}

// statusFallback turns a non-2xx robots.txt response into rules or a refusal.
func statusFallback(code int, host string) (*robotstxt.RobotsData, error) {
	switch code {
	case 404, 410:
		return robotstxt.FromString("")
	case 401, 403:
		return nil, fmt.Errorf("%w: %s refuses this client (%d)", domain.ErrRobotsDisallowed, host, code)
	default:
		return nil, fmt.Errorf("%w: %s answered %d", ErrUnreadable, host, code)
	}
}

// Host returns the host a URL will be fetched from, which is the key both the
// rules cache and the rate limiter are organised by.
func Host(rawURL string) string {
	u, err := url.Parse(domain.FetchURL(rawURL))
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Host)
}
