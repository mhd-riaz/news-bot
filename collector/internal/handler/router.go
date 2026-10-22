package handler

import (
	"log/slog"
	"net/http"

	"github.com/riaz/newscollector/internal/observability"
)

// NewRouter wires every route the API serves. A nil auth leaves the API
// unguarded, which the configuration layer permits only outside production. A
// nil pages leaves the process a pure API with no reader-facing site.
func NewRouter(health *Health, sources *Source, runs *CollectionRun, articles *Article, pages http.Handler, auth *Authenticator, logger *slog.Logger) http.Handler {
	// The guarded routes live on their own mux, so what auth covers is decided by
	// which handlers are registered here rather than by matching the request path
	// twice — once in the middleware and once in the router.
	api := http.NewServeMux()

	api.HandleFunc("POST /api/v1/sources", sources.Create)
	api.HandleFunc("GET /api/v1/sources", sources.List)
	api.HandleFunc("GET /api/v1/sources/{id}", sources.Get)
	api.HandleFunc("PATCH /api/v1/sources/{id}", sources.Update)
	api.HandleFunc("DELETE /api/v1/sources/{id}", sources.Delete)

	// Collections are driven by the scheduler and the collector CLI, never by a
	// caller, so the history is read-only over HTTP.
	api.HandleFunc("GET /api/v1/collection-runs", runs.List)
	api.HandleFunc("GET /api/v1/collection-runs/{id}", runs.Get)

	// Articles are written only by the collection pipeline; the one write a
	// caller may make is the retention sweep that expires old ones.
	api.HandleFunc("GET /api/v1/articles", articles.List)
	api.HandleFunc("DELETE /api/v1/articles", articles.Delete)
	api.HandleFunc("GET /api/v1/articles/{id}", articles.Get)

	// An unmatched path under the guarded prefix is answered here rather than by
	// the outer mux, so a caller cannot tell an unknown route from a known one
	// without first authenticating.
	api.HandleFunc("/", notFound)

	mux := http.NewServeMux()

	// Health stays open: the container healthcheck and the reverse proxy probe it
	// before any credential is in play, and it reveals nothing but liveness.
	mux.HandleFunc("GET /health/live", health.Live)
	mux.HandleFunc("GET /health/ready", health.Ready)

	mux.Handle("/api/v1/", auth.Require(api))

	// The reader-facing site sits behind the same credentials as the API, so
	// there is no second authentication path to get wrong. It takes everything
	// the API did not claim, including its own 404 page.
	if pages != nil {
		mux.Handle("/", auth.Require(pages))
	} else {
		mux.HandleFunc("/", notFound)
	}

	return observability.Chain(mux,
		observability.RequestID,
		observability.Recover(logger),
		observability.AccessLog(logger),
	)
}

func notFound(w http.ResponseWriter, _ *http.Request) {
	writeError(w, http.StatusNotFound, CodeNotFound, "the requested resource does not exist")
}
