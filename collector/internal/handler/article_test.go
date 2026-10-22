package handler

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

// fakeArticleReader stands in for the service so these tests exercise HTTP
// behaviour only.
type fakeArticleReader struct {
	article  *domain.Article
	page     domain.ArticlePage
	deleted  int64
	err      error
	lastID   string
	lastFltr domain.ArticleFilter
	lastDel  domain.ArticleDeletion
	calls    int
}

var _ ArticleManager = (*fakeArticleReader)(nil)

func (f *fakeArticleReader) List(_ context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error) {
	f.calls++
	f.lastFltr = filter
	return f.page, f.err
}

func (f *fakeArticleReader) Get(_ context.Context, id string) (*domain.Article, error) {
	f.calls++
	f.lastID = id
	return f.article, f.err
}

func (f *fakeArticleReader) DeleteOlderThan(_ context.Context, d domain.ArticleDeletion) (int64, error) {
	f.calls++
	f.lastDel = d
	return f.deleted, f.err
}

func sampleArticle() *domain.Article {
	published := time.Date(2026, 8, 22, 9, 0, 0, 0, time.UTC)
	return &domain.Article{
		ID:            "0198f3d2-3333-7000-8000-000000000001",
		DedupID:       "8f14e45fceea167a5a36dedd4bea2543",
		SourceID:      "0198f3d2-1111-7000-8000-000000000001",
		SourceName:    "The Hindu — Bengaluru",
		URL:           "https://www.thehindu.com/news/cities/bangalore/a-story/article1.ece",
		NormalizedURL: "https://thehindu.com/news/cities/bangalore/a-story/article1.ece",
		ContentHash:   "9c1185a5c5e9fc54612808977ee8f548b2258d31",
		Title:         "A story about Bengaluru",
		Summary:       "A summary.",
		Content:       "The full text of the article.",
		Language:      "en",
		Country:       "IN",
		State:         "Karnataka",
		City:          "Bengaluru",
		PublishedAt:   published,
		CollectedAt:   published.Add(time.Hour),
	}
}

func newArticleServer(t *testing.T, articles ArticleManager) http.Handler {
	t.Helper()
	logger := discardLogger()
	return NewRouter(
		NewHealth(stubPinger{}, 100*time.Millisecond, "test", logger),
		NewSource(&fakeSourceManager{}, logger),
		NewCollectionRun(&fakeRunReader{}, logger),
		NewArticle(articles, logger),
		nil,
		nil,
		logger,
	)
}

func TestListArticlesReturnsThePage(t *testing.T) {
	articles := &fakeArticleReader{page: domain.ArticlePage{
		Items:      []domain.Article{*sampleArticle()},
		Limit:      50,
		HasMore:    true,
		NextCursor: "MTc2Njk5MDgwMDAwMC4wMTk4ZjNkMi0zMzMzLTcwMDAtODAwMC0wMDAwMDAwMDAwMDE",
	}}

	rec := do(t, newArticleServer(t, articles), http.MethodGet, "/api/v1/articles")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	var body articleListResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Items) != 1 || !body.HasMore || body.NextCursor == "" {
		t.Fatalf("body = %+v, want one article and a continuation", body)
	}
	if body.Items[0].Title != "A story about Bengaluru" || body.Items[0].City != "Bengaluru" {
		t.Errorf("article was not rendered faithfully: %+v", body.Items[0])
	}
}

// The deduplication keys are internal machinery. A caller who can see them can
// guess how articles are matched, and none of them mean anything to a reader.
func TestArticleResponseHidesInternalKeys(t *testing.T) {
	rec := do(t, newArticleServer(t, &fakeArticleReader{article: sampleArticle()}), http.MethodGet,
		"/api/v1/articles/0198f3d2-3333-7000-8000-000000000001")

	body := rec.Body.String()
	for _, leaked := range []string{"dedup_id", "normalized_url", "content_hash", "processing_status", "feed_guid"} {
		if strings.Contains(body, leaked) {
			t.Errorf("%s reached the response: %s", leaked, body)
		}
	}
}

func TestGetArticleIncludesItsContent(t *testing.T) {
	articles := &fakeArticleReader{article: sampleArticle()}

	rec := do(t, newArticleServer(t, articles), http.MethodGet, "/api/v1/articles/"+articles.article.ID)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	var body articleResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Content != "The full text of the article." {
		t.Errorf("content = %q, want the full text on a single-article read", body.Content)
	}
	if articles.lastID != sampleArticle().ID {
		t.Errorf("id = %q, want the path value", articles.lastID)
	}
}

