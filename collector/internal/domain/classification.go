package domain

import "time"

// ClassificationStatus records the most recent model-classification outcome.
type ClassificationStatus string

const (
	ClassificationStatusPending     ClassificationStatus = "pending"
	ClassificationStatusClassifying ClassificationStatus = "classifying"
	ClassificationStatusClassified  ClassificationStatus = "classified"
	ClassificationStatusUnsorted    ClassificationStatus = "unsorted"
	ClassificationStatusFailed      ClassificationStatus = "failed"
)

// Valid reports whether s is a classification status this package defines.
func (s ClassificationStatus) Valid() bool {
	switch s {
	case ClassificationStatusPending, ClassificationStatusClassifying,
		ClassificationStatusClassified, ClassificationStatusUnsorted,
		ClassificationStatusFailed:
		return true
	}
	return false
}

// Retryable reports whether a later worker may claim an article in this state.
func (s ClassificationStatus) Retryable() bool { return s == ClassificationStatusPending }

// RetryableClassificationStatuses lists the states selected by the claim query.
func RetryableClassificationStatuses() []ClassificationStatus {
	return []ClassificationStatus{ClassificationStatusPending}
}

// ClassificationResult is the narrow outcome written by a classification worker.
type ClassificationResult struct {
	Status             ClassificationStatus
	Topic              string
	Confidence         float64
	ModelVersion       string
	CleanTitle         string
	CleanSummary       string
	CleanBody          string
	DetectedLanguage   string
	LanguageConfidence float64
	At                 time.Time
	ClaimedAt          time.Time
}

// ClassificationClaim selects the next pending article and stamps its claim.
type ClassificationClaim struct {
	Now            time.Time
	MaxAttempts    int
	PublishedAfter time.Time
}
