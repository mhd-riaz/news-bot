// Package httpclient is the application's only outbound HTTP client. Feed URLs
// are operator-supplied, so every fetch is a potential server-side request
// forgery: the client therefore validates the URL, refuses to connect to any
// address that is not publicly routable, bounds redirects and caps how much of
// a response it will read. Keeping this in one package means no caller can
// accidentally reach the network without those guards.
package httpclient

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"
)

// Failure modes a caller may want to distinguish. Everything else is a
// transport error and travels unchanged.
var (
	// ErrInvalidURL means the URL could not be fetched as written.
	ErrInvalidURL = errors.New("httpclient: invalid url")

	// ErrBlockedAddress means the destination is not publicly routable, or is
	// on a port the client refuses to contact.
	ErrBlockedAddress = errors.New("httpclient: destination address is not allowed")

	// ErrTooManyRedirects means the server exceeded the redirect budget.
	ErrTooManyRedirects = errors.New("httpclient: too many redirects")

	// ErrResponseTooLarge means the body exceeded MaxResponseBytes. The body is
	// rejected rather than truncated: half a feed is not a feed.
	ErrResponseTooLarge = errors.New("httpclient: response body is too large")
)

// StatusError reports a response the server refused to fulfil. It is a distinct
// type so a caller can branch on the code — a 404 is a configuration problem,
// a 503 is worth retrying — without re-reading the message.
type StatusError struct {
	StatusCode int
}

func (e *StatusError) Error() string {
	return "httpclient: unexpected status " + strconv.Itoa(e.StatusCode) + " " + http.StatusText(e.StatusCode)
}

// Defaults applied to any zero-valued Config field.
const (
	DefaultTimeout          = 20 * time.Second
	DefaultMaxResponseBytes = 10 << 20 // 10 MiB
	DefaultMaxRedirects     = 5
	DefaultUserAgent        = "news-collector/1.0 (+https://github.com/riaz/newscollector)"

	dialTimeout           = 5 * time.Second
	tlsHandshakeTimeout   = 10 * time.Second
	responseHeaderTimeout = 15 * time.Second
	idleConnTimeout       = 90 * time.Second
	maxIdleConns          = 32

	// acceptHeader prefers the feed types but does not insist on them: plenty
	// of publishers serve a perfectly valid feed as text/xml or text/plain.
	acceptHeader = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.1"
)

// Accept headers for the things this client fetches that are not feeds. A page
// asked for as a feed is still usually served, but a publisher is entitled to
// answer 406, and content negotiation on some sites turns on it.
const (
	AcceptHTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
	AcceptText = "text/plain,*/*;q=0.8"
)

// Config tunes the client. The zero value is usable and yields the defaults above.
type Config struct {
	// Timeout bounds the whole exchange, body included.
	Timeout time.Duration

	// MaxResponseBytes caps the decompressed body, which is what makes a
	// compression bomb harmless.
	MaxResponseBytes int64

	// MaxRedirects is the number of hops allowed; every hop is re-validated.
	MaxRedirects int

	// UserAgent identifies the collector to publishers.
	UserAgent string

	// AllowPrivateNetworks disables the address guard entirely — both the
	// private-range block and the port allow-list. It exists so tests can reach
	// a loopback server. Enabling it in a deployed environment re-opens the
	// SSRF hole the rest of this package exists to close.
	AllowPrivateNetworks bool
}

func (c Config) withDefaults() Config {
	if c.Timeout <= 0 {
		c.Timeout = DefaultTimeout
	}
	if c.MaxResponseBytes <= 0 {
		c.MaxResponseBytes = DefaultMaxResponseBytes
	}
	if c.MaxRedirects <= 0 {
		c.MaxRedirects = DefaultMaxRedirects
	}
	if c.UserAgent == "" {
		c.UserAgent = DefaultUserAgent
	}
	return c
}

// Request is one conditional fetch. ETag and LastModified are the validators
// stored from the previous fetch of the same URL; sending them lets a publisher
// answer 304 and save both sides the transfer.
type Request struct {
	URL          string
	ETag         string
	LastModified string

	// Accept overrides the feed-oriented default, for the article pages and
	// robots.txt files the enrichment stage reads.
	Accept string
}

