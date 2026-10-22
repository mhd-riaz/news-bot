package observability

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestNewLoggerFormats(t *testing.T) {
	tests := []struct {
		format   string
		wantJSON bool
	}{
		{"json", true},
		{"text", false},
	}

	for _, tc := range tests {
		t.Run(tc.format, func(t *testing.T) {
			var buf bytes.Buffer
			logger, err := NewLogger("info", tc.format, &buf)
			if err != nil {
				t.Fatalf("NewLogger: %v", err)
			}
			logger.Info("hello", "key", "value")

			line := buf.String()
			isJSON := json.Valid([]byte(strings.TrimSpace(line)))
			if isJSON != tc.wantJSON {
				t.Errorf("format %q produced JSON=%v, want %v (line: %s)", tc.format, isJSON, tc.wantJSON, line)
			}
			if !strings.Contains(line, "hello") {
				t.Errorf("log line missing message: %s", line)
			}
		})
	}
}

func TestNewLoggerRejectsUnknownFormat(t *testing.T) {
	if _, err := NewLogger("info", "xml", &bytes.Buffer{}); err == nil {
		t.Fatal("expected an error for an unsupported format")
	}
}

func TestNewLoggerHonoursLevel(t *testing.T) {
	var buf bytes.Buffer
	logger, err := NewLogger("warn", "json", &buf)
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}

	logger.Info("suppressed")
	if buf.Len() != 0 {
		t.Errorf("info must be filtered out at warn level, got: %s", buf.String())
	}

	logger.Warn("emitted")
	if !strings.Contains(buf.String(), "emitted") {
		t.Errorf("warn must be emitted at warn level, got: %s", buf.String())
	}
}

func TestParseLevel(t *testing.T) {
	tests := map[string]slog.Level{
		"debug":   slog.LevelDebug,
		"INFO":    slog.LevelInfo,
		" warn ":  slog.LevelWarn,
		"warning": slog.LevelWarn,
		"error":   slog.LevelError,
	}
	for in, want := range tests {
		got, err := ParseLevel(in)
		if err != nil {
			t.Errorf("ParseLevel(%q): %v", in, err)
			continue
		}
		if got != want {
			t.Errorf("ParseLevel(%q) = %v, want %v", in, got, want)
		}
	}

	if _, err := ParseLevel("verbose"); err == nil {
		t.Error("expected an error for an unknown level")
	}
}

func TestRequestIDIsSetAndUnique(t *testing.T) {
	var seen []string
	handler := RequestID(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		seen = append(seen, RequestIDFrom(r.Context()))
	}))

	var headers []string
	for range 2 {
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/health/live", nil))
		headers = append(headers, rec.Header().Get(RequestIDHeader))
	}

	for i, id := range seen {
		if id == "" {
			t.Fatalf("request %d had no id in context", i)
		}
		if headers[i] != id {
			t.Errorf("response header %q does not match context id %q", headers[i], id)
		}
	}
	if seen[0] == seen[1] {
		t.Error("request ids must not repeat across requests")
	}
}

func TestRequestIDIgnoresClientSuppliedValue(t *testing.T) {
	handler := RequestID(http.HandlerFunc(func(_ http.ResponseWriter, _ *http.Request) {}))

	req := httptest.NewRequest(http.MethodGet, "/health/live", nil)
	req.Header.Set(RequestIDHeader, "forged-by-client")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if got := rec.Header().Get(RequestIDHeader); got == "forged-by-client" {
		t.Error("a client-supplied request id must not be echoed back")
	}
}

func TestAccessLogRecordsOutcomeWithoutHeaders(t *testing.T) {
	var buf bytes.Buffer
	logger, err := NewLogger("info", "json", &buf)
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}

	handler := Chain(
		http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusTeapot)
			_, _ = w.Write([]byte("nope"))
		}),
		RequestID, AccessLog(logger),
	)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.Header.Set("Authorization", "Bearer super-secret-token")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("access log is not valid JSON: %v (%s)", err, buf.String())
	}
	if entry["status"] != float64(http.StatusTeapot) {
		t.Errorf("status = %v, want %d", entry["status"], http.StatusTeapot)
	}
	if entry["path"] != "/api/v1/articles" {
		t.Errorf("path = %v", entry["path"])
	}
	if id, _ := entry["request_id"].(string); id == "" {
		t.Error("access log must carry the request id")
	}
	if strings.Contains(buf.String(), "super-secret-token") {
		t.Error("access log leaked an Authorization header value")
	}
}

func TestRecoverReturnsOpaqueError(t *testing.T) {
	var buf bytes.Buffer
	logger, err := NewLogger("error", "json", &buf)
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}

	handler := Chain(
		http.HandlerFunc(func(_ http.ResponseWriter, _ *http.Request) {
			panic("connection string mongodb://admin:hunter2@db")
		}),
		Recover(logger),
	)

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/boom", nil))

	if rec.Code != http.StatusInternalServerError {
		t.Errorf("status = %d, want 500", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "hunter2") {
		t.Errorf("panic detail leaked to the client: %s", rec.Body.String())
	}
	if !strings.Contains(buf.String(), "panic recovered") {
		t.Errorf("panic should be logged server-side, got: %s", buf.String())
	}
}

func TestChainAppliesOutermostFirst(t *testing.T) {
	var order []string
	mark := func(name string) Middleware {
		return func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				order = append(order, name)
				next.ServeHTTP(w, r)
			})
		}
	}

	handler := Chain(http.HandlerFunc(func(_ http.ResponseWriter, _ *http.Request) {
		order = append(order, "handler")
	}), mark("first"), mark("second"))

	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))

	want := []string{"first", "second", "handler"}
	if strings.Join(order, ",") != strings.Join(want, ",") {
		t.Errorf("order = %v, want %v", order, want)
	}
}
