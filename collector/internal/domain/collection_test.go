package domain

import (
	"errors"
	"strings"
	"testing"
	"time"
)

var runNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func runSource() Source {
	return Source{
		ID:                   "0198f3d2-1111-7000-8000-000000000001",
		Name:                 "  Mysuru   Daily  ",
		FetchIntervalSeconds: DefaultFetchIntervalSeconds,
	}
}

func TestNewCollectionRunOpensAgainstItsSource(t *testing.T) {
	run, err := NewCollectionRun(runSource(), runNow)
	if err != nil {
		t.Fatalf("NewCollectionRun: %v", err)
	}

	if run.ID == "" || run.SourceID != runSource().ID {
		t.Fatalf("run = %+v, want an id of its own and its source's id", run)
	}
	if run.SourceName != "Mysuru Daily" {
		t.Errorf("source name = %q, want it collapsed and trimmed", run.SourceName)
	}
	if run.Status != "" {
		t.Errorf("status = %q, want an open run to carry no outcome", run.Status)
	}
}

func TestCompleteChoosesTheOutcome(t *testing.T) {
	tests := []struct {
		name        string
		notModified bool
		mutate      func(*CollectionRun)
		want        RunStatus
	}{
		{
			name:   "everything the feed offered was stored",
			mutate: func(r *CollectionRun) { r.ItemsFound, r.ItemsStored = 10, 10 },
			want:   RunStatusSuccess,
		},
		{
			name:   "duplicates are not a partial collection",
			mutate: func(r *CollectionRun) { r.ItemsFound, r.ItemsDuplicate = 10, 10 },
			want:   RunStatusSuccess,
		},
		{
			name:        "the publisher had nothing new",
			notModified: true,
			want:        RunStatusNotModified,
		},
		{
			name:   "the feed published entries this system cannot use",
			mutate: func(r *CollectionRun) { r.ItemsFound, r.ItemsSkipped = 10, 2 },
			want:   RunStatusPartial,
		},
		{
			name:   "an entry was rejected by the article rules",
			mutate: func(r *CollectionRun) { r.ItemsFound, r.ItemsInvalid = 10, 1 },
			want:   RunStatusPartial,
		},
		{
			name:   "the feed was longer than one collection accepts",
			mutate: func(r *CollectionRun) { r.Truncated = true },
			want:   RunStatusPartial,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			run, err := NewCollectionRun(runSource(), runNow)
			if err != nil {
				t.Fatalf("NewCollectionRun: %v", err)
			}
			if tt.mutate != nil {
				tt.mutate(run)
			}

			run.Complete(runNow.Add(1500*time.Millisecond), tt.notModified)

			if run.Status != tt.want {
				t.Fatalf("status = %q, want %q", run.Status, tt.want)
			}
			if run.DurationMS != 1500 {
				t.Errorf("duration = %dms, want 1500", run.DurationMS)
			}
			if run.Error != "" {
				t.Errorf("error = %q, want none on a completed run", run.Error)
			}
		})
	}
}

func TestFailBoundsTheReason(t *testing.T) {
	run, err := NewCollectionRun(runSource(), runNow)
	if err != nil {
		t.Fatalf("NewCollectionRun: %v", err)
	}

	run.Fail(strings.Repeat("a", MaxRunErrorLength+50), runNow.Add(time.Second))

	if run.Status != RunStatusFailed {
		t.Fatalf("status = %q, want failed", run.Status)
	}
	if len(run.Error) > MaxRunErrorLength {
		t.Errorf("reason is %d bytes, want at most %d", len(run.Error), MaxRunErrorLength)
	}
}

// A clock that steps backwards — an NTP correction between the two readings —
// must not produce a negative duration.
func TestFinishNeverReportsNegativeDuration(t *testing.T) {
	run, err := NewCollectionRun(runSource(), runNow)
	if err != nil {
		t.Fatalf("NewCollectionRun: %v", err)
	}

	run.Complete(runNow.Add(-time.Minute), false)

	if run.DurationMS != 0 {
		t.Errorf("duration = %dms, want 0", run.DurationMS)
	}
}

func TestCollectionRunFilterNormalizeAndValidate(t *testing.T) {
	status := RunStatus("  FAILED ")
	filter := CollectionRunFilter{SourceID: " 0198f3d2-1111-7000-8000-000000000001 ", Status: &status}

	filter.Normalize()

	if filter.Limit != DefaultListLimit {
		t.Errorf("limit = %d, want the default %d", filter.Limit, DefaultListLimit)
	}
	if *filter.Status != RunStatusFailed {
		t.Errorf("status = %q, want it case-folded and trimmed", *filter.Status)
	}
	if err := filter.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

func TestCollectionRunFilterRejectsBadInput(t *testing.T) {
	unknown := RunStatus("exploded")
	filter := CollectionRunFilter{
		SourceID: "'; drop everything",
		Status:   &unknown,
		Limit:    MaxListLimit + 1,
		Offset:   -1,
	}

	err := filter.Validate()

	var ve *ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("Validate error = %v, want a validation error", err)
	}
	if len(ve.Fields) != 4 {
		t.Fatalf("fields = %+v, want all four problems reported at once", ve.Fields)
	}
	if !errors.Is(err, ErrValidation) {
		t.Error("a validation error must match ErrValidation")
	}
}