// Response is a completed fetch. Body is empty when NotModified is set.
type Response struct {
	StatusCode   int
	NotModified  bool
	Body         []byte
	ContentType  string
	ETag         string
	LastModified string

	// FinalURL is the URL the body actually came from, which differs from the
	// requested one when the publisher redirected.
	FinalURL string
}

// Client fetches feeds. It is safe for concurrent use and should be shared, so
// connections are pooled across sources.
type Client struct {
	cfg  Config
	http *http.Client
}

// New builds a guarded client.
func New(cfg Config) *Client {
	cfg = cfg.withDefaults()

	dialer := &net.Dialer{Timeout: dialTimeout, KeepAlive: 30 * time.Second}
	if !cfg.AllowPrivateNetworks {
		dialer.Control = guardDial
	}

	transport := &http.Transport{
		DialContext:           dialer.DialContext,
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          maxIdleConns,
		MaxIdleConnsPerHost:   2,
		IdleConnTimeout:       idleConnTimeout,
		TLSHandshakeTimeout:   tlsHandshakeTimeout,
		ResponseHeaderTimeout: responseHeaderTimeout,
		ExpectContinueTimeout: time.Second,
	}

	client := &http.Client{
		Transport: transport,
		Timeout:   cfg.Timeout,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= cfg.MaxRedirects {
				return fmt.Errorf("%w: stopped after %d", ErrTooManyRedirects, len(via))
			}
			// A redirect is a fresh destination chosen by the server, so it goes
			// through the same checks as the URL the operator configured.
			return checkParsedURL(req.URL, !cfg.AllowPrivateNetworks)
		},
	}

	return &Client{cfg: cfg, http: client}
}

// Fetch performs one conditional GET.
//
// A 304 returns a Response with NotModified set and the validators echoed back,
// so a caller can store what it receives without special-casing. Any other
// non-2xx status is a *StatusError.
func (c *Client) Fetch(ctx context.Context, r Request) (*Response, error) {
	u, err := checkURL(r.URL, !c.cfg.AllowPrivateNetworks)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("httpclient: build request: %w", err)
	}
	req.Header.Set("User-Agent", c.cfg.UserAgent)
	req.Header.Set("Accept", firstNonEmpty(r.Accept, acceptHeader))
	if r.ETag != "" {
		req.Header.Set("If-None-Match", r.ETag)
	}
	if r.LastModified != "" {
		req.Header.Set("If-Modified-Since", r.LastModified)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() {
		// Drain a little before closing so the connection can be reused; a body
		// that is still huge is not worth the read.
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		_ = resp.Body.Close()
	}()

	out := &Response{
		StatusCode:   resp.StatusCode,
		ContentType:  resp.Header.Get("Content-Type"),
		ETag:         firstNonEmpty(resp.Header.Get("ETag"), r.ETag),
		LastModified: firstNonEmpty(resp.Header.Get("Last-Modified"), r.LastModified),
		FinalURL:     resp.Request.URL.String(),
	}

	if resp.StatusCode == http.StatusNotModified {
		out.NotModified = true
		return out, nil
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, &StatusError{StatusCode: resp.StatusCode}
	}

	// A declared length over the cap is refused before a byte is read.
	if resp.ContentLength > c.cfg.MaxResponseBytes {
		return nil, fmt.Errorf("%w: declared %d bytes, limit is %d",
			ErrResponseTooLarge, resp.ContentLength, c.cfg.MaxResponseBytes)
	}

	body, err := readCapped(resp.Body, c.cfg.MaxResponseBytes)
	if err != nil {
		return nil, err
	}
	out.Body = body
	return out, nil
}

// readCapped reads at most limit bytes and fails if the source had more, rather
// than returning a body that has been silently cut in half. The limit applies
// after transparent decompression, so an over-large body cannot be smuggled in
// as a small gzip stream.
func readCapped(r io.Reader, limit int64) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r, limit+1))
	if err != nil {
		return nil, fmt.Errorf("httpclient: read body: %w", err)
	}
	if int64(len(body)) > limit {
		return nil, fmt.Errorf("%w: limit is %d bytes", ErrResponseTooLarge, limit)
	}
	return body, nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
