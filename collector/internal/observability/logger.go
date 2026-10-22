// Package observability provides the process logger and the HTTP middleware
// that gives every request an identifier, an access log line and panic safety.
package observability

import (
	"fmt"
	"io"
	"log/slog"
	"strings"
)

// NewLogger builds a slog logger for the given level (debug, info, warn, error)
// and format (json, text).
func NewLogger(level, format string, w io.Writer) (*slog.Logger, error) {
	lvl, err := ParseLevel(level)
	if err != nil {
		return nil, err
	}

	opts := &slog.HandlerOptions{Level: lvl}

	var h slog.Handler
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "json":
		h = slog.NewJSONHandler(w, opts)
	case "text":
		h = slog.NewTextHandler(w, opts)
	default:
		return nil, fmt.Errorf("unsupported log format %q: want json or text", format)
	}
	return slog.New(h), nil
}

// ParseLevel maps a configured level name onto a slog level.
func ParseLevel(level string) (slog.Level, error) {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "debug":
		return slog.LevelDebug, nil
	case "info":
		return slog.LevelInfo, nil
	case "warn", "warning":
		return slog.LevelWarn, nil
	case "error":
		return slog.LevelError, nil
	default:
		return 0, fmt.Errorf("unsupported log level %q: want debug, info, warn or error", level)
	}
}
