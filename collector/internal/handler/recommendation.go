package handler

import (
	"errors"
	"log/slog"
	"net/http"

	"github.com/riaz/newscollector/internal/recommendation"
)

type Recommendation struct {
	service *recommendation.Service
	logger  *slog.Logger
}

func NewRecommendation(service *recommendation.Service, logger *slog.Logger) *Recommendation {
	return &Recommendation{service: service, logger: logger}
}

type storyResponse struct {
	articleResponse
	Score     float64 `json:"score"`
	Reason    string  `json:"reason"`
	Text      string  `json:"text"`
	TextKind  string  `json:"text_kind"`
	InputKind string  `json:"input_kind"`
	Group     string  `json:"group"`
	DateKind  string  `json:"date_kind"`
}

func (h *Recommendation) Metadata(w http.ResponseWriter, r *http.Request) {
	metadata, err := h.service.Metadata(r.Context())
	if err != nil {
		h.failure(w, r, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, metadata)
}

func (h *Recommendation) Recommend(w http.ResponseWriter, r *http.Request) {
	var input recommendation.Request
	if err := decodeJSONLimit(w, r, &input, 128<<10); err != nil {
		status := http.StatusBadRequest
		if errors.Is(err, errUnsupportedMediaType) {
			status = http.StatusUnsupportedMediaType
		}
		writeError(w, status, CodeInvalidInput, err.Error())
		return
	}
	result, err := h.service.Recommend(r.Context(), input)
	if err != nil {
		h.failure(w, r, err)
		return
	}
	items := make([]storyResponse, 0, len(result.Articles))
	for _, item := range result.Articles {
		dateKind := "Stored publication date"
		if item.Article.PublishedAt.Equal(item.Article.CollectedAt) {
			dateKind = "Collected"
		}
		items = append(items, storyResponse{
			articleResponse: newArticleResponse(&item.Article),
			Score:           item.Score, Reason: item.Reason, Text: item.Text, TextKind: item.TextKind,
			InputKind: item.InputKind, Group: item.Topic, DateKind: dateKind,
		})
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, struct {
		Items            []storyResponse `json:"items"`
		Method           string          `json:"method"`
		SnapshotID       string          `json:"snapshot_id"`
		Exhausted        bool            `json:"exhausted"`
		UnavailableIDs   []string        `json:"unavailable_ids"`
		IgnoredViewedIDs int             `json:"ignored_viewed_ids"`
	}{items, result.Method, result.SnapshotID, result.Exhausted, result.UnavailableIDs, result.IgnoredViewedIDs})
}

func (h *Recommendation) failure(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, recommendation.ErrInvalid):
		h.logger.InfoContext(r.Context(), "invalid recommendation request")
		writeError(w, http.StatusBadRequest, CodeInvalidInput, "Choose valid interests, a known method and at most 30 results.")
	case errors.Is(err, recommendation.ErrNotIndexed):
		writeError(w, http.StatusNotFound, CodeNotFound, "An interest or article is outside this indexed archive. Reset your interests.")
	default:
		h.logger.ErrorContext(r.Context(), "recommendations failed", "error", err)
		writeError(w, http.StatusServiceUnavailable, CodeUnavailable, "Recommendations are unavailable. Check the model service and try again.")
	}
}
