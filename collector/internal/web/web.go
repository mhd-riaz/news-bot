// Package web serves the reader-facing pages.
//
// Deliberately small: html/template, hand-written CSS, and no build step of any
// kind — no npm, no bundler, no Node at runtime. Everything it serves is
// embedded in the binary, so a deployment stays one image with no asset
// pipeline behind it.
//
// Contextual escaping is what stands between scraped third-party text and
// stored XSS, so every field reaches the page through a template action and
// nothing here builds HTML by concatenation.
package web

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"log/slog"
	"mime"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/service"
)

//go:embed templates/*.html
var templateFS embed.FS

//go:embed static
var staticFS embed.FS

// pageNames are the page templates, each rendered inside layout.html.
var pageNames = []string{"feed.html", "article.html", "message.html"}

// maxTelemetryBytes caps a telemetry flush. A full batch of small events is a
// few tens of kilobytes; this refuses a body that could not be one.
const maxTelemetryBytes = 128 << 10

// excerptRunes is how much of a summary a card shows before it is cut at a word
// boundary. Long enough to say what the story is, short enough that the card
// stays a card.
const excerptRunes = 200

// Articles is the slice of article access the pages need.
type Articles interface {
	List(ctx context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error)
	Get(ctx context.Context, id string) (*domain.Article, error)
}

// ReadEvents records reader telemetry. A nil ReadEvents serves the pages with
// telemetry switched off rather than failing.
type ReadEvents interface {
	Record(ctx context.Context, inputs []domain.ReadEventInput) (int64, error)
}

// Handler serves the pages and the one endpoint they write to.
type Handler struct {
	articles Articles
	events   ReadEvents
	pages    map[string]*template.Template
	logger   *slog.Logger
	pageSize int
	topics   classifier.TopicSource
}

// New parses the embedded templates and wires the handler. Parsing at startup
// means a broken template fails the deployment rather than the first reader.
func New(articles Articles, events ReadEvents, pageSize int, logger *slog.Logger, topicSources ...classifier.TopicSource) (*Handler, error) {
	if articles == nil {
		return nil, errors.New("web: articles must not be nil")
	}
	if pageSize < 1 {
		return nil, fmt.Errorf("web: page size must be greater than zero, got %d", pageSize)
	}
	if logger == nil {
		logger = slog.New(slog.DiscardHandler)
	}

	pages := make(map[string]*template.Template, len(pageNames))
	for _, name := range pageNames {
		t, err := template.New("layout.html").Funcs(funcs).ParseFS(templateFS, "templates/layout.html", "templates/"+name)
		if err != nil {
			return nil, fmt.Errorf("web: parse %s: %w", name, err)
		}
		pages[name] = t
	}
	stories, err := template.New("stories.html").ParseFS(templateFS, "templates/stories.html")
	if err != nil {
		return nil, fmt.Errorf("web: parse stories.html: %w", err)
	}
	pages["stories.html"] = stories

	var topics classifier.TopicSource
	if len(topicSources) > 0 {
		topics = topicSources[0]
	}
	return &Handler{articles: articles, events: events, pages: pages, logger: logger, pageSize: pageSize, topics: topics}, nil
}

// Routes returns the page routes. The caller decides what guards them.
func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", h.feed)
	mux.HandleFunc("GET /archive", h.feed)
	mux.HandleFunc("GET /articles/{id}", h.article)
	mux.HandleFunc("GET /stories", func(w http.ResponseWriter, r *http.Request) {
		h.render(w, r, http.StatusOK, "stories.html", messageView{Title: "Afterline"})
	})
	mux.HandleFunc("POST /read-events", h.readEvents)
	mux.Handle("GET /static/", http.FileServerFS(staticFS))
	mux.HandleFunc("/", h.notFound)
	return mux
}

// card is one article as the feed renders it.
type card struct {
	Article    domain.Article
	Position   int
	Href       string
	TopicLabel string
}

