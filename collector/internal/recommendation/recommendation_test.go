package recommendation

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/riaz/newscollector/internal/domain"
)

const (
	oneID = "0198f3d2-3333-7000-8000-000000000001"
	twoID = "0198f3d2-3333-7000-8000-000000000002"
)

type articleStub struct {
	rows []domain.Article
	err  error
	ids  []string
}

func (s *articleStub) GetByIDs(_ context.Context, ids []string) ([]domain.Article, error) {
	s.ids = append([]string{}, ids...)
	return s.rows, s.err
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func stubService(t *testing.T, status int, body string, articles *articleStub) *Service {
	t.Helper()
	service, err := New("http://ranker.test", "unit-only-key", articles)
	if err != nil {
		t.Fatal(err)
	}
	service.client.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Header.Get("X-Recommender-Key") != "unit-only-key" {
			t.Error("missing internal service key")
		}
		return &http.Response{
			StatusCode: status, Body: io.NopCloser(strings.NewReader(body)),
			Header: http.Header{"Content-Type": {"application/json"}},
		}, nil
	})
	return service
}

func TestHydratesRankingInOneBatchAndPreservesOrder(t *testing.T) {
	t.Parallel()
	repo := &articleStub{rows: []domain.Article{{ID: twoID}, {ID: oneID}}}
	service := stubService(t, 200, `{"snapshot_id":"test","method":"neural","items":[{"id":"`+oneID+`","score":0.8},{"id":"`+twoID+`","score":0.7}]}`, repo)
	result, err := service.Recommend(t.Context(), Request{SeedID: twoID, Limit: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(repo.ids) != 2 || result.Articles[0].Article.ID != oneID || result.Articles[1].Article.ID != twoID {
		t.Fatalf("wrong batch or order: %+v", result)
	}
}

func TestUnavailableArticlesAreExplicit(t *testing.T) {
	t.Parallel()
	repo := &articleStub{rows: []domain.Article{{ID: oneID}}}
	service := stubService(t, 200, `{"snapshot_id":"test","items":[{"id":"`+oneID+`"},{"id":"`+twoID+`"}]}`, repo)
	result, err := service.Recommend(t.Context(), Request{})
	if err != nil || len(result.UnavailableIDs) != 1 || result.UnavailableIDs[0] != twoID {
		t.Fatalf("missing articles not exposed: %+v, %v", result, err)
	}
	repo.rows = nil
	if _, err := service.Recommend(t.Context(), Request{}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("empty hydration error = %v", err)
	}
}

func TestRecommendationRequestValidation(t *testing.T) {
	t.Parallel()
	for name, request := range map[string]Request{
		"limit": {Limit: 31}, "negative limit": {Limit: -1}, "method": {Method: "other"},
		"topic bound": {Topic: "long"}, "invalid seed": {SeedID: "$where"},
		"invalid history":          {Viewed: []string{"invalid"}},
		"large interests":          {Liked: make([]string, 51)},
		"large negative interests": {Disliked: make([]string, 51)},
		"large history":            {Viewed: make([]string, 2001)},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			if !errors.Is(request.Validate(), ErrInvalid) {
				t.Error("invalid request accepted")
			}
		})
	}
	if err := (Request{Liked: []string{oneID}, Viewed: []string{twoID}, Method: "svd", Limit: 30}).Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestHTTPFailuresAndMalformedRanking(t *testing.T) {
	t.Parallel()
	for name, sample := range map[string]struct {
		status int
		body   string
		want   error
	}{
		"bad input":      {400, `{}`, ErrInvalid},
		"not indexed":    {404, `{}`, ErrNotIndexed},
		"outage":         {503, `{}`, ErrUnavailable},
		"non JSON":       {200, `<html>`, ErrUnavailable},
		"trailing JSON":  {200, `{} {}`, ErrUnavailable},
		"empty response": {200, `{}`, ErrUnavailable},
		"invalid ID":     {200, `{"snapshot_id":"test","items":[{"id":"bad"}]}`, ErrUnavailable},
		"duplicate IDs":  {200, `{"snapshot_id":"test","items":[{"id":"` + oneID + `"},{"id":"` + oneID + `"}]}`, ErrUnavailable},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			service := stubService(t, sample.status, sample.body, &articleStub{})
			_, err := service.Recommend(t.Context(), Request{})
			if !errors.Is(err, sample.want) {
				t.Fatalf("got %v, want %v", err, sample.want)
			}
		})
	}
}

func TestDatabaseFailureAndEmptyFeed(t *testing.T) {
	t.Parallel()
	service := stubService(t, 200, `{"snapshot_id":"test","items":[{"id":"`+oneID+`"}]}`, &articleStub{err: errors.New("stub outage")})
	if _, err := service.Recommend(t.Context(), Request{}); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	service = stubService(t, 200, `{"snapshot_id":"test","items":[],"exhausted":true}`, &articleStub{})
	if result, err := service.Recommend(t.Context(), Request{}); err != nil || !result.Exhausted || len(result.Articles) != 0 {
		t.Fatalf("empty result = %+v, %v", result, err)
	}
}

func TestMetadataValidationAndTransportError(t *testing.T) {
	t.Parallel()
	service := stubService(t, 200, `{"snapshot_id":"test","articles":2,"topics":[{"id":"0","label":"science"}]}`, &articleStub{})
	if meta, err := service.Metadata(t.Context()); err != nil || meta.Articles != 2 {
		t.Fatalf("metadata = %+v, %v", meta, err)
	}
	service = stubService(t, 200, `{}`, &articleStub{})
	if _, err := service.Metadata(t.Context()); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	service.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return nil, context.DeadlineExceeded
	})
	if _, err := service.Metadata(t.Context()); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	if _, err := service.Recommend(t.Context(), Request{Limit: 100}); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}

func TestEndpointValidation(t *testing.T) {
	t.Parallel()
	for _, endpoint := range []string{"", "/relative", "file:///tmp/model", "http://u:p@ranker.test", "http://ranker.test?key=x", "http://ranker.test#fragment", "http://["} {
		if _, err := New(endpoint, "", &articleStub{}); err == nil {
			t.Errorf("accepted endpoint %q", endpoint)
		}
	}
	if _, err := New("http://ranker.test", "", nil); err == nil {
		t.Error("accepted missing repository")
	}
}
