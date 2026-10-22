package web

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

type fakeArticles struct {
	page       domain.ArticlePage
	article    *domain.Article
	err        error
	lastFilter domain.ArticleFilter
	lastID     string
}

var _ Articles = (*fakeArticles)(nil)

func (f *fakeArticles) List(_ context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error) {
	f.lastFilter = filter
	return f.page, f.err
}

func (f *fakeArticles) Get(_ context.Context, id string) (*domain.Article, error) {
	f.lastID = id
	if f.err != nil {
		return nil, f.err
	}
	return f.article, nil
}

type fakeEvents struct {
	batches [][]domain.ReadEventInput
	err     error
}

type staticTopics []classifier.Topic

func (topics staticTopics) Topics() []classifier.Topic {
	return append([]classifier.Topic(nil), topics...)
}

var _ ReadEvents = (*fakeEvents)(nil)

func (f *fakeEvents) Record(_ context.Context, inputs []domain.ReadEventInput) (int64, error) {
	f.batches = append(f.batches, inputs)
	if f.err != nil {
		return 0, f.err
	}
	return int64(len(inputs)), nil
}

func (f *fakeEvents) all() []domain.ReadEventInput {
	var out []domain.ReadEventInput
	for _, b := range f.batches {
		out = append(out, b...)
	}
	return out
}

const (
	articleOneID = "0198f3d2-3333-7000-8000-000000000001"
	articleTwoID = "0198f3d2-3333-7000-8000-000000000002"
)

func sampleArticles() []domain.Article {
	published := time.Date(2026, 8, 23, 9, 0, 0, 0, time.UTC)
	return []domain.Article{
		{
			ID:          articleOneID,
			SourceName:  "The Hindu — Bengaluru",
			URL:         "https://www.thehindu.com/a-story/article1.ece",
			Title:       "Metro line opens",
			Summary:     "The new line runs from Whitefield.",
			PublishedAt: published,
		},
		{
			ID:          articleTwoID,
			SourceName:  "The Register",
			URL:         "https://www.theregister.com/a-story/",
			Title:       "Chip shortage eases",
			Summary:     "Foundries report improving yields.",
			PublishedAt: published.Add(-time.Hour),
		},
	}
}

func newSite(t *testing.T, articles Articles, events ReadEvents) http.Handler {
	t.Helper()
	h, err := New(articles, events, 30, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return h.Routes()
}

func get(t *testing.T, site http.Handler, target string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	site.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, target, nil))
	return rec
}

func postEvents(t *testing.T, site http.Handler, body string, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/read-events", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	site.ServeHTTP(rec, req)
	return rec
}

func TestFeedRendersStoredArticles(t *testing.T) {
	articles := &fakeArticles{page: domain.ArticlePage{
		Items:      sampleArticles(),
		Limit:      30,
		HasMore:    true,
		NextCursor: "abc",
	}}
	rec := get(t, newSite(t, articles, &fakeEvents{}), "/")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	body := rec.Body.String()
	for _, want := range []string{
		"Metro line opens",
		"The new line runs from Whitefield.",
		"The Hindu — Bengaluru",
		`href="/articles/` + articleOneID + `?pos=0"`,
		`data-position="1"`,
		"cursor=abc",
		"from=2",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("feed does not contain %q", want)
		}
	}
}

// Feed position has to survive paging, or every page looks like the first and
// the position-bias correction a ranker needs is built on a lie.
func TestFeedCarriesPositionAcrossPages(t *testing.T) {
	articles := &fakeArticles{page: domain.ArticlePage{Items: sampleArticles(), Limit: 30}}
	rec := get(t, newSite(t, articles, &fakeEvents{}), "/?from=30")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if body := rec.Body.String(); !strings.Contains(body, `data-position="30"`) {
		t.Error("second page did not start at position 30")
	}
}