type feedView struct {
	Title         string
	Cards         []card
	NextHref      string
	Topics        []classifier.Topic
	SelectedTopic string
}

type articleView struct {
	Title      string
	Article    *domain.Article
	Position   int
	TopicLabel string
}

type messageView struct {
	Title   string
	Heading string
	Message string
}

// feed renders one page of the newest articles.
func (h *Handler) feed(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()

	// from is the feed position of the first card on this page. Cursor paging
	// has no offset of its own, so the position a reader actually saw has to be
	// carried forward from page to page or every page looks like the first.
	from, err := parseFeedStart(q.Get("from"))
	if err != nil {
		h.renderMessage(w, r, http.StatusBadRequest, "Bad link", "That is not a page reference this feed produced.")
		return
	}

	filter := domain.ArticleFilter{Limit: h.pageSize, Sort: domain.SortPublishedAt, Topic: q.Get("topic")}
	if raw := q.Get("cursor"); raw != "" {
		cursor, err := domain.ParseArticleCursor(raw)
		if err != nil {
			h.renderMessage(w, r, http.StatusBadRequest, "Bad link", "That is not a page reference this feed produced.")
			return
		}
		filter.Cursor = cursor
	}

	page, err := h.articles.List(r.Context(), filter)
	if err != nil {
		h.renderServiceError(w, r, err, "list articles")
		return
	}

	cards := make([]card, 0, len(page.Items))
	for i := range page.Items {
		position := from + i
		cards = append(cards, card{
			Article:    page.Items[i],
			Position:   position,
			Href:       articleHref(page.Items[i].ID, position),
			TopicLabel: h.topicLabel(page.Items[i]),
		})
	}

	view := feedView{Title: "Latest", Cards: cards, SelectedTopic: filter.Topic}
	if h.topics != nil {
		view.Topics = h.topics.Topics()
	}
	if page.HasMore && from+len(cards) <= domain.MaxFeedPosition {
		query := url.Values{
			"cursor": {page.NextCursor},
			"from":   {strconv.Itoa(from + len(cards))},
		}
		if filter.Topic != "" {
			query.Set("topic", filter.Topic)
		}
		view.NextHref = r.URL.Path + "?" + query.Encode()
	}
	h.render(w, r, http.StatusOK, "feed.html", view)
}

// article renders one article and records the click that opened it.
func (h *Handler) article(w http.ResponseWriter, r *http.Request) {
	article, err := h.articles.Get(r.Context(), r.PathValue("id"))
	if err != nil {
		h.renderServiceError(w, r, err, "get article")
		return
	}

	position, err := parsePosition(r.URL.Query().Get("pos"))
	if err != nil {
		// A malformed position is not worth refusing the article over; it just
		// means this read cannot be attributed to a slot in the feed.
		position = domain.PositionUnknown
	}
	h.recordClick(r, article.ID, position)

	h.render(w, r, http.StatusOK, "article.html", articleView{
		Title:      article.Title,
		Article:    article,
		Position:   position,
		TopicLabel: h.topicLabel(*article),
	})
}

func (h *Handler) topicLabel(article domain.Article) string {
	if article.ClassificationStatus == domain.ClassificationStatusUnsorted {
		return "Unsorted"
	}
	if article.ClassificationStatus != domain.ClassificationStatusClassified {
		return ""
	}
	if h.topics != nil {
		for _, topic := range h.topics.Topics() {
			if topic.ID == article.Topic {
				return topic.Label
			}
		}
	}
	return article.Topic
}

// telemetryPayload is one flush from the page.
//
// Age, not a timestamp, crosses the wire: events are queued in the page and
// sent when it is hidden, and deriving the instant from this server's clock
// minus a reported elapsed time keeps a wrong or hostile client clock out of
// the data entirely.
type telemetryPayload struct {
	Events []struct {
		ArticleID string `json:"article_id"`
		Kind      string `json:"kind"`
		Position  int    `json:"position"`
		DwellMs   int64  `json:"dwell_ms"`
		AgeMs     int64  `json:"age_ms"`
	} `json:"events"`
}

