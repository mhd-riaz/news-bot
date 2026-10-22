package handler

import (
	"context"
	"log/slog"
	"net/http"
	"time"
)

// Pinger reports whether a downstream dependency is reachable. It is declared
// here, at the point of use, so the handler does not depend on the driver.
type Pinger interface {
	Ping(ctx context.Context) error
}

// Health serves the liveness and readiness probes.
type Health struct {
	mongo   Pinger
	timeout time.Duration
	version string
	logger  *slog.Logger
}

// healthResponse is the probe payload. Check values are fixed labels, never
// the underlying error text.
type healthResponse struct {
	Status  string            `json:"status"`
	Version string            `json:"version"`
	Checks  map[string]string `json:"checks,omitempty"`
}

// NewHealth builds the probe handlers. timeout bounds each dependency check so
// a hung dependency cannot stall the probe.
func NewHealth(mongo Pinger, timeout time.Duration, version string, logger *slog.Logger) *Health {
	return &Health{mongo: mongo, timeout: timeout, version: version, logger: logger}
}

// Live reports that the process is running. It never touches a dependency, so
// an orchestrator does not restart the process for a transient database outage.
func (h *Health) Live(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{Status: "alive", Version: h.version})
}

// Ready reports whether the process can serve traffic, which requires MongoDB.
func (h *Health) Ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	if err := h.mongo.Ping(ctx); err != nil {
		h.logger.WarnContext(ctx, "readiness check failed", "dependency", "mongodb", "error", err)
		writeJSON(w, http.StatusServiceUnavailable, healthResponse{
			Status:  "not_ready",
			Version: h.version,
			Checks:  map[string]string{"mongodb": "unavailable"},
		})
		return
	}

	writeJSON(w, http.StatusOK, healthResponse{
		Status:  "ready",
		Version: h.version,
		Checks:  map[string]string{"mongodb": "ok"},
	})
}