func TestFeedFiltersAndPaginatesByTopicUsingCachedMetadata(t *testing.T) {
	items := sampleArticles()
	items[0].ClassificationStatus = domain.ClassificationStatusClassified
	items[0].Topic = "politics"
	articles := &fakeArticles{page: domain.ArticlePage{Items: items[:1], Limit: 30, HasMore: true, NextCursor: "abc"}}
	h, err := New(articles, &fakeEvents{}, 30, slog.New(slog.DiscardHandler), staticTopics{{ID: "politics", Label: "Politics"}, {ID: "unsorted", Label: "Unsorted"}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	rec := get(t, h.Routes(), "/?topic=politics")
	if articles.lastFilter.Topic != "politics" || !strings.Contains(rec.Body.String(), "Politics") || !strings.Contains(rec.Body.String(), "topic=politics") {
		t.Fatalf("topic feed = filter:%+v body:%s", articles.lastFilter, rec.Body.String())
	}
}

func TestFeedRendersUnsortedBadge(t *testing.T) {
	items := sampleArticles()
	items[0].ClassificationStatus = domain.ClassificationStatusUnsorted
	items[0].Topic = "unsorted"
	rec := get(t, newSite(t, &fakeArticles{page: domain.ArticlePage{Items: items[:1], Limit: 30}}, &fakeEvents{}), "/?topic=unsorted")
	if !strings.Contains(rec.Body.String(), "Unsorted") {
		t.Error("feed does not render the unsorted classification badge")
	}
}

func TestFeedRejectsAForgedPageReference(t *testing.T) {
	site := newSite(t, &fakeArticles{}, &fakeEvents{})

	for _, target := range []string{"/?from=-5", "/?from=nonsense", "/?cursor=not-a-cursor"} {
		if rec := get(t, site, target); rec.Code != http.StatusBadRequest {
			t.Errorf("GET %s: status = %d, want 400", target, rec.Code)
		}
	}
}

func TestArticlePageRendersAndRecordsTheClick(t *testing.T) {
	items := sampleArticles()
	events := &fakeEvents{}
	site := newSite(t, &fakeArticles{article: &items[0]}, events)

	rec := get(t, site, "/articles/"+articleOneID+"?pos=7")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "Metro line opens") {
		t.Error("article page does not contain the title")
	}

	recorded := events.all()
	if len(recorded) != 1 {
		t.Fatalf("recorded %d events, want 1", len(recorded))
	}
	if recorded[0].Kind != domain.ReadEventClick || recorded[0].Position != 7 {
		t.Errorf("recorded %+v, want a click at position 7", recorded[0])
	}
}

// A link that arrived from outside the feed has no position, and recording it
// as zero would claim it was the top story.
func TestArticlePageRecordsAnUnknownPositionForADirectVisit(t *testing.T) {
	items := sampleArticles()
	events := &fakeEvents{}
	site := newSite(t, &fakeArticles{article: &items[0]}, events)

	if rec := get(t, site, "/articles/"+articleOneID); rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := events.all()[0].Position; got != domain.PositionUnknown {
		t.Errorf("position = %d, want %d", got, domain.PositionUnknown)
	}
}

// Ground rule 9 applied to the reader: telemetry is not allowed to be the
// reason a page fails.
func TestArticlePageSurvivesTelemetryFailure(t *testing.T) {
	items := sampleArticles()
	site := newSite(t, &fakeArticles{article: &items[0]}, &fakeEvents{err: errors.New("mongo is down")})

	rec := get(t, site, "/articles/"+articleOneID+"?pos=1")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "Metro line opens") {
		t.Error("article page did not render")
	}
}

func TestArticlePageMapsServiceErrors(t *testing.T) {
	cases := map[string]struct {
		err  error
		want int
	}{
		"a missing article":  {service.ErrNotFound, http.StatusNotFound},
		"a malformed id":     {domain.ErrValidation, http.StatusBadRequest},
		"a cancelled lookup": {context.Canceled, http.StatusServiceUnavailable},
		"anything else":      {errors.New("boom"), http.StatusInternalServerError},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			site := newSite(t, &fakeArticles{err: tc.err}, &fakeEvents{})
			rec := get(t, site, "/articles/"+articleOneID)
			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d", rec.Code, tc.want)
			}
			if body := rec.Body.String(); strings.Contains(body, "boom") || strings.Contains(body, "mongo") {
				t.Error("the page quoted internal error detail back to the reader")
			}
		})
	}
}

// Scraped third-party text is the input here, so contextual escaping is the
// control that matters most on these pages.
func TestArticleTextIsEscaped(t *testing.T) {
	hostile := domain.Article{
		ID:          articleOneID,
		SourceName:  `<img src=x onerror="alert(1)">`,
		URL:         "https://example.com/a",
		Title:       `<script>alert("xss")</script>`,
		Summary:     `" onmouseover="alert(1)`,
		PublishedAt: time.Now().Add(-time.Hour),
	}

	site := newSite(t, &fakeArticles{
		page:    domain.ArticlePage{Items: []domain.Article{hostile}, Limit: 30},
		article: &hostile,
	}, &fakeEvents{})

	for _, target := range []string{"/", "/articles/" + articleOneID} {
		body := get(t, site, target).Body.String()
		for _, forbidden := range []string{"<script>alert", "<img src=x", `onerror="alert`} {
			if strings.Contains(body, forbidden) {
				t.Errorf("GET %s: unescaped %q reached the page", target, forbidden)
			}
		}
		if !strings.Contains(body, "&lt;script&gt;") {
			t.Errorf("GET %s: the title was not rendered at all", target)
		}
	}
}

