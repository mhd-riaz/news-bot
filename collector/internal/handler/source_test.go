package handler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

// fakeSourceManager stands in for the service so handler tests exercise HTTP
// behaviour only. Each field lets one test choose the outcome it needs.
type fakeSourceManager struct {
	source   *domain.Source
	page     domain.SourcePage
	err      error
	lastIn   domain.SourceInput
	lastID   string
	lastPtch domain.SourcePatch
	lastFltr domain.SourceFilter
	calls    int
}

var _ SourceManager = (*fakeSourceManager)(nil)

func (f *fakeSourceManager) Create(_ context.Context, in domain.SourceInput) (*domain.Source, error) {
	f.calls++
	f.lastIn = in
	return f.source, f.err
}

func (f *fakeSourceManager) Get(_ context.Context, id string) (*domain.Source, error) {
	f.calls++
	f.lastID = id
	return f.source, f.err
}

func (f *fakeSourceManager) List(_ context.Context, filter domain.SourceFilter) (domain.SourcePage, error) {
	f.calls++
	f.lastFltr = filter
	return f.page, f.err
}

func (f *fakeSourceManager) Update(_ context.Context, id string, patch domain.SourcePatch) (*domain.Source, error) {
	f.calls++
	f.lastID = id
	f.lastPtch = patch
	return f.source, f.err
}

func (f *fakeSourceManager) Delete(_ context.Context, id string) error {
	f.calls++
	f.lastID = id
	return f.err
}

func sampleSource() *domain.Source {
	return &domain.Source{
		ID:                   "0198f3d2-1111-7000-8000-000000000001",
		Name:                 "The Hindu — Bengaluru",
		FeedURL:              "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
		Type:                 domain.SourceTypeRSS,
		Enabled:              true,
		Priority:             50,
		Language:             "en",
		Country:              "IN",
		State:                "Karnataka",
		City:                 "Bengaluru",
		FetchIntervalSeconds: 900,
		NextScheduledAt:      time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC),
		HealthStatus:         domain.HealthUnknown,
		CreatedAt:            time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC),
		UpdatedAt:            time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC),
	}
}

func newSourceServer(t *testing.T, mgr SourceManager) http.Handler {
	t.Helper()
	logger := discardLogger()
	return NewRouter(
		NewHealth(stubPinger{}, time.Second, "test", logger),
		NewSource(mgr, logger),
		NewCollectionRun(&fakeRunReader{}, logger),
		NewArticle(&fakeArticleReader{}, logger),
		nil,
		nil,
		logger,
	)
}

func request(t *testing.T, h http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	var req *http.Request
	if body == "" {
		req = httptest.NewRequest(method, path, nil)
	} else {
		req = httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decodeError(t *testing.T, rec *httptest.ResponseRecorder) errorEnvelope {
	t.Helper()
	var env errorEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil {
		t.Fatalf("decode error body %q: %v", rec.Body.String(), err)
	}
	return env
}

const validCreateBody = `{
  "name": "The Hindu — Bengaluru",
  "feed_url": "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
  "type": "rss",
  "language": "en",
  "country": "IN",
  "state": "Karnataka",
  "city": "Bengaluru"
}`

func TestCreateSourceReturns201AndLocation(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", validCreateBody)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201: %s", rec.Code, rec.Body.String())
	}
	if got, want := rec.Header().Get("Location"), "/api/v1/sources/"+sampleSource().ID; got != want {
		t.Errorf("Location = %q, want %q", got, want)
	}
	if got := rec.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Errorf("X-Content-Type-Options = %q, want nosniff", got)
	}

	var body sourceResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.ID != sampleSource().ID {
		t.Errorf("id = %q, want %q", body.ID, sampleSource().ID)
	}
}

// The response must be built from an explicit DTO. If it were the domain model,
// it would carry bson field names and no JSON tags.
func TestCreateSourceResponseUsesTheWireContract(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", validCreateBody)

	var raw map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &raw); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	for _, key := range []string{"id", "feed_url", "fetch_interval_seconds", "health_status", "created_at"} {
		if _, ok := raw[key]; !ok {
			t.Errorf("response is missing %q: %v", key, raw)
		}
	}
	if _, ok := raw["_id"]; ok {
		t.Error("response exposes the storage field _id")
	}
}

// A caller must not be able to set fields the server owns.
func TestCreateSourceRejectsServerOwnedFields(t *testing.T) {
	tests := []string{"health_status", "consecutive_failures", "created_at", "id", "last_error", "next_scheduled_at"}

	for _, field := range tests {
		t.Run(field, func(t *testing.T) {
			mgr := &fakeSourceManager{source: sampleSource()}
			body := fmt.Sprintf(`{"name":"n","feed_url":"https://e.com/f","type":"rss","language":"en","country":"IN","%s":"x"}`, field)
			rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", body)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400 for an attempt to set %q", rec.Code, field)
			}
			if mgr.calls != 0 {
				t.Error("the service was called despite an invalid payload")
			}
		})
	}
}

