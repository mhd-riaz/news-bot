package handler

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/observability"
	"github.com/riaz/newscollector/internal/service"
)

// ArticleManager is the slice of article access this handler needs. Articles
// are written only by the collection pipeline, so the only write in the
// contract is the retention sweep.
type ArticleManager interface {
	List(ctx context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error)
	Get(ctx context.Context, id string) (*domain.Article, error)
	DeleteOlderThan(ctx context.Context, d domain.ArticleDeletion) (int64, error)
}

// Article serves the article query endpoints.
type Article struct {
	articles ArticleManager
	logger   *slog.Logger
}

// NewArticle builds the article handlers.
func NewArticle(articles ArticleManager, logger *slog.Logger) *Article {
	return &Article{articles: articles, logger: logger}
}

// articleResponse is the wire representation of an article.
//
// The deduplication keys — dedup_id, normalized_url and content_hash — are
// internal machinery and are never exposed. Content is empty in a listing,
// where it is projected away, and omitted from the JSON when it is.
type articleResponse struct {
	ID         string `json:"id"`
	SourceID   string `json:"source_id"`
	SourceName string `json:"source_name"`

	URL          string `json:"url"`
	CanonicalURL string `json:"canonical_url,omitempty"`
	ImageURL     string `json:"image_url,omitempty"`

	Title      string   `json:"title"`
	Summary    string   `json:"summary,omitempty"`
	Content    string   `json:"content,omitempty"`
	Authors    []string `json:"authors,omitempty"`
	Categories []string `json:"categories,omitempty"`

	Language string `json:"language"`
	Country  string `json:"country"`
	State    string `json:"state,omitempty"`
	City     string `json:"city,omitempty"`

	PublishedAt time.Time `json:"published_at"`
	CollectedAt time.Time `json:"collected_at"`

	Topic                string   `json:"topic,omitempty"`
	ClassificationStatus string   `json:"classification_status,omitempty"`
	Confidence           *float64 `json:"confidence,omitempty"`
}

func newArticleResponse(a *domain.Article) articleResponse {
	response := articleResponse{
		ID:           a.ID,
		SourceID:     a.SourceID,
		SourceName:   a.SourceName,
		URL:          a.URL,
		CanonicalURL: a.CanonicalURL,
		ImageURL:     a.ImageURL,
		Title:        a.Title,
		Summary:      a.Summary,
		Content:      a.Content,
		Authors:      a.Authors,
		Categories:   a.Categories,
		Language:     a.Language,
		Country:      a.Country,
		State:        a.State,
		City:         a.City,
		PublishedAt:  a.PublishedAt,
		CollectedAt:  a.CollectedAt,
	}
	if a.ClassificationStatus == domain.ClassificationStatusClassified || a.ClassificationStatus == domain.ClassificationStatusUnsorted {
		response.Topic = a.Topic
		response.ClassificationStatus = string(a.ClassificationStatus)
		response.Confidence = &a.Confidence
	}
	return response
}

// articleListResponse is a page plus the token that continues it. There is no
// total: see domain.ArticlePage.
type articleListResponse struct {
	Items      []articleResponse `json:"items"`
	Limit      int               `json:"limit"`
	HasMore    bool              `json:"has_more"`
	NextCursor string            `json:"next_cursor,omitempty"`
}

// articleDeleteResponse reports the size of a sweep. It is returned with 200
// rather than 204 because the count is the only way a caller can tell a sweep
// that expired a month of articles from one that matched nothing.
type articleDeleteResponse struct {
	Deleted int64 `json:"deleted"`
}

// List returns the articles matching the query parameters.
func (h *Article) List(w http.ResponseWriter, r *http.Request) {
	filter, err := parseArticleFilter(r)
	if err != nil {
		writeValidationError(w, err)
		return
	}

	page, err := h.articles.List(r.Context(), filter)
	if err != nil {
		h.writeServiceError(w, r, err, "list articles")
		return
	}

	items := make([]articleResponse, 0, len(page.Items))
	for i := range page.Items {
		items = append(items, newArticleResponse(&page.Items[i]))
	}
	writeJSON(w, http.StatusOK, articleListResponse{
		Items:      items,
		Limit:      page.Limit,
		HasMore:    page.HasMore,
		NextCursor: page.NextCursor,
	})
}

// Get returns one article, content included.
func (h *Article) Get(w http.ResponseWriter, r *http.Request) {
	article, err := h.articles.Get(r.Context(), r.PathValue("id"))
	if err != nil {
		h.writeServiceError(w, r, err, "get article")
		return
	}
	writeJSON(w, http.StatusOK, newArticleResponse(article))
}