// A listing projects the content away, and an empty one must be omitted rather
// than rendered as an empty string a caller might mistake for an empty article.
func TestListedArticlesOmitContent(t *testing.T) {
	listed := sampleArticle()
	listed.Content = ""

	rec := do(t, newArticleServer(t, &fakeArticleReader{page: domain.ArticlePage{Items: []domain.Article{*listed}, Limit: 50}}),
		http.MethodGet, "/api/v1/articles")

	if strings.Contains(rec.Body.String(), `"content"`) {
		t.Errorf("content was rendered in a listing: %s", rec.Body)
	}
}

func TestListArticlesPassesTheFilterThrough(t *testing.T) {
	articles := &fakeArticleReader{}
	sourceID := "0198f3d2-1111-7000-8000-000000000001"

	rec := do(t, newArticleServer(t, articles), http.MethodGet,
		"/api/v1/articles?source_id="+sourceID+
			"&language=en&country=IN&state=Karnataka&city=Bengaluru"+
			"&topic=Politics"+
			"&published_from=2026-08-01T00:00:00Z&published_to=2026-08-22T00:00:00Z"+
			"&sort=collected_at&limit=25")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	got := articles.lastFltr
	if got.SourceID != sourceID || got.Language != "en" || got.Country != "IN" ||
		got.State != "Karnataka" || got.City != "Bengaluru" || got.Topic != "Politics" {
		t.Fatalf("filter = %+v, want every parameter carried through", got)
	}
	if got.Sort != domain.SortCollectedAt || got.Limit != 25 {
		t.Errorf("sort/limit = %q/%d, want collected_at/25", got.Sort, got.Limit)
	}
	if got.PublishedFrom == nil || got.PublishedTo == nil {
		t.Fatalf("date bounds = %v..%v, want both parsed", got.PublishedFrom, got.PublishedTo)
	}
	if !got.PublishedFrom.Equal(time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("published_from = %v, want 2026-08-01T00:00:00Z", got.PublishedFrom)
	}
}

func TestArticleResponseIncludesSuccessfulClassification(t *testing.T) {
	article := sampleArticle()
	article.ClassificationStatus = domain.ClassificationStatusClassified
	article.Topic = "politics"
	article.Confidence = 0.9
	article.ModelVersion = "v2-001"

	rec := do(t, newArticleServer(t, &fakeArticleReader{article: article}), http.MethodGet,
		"/api/v1/articles/"+article.ID)
	var body articleResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Topic != "politics" || body.ClassificationStatus != "classified" || body.Confidence == nil || *body.Confidence != 0.9 {
		t.Errorf("classification response = %+v", body)
	}
}

func TestListArticlesForwardsACursor(t *testing.T) {
	articles := &fakeArticleReader{}
	cursor := domain.ArticleCursor{
		Value: time.Date(2026, 8, 22, 9, 0, 0, 0, time.UTC),
		ID:    "0198f3d2-3333-7000-8000-000000000001",
	}

	rec := do(t, newArticleServer(t, articles), http.MethodGet, "/api/v1/articles?cursor="+cursor.Encode())

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	got := articles.lastFltr.Cursor
	if got == nil || got.ID != cursor.ID || !got.Value.Equal(cursor.Value) {
		t.Fatalf("cursor = %+v, want %+v", got, cursor)
	}
}

// A tampered cursor is a bad request, not a silent reset to the first page: a
// caller that quietly restarts a walk would process the same articles twice.
func TestListArticlesRejectsATamperedCursor(t *testing.T) {
	tests := []string{
		"not-base64!!",
		"YWJjZGVm",                 // decodes, but has no separator
		"MTIzNDU2Nzg5MC57JG5lOjF9", // a well-formed prefix with an operator where the id belongs
	}

	for _, cursor := range tests {
		t.Run(cursor, func(t *testing.T) {
			articles := &fakeArticleReader{}

			rec := do(t, newArticleServer(t, articles), http.MethodGet, "/api/v1/articles?cursor="+cursor)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400", rec.Code)
			}
			if articles.calls != 0 {
				t.Errorf("service was called %d times, want 0", articles.calls)
			}
		})
	}
}