func TestCreateSourceRejectsMalformedBodies(t *testing.T) {
	tests := []struct {
		name string
		body string
		want int
	}{
		{"not json", `{oops`, http.StatusBadRequest},
		{"unknown field", `{"name":"n","nope":1}`, http.StatusBadRequest},
		{"wrong type for field", `{"priority":"high"}`, http.StatusBadRequest},
		{"trailing object", `{"name":"a"}{"name":"b"}`, http.StatusBadRequest},
		{"json array", `[{"name":"a"}]`, http.StatusBadRequest},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mgr := &fakeSourceManager{source: sampleSource()}
			rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", tc.body)

			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d: %s", rec.Code, tc.want, rec.Body.String())
			}
			if code := decodeError(t, rec).Error.Code; code != CodeInvalidInput {
				t.Errorf("code = %q, want %q", code, CodeInvalidInput)
			}
		})
	}
}

func TestCreateSourceRejectsAnEmptyBody(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sources", nil)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	newSourceServer(t, mgr).ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
	if mgr.calls != 0 {
		t.Error("the service was called for an empty body")
	}
}

func TestCreateSourceRejectsANonJSONContentType(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sources", strings.NewReader(validCreateBody))
	req.Header.Set("Content-Type", "text/plain")
	rec := httptest.NewRecorder()
	newSourceServer(t, mgr).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("status = %d, want 415", rec.Code)
	}
}

func TestCreateSourceAcceptsAContentTypeWithCharset(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sources", strings.NewReader(validCreateBody))
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	rec := httptest.NewRecorder()
	newSourceServer(t, mgr).ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201: %s", rec.Code, rec.Body.String())
	}
}

func TestCreateSourceRejectsAnOversizedBody(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	body := `{"name":"` + strings.Repeat("a", maxRequestBodyBytes+1) + `"}`
	rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", body)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
	if mgr.calls != 0 {
		t.Error("the service was called for an oversized body")
	}
}

func TestCreateSourceMapsValidationFailureTo400WithFields(t *testing.T) {
	mgr := &fakeSourceManager{err: &domain.ValidationError{Fields: []domain.FieldError{
		{Field: "feed_url", Message: "must use the http or https scheme"},
	}}}
	rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", validCreateBody)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
	env := decodeError(t, rec)
	if env.Error.Code != CodeInvalidInput {
		t.Errorf("code = %q, want %q", env.Error.Code, CodeInvalidInput)
	}
	if len(env.Error.Fields) != 1 || env.Error.Fields[0].Field != "feed_url" {
		t.Errorf("fields = %v, want the offending field reported", env.Error.Fields)
	}
}

func TestCreateSourceMapsConflictTo409(t *testing.T) {
	mgr := &fakeSourceManager{err: fmt.Errorf("%w: taken", service.ErrConflict)}
	rec := request(t, newSourceServer(t, mgr), http.MethodPost, "/api/v1/sources", validCreateBody)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409", rec.Code)
	}
	if code := decodeError(t, rec).Error.Code; code != CodeConflict {
		t.Errorf("code = %q, want %q", code, CodeConflict)
	}
}

func TestSourceErrorsNeverLeakInternalDetail(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{"driver failure", errors.New("server selection error: no reachable servers at cluster0.internal:27017"), http.StatusInternalServerError},
		{"deadline exceeded", fmt.Errorf("find sources: %w", context.DeadlineExceeded), http.StatusServiceUnavailable},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mgr := &fakeSourceManager{err: tc.err}
			rec := request(t, newSourceServer(t, mgr), http.MethodGet, "/api/v1/sources", "")

			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d", rec.Code, tc.want)
			}
			if strings.Contains(rec.Body.String(), "cluster0.internal") {
				t.Errorf("response leaked internal topology: %s", rec.Body.String())
			}
			if strings.Contains(rec.Body.String(), "deadline") {
				t.Errorf("response leaked driver detail: %s", rec.Body.String())
			}
		})
	}
}