func TestReadEventsAcceptsASameOriginFlush(t *testing.T) {
	events := &fakeEvents{}
	site := newSite(t, &fakeArticles{}, events)

	body := `{"events":[
		{"article_id":"` + articleOneID + `","kind":"impression","position":0,"dwell_ms":0,"age_ms":1200},
		{"article_id":"` + articleTwoID + `","kind":"dwell","position":1,"dwell_ms":5000,"age_ms":300}
	]}`
	rec := postEvents(t, site, body, map[string]string{"Sec-Fetch-Site": "same-origin"})

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204: %s", rec.Code, rec.Body.String())
	}

	recorded := events.all()
	if len(recorded) != 2 {
		t.Fatalf("recorded %d events, want 2", len(recorded))
	}
	if recorded[0].Kind != domain.ReadEventImpression {
		t.Errorf("first event kind = %q, want impression", recorded[0].Kind)
	}
	if recorded[1].Dwell != 5*time.Second || recorded[1].Age != 300*time.Millisecond {
		t.Errorf("second event = %+v, want a 5s dwell reported 300ms ago", recorded[1])
	}
}

func TestReadEventsRejectsAnythingButASameOriginPost(t *testing.T) {
	body := `{"events":[{"article_id":"` + articleOneID + `","kind":"click","position":0,"dwell_ms":0,"age_ms":0}]}`

	cases := map[string]map[string]string{
		"a cross-site post":       {"Sec-Fetch-Site": "cross-site"},
		"a same-site post":        {"Sec-Fetch-Site": "same-site"},
		"a foreign origin":        {"Origin": "https://evil.example"},
		"no origin signal at all": {},
	}

	for name, headers := range cases {
		t.Run(name, func(t *testing.T) {
			events := &fakeEvents{}
			rec := postEvents(t, newSite(t, &fakeArticles{}, events), body, headers)
			if rec.Code != http.StatusForbidden {
				t.Fatalf("status = %d, want 403", rec.Code)
			}
			if len(events.batches) != 0 {
				t.Error("a rejected request still reached the service")
			}
		})
	}
}

