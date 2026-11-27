// Package classifier calls the trusted internal model-classification service.
package classifier

import (
	"context"
	"errors"
	"fmt"
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

// ItemError lists the items the service declined to classify, for example because
// every text field was empty. Classify returns it instead of results, so a caller
// can drop these items and resubmit the rest; it matches ErrBadResponse.
type ItemError struct {
	IDs []string
}

func (e *ItemError) Error() string {
	return fmt.Sprintf("%v: %d items could not be classified", ErrBadResponse, len(e.IDs))
}

func (*ItemError) Is(target error) bool { return target == ErrBadResponse }

// Item is the article data accepted by the classifier API.
type Item struct {
	ID      string `json:"id"`
	Title   string `json:"title"`
	Summary string `json:"summary"`
	Body    string `json:"body"`
	Source  string `json:"source,omitempty"`
}

// Result is one valid classification returned by the service.
type Result struct {
	ID                 string
	Topic              string
	Confidence         float64
	Filed              bool
	ModelVersion       string
	CleanTitle         string
	CleanSummary       string
	CleanBody          string
	DetectedLanguage   string
	LanguageConfidence float64
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