// Delete expires articles published before delete_older_than, optionally
// limited to one source by source_id or source_name.
func (h *Article) Delete(w http.ResponseWriter, r *http.Request) {
	deletion, err := parseArticleDeletion(r)
	if err != nil {
		writeValidationError(w, err)
		return
	}

	deleted, err := h.articles.DeleteOlderThan(r.Context(), deletion)
	if err != nil {
		h.writeServiceError(w, r, err, "delete articles")
		return
	}

	h.logger.InfoContext(r.Context(), "articles expired",
		slog.Int64("deleted", deleted),
		slog.Time("older_than", deletion.OlderThan),
		slog.String("source_id", deletion.SourceID),
		slog.String("source_name", deletion.SourceName),
	)
	writeJSON(w, http.StatusOK, articleDeleteResponse{Deleted: deleted})
}

// parseArticleDeletion reads the sweep's parameters. The bound is required
// here as well as in the domain, so a request that simply forgot it is
// rejected as a missing parameter rather than as a zero timestamp.
func parseArticleDeletion(r *http.Request) (domain.ArticleDeletion, error) {
	q := r.URL.Query()
	deletion := domain.ArticleDeletion{
		SourceID:   q.Get("source_id"),
		SourceName: q.Get("source_name"),
	}

	var v domain.FieldErrors

	raw := q.Get("delete_older_than")
	if raw == "" {
		v.Add("delete_older_than", "is required")
	} else if bound := parseTimestamp(&v, raw, "delete_older_than"); bound != nil {
		deletion.OlderThan = *bound
	}

	if err := v.Err(); err != nil {
		return domain.ArticleDeletion{}, err
	}
	return deletion, nil
}

// parseArticleFilter reads the listing query parameters. Enum values, the
// identifier and the cursor are handed to the domain to validate rather than
// being trusted here.
func parseArticleFilter(r *http.Request) (domain.ArticleFilter, error) {
	q := r.URL.Query()
	filter := domain.ArticleFilter{
		SourceID: q.Get("source_id"),
		Language: q.Get("language"),
		Country:  q.Get("country"),
		State:    q.Get("state"),
		City:     q.Get("city"),
		Topic:    q.Get("topic"),
		Sort:     domain.ArticleSort(q.Get("sort")),
	}

	var v domain.FieldErrors

	filter.PublishedFrom = parseTimestamp(&v, q.Get("published_from"), "published_from")
	filter.PublishedTo = parseTimestamp(&v, q.Get("published_to"), "published_to")

	if raw := q.Get("limit"); raw != "" {
		limit, err := strconv.Atoi(raw)
		if err != nil {
			v.Add("limit", "must be an integer")
		} else {
			filter.Limit = limit
		}
	}
	if raw := q.Get("cursor"); raw != "" {
		cursor, err := domain.ParseArticleCursor(raw)
		if err != nil {
			v.Add("cursor", "must be a cursor returned by a previous page")
		} else {
			filter.Cursor = cursor
		}
	}

	if err := v.Err(); err != nil {
		return domain.ArticleFilter{}, err
	}
	return filter, nil
}

// parseTimestamp reads an RFC 3339 bound, recording a field error rather than
// failing the whole parse so every bad parameter is reported at once.
func parseTimestamp(v *domain.FieldErrors, raw, field string) *time.Time {
	if raw == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		v.Add(field, "must be an RFC 3339 timestamp, for example 2026-08-22T10:30:00Z")
		return nil
	}
	return &t
}

// writeServiceError maps a service failure to a status and a fixed code. The
// underlying error is logged with the request id and never sent to the caller.
func (h *Article) writeServiceError(w http.ResponseWriter, r *http.Request, err error, operation string) {
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeValidationError(w, err)
	case errors.Is(err, service.ErrNotFound):
		writeError(w, http.StatusNotFound, CodeNotFound, "the requested article does not exist")
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		h.logError(r, err, operation)
		writeError(w, http.StatusServiceUnavailable, CodeUnavailable, "the service is temporarily unavailable")
	default:
		h.logError(r, err, operation)
		writeError(w, http.StatusInternalServerError, CodeInternalError, "internal server error")
	}
}

func (h *Article) logError(r *http.Request, err error, operation string) {
	h.logger.ErrorContext(r.Context(), "article request failed",
		"request_id", observability.RequestIDFrom(r.Context()),
		"operation", operation,
		"error", err,
	)
}