func TestReadEventsAcceptsAMatchingOriginWhenTheFetchMetadataIsAbsent(t *testing.T) {
	events := &fakeEvents{}
	site := newSite(t, &fakeArticles{}, events)

	req := httptest.NewRequest(http.MethodPost, "/read-events",
		strings.NewReader(`{"events":[{"article_id":"`+articleOneID+`","kind":"click","position":0,"dwell_ms":0,"age_ms":0}]}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Origin", "http://"+req.Host)

	rec := httptest.NewRecorder()
	site.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204: %s", rec.Code, rec.Body.String())
	}
}

func TestReadEventsRejectsAMalformedFlush(t *testing.T) {
	site := newSite(t, &fakeArticles{}, &fakeEvents{})
	sameOrigin := map[string]string{"Sec-Fetch-Site": "same-origin"}

	cases := map[string]struct {
		body    string
		headers map[string]string
		want    int
	}{
		"not json":       {`{"events":`, sameOrigin, http.StatusBadRequest},
		"unknown fields": {`{"events":[],"admin":true}`, sameOrigin, http.StatusBadRequest},
		"wrong media type": {`{"events":[]}`, map[string]string{
			"Sec-Fetch-Site": "same-origin",
			"Content-Type":   "text/plain",
		}, http.StatusUnsupportedMediaType},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if rec := postEvents(t, site, tc.body, tc.headers); rec.Code != tc.want {
				t.Fatalf("status = %d, want %d", rec.Code, tc.want)
			}
		})
	}
}

func TestReadEventsReportsARejectedEventAsABadRequest(t *testing.T) {
	site := newSite(t, &fakeArticles{}, &fakeEvents{err: domain.ErrValidation})

	body := `{"events":[{"article_id":"nope","kind":"click","position":0,"dwell_ms":0,"age_ms":0}]}`
	rec := postEvents(t, site, body, map[string]string{"Sec-Fetch-Site": "same-origin"})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestReadEventsReportsAStorageFailureAsUnavailable(t *testing.T) {
	site := newSite(t, &fakeArticles{}, &fakeEvents{err: errors.New("mongo is down")})

	body := `{"events":[{"article_id":"` + articleOneID + `","kind":"click","position":0,"dwell_ms":0,"age_ms":0}]}`
	rec := postEvents(t, site, body, map[string]string{"Sec-Fetch-Site": "same-origin"})
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "mongo") {
		t.Error("the response quoted internal error detail")
	}
}

// The page must work with JavaScript off; telemetry is the only thing lost.
// That means no inline script, and the article text present in the response
// rather than fetched afterwards.
func TestPagesWorkWithoutJavaScript(t *testing.T) {
	articles := &fakeArticles{page: domain.ArticlePage{Items: sampleArticles(), Limit: 30}}
	body := get(t, newSite(t, articles, &fakeEvents{}), "/").Body.String()

	if strings.Contains(body, "<script>") {
		t.Error("the page carries an inline script")
	}
	if !strings.Contains(body, `<script src="/static/telemetry.js" defer></script>`) {
		t.Error("telemetry is not loaded as an external, deferred script")
	}
	if !strings.Contains(body, "Metro line opens") || !strings.Contains(body, "Chip shortage eases") {
		t.Error("article text is not in the served HTML")
	}
}

func TestStaticAssetsAreServedFromTheBinary(t *testing.T) {
	site := newSite(t, &fakeArticles{}, &fakeEvents{})

	for _, path := range []string{"/static/app.css", "/static/telemetry.js"} {
		rec := get(t, site, path)
		if rec.Code != http.StatusOK {
			t.Errorf("GET %s: status = %d, want 200", path, rec.Code)
		}
		if rec.Body.Len() == 0 {
			t.Errorf("GET %s: empty body", path)
		}
	}
}

func TestUnknownPathRendersAnHTMLNotFound(t *testing.T) {
	rec := get(t, newSite(t, &fakeArticles{}, &fakeEvents{}), "/nothing-here")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/html") {
		t.Errorf("Content-Type = %q, want text/html", ct)
	}
}

func TestPagesCarryTheirSecurityHeaders(t *testing.T) {
	articles := &fakeArticles{page: domain.ArticlePage{Items: sampleArticles(), Limit: 30}}
	head := get(t, newSite(t, articles, &fakeEvents{}), "/").Header()

	if got := head.Get("X-Content-Type-Options"); got != "nosniff" {
		t.Errorf("X-Content-Type-Options = %q", got)
	}
	csp := head.Get("Content-Security-Policy")
	for _, want := range []string{"default-src 'none'", "script-src 'self'", "frame-ancestors 'none'"} {
		if !strings.Contains(csp, want) {
			t.Errorf("CSP %q is missing %q", csp, want)
		}
	}
}

func TestExcerptCutsAtAWordBoundary(t *testing.T) {
	short := "A summary that fits."
	if got := excerpt(short); got != short {
		t.Errorf("excerpt(short) = %q, want it unchanged", got)
	}

	long := strings.Repeat("word ", 100)
	got := excerpt(long)
	if !strings.HasSuffix(got, "…") {
		t.Errorf("excerpt(long) = %q, want an ellipsis", got)
	}
	if len([]rune(got)) > excerptRunes+1 {
		t.Errorf("excerpt(long) is %d runes, want at most %d", len([]rune(got)), excerptRunes+1)
	}
	if strings.HasSuffix(strings.TrimSuffix(got, "…"), " ") {
		t.Errorf("excerpt(long) = %q, want no trailing space before the ellipsis", got)
	}
}

func TestSinceRendersAnAge(t *testing.T) {
	now := time.Date(2026, 8, 23, 12, 0, 0, 0, time.UTC)

	cases := map[time.Duration]string{
		30 * time.Second:    "just now",
		20 * time.Minute:    "20m ago",
		5 * time.Hour:       "5h ago",
		50 * time.Hour:      "2d ago",
		30 * 24 * time.Hour: "24 Jul 2026",
	}
	for age, want := range cases {
		if got := since(now.Add(-age), now); got != want {
			t.Errorf("since(-%s) = %q, want %q", age, got, want)
		}
	}
}

func TestNewRefusesAnUnusableConfiguration(t *testing.T) {
	if _, err := New(nil, &fakeEvents{}, 30, nil); err == nil {
		t.Error("New accepted a nil article reader")
	}
	if _, err := New(&fakeArticles{}, &fakeEvents{}, 0, nil); err == nil {
		t.Error("New accepted a page size of zero")
	}
}
