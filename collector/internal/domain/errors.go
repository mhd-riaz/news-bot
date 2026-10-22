// Package domain holds the models and the rules that govern them. It depends on
// nothing but the standard library and the UUID generator, so the rules stay
// testable without a database, an HTTP server or any other infrastructure.
package domain

import (
	"errors"
	"fmt"
	"sort"
	"strings"
)

// ErrValidation is the sentinel every rule violation wraps, so callers can map
// the whole class to one HTTP status without inspecting individual fields.
var ErrValidation = errors.New("validation failed")

// FieldError names the offending field and explains the rule it broke. The
// message is written for the API caller, so it must never quote internal
// detail such as a driver error or a host name.
type FieldError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func (e FieldError) Error() string { return e.Field + ": " + e.Message }

// ValidationError reports every broken rule at once. Returning the full set
// rather than the first failure means a caller fixes one payload instead of
// discovering problems one request at a time.
type ValidationError struct {
	Fields []FieldError
}

func (e *ValidationError) Error() string {
	parts := make([]string, 0, len(e.Fields))
	for _, f := range e.Fields {
		parts = append(parts, f.Error())
	}
	return "validation failed: " + strings.Join(parts, "; ")
}

// Unwrap ties every ValidationError to ErrValidation for errors.Is.
func (e *ValidationError) Unwrap() error { return ErrValidation }

// validator accumulates rule violations so a single pass reports them all.
type validator struct {
	fields []FieldError
}

func (v *validator) add(field, format string, args ...any) {
	v.fields = append(v.fields, FieldError{Field: field, Message: fmt.Sprintf(format, args...)})
}

// err returns a *ValidationError, or nil when nothing was added. Fields are
// sorted so the response is deterministic and diffable in tests.
func (v *validator) err() error {
	if len(v.fields) == 0 {
		return nil
	}
	sort.SliceStable(v.fields, func(i, j int) bool { return v.fields[i].Field < v.fields[j].Field })
	return &ValidationError{Fields: v.fields}
}

// FieldErrors lets a layer outside the domain — query-parameter parsing, for
// instance — report input problems in exactly the same shape as a model rule,
// so the API has one error format rather than two.
type FieldErrors struct {
	v validator
}

// Add records one violation.
func (f *FieldErrors) Add(field, message string) {
	f.v.add(field, "%s", message)
}

// Err returns a *ValidationError, or nil when nothing was recorded.
func (f *FieldErrors) Err() error { return f.v.err() }
