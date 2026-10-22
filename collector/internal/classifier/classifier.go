// Package classifier calls the trusted internal model-classification service.
package classifier

import (
	"context"
	"errors"
)

var (
	ErrInvalidEndpoint  = errors.New("classifier: invalid endpoint")
	ErrRequestTooLarge  = errors.New("classifier: request exceeds limit")
	ErrResponseTooLarge = errors.New("classifier: response exceeds limit")
	ErrBadResponse      = errors.New("classifier: invalid response contract")
	ErrService          = errors.New("classifier: service error")
	ErrUnauthenticated  = errors.New("classifier: authentication failed")
)

// Client submits article batches and retrieves immutable topic metadata.
type Client interface {
	Classify(context.Context, []Item) ([]Result, error)
	Metadata(context.Context) (Metadata, error)

	// BatchSize reports the largest batch Classify accepts in one call, so a
	// caller with more items than that can split them into several calls.
	BatchSize() int
}

// Item is the article data accepted by the classifier API.
type Item struct {
	ID      string `json:"id"`
	Title   string `json:"title"`
	Summary string `json:"summary"`
	Body    string `json:"body"`
}

// Result is one valid classification returned by the service.
type Result struct {
	ID           string
	Topic        string
	Confidence   float64
	Filed        bool
	ModelVersion string
}

// Topic is a canonical topic identifier and reader-facing label.
type Topic struct {
	ID    string
	Label string
}

// Metadata is the immutable model release information returned by /v1/meta.
type Metadata struct {
	ModelVersion string
	Cut          float64
	Topics       []Topic
}