func TestGetSourceMapsNotFoundTo404(t *testing.T) {
	mgr := &fakeSourceManager{err: service.ErrNotFound}
	rec := request(t, newSourceServer(t, mgr), http.MethodGet, "/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
	if code := decodeError(t, rec).Error.Code; code != CodeNotFound {
		t.Errorf("code = %q, want %q", code, CodeNotFound)
	}
}

func TestGetSourcePassesThePathIdentifierThrough(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	rec := request(t, newSourceServer(t, mgr), http.MethodGet, "/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if mgr.lastID != "0198f3d2-1111-7000-8000-000000000001" {
		t.Errorf("id = %q, want the path value", mgr.lastID)
	}
}

func TestListSourcesParsesFilters(t *testing.T) {
	mgr := &fakeSourceManager{page: domain.SourcePage{
		Items:  []domain.Source{*sampleSource()},
		Total:  1,
		Limit:  25,
		Offset: 5,
	}}
	rec := request(t, newSourceServer(t, mgr), http.MethodGet,
		"/api/v1/sources?enabled=true&type=rss&health_status=healthy&country=in&state=Karnataka&city=Mysuru&limit=25&offset=5", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body.String())
	}
	f := mgr.lastFltr
	if f.Enabled == nil || !*f.Enabled {
		t.Error("enabled filter was not parsed")
	}
	if f.Type == nil || *f.Type != domain.SourceTypeRSS {
		t.Errorf("type filter = %v, want rss", f.Type)
	}
	if f.HealthStatus == nil || *f.HealthStatus != domain.HealthHealthy {
		t.Errorf("health_status filter = %v, want healthy", f.HealthStatus)
	}
	if f.Country != "in" || f.State != "Karnataka" || f.City != "Mysuru" {
		t.Errorf("region filters = %q/%q/%q", f.Country, f.State, f.City)
	}
	if f.Limit != 25 || f.Offset != 5 {
		t.Errorf("pagination = %d/%d, want 25/5", f.Limit, f.Offset)
	}

	var body sourceListResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body.Total != 1 || len(body.Items) != 1 || body.Limit != 25 || body.Offset != 5 {
		t.Errorf("body = %+v, want the page echoed back", body)
	}
}

func TestListSourcesRejectsUnparseableQueryParameters(t *testing.T) {
	tests := []struct {
		query string
		field string
	}{
		{"enabled=maybe", "enabled"},
		{"limit=lots", "limit"},
		{"offset=-", "offset"},
	}

	for _, tc := range tests {
		t.Run(tc.query, func(t *testing.T) {
			mgr := &fakeSourceManager{}
			rec := request(t, newSourceServer(t, mgr), http.MethodGet, "/api/v1/sources?"+tc.query, "")

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400", rec.Code)
			}
			if mgr.calls != 0 {
				t.Error("the service was called with an unparseable filter")
			}
			fields := decodeError(t, rec).Error.Fields
			if len(fields) == 0 || fields[0].Field != tc.field {
				t.Errorf("fields = %v, want one named %q", fields, tc.field)
			}
		})
	}
}

func TestListSourcesReturnsAnEmptyArrayNotNull(t *testing.T) {
	mgr := &fakeSourceManager{page: domain.SourcePage{Items: nil, Limit: 50}}
	rec := request(t, newSourceServer(t, mgr), http.MethodGet, "/api/v1/sources", "")

	if !strings.Contains(rec.Body.String(), `"items":[]`) {
		t.Errorf("body = %s, want an empty array so clients need no null check", rec.Body.String())
	}
}

func TestUpdateSourceAppliesOnlySuppliedFields(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	rec := request(t, newSourceServer(t, mgr), http.MethodPatch,
		"/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", `{"enabled":false}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body.String())
	}
	if mgr.lastPtch.Enabled == nil || *mgr.lastPtch.Enabled {
		t.Error("enabled was not carried into the patch")
	}
	if mgr.lastPtch.Name != nil || mgr.lastPtch.Priority != nil {
		t.Error("omitted fields became part of the patch, want them left nil")
	}
}

func TestUpdateSourceCarriesTypeIntoThePatch(t *testing.T) {
	mgr := &fakeSourceManager{source: sampleSource()}
	rec := request(t, newSourceServer(t, mgr), http.MethodPatch,
		"/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", `{"type":"atom"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if mgr.lastPtch.Type == nil || *mgr.lastPtch.Type != domain.SourceTypeAtom {
		t.Errorf("type patch = %v, want atom", mgr.lastPtch.Type)
	}
}

func TestDeleteSourceReturns204WithNoBody(t *testing.T) {
	mgr := &fakeSourceManager{}
	rec := request(t, newSourceServer(t, mgr), http.MethodDelete,
		"/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", "")

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", rec.Code)
	}
	if rec.Body.Len() != 0 {
		t.Errorf("body = %q, want it empty", rec.Body.String())
	}
}

func TestDeleteSourceMapsNotFoundTo404(t *testing.T) {
	mgr := &fakeSourceManager{err: service.ErrNotFound}
	rec := request(t, newSourceServer(t, mgr), http.MethodDelete,
		"/api/v1/sources/0198f3d2-1111-7000-8000-000000000001", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestSourceRoutesRejectUnsupportedMethods(t *testing.T) {
	tests := []struct{ method, path string }{
		{http.MethodPut, "/api/v1/sources"},
		{http.MethodDelete, "/api/v1/sources"},
		{http.MethodPost, "/api/v1/sources/0198f3d2-1111-7000-8000-000000000001"},
	}

	for _, tc := range tests {
		t.Run(tc.method+" "+tc.path, func(t *testing.T) {
			mgr := &fakeSourceManager{source: sampleSource()}
			rec := request(t, newSourceServer(t, mgr), tc.method, tc.path, "")

			if rec.Code == http.StatusOK || rec.Code == http.StatusCreated {
				t.Fatalf("status = %d, want the method to be refused", rec.Code)
			}
			if mgr.calls != 0 {
				t.Error("the service was reached over an unsupported method")
			}
		})
	}
}
