// Package handler holds the thin HTTP layer. Handlers bind and validate input,
// delegate to application services, and never expose internal error detail.
package handler

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"

	"github.com/riaz/newscollector/internal/domain"
)

// Error codes returned to clients. They are deliberately coarse so that no
// database, driver or topology detail reaches the caller.
const (
	CodeNotFound      = "not_found"
	CodeInternalError = "internal_error"
	CodeUnavailable   = "unavailable"
	CodeInvalidInput  = "invalid_input"
	CodeConflict      = "conflict"
	CodeUnauthorized  = "unauthorized"
)

// maxRequestBodyBytes caps a request body. Source management payloads are small,
// so a generous cap still refuses a body large enough to exhaust memory.
const maxRequestBodyBytes = 64 << 10

// errorEnvelope is the single error shape used by every endpoint.
type errorEnvelope struct {
	Error errorDetail `json:"error"`
}

type errorDetail struct {
	Code    string              `json:"code"`
	Message string              `json:"message"`
	Fields  []domain.FieldError `json:"fields,omitempty"`
}

// writeJSON serialises payload before touching the response, so an encoding
// failure cannot emit a half-written body under an already-sent 200.
func writeJSON(w http.ResponseWriter, status int, payload any) {
	body, err := json.Marshal(payload)
	if err != nil {
		writeError(w, http.StatusInternalServerError, CodeInternalError, "internal server error")
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// writeError emits the error envelope. message must be a fixed, caller-safe
// string, never a wrapped internal error.
func writeError(w http.ResponseWriter, status int, code, message string) {
	writeErrorFields(w, status, code, message, nil)
}

// writeErrorFields emits the error envelope with per-field detail. Only
// validation messages produced by the domain may be passed here; they are
// written for the caller and never quote internal state.
func writeErrorFields(w http.ResponseWriter, status int, code, message string, fields []domain.FieldError) {
	body, err := json.Marshal(errorEnvelope{Error: errorDetail{Code: code, Message: message, Fields: fields}})
	if err != nil {
		http.Error(w, "internal server error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// writeValidationError reports a domain rule violation as a 400 with the full
// set of offending fields, so the caller can fix one payload in one round trip.
func writeValidationError(w http.ResponseWriter, err error) {
	var ve *domain.ValidationError
	if errors.As(err, &ve) {
		writeErrorFields(w, http.StatusBadRequest, CodeInvalidInput, "the request payload is invalid", ve.Fields)
		return
	}
	writeError(w, http.StatusBadRequest, CodeInvalidInput, "the request payload is invalid")
}

// decodeJSON reads a JSON request body into dst under a size cap, rejecting
// unknown fields so a typo'd or injected key fails loudly instead of being
// silently dropped. The returned error is already caller-safe.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	if ct := r.Header.Get("Content-Type"); ct != "" {
		if mediaType, _, err := mime.ParseMediaType(ct); err != nil || mediaType != "application/json" {
			return errUnsupportedMediaType
		}
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyBytes)

	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()

	if err := dec.Decode(dst); err != nil {
		var maxBytes *http.MaxBytesError
		switch {
		case errors.As(err, &maxBytes):
			return fmt.Errorf("request body must not exceed %d bytes", maxRequestBodyBytes)
		case errors.Is(err, io.EOF):
			return errors.New("request body must not be empty")
		default:
			return errors.New("request body is not valid JSON, or contains unknown fields")
		}
	}

	// A second value would mean the client sent a JSON stream, not one object.
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("request body must contain exactly one JSON object")
	}
	return nil
}

// errUnsupportedMediaType is reported as 415 rather than 400.
var errUnsupportedMediaType = errors.New("Content-Type must be application/json")
