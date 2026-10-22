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

// SourceManager is the slice of source management this handler needs. It is
// declared at the point of use so the HTTP layer depends on behaviour rather
// than on a concrete service.
type SourceManager interface {
	Create(ctx context.Context, in domain.SourceInput) (*domain.Source, error)
	Get(ctx context.Context, id string) (*domain.Source, error)
	List(ctx context.Context, filter domain.SourceFilter) (domain.SourcePage, error)
	Update(ctx context.Context, id string, patch domain.SourcePatch) (*domain.Source, error)
	Delete(ctx context.Context, id string) error
}

// Source serves the source management endpoints.
type Source struct {
	sources SourceManager
	logger  *slog.Logger
}

// NewSource builds the source handlers.
func NewSource(sources SourceManager, logger *slog.Logger) *Source {
	return &Source{sources: sources, logger: logger}
}

// createSourceRequest is the create payload. It is a separate type from the
// domain model so a caller cannot set server-owned fields such as health,
// failure counts or timestamps.
type createSourceRequest struct {
	Name                 string `json:"name"`
	FeedURL              string `json:"feed_url"`
	Type                 string `json:"type"`
	Language             string `json:"language"`
	Country              string `json:"country"`
	State                string `json:"state"`
	City                 string `json:"city"`
	Enabled              *bool  `json:"enabled"`
	Priority             *int   `json:"priority"`
	FetchIntervalSeconds *int   `json:"fetch_interval_seconds"`
}

func (r createSourceRequest) toInput() domain.SourceInput {
	return domain.SourceInput{
		Name:                 r.Name,
		FeedURL:              r.FeedURL,
		Type:                 domain.SourceType(r.Type),
		Language:             r.Language,
		Country:              r.Country,
		State:                r.State,
		City:                 r.City,
		Enabled:              r.Enabled,
		Priority:             r.Priority,
		FetchIntervalSeconds: r.FetchIntervalSeconds,
	}
}

// updateSourceRequest is a partial update: an omitted field is left untouched.
type updateSourceRequest struct {
	Name                 *string `json:"name"`
	FeedURL              *string `json:"feed_url"`
	Type                 *string `json:"type"`
	Language             *string `json:"language"`
	Country              *string `json:"country"`
	State                *string `json:"state"`
	City                 *string `json:"city"`
	Enabled              *bool   `json:"enabled"`
	Priority             *int    `json:"priority"`
	FetchIntervalSeconds *int    `json:"fetch_interval_seconds"`
}

func (r updateSourceRequest) toPatch() domain.SourcePatch {
	patch := domain.SourcePatch{
		Name:                 r.Name,
		FeedURL:              r.FeedURL,
		Language:             r.Language,
		Country:              r.Country,
		State:                r.State,
		City:                 r.City,
		Enabled:              r.Enabled,
		Priority:             r.Priority,
		FetchIntervalSeconds: r.FetchIntervalSeconds,
	}
	if r.Type != nil {
		t := domain.SourceType(*r.Type)
		patch.Type = &t
	}
	return patch
}

// sourceResponse is the wire representation of a source.
type sourceResponse struct {
	ID                   string     `json:"id"`
	Name                 string     `json:"name"`
	FeedURL              string     `json:"feed_url"`
	Type                 string     `json:"type"`
	Enabled              bool       `json:"enabled"`
	Priority             int        `json:"priority"`
	Language             string     `json:"language"`
	Country              string     `json:"country"`
	State                string     `json:"state,omitempty"`
	City                 string     `json:"city,omitempty"`
	FetchIntervalSeconds int        `json:"fetch_interval_seconds"`
	NextScheduledAt      time.Time  `json:"next_scheduled_at"`
	LastCollectedAt      *time.Time `json:"last_collected_at,omitempty"`
	HealthStatus         string     `json:"health_status"`
	ConsecutiveFailures  int        `json:"consecutive_failures"`
	LastError            string     `json:"last_error,omitempty"`
	CreatedAt            time.Time  `json:"created_at"`
	UpdatedAt            time.Time  `json:"updated_at"`
}

func newSourceResponse(s *domain.Source) sourceResponse {
	return sourceResponse{
		ID:                   s.ID,
		Name:                 s.Name,
		FeedURL:              s.FeedURL,
		Type:                 string(s.Type),
		Enabled:              s.Enabled,
		Priority:             s.Priority,
		Language:             s.Language,
		Country:              s.Country,
		State:                s.State,
		City:                 s.City,
		FetchIntervalSeconds: s.FetchIntervalSeconds,
		NextScheduledAt:      s.NextScheduledAt,
		LastCollectedAt:      s.LastCollectedAt,
		HealthStatus:         string(s.HealthStatus),
		ConsecutiveFailures:  s.ConsecutiveFailures,
		LastError:            s.LastError,
		CreatedAt:            s.CreatedAt,
		UpdatedAt:            s.UpdatedAt,
	}
}

// sourceListResponse pairs the page with the counts needed to render it.
type sourceListResponse struct {
	Items  []sourceResponse `json:"items"`
	Total  int64            `json:"total"`
	Limit  int              `json:"limit"`
	Offset int              `json:"offset"`
}

