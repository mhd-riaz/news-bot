package classifier

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func newTestClient(t *testing.T, handler http.HandlerFunc) *HTTPClient {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	client, err := NewHTTPClient(server.URL, time.Second, 2, "test-secret")
	if err != nil {
		t.Fatalf("NewHTTPClient: %v", err)
	}
	return client
}

func TestNewHTTPClientRejectsInvalidConfiguration(t *testing.T) {
	for name, args := range map[string]struct {
		endpoint  string
		timeout   time.Duration
		batchSize int
	}{
		"blank endpoint":       {"", time.Second, 1},
		"relative endpoint":    {"/v1", time.Second, 1},
		"unsupported scheme":   {"ftp://model", time.Second, 1},
		"non-positive timeout": {"http://model", 0, 1},
		"non-positive batch":   {"http://model", time.Second, 0},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := NewHTTPClient(args.endpoint, args.timeout, args.batchSize, ""); !errors.Is(err, ErrInvalidEndpoint) {
				t.Errorf("error = %v, want ErrInvalidEndpoint", err)
			}
		})
	}
}

func TestHTTPClientReportsItsConfiguredBatchSize(t *testing.T) {
	client, err := NewHTTPClient("http://model", time.Second, 25, "")
	if err != nil {
		t.Fatalf("NewHTTPClient: %v", err)
	}
	if got := client.BatchSize(); got != 25 {
		t.Errorf("BatchSize() = %d, want 25", got)
	}
}

func TestClassifySendsTheExpectedRequestAndValidatesResponse(t *testing.T) {
	client := newTestClient(t, func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost || request.URL.Path != "/v1/classify" || request.Header.Get("X-Classifier-Key") != "test-secret" {
			t.Fatalf("unexpected request %s %s", request.Method, request.URL)
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"model_version":"v2-001","items":[{"id":"a","topic":"politics","confidence":0.9,"filed":true},{"id":"b","topic":"unsorted","confidence":0.4,"filed":false}]}`))
	})
	results, err := client.Classify(t.Context(), []Item{{ID: "a", Title: "Budget"}, {ID: "b", Summary: "Story"}})
	if err != nil {
		t.Fatalf("Classify: %v", err)
	}
	if len(results) != 2 || results[0].Topic != "politics" || results[1].Topic != "unsorted" {
		t.Errorf("results = %#v", results)
	}
}

func TestClassifyRejectsInvalidResponseContracts(t *testing.T) {
	client := newTestClient(t, func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"model_version":"v2-001","items":[{"id":"wrong","topic":"politics","confidence":0.9,"filed":true}]}`))
	})
	_, err := client.Classify(t.Context(), []Item{{ID: "expected"}})
	if !errors.Is(err, ErrBadResponse) {
		t.Errorf("error = %v, want ErrBadResponse", err)
	}
}

func TestClassifyMapsHTTPAndContentTypeFailures(t *testing.T) {
	client := newTestClient(t, func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusServiceUnavailable)
	})
	if _, err := client.Classify(t.Context(), []Item{{ID: "a"}}); !errors.Is(err, ErrService) {
		t.Errorf("error = %v, want ErrService", err)
	}
}

func TestMetadataRequiresCanonicalJSON(t *testing.T) {
	client := newTestClient(t, func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"model_version":"v2-001","cut":0.6,"topics":[{"id":"politics","label":"Politics"},{"id":"unsorted","label":"Unsorted"}]}`))
	})
	metadata, err := client.Metadata(t.Context())
	if err != nil || len(metadata.Topics) != 2 {
		t.Errorf("Metadata = %#v, %v", metadata, err)
	}
}
