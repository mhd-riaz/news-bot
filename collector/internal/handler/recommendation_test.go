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

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/recommendation"
)

const recommendedID = "0198f3d2-3333-7000-8000-000000000001"

type recommendationArticles struct{}

func (recommendationArticles) GetByIDs(context.Context, []string) ([]domain.Article, error) {
	when := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	return []domain.Article{{
		ID: recommendedID, Title: "<script>not HTML</script>", SourceName: "Test source",
		URL: "https://example.test/story", PublishedAt: when, CollectedAt: when,
	}}, nil
}

func recommendationHandler(t *testing.T, status int, body string) *Recommendation {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(server.Close)
	service, err := recommendation.New(server.URL, "", recommendationArticles{})
	if err != nil {
		t.Fatal(err)
	}
	return NewRecommendation(service, slog.New(slog.DiscardHandler))
}

func TestRecommendationsSerializeOriginalMetadataAndCleanText(t *testing.T) {
	t.Parallel()
	h := recommendationHandler(t, 200, `{"snapshot_id":"test","method":"neural","items":[{"id":"`+recommendedID+`","text":"An excerpt.","text_kind":"Excerpt","input_kind":"body","topic":"0","score":0.8,"reason":"Related to this article"}]}`)
	request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"limit":1}`))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	h.Recommend(recorder, request)
	var result struct {
		Items []storyResponse `json:"items"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if recorder.Code != 200 || len(result.Items) != 1 || result.Items[0].DateKind != "Collected" ||
		result.Items[0].Title != "<script>not HTML</script>" || result.Items[0].Text != "An excerpt." {
		t.Fatalf("response = %d %s", recorder.Code, recorder.Body)
	}
	if strings.Contains(recorder.Body.String(), "<script>") || recorder.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("JSON escaping or private response cache policy missing")
	}
}

func TestRecommendationMetadataAndDownstreamFailures(t *testing.T) {
	t.Parallel()
	h := recommendationHandler(t, 200, `{"snapshot_id":"test","articles":2,"topics":[{"id":"0"}]}`)
	recorder := httptest.NewRecorder()
	h.Metadata(recorder, httptest.NewRequest(http.MethodGet, "/", nil))
	if recorder.Code != 200 || !strings.Contains(recorder.Body.String(), `"snapshot_id":"test"`) {
		t.Fatal(recorder.Body.String())
	}
	for status, want := range map[int]int{400: 400, 404: 404, 503: 503} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			t.Parallel()
			h := recommendationHandler(t, status, `{}`)
			recorder := httptest.NewRecorder()
			h.Metadata(recorder, httptest.NewRequest(http.MethodGet, "/", nil))
			if recorder.Code != want || !strings.Contains(recorder.Body.String(), `"error"`) {
				t.Fatalf("status = %d, body=%s", recorder.Code, recorder.Body)
			}
		})
	}
}

func TestRecommendationPayloadValidationAndLargeValidHistory(t *testing.T) {
	t.Parallel()
	h := recommendationHandler(t, 200, `{"snapshot_id":"test","items":[],"exhausted":true}`)
	for name, sample := range map[string]struct {
		body, contentType string
		want              int
	}{
		"malformed":        {`{`, "application/json", 400},
		"unknown fields":   {`{"where":{}}`, "application/json", 400},
		"multiple objects": {`{} {}`, "application/json", 400},
		"wrong media":      {`{}`, "text/plain", 415},
		"too large":        {strings.Repeat("x", 130<<10), "application/json", 400},
		"invalid seed":     {`{"seed_id":"$where"}`, "application/json", 400},
		"bad method":       {`{"method":"invalid"}`, "application/json", 400},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(sample.body))
			request.Header.Set("Content-Type", sample.contentType)
			h.Recommend(recorder, request)
			if recorder.Code != sample.want {
				t.Fatalf("status = %d, body=%s", recorder.Code, recorder.Body)
			}
		})
	}
	payload, err := json.Marshal(recommendation.Request{Viewed: makeViewedIDs(2000)})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(string(payload)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	h.Recommend(recorder, request)
	if len(payload) <= 64<<10 || recorder.Code != 200 {
		t.Fatalf("bounded 2000-ID history rejected: %d (%d bytes): %s", recorder.Code, len(payload), recorder.Body)
	}
}

func makeViewedIDs(count int) []string {
	values := make([]string, count)
	for i := range values {
		values[i] = recommendedID
	}
	return values
}

func TestRecommendationFailureDoesNotLeakInternalDetails(t *testing.T) {
	t.Parallel()
	h := &Recommendation{logger: slog.New(slog.DiscardHandler)}
	recorder := httptest.NewRecorder()
	h.failure(recorder, httptest.NewRequest(http.MethodPost, "/", nil), errors.New("private database detail"))
	body, err := io.ReadAll(recorder.Result().Body)
	if err != nil {
		t.Fatal(err)
	}
	if recorder.Code != 503 || strings.Contains(string(body), "private database") {
		t.Fatalf("unsafe error: %s", body)
	}
}