// readEvents accepts a telemetry flush. It is the only state-changing request a
// browser makes, so it is also the only one that needs cross-origin defence.
func (h *Handler) readEvents(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		http.Error(w, "cross-origin requests are not accepted here", http.StatusForbidden)
		return
	}
	if h.events == nil {
		http.Error(w, "telemetry is not enabled", http.StatusServiceUnavailable)
		return
	}
	if !isJSON(r.Header.Get("Content-Type")) {
		http.Error(w, "expected application/json", http.StatusUnsupportedMediaType)
		return
	}

	var payload telemetryPayload
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxTelemetryBytes))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&payload); err != nil {
		http.Error(w, "malformed telemetry payload", http.StatusBadRequest)
		return
	}

	inputs := make([]domain.ReadEventInput, 0, len(payload.Events))
	for _, e := range payload.Events {
		inputs = append(inputs, domain.ReadEventInput{
			ArticleID: e.ArticleID,
			Kind:      domain.ReadEventKind(e.Kind),
			Position:  e.Position,
			Dwell:     time.Duration(e.DwellMs) * time.Millisecond,
			Age:       time.Duration(e.AgeMs) * time.Millisecond,
		})
	}

	if _, err := h.events.Record(r.Context(), inputs); err != nil {
		if errors.Is(err, domain.ErrValidation) {
			// Only this application's own page posts here, so an invalid event
			// is this system's bug and is worth a log line, not silence.
			h.logger.WarnContext(r.Context(), "telemetry rejected", "error", err)
			http.Error(w, "invalid telemetry payload", http.StatusBadRequest)
			return
		}
		h.logger.ErrorContext(r.Context(), "telemetry not stored", "error", err)
		http.Error(w, "telemetry could not be stored", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// recordClick logs the click that opened an article page. Best-effort by
// design: telemetry must never be the reason a reader cannot read.
func (h *Handler) recordClick(r *http.Request, articleID string, position int) {
	if h.events == nil {
		return
	}
	in := domain.ReadEventInput{ArticleID: articleID, Kind: domain.ReadEventClick, Position: position}
	if _, err := h.events.Record(r.Context(), []domain.ReadEventInput{in}); err != nil {
		h.logger.WarnContext(r.Context(), "click not recorded", "article_id", articleID, "error", err)
	}
}

func (h *Handler) notFound(w http.ResponseWriter, r *http.Request) {
	h.renderMessage(w, r, http.StatusNotFound, "Not found", "There is nothing at this address.")
}

// renderServiceError maps a service failure onto a page without quoting any
// internal detail back to the reader.
func (h *Handler) renderServiceError(w http.ResponseWriter, r *http.Request, err error, action string) {
	switch {
	case errors.Is(err, service.ErrNotFound):
		h.renderMessage(w, r, http.StatusNotFound, "Not found", "That article is not here. It may have been expired by the retention sweep.")
	case errors.Is(err, domain.ErrValidation):
		h.renderMessage(w, r, http.StatusBadRequest, "Bad link", "That is not an address this site produces.")
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		h.logger.ErrorContext(r.Context(), action+" failed", "error", err)
		h.renderMessage(w, r, http.StatusServiceUnavailable, "Unavailable", "The archive is not reachable right now.")
	default:
		h.logger.ErrorContext(r.Context(), action+" failed", "error", err)
		h.renderMessage(w, r, http.StatusInternalServerError, "Error", "Something went wrong.")
	}
}

func (h *Handler) renderMessage(w http.ResponseWriter, r *http.Request, status int, heading, message string) {
	h.render(w, r, status, "message.html", messageView{Title: heading, Heading: heading, Message: message})
}

// render writes a page. The template is executed into a buffer first, so a
// failure halfway through cannot emit a half-written page under a sent 200.
func (h *Handler) render(w http.ResponseWriter, r *http.Request, status int, page string, data any) {
	var buf bytes.Buffer
	entry := "layout.html"
	if page == "stories.html" {
		entry = page
	}
	if err := h.pages[page].ExecuteTemplate(&buf, entry, data); err != nil {
		h.logger.ErrorContext(r.Context(), "template render failed", "page", page, "error", err)
		http.Error(w, "internal server error", http.StatusInternalServerError)
		return
	}

	head := w.Header()
	head.Set("Content-Type", "text/html; charset=utf-8")
	head.Set("X-Content-Type-Options", "nosniff")
	head.Set("Referrer-Policy", "no-referrer")
	// Everything is same-origin and there is no inline script or style, so the
	// policy can be absolute rather than negotiated. It is the second line of
	// defence behind html/template's escaping, not a replacement for it.
	policy :=
		"default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; " +
			"connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
	if page == "stories.html" {
		// Images load in the browser, not through a server-side URL fetch/proxy.
		policy = strings.Replace(policy, "img-src 'self' data:", "img-src 'self' https:", 1)
	}
	head.Set("Content-Security-Policy", policy)
	w.WriteHeader(status)
	_, _ = buf.WriteTo(w)
}

// sameOrigin reports whether a state-changing request came from this site.
//
// Sec-Fetch-Site is preferred because the browser computes it and a page cannot
// forge it. Origin is the fallback for a browser that does not send it, and a
// request carrying neither signal is refused: this endpoint has exactly one
// legitimate caller, and it is a browser.
func sameOrigin(r *http.Request) bool {
	switch site := r.Header.Get("Sec-Fetch-Site"); site {
	case "same-origin":
		return true
	case "":
		// Fall through to the Origin check below.
	default:
		return false
	}

	origin := r.Header.Get("Origin")
	if origin == "" {
		return false
	}
	u, err := url.Parse(origin)
	return err == nil && u.Host != "" && strings.EqualFold(u.Host, r.Host)
}

func isJSON(header string) bool {
	mediaType, _, err := mime.ParseMediaType(header)
	return err == nil && mediaType == "application/json"
}

// parsePosition reads a feed position. An absent value is "not from a feed",
// which is a different fact from position zero.
func parsePosition(raw string) (int, error) {
	if raw == "" {
		return domain.PositionUnknown, nil
	}
	return parseFeedStart(raw)
}

// parseFeedStart reads the offset of a feed page. Absent means the first page,
// which really is position zero.
func parseFeedStart(raw string) (int, error) {
	if raw == "" {
		return 0, nil
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 0 || n > domain.MaxFeedPosition {
		return domain.PositionUnknown, fmt.Errorf("web: position %q is out of range", raw)
	}
	return n, nil
}

func articleHref(id string, position int) string {
	return "/articles/" + url.PathEscape(id) + "?" + url.Values{"pos": {strconv.Itoa(position)}}.Encode()
}

var funcs = template.FuncMap{
	"excerpt": excerpt,
	"since":   func(t time.Time) string { return since(t, time.Now()) },
	"iso":     func(t time.Time) string { return t.UTC().Format(time.RFC3339) },
}

// excerpt cuts s at a word boundary. Truncating here rather than in CSS means
// the bytes are never sent, so a 20 KB summary does not become 20 KB of a card
// the reader can only see two lines of.
func excerpt(s string) string {
	runes := []rune(s)
	if len(runes) <= excerptRunes {
		return s
	}

	cut := string(runes[:excerptRunes])
	if space := strings.LastIndexByte(cut, ' '); space > 0 {
		cut = cut[:space]
	}
	return strings.TrimRight(cut, " ,;:-") + "…"
}

// since renders an age the way a newspaper would date a story.
func since(t, now time.Time) string {
	d := now.Sub(t)
	switch {
	case d < time.Minute:
		return "just now"
	case d < time.Hour:
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh ago", int(d.Hours()))
	case d < 7*24*time.Hour:
		return fmt.Sprintf("%dd ago", int(d.Hours()/24))
	default:
		return t.UTC().Format("2 Jan 2006")
	}
}
