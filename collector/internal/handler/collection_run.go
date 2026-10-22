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

// CollectionRunReader is the slice of run history this handler needs. Runs are
// written by the collector, never by a caller, so the contract is read-only.
type CollectionRunReader interface {
	ListRuns(ctx context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error)
	GetRun(ctx context.Context, id string) (*domain.CollectionRun, error)
}

// CollectionRun serves the collection history endpoints.
type CollectionRun struct {
	runs   CollectionRunReader
	logger *slog.Logger
}

// NewCollectionRun builds the collection-run handlers.
func NewCollectionRun(runs CollectionRunReader, logger *slog.Logger) *CollectionRun {
	return &CollectionRun{runs: runs, logger: logger}
}

// collectionRunResponse is the wire representation of one collection attempt.
type collectionRunResponse struct {
	ID          string    `json:"id"`
	SourceID    string    `json:"source_id"`
	SourceName  string    `json:"source_name"`
	Status      string    `json:"status"`
	StartedAt   time.Time `json:"started_at"`
	CompletedAt time.Time `json:"completed_at"`
	DurationMS  int64     `json:"duration_ms"`
	FeedType    string    `json:"feed_type,omitempty"`

	ItemsFound     int  `json:"items_found"`
	ItemsStored    int  `json:"items_stored"`
	ItemsDuplicate int  `json:"items_duplicate"`
	ItemsInvalid   int  `json:"items_invalid"`
	ItemsSkipped   int  `json:"items_skipped"`
	Truncated      bool `json:"truncated"`

	Error string `json:"error,omitempty"`
}

func newCollectionRunResponse(r *domain.CollectionRun) collectionRunResponse {
	return collectionRunResponse{
		ID:             r.ID,
		SourceID:       r.SourceID,
		SourceName:     r.SourceName,
		Status:         string(r.Status),
		StartedAt:      r.StartedAt,
		CompletedAt:    r.CompletedAt,
		DurationMS:     r.DurationMS,
		FeedType:       r.FeedType,
		ItemsFound:     r.ItemsFound,
		ItemsStored:    r.ItemsStored,
		ItemsDuplicate: r.ItemsDuplicate,
		ItemsInvalid:   r.ItemsInvalid,
		ItemsSkipped:   r.ItemsSkipped,
		Truncated:      r.Truncated,
		Error:          r.Error,
	}
}

// collectionRunListResponse pairs the page with the counts needed to render it.
type collectionRunListResponse struct {
	Items  []collectionRunResponse `json:"items"`
	Total  int64                   `json:"total"`
	Limit  int                     `json:"limit"`
	Offset int                     `json:"offset"`
}

// List returns the collection runs matching the query parameters.
func (h *CollectionRun) List(w http.ResponseWriter, r *http.Request) {
	filter, err := parseCollectionRunFilter(r)
	if err != nil {
		writeValidationError(w, err)
		return
	}

	page, err := h.runs.ListRuns(r.Context(), filter)
	if err != nil {
		h.writeServiceError(w, r, err, "list collection runs")
		return
	}

	items := make([]collectionRunResponse, 0, len(page.Items))
	for i := range page.Items {
		items = append(items, newCollectionRunResponse(&page.Items[i]))
	}
	writeJSON(w, http.StatusOK, collectionRunListResponse{
		Items:  items,
		Total:  page.Total,
		Limit:  page.Limit,
		Offset: page.Offset,
	})
}

// Get returns one collection run.
func (h *CollectionRun) Get(w http.ResponseWriter, r *http.Request) {
	run, err := h.runs.GetRun(r.Context(), r.PathValue("id"))
	if err != nil {
		h.writeServiceError(w, r, err, "get collection run")
		return
	}
	writeJSON(w, http.StatusOK, newCollectionRunResponse(run))
}

// parseCollectionRunFilter reads the listing query parameters. The enum and the
// identifier are handed to the domain to validate rather than trusted here.
func parseCollectionRunFilter(r *http.Request) (domain.CollectionRunFilter, error) {
	q := r.URL.Query()
	filter := domain.CollectionRunFilter{SourceID: q.Get("source_id")}

	var v domain.FieldErrors

	if raw := q.Get("status"); raw != "" {
		status := domain.RunStatus(raw)
		filter.Status = &status
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
		return domain.CollectionRunFilter{}, err
	}
	return filter, nil
}

// writeServiceError maps a service failure to a status and a fixed code. The
// underlying error is logged with the request id and never sent to the caller.
func (h *CollectionRun) writeServiceError(w http.ResponseWriter, r *http.Request, err error, operation string) {
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeValidationError(w, err)
	case errors.Is(err, service.ErrNotFound):
		writeError(w, http.StatusNotFound, CodeNotFound, "the requested collection run does not exist")
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		h.logError(r, err, operation)
		writeError(w, http.StatusServiceUnavailable, CodeUnavailable, "the service is temporarily unavailable")
	default:
		h.logError(r, err, operation)
		writeError(w, http.StatusInternalServerError, CodeInternalError, "internal server error")
	}
}

func (h *CollectionRun) logError(r *http.Request, err error, operation string) {
	h.logger.ErrorContext(r.Context(), "collection run request failed",
		"request_id", observability.RequestIDFrom(r.Context()),
		"operation", operation,
		"error", err,
	)
}
