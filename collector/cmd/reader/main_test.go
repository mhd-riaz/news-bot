package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/handler"
	"github.com/riaz/newscollector/internal/recommendation"
	"github.com/riaz/newscollector/internal/repository"
	"github.com/riaz/newscollector/internal/service"
)

const readID = "0198f3d2-3333-7000-8000-000000000001"

// Unimplemented writes panic: route tests must never reach a database write method.
type readerRepository struct{ repository.ArticleRepository }

func (readerRepository) GetByID(context.Context, string) (*domain.Article, error) {
	return &domain.Article{ID: readID, Title: "A real read-only route"}, nil
}

func (readerRepository) List(context.Context, domain.ArticleFilter) (domain.ArticlePage, error) {
	return domain.ArticlePage{Items: []domain.Article{{ID: readID}}, Limit: 30}, nil
}

func (readerRepository) GetByIDs(context.Context, []string) ([]domain.Article, error) {
	return []domain.Article{{ID: readID}}, nil
}

type readerPing struct{ err error }

func (p readerPing) Ping(context.Context) error { return p.err }

func testReader(t *testing.T, auth *handler.Authenticator, ping error, modelStatus int) http.Handler {
	t.Helper()
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(modelStatus)
		_, _ = io.WriteString(w, `{"snapshot_id":"test","articles":1,"topics":[{"id":"0"}]}`)
	}))
	t.Cleanup(model.Close)
	repo := readerRepository{}
	ranker, err := recommendation.New(model.URL, "", repo)
	if err != nil {
		t.Fatal(err)
	}
	pages := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "story reader")
	})
	return readerRoutes(pages, ranker, service.NewArticleService(repo), auth,
		readerPing{ping}, slog.New(slog.DiscardHandler))
}

func TestReaderExposesReadsButNoMutationEndpoints(t *testing.T) {
	t.Parallel()
	reader := testReader(t, nil, nil, 200)
	for path, want := range map[string]int{
		"/health/live": 200, "/health/ready": 200,
		"/api/v1/recommendations/meta": 200, "/stories": 200,
		"/api/v1/articles": 200, "/api/v1/articles/" + readID: 200,
		"/": 307,
	} {
		recorder := httptest.NewRecorder()
		reader.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != want {
			t.Errorf("%s: status %d, want %d", path, recorder.Code, want)
		}
	}
	for _, action := range []struct{ method, path string }{
		{"DELETE", "/api/v1/articles"}, {"POST", "/api/v1/sources"},
		{"PATCH", "/api/v1/sources/" + readID}, {"POST", "/read-events"},
	} {
		recorder := httptest.NewRecorder()
		reader.ServeHTTP(recorder, httptest.NewRequest(action.method, action.path, strings.NewReader(`{}`)))
		if recorder.Code != 404 && recorder.Code != 405 {
			t.Errorf("mutation exposed: %s %s = %d", action.method, action.path, recorder.Code)
		}
	}
}

func TestReaderPreservesAuthAndReportsDependencyOutages(t *testing.T) {
	t.Parallel()
	auth := handler.NewAuthenticator(handler.AuthCredentials{
		APIKeyHeader: "X-API-Key", APIKeys: []string{strings.Repeat("unit", 8)},
	})
	reader := testReader(t, auth, nil, 200)
	recorder := httptest.NewRecorder()
	reader.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/stories", nil))
	if recorder.Code != 401 {
		t.Fatal("reader authentication bypassed")
	}
	for name, sample := range map[string]struct {
		mongo error
		model int
	}{"database": {errors.New("stub outage"), 200}, "model": {nil, 503}} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			reader := testReader(t, nil, sample.mongo, sample.model)
			recorder := httptest.NewRecorder()
			reader.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/health/ready", nil))
			if recorder.Code != 503 {
				t.Errorf("outage status = %d", recorder.Code)
			}
		})
	}
}