func TestListArticlesReportsEveryBadParameterAtOnce(t *testing.T) {
	articles := &fakeArticleReader{}

	rec := do(t, newArticleServer(t, articles), http.MethodGet,
		"/api/v1/articles?limit=lots&published_from=yesterday&published_to=tomorrow")

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
	var body errorEnvelope
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Error.Fields) != 3 {
		t.Errorf("fields = %+v, want all three reported at once", body.Error.Fields)
	}
	if articles.calls != 0 {
		t.Errorf("service was called %d times, want 0", articles.calls)
	}
}

func TestGetArticleMapsServiceErrors(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{"unknown article", service.ErrNotFound, http.StatusNotFound},
		{"invalid id", &domain.ValidationError{Fields: []domain.FieldError{{Field: "id", Message: "must be a valid UUID"}}}, http.StatusBadRequest},
		{"dependency timed out", context.DeadlineExceeded, http.StatusServiceUnavailable},
		{"anything else", errors.New("server selection error: no reachable servers at cluster0.internal:27017"), http.StatusInternalServerError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := do(t, newArticleServer(t, &fakeArticleReader{err: tt.err}), http.MethodGet,
				"/api/v1/articles/0198f3d2-3333-7000-8000-000000000001")

			if rec.Code != tt.want {
				t.Fatalf("status = %d, want %d", rec.Code, tt.want)
			}
			if strings.Contains(rec.Body.String(), "cluster0.internal") {
				t.Error("an internal host name reached the caller")
			}
		})
	}
}

func TestArticlesRejectWrites(t *testing.T) {
	h := newArticleServer(t, &fakeArticleReader{})

	for _, method := range []string{http.MethodPost, http.MethodPatch} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(method, "/api/v1/articles", nil))

		if rec.Code != http.StatusNotFound {
			t.Errorf("%s: status = %d, want 404: articles are written only by the collector", method, rec.Code)
		}
	}
}

func TestDeleteArticlesPassesTheDeletionThroughAndReportsTheCount(t *testing.T) {
	articles := &fakeArticleReader{deleted: 42}
	sourceID := "0198f3d2-1111-7000-8000-000000000001"

	rec := do(t, newArticleServer(t, articles), http.MethodDelete,
		"/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z&source_id="+sourceID+
			"&source_name=The+Hindu")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200: %s", rec.Code, rec.Body)
	}
	got := articles.lastDel
	if !got.OlderThan.Equal(time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("older_than = %v, want 2026-07-01T00:00:00Z", got.OlderThan)
	}
	if got.SourceID != sourceID || got.SourceName != "The Hindu" {
		t.Errorf("deletion = %+v, want both source filters carried through", got)
	}

	var body articleDeleteResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Deleted != 42 {
		t.Errorf("deleted = %d, want 42", body.Deleted)
	}
}

// The bound is what stops the sweep emptying the collection, so a request that
// omits it must never reach the service.
func TestDeleteArticlesRequiresTheBound(t *testing.T) {
	for _, query := range []string{"", "?source_id=0198f3d2-1111-7000-8000-000000000001", "?delete_older_than=last+week"} {
		t.Run(query, func(t *testing.T) {
			articles := &fakeArticleReader{}

			rec := do(t, newArticleServer(t, articles), http.MethodDelete, "/api/v1/articles"+query)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400: %s", rec.Code, rec.Body)
			}
			if articles.calls != 0 {
				t.Errorf("service was called %d times, want 0", articles.calls)
			}
		})
	}
}

func TestDeleteArticlesMapsServiceErrors(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{"invalid source id", &domain.ValidationError{Fields: []domain.FieldError{{Field: "source_id", Message: "must be a valid UUID"}}}, http.StatusBadRequest},
		{"dependency timed out", context.DeadlineExceeded, http.StatusServiceUnavailable},
		{"anything else", errors.New("server selection error: no reachable servers at cluster0.internal:27017"), http.StatusInternalServerError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := do(t, newArticleServer(t, &fakeArticleReader{err: tt.err}), http.MethodDelete,
				"/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z")

			if rec.Code != tt.want {
				t.Fatalf("status = %d, want %d", rec.Code, tt.want)
			}
			if strings.Contains(rec.Body.String(), "cluster0.internal") {
				t.Error("an internal host name reached the caller")
			}
		})
	}
}
