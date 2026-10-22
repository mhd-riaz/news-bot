package httpclient

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// testClient reaches a loopback test server, which the address guard exists to
// prevent. Every other test in this file that cares about the guard builds a
// guarded client explicitly.
func testClient(cfg Config) *Client {
	cfg.AllowPrivateNetworks = true
	return New(cfg)
}

func TestFetchReturnsBodyAndValidators(t *testing.T) {
	var gotUserAgent, gotAccept string

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserAgent = r.Header.Get("User-Agent")
		gotAccept = r.Header.Get("Accept")

		w.Header().Set("Content-Type", "application/rss+xml")
		w.Header().Set("ETag", `"v1"`)
		w.Header().Set("Last-Modified", "Tue, 12 Aug 2025 04:00:00 GMT")
		_, _ = w.Write([]byte("<rss></rss>"))
	}))
	defer srv.Close()

	resp, err := testClient(Config{UserAgent: "test-agent/1.0"}).Fetch(t.Context(), Request{URL: srv.URL})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}

	if string(resp.Body) != "<rss></rss>" {
		t.Errorf("Body = %q", resp.Body)
	}
	if resp.StatusCode != http.StatusOK || resp.NotModified {
		t.Errorf("StatusCode = %d, NotModified = %v", resp.StatusCode, resp.NotModified)
	}
	if resp.ETag != `"v1"` || resp.LastModified != "Tue, 12 Aug 2025 04:00:00 GMT" {
		t.Errorf("validators = %q / %q", resp.ETag, resp.LastModified)
	}
	if resp.ContentType != "application/rss+xml" {
		t.Errorf("ContentType = %q", resp.ContentType)
	}
	if gotUserAgent != "test-agent/1.0" {
		t.Errorf("User-Agent = %q, want the configured one", gotUserAgent)
	}
	if !strings.Contains(gotAccept, "application/rss+xml") {
		t.Errorf("Accept = %q, should prefer feed types", gotAccept)
	}
}

func TestFetchSendsValidatorsAndReportsNotModified(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("If-None-Match") != `"v1"` {
			t.Errorf("If-None-Match = %q", r.Header.Get("If-None-Match"))
		}
		if r.Header.Get("If-Modified-Since") != "Tue, 12 Aug 2025 04:00:00 GMT" {
			t.Errorf("If-Modified-Since = %q", r.Header.Get("If-Modified-Since"))
		}
		w.WriteHeader(http.StatusNotModified)
	}))
	defer srv.Close()

	resp, err := testClient(Config{}).Fetch(t.Context(), Request{
		URL:          srv.URL,
		ETag:         `"v1"`,
		LastModified: "Tue, 12 Aug 2025 04:00:00 GMT",
	})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}

	if !resp.NotModified || len(resp.Body) != 0 {
		t.Fatalf("NotModified = %v, body length = %d", resp.NotModified, len(resp.Body))
	}
	// A 304 usually repeats no validators, so the caller can still store what it
	// receives instead of remembering what it sent.
	if resp.ETag != `"v1"` || resp.LastModified != "Tue, 12 Aug 2025 04:00:00 GMT" {
		t.Errorf("validators were not echoed: %q / %q", resp.ETag, resp.LastModified)
	}
}

func TestFetchReportsUnexpectedStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	_, err := testClient(Config{}).Fetch(t.Context(), Request{URL: srv.URL})

	var statusErr *StatusError
	if !errors.As(err, &statusErr) {
		t.Fatalf("Fetch error = %v, want *StatusError", err)
	}
	if statusErr.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("StatusCode = %d, want 503", statusErr.StatusCode)
	}
}

func TestFetchRejectsOversizedBody(t *testing.T) {
	tests := []struct {
		name    string
		handler http.HandlerFunc
	}{
		{
			name: "declared length",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				_, _ = w.Write([]byte(strings.Repeat("a", 4096)))
			},
		},
		{
			name: "streamed without a length",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				for range 8 {
					_, _ = w.Write([]byte(strings.Repeat("a", 512)))
					w.(http.Flusher).Flush()
				}
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(tc.handler)
			defer srv.Close()

			_, err := testClient(Config{MaxResponseBytes: 1024}).Fetch(t.Context(), Request{URL: srv.URL})
			if !errors.Is(err, ErrResponseTooLarge) {
				t.Fatalf("Fetch error = %v, want ErrResponseTooLarge", err)
			}
		})
	}
}

func TestFetchFollowsRedirectsUpToTheBudget(t *testing.T) {
	var hops int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/final" {
			_, _ = w.Write([]byte("<rss></rss>"))
			return
		}
		hops++
		http.Redirect(w, r, "/final", http.StatusMovedPermanently)
	}))
	defer srv.Close()

	resp, err := testClient(Config{MaxRedirects: 3}).Fetch(t.Context(), Request{URL: srv.URL + "/feed.xml"})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if hops != 1 {
		t.Errorf("hops = %d, want 1", hops)
	}
	if !strings.HasSuffix(resp.FinalURL, "/final") {
		t.Errorf("FinalURL = %q, should report where the body came from", resp.FinalURL)
	}
}

func TestFetchStopsAnEndlessRedirectChain(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/next", http.StatusFound)
	}))
	defer srv.Close()

	_, err := testClient(Config{MaxRedirects: 2}).Fetch(t.Context(), Request{URL: srv.URL})
	if !errors.Is(err, ErrTooManyRedirects) {
		t.Fatalf("Fetch error = %v, want ErrTooManyRedirects", err)
	}
}

// The guard is on by default, so the same test server the other cases talk to
// is unreachable for a client built without the escape hatch.
func TestGuardedClientRefusesLoopback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		t.Error("a guarded client must not reach a loopback server")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	_, err := New(Config{}).Fetch(t.Context(), Request{URL: srv.URL})
	if !errors.Is(err, ErrBlockedAddress) {
		t.Fatalf("Fetch error = %v, want ErrBlockedAddress", err)
	}
}

func TestFetchHonoursContextCancellation(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		<-release
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	defer close(release)

	ctx, cancel := context.WithTimeout(t.Context(), 50*time.Millisecond)
	defer cancel()

	if _, err := testClient(Config{}).Fetch(ctx, Request{URL: srv.URL}); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Fetch error = %v, want context.DeadlineExceeded", err)
	}
}

func TestConfigDefaults(t *testing.T) {
	cfg := Config{}.withDefaults()

	if cfg.Timeout != DefaultTimeout || cfg.MaxResponseBytes != DefaultMaxResponseBytes ||
		cfg.MaxRedirects != DefaultMaxRedirects || cfg.UserAgent != DefaultUserAgent {
		t.Fatalf("zero Config should yield the documented defaults, got %+v", cfg)
	}
}
