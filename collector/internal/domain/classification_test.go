package domain

import "testing"

func TestClassificationStatusValidAndRetryable(t *testing.T) {
	for _, status := range []ClassificationStatus{
		ClassificationStatusPending,
		ClassificationStatusClassifying,
		ClassificationStatusClassified,
		ClassificationStatusUnsorted,
		ClassificationStatusFailed,
	} {
		if !status.Valid() {
			t.Errorf("%q.Valid() = false, want true", status)
		}
	}
	if ClassificationStatus("unknown").Valid() {
		t.Error("unknown classification status reported itself valid")
	}
	if !ClassificationStatusPending.Retryable() {
		t.Error("pending classification is not retryable")
	}
	for _, status := range []ClassificationStatus{
		ClassificationStatusClassifying,
		ClassificationStatusClassified,
		ClassificationStatusUnsorted,
		ClassificationStatusFailed,
	} {
		if status.Retryable() {
			t.Errorf("%q.Retryable() = true, want false", status)
		}
	}
}

func TestRetryableClassificationStatusesMatchesStatusMethod(t *testing.T) {
	for _, status := range RetryableClassificationStatuses() {
		if !status.Retryable() {
			t.Errorf("backlog status %q is not retryable", status)
		}
	}
}
