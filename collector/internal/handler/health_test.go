package handler

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type stubPinger struct {
	err   error
	delay time.Duration
}

func (s stubPinger) Ping(ctx context.Context) error {
	if s.delay > 0 {
		select {
		case <-time.After(s.delay):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return s.err
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewJSONHandler(io.Discard, nil))
}

func newTestServer(t *testing.T, p Pinger) http.Handler {
	t.Helper()
	logger := discardLogger()
	return NewRouter(
		NewHealth(p, 100*time.Millisecond, "test", logger),
		NewSource(&fakeSourceManager{}, logger),
		NewCollectionRun(&fakeRunReader{}, logger),
		NewArticle(&fakeArticleReader{}, logger),
		nil,
		nil,
		logger,
	)
}

func do(t *testing.T, h http.Handler, method, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, path, nil))
	return rec
}

func TestLiveIsIndependentOfDependencies(t *testing.T) {
	h := newTestServer(t, stubPinger{err: errors.New("mongo down")})

	rec := do(t, h, http.MethodGet, "/health/live")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var body healthResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.Status != "alive" {
		t.Errorf("status = %q, want %q", body.Status, "alive")
	}
	if got := rec.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Errorf("Content-Type = %q", got)
	}
	if got := rec.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Errorf("X-Content-Type-Options = %q, want nosniff", got)
	}
}

func TestReadyWhenDependencyIsHealthy(t *testing.T) {
	h := newTestServer(t, stubPinger{})

	rec := do(t, h, http.MethodGet, "/health/ready")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var body healthResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.Status != "ready" {
		t.Errorf("status = %q, want %q", body.Status, "ready")
	}
	if body.Checks["mongodb"] != "ok" {
		t.Errorf("mongodb check = %q, want ok", body.Checks["mongodb"])
	}
}

func TestReadyWhenDependencyIsDown(t *testing.T) {
	h := newTestServer(t, stubPinger{err: errors.New("server selection error: no reachable servers at cluster0.internal:27017")})

	rec := do(t, h, http.MethodGet, "/health/ready")

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "cluster0.internal") {
		t.Errorf("readiness leaked internal topology detail: %s", rec.Body.String())
	}

	var body healthResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.Status != "not_ready" {
		t.Errorf("status = %q, want %q", body.Status, "not_ready")
	}
}

func TestReadyTimesOutOnHungDependency(t *testing.T) {
	h := newTestServer(t, stubPinger{delay: time.Second})

	start := time.Now()
	rec := do(t, h, http.MethodGet, "/health/ready")
	elapsed := time.Since(start)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	if elapsed >= time.Second {
		t.Errorf("probe waited %s; the check timeout must bound it", elapsed)
	}
}

func TestUnknownRouteReturnsJSONError(t *testing.T) {
	h := newTestServer(t, stubPinger{})

	rec := do(t, h, http.MethodGet, "/api/v1/does-not-exist")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}

	var body errorEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.Error.Code != CodeNotFound {
		t.Errorf("code = %q, want %q", body.Error.Code, CodeNotFound)
	}
}

func TestHealthRoutesRejectNonGET(t *testing.T) {
	h := newTestServer(t, stubPinger{})

	for _, method := range []string{http.MethodPost, http.MethodDelete} {
		rec := do(t, h, method, "/health/live")
		if rec.Code == http.StatusOK {
			t.Errorf("%s /health/live returned 200; only GET should be routed", method)
		}
	}
}

func TestEveryResponseCarriesARequestID(t *testing.T) {
	h := newTestServer(t, stubPinger{})

	rec := do(t, h, http.MethodGet, "/health/live")

	if rec.Header().Get("X-Request-Id") == "" {
		t.Error("responses must carry a correlation id")
	}
}