// Create registers a new feed.
func (h *Source) Create(w http.ResponseWriter, r *http.Request) {
	var req createSourceRequest
	if err := decodeJSON(w, r, &req); err != nil {
		h.writeDecodeError(w, err)
		return
	}

	src, err := h.sources.Create(r.Context(), req.toInput())
	if err != nil {
		h.writeServiceError(w, r, err, "create source")
		return
	}

	w.Header().Set("Location", "/api/v1/sources/"+src.ID)
	writeJSON(w, http.StatusCreated, newSourceResponse(src))
}

// List returns the sources matching the query parameters.
func (h *Source) List(w http.ResponseWriter, r *http.Request) {
	filter, err := parseSourceFilter(r)
	if err != nil {
		writeValidationError(w, err)
		return
	}

	page, err := h.sources.List(r.Context(), filter)
	if err != nil {
		h.writeServiceError(w, r, err, "list sources")
		return
	}

	items := make([]sourceResponse, 0, len(page.Items))
	for i := range page.Items {
		items = append(items, newSourceResponse(&page.Items[i]))
	}
	writeJSON(w, http.StatusOK, sourceListResponse{
		Items:  items,
		Total:  page.Total,
		Limit:  page.Limit,
		Offset: page.Offset,
	})
}

// Get returns one source.
func (h *Source) Get(w http.ResponseWriter, r *http.Request) {
	src, err := h.sources.Get(r.Context(), r.PathValue("id"))
	if err != nil {
		h.writeServiceError(w, r, err, "get source")
		return
	}
	writeJSON(w, http.StatusOK, newSourceResponse(src))
}

// Update applies a partial change to a source.
func (h *Source) Update(w http.ResponseWriter, r *http.Request) {
	var req updateSourceRequest
	if err := decodeJSON(w, r, &req); err != nil {
		h.writeDecodeError(w, err)
		return
	}

	src, err := h.sources.Update(r.Context(), r.PathValue("id"), req.toPatch())
	if err != nil {
		h.writeServiceError(w, r, err, "update source")
		return
	}
	writeJSON(w, http.StatusOK, newSourceResponse(src))
}

// Delete removes a source.
func (h *Source) Delete(w http.ResponseWriter, r *http.Request) {
	if err := h.sources.Delete(r.Context(), r.PathValue("id")); err != nil {
		h.writeServiceError(w, r, err, "delete source")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// parseSourceFilter reads the listing query parameters. Enum values are handed
// to the domain to validate rather than being trusted here.
func parseSourceFilter(r *http.Request) (domain.SourceFilter, error) {
	q := r.URL.Query()
	filter := domain.SourceFilter{
		Country: q.Get("country"),
		State:   q.Get("state"),
		City:    q.Get("city"),
	}

	var v domain.FieldErrors

	if raw := q.Get("enabled"); raw != "" {
		enabled, err := strconv.ParseBool(raw)
		if err != nil {
			v.Add("enabled", "must be true or false")
		} else {
			filter.Enabled = &enabled
		}
	}
	if raw := q.Get("type"); raw != "" {
		t := domain.SourceType(raw)
		filter.Type = &t
	}
	if raw := q.Get("health_status"); raw != "" {
		hs := domain.HealthStatus(raw)
		filter.HealthStatus = &hs
	}
	if raw := q.Get("limit"); raw != "" {
		limit, err := strconv.Atoi(raw)
		if err != nil {
			v.Add("limit", "must be an integer")
		} else {
			filter.Limit = limit
		}
	}
	if raw := q.Get("offset"); raw != "" {
		offset, err := strconv.Atoi(raw)
		if err != nil {
			v.Add("offset", "must be an integer")
		} else {
			filter.Offset = offset
		}
	}

	if err := v.Err(); err != nil {
		return domain.SourceFilter{}, err
	}
	return filter, nil
}

// writeDecodeError reports a malformed request body without echoing it back.
func (h *Source) writeDecodeError(w http.ResponseWriter, err error) {
	if errors.Is(err, errUnsupportedMediaType) {
		writeError(w, http.StatusUnsupportedMediaType, CodeInvalidInput, err.Error())
		return
	}
	writeError(w, http.StatusBadRequest, CodeInvalidInput, err.Error())
}

// writeServiceError maps a service failure to a status and a fixed code. The
// underlying error is logged with the request id and never sent to the caller.
func (h *Source) writeServiceError(w http.ResponseWriter, r *http.Request, err error, operation string) {
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeValidationError(w, err)
	case errors.Is(err, service.ErrNotFound):
		writeError(w, http.StatusNotFound, CodeNotFound, "the requested source does not exist")
	case errors.Is(err, service.ErrConflict):
		writeError(w, http.StatusConflict, CodeConflict, "a source with this feed URL already exists")
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		h.logError(r, err, operation)
		writeError(w, http.StatusServiceUnavailable, CodeUnavailable, "the service is temporarily unavailable")
	default:
		h.logError(r, err, operation)
		writeError(w, http.StatusInternalServerError, CodeInternalError, "internal server error")
	}
}

func (h *Source) logError(r *http.Request, err error, operation string) {
	h.logger.ErrorContext(r.Context(), "source request failed",
		"request_id", observability.RequestIDFrom(r.Context()),
		"operation", operation,
		"error", err,
	)
}
