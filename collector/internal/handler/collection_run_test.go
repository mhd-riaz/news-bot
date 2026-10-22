package handler

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

// fakeRunReader stands in for the collection service so these tests exercise
// HTTP behaviour only.
type fakeRunReader struct {
	run      *domain.CollectionRun
	page     domain.CollectionRunPage
	err      error
	lastID   string
	lastFltr domain.CollectionRunFilter
	calls    int
}

var _ CollectionRunReader = (*fakeRunReader)(nil)

func (f *fakeRunReader) ListRuns(_ context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error) {
	f.calls++
	f.lastFltr = filter
	return f.page, f.err
}

func (f *fakeRunReader) GetRun(_ context.Context, id string) (*domain.CollectionRun, error) {
	f.calls++
	f.lastID = id
	return f.run, f.err
}

func sampleRun() *domain.CollectionRun {
	started := time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)
	return &domain.CollectionRun{
		ID:          "0198f3d2-2222-7000-8000-000000000001",
		SourceID:    "0198f3d2-1111-7000-8000-000000000001",
		SourceName:  "The Hindu — Bengaluru",
		Status:      domain.RunStatusSuccess,
		StartedAt:   started,
		CompletedAt: started.Add(1200 * time.Millisecond),
		DurationMS:  1200,
		FeedType:    "rss",
		ItemsFound:  20,
		ItemsStored: 18,
	}
}

func newRunServer(t *testing.T, runs CollectionRunReader) http.Handler {
	t.Helper()
	logger := discardLogger()
	return NewRouter(
		NewHealth(stubPinger{}, 100*time.Millisecond, "test", logger),
		NewSource(&fakeSourceManager{}, logger),
		NewCollectionRun(runs, logger),
		NewArticle(&fakeArticleReader{}, logger),
		nil,
		nil,
		logger,
	)
}

func TestListRunsReturnsThePage(t *testing.T) {
	runs := &fakeRunReader{page: domain.CollectionRunPage{
		Items:  []domain.CollectionRun{*sampleRun()},
		Total:  1,
		Limit:  50,
		Offset: 0,
	}}

	rec := do(t, newRunServer(t, runs), http.MethodGet, "/api/v1/collection-runs")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	var body collectionRunListResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Items) != 1 || body.Total != 1 {
		t.Fatalf("body = %+v, want one run and a total of 1", body)
	}
	if body.Items[0].Status != "success" || body.Items[0].ItemsStored != 18 {
		t.Errorf("run was not rendered faithfully: %+v", body.Items[0])
	}
}

func TestListRunsPassesTheFilterThrough(t *testing.T) {
	runs := &fakeRunReader{}
	sourceID := "0198f3d2-1111-7000-8000-000000000001"

	rec := do(t, newRunServer(t, runs), http.MethodGet,
		"/api/v1/collection-runs?source_id="+sourceID+"&status=failed&limit=10&offset=20")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	got := runs.lastFltr
	if got.SourceID != sourceID || got.Limit != 10 || got.Offset != 20 {
		t.Fatalf("filter = %+v, want the query parameters carried through", got)
	}
	if got.Status == nil || *got.Status != domain.RunStatusFailed {
		t.Fatalf("status filter = %v, want failed", got.Status)
	}
}

// The handler must not decide what a valid status is; it hands the value to the
// domain, and the service rejects it. Only malformed numbers are caught here.
func TestListRunsRejectsNonNumericPagination(t *testing.T) {
	runs := &fakeRunReader{}

	rec := do(t, newRunServer(t, runs), http.MethodGet, "/api/v1/collection-runs?limit=ten&offset=x")

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
	if runs.calls != 0 {
		t.Errorf("service was called %d times, want 0: a malformed page must not reach it", runs.calls)
	}

	var body errorEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Error.Fields) != 2 {
		t.Errorf("fields = %+v, want both limit and offset reported at once", body.Error.Fields)
	}
}

func TestGetRunReturnsOneRun(t *testing.T) {
	runs := &fakeRunReader{run: sampleRun()}

	rec := do(t, newRunServer(t, runs), http.MethodGet, "/api/v1/collection-runs/"+runs.run.ID)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	if runs.lastID != sampleRun().ID {
		t.Errorf("id = %q, want the path value", runs.lastID)
	}
}

func TestGetRunMapsServiceErrors(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{"unknown run", service.ErrNotFound, http.StatusNotFound},
		{"invalid id", &domain.ValidationError{Fields: []domain.FieldError{{Field: "id", Message: "must be a valid UUID"}}}, http.StatusBadRequest},
		{"dependency timed out", context.DeadlineExceeded, http.StatusServiceUnavailable},
		{"anything else", errors.New("server selection error: no reachable servers at cluster0.internal:27017"), http.StatusInternalServerError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := do(t, newRunServer(t, &fakeRunReader{err: tt.err}), http.MethodGet,
				"/api/v1/collection-runs/0198f3d2-2222-7000-8000-000000000001")

			if rec.Code != tt.want {
				t.Fatalf("status = %d, want %d", rec.Code, tt.want)
			}
		})
	}
}

// A failure reason is written for an operator, so it is served as-is; nothing
// internal reaches it, because the service only ever stores fixed phrases.
func TestFailedRunReportsItsReason(t *testing.T) {
	run := sampleRun()
	run.Status = domain.RunStatusFailed
	run.Error = "the publisher answered HTTP 404"

	rec := do(t, newRunServer(t, &fakeRunReader{run: run}), http.MethodGet, "/api/v1/collection-runs/"+run.ID)

	var body collectionRunResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Error != "the publisher answered HTTP 404" {
		t.Errorf("error = %q, want the stored reason", body.Error)
	}
}

// Collections are driven by the scheduler and the CLI, never by a caller, so no
// write verb is routed. The catch-all answers them the same way it answers any
// unknown route, which keeps one error shape across the whole API.
func TestCollectionRunsRejectWrites(t *testing.T) {
	h := newRunServer(t, &fakeRunReader{})

	for _, method := range []string{http.MethodPost, http.MethodDelete, http.MethodPatch} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(method, "/api/v1/collection-runs", nil))

		if rec.Code != http.StatusNotFound {
			t.Errorf("%s: status = %d, want 404: collections are not triggered over HTTP", method, rec.Code)
		}
	}
}
