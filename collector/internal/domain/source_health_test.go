package domain

import (
	"strings"
	"testing"
	"time"
)

var healthNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func schedulableSource() *Source {
	return &Source{
		ID:                   "0198f3d2-1111-7000-8000-000000000001",
		FetchIntervalSeconds: DefaultFetchIntervalSeconds,
		HealthStatus:         HealthUnknown,
	}
}

func TestRecordSuccessClearsTheFailureHistory(t *testing.T) {
	s := schedulableSource()
	s.ConsecutiveFailures = 4
	s.HealthStatus = HealthFailing
	s.LastError = "the publisher answered HTTP 500"

	s.RecordSuccess(healthNow)

	if s.HealthStatus != HealthHealthy || s.ConsecutiveFailures != 0 || s.LastError != "" {
		t.Fatalf("source = %+v, want healthy with no failure history", s)
	}
	if s.LastCollectedAt == nil || !s.LastCollectedAt.Equal(healthNow) {
		t.Errorf("last collected = %v, want %v", s.LastCollectedAt, healthNow)
	}
	if want := healthNow.Add(s.FetchInterval()); !s.NextScheduledAt.Equal(want) {
		t.Errorf("next scheduled = %v, want one interval away at %v", s.NextScheduledAt, want)
	}
}

func TestRecordFailureDegradesThenFails(t *testing.T) {
	s := schedulableSource()

	for i := 1; i <= failuresBeforeFailing; i++ {
		s.RecordFailure(healthNow, "the publisher answered HTTP 503")

		want := HealthDegraded
		if i >= failuresBeforeFailing {
			want = HealthFailing
		}
		if s.HealthStatus != want {
			t.Fatalf("after %d failures health = %q, want %q", i, s.HealthStatus, want)
		}
		if s.ConsecutiveFailures != i {
			t.Fatalf("consecutive failures = %d, want %d", s.ConsecutiveFailures, i)
		}
	}
}

// A failed attempt is not a collection, so it must not claim the source was
// last collected just now.
func TestRecordFailureLeavesLastCollectedAlone(t *testing.T) {
	s := schedulableSource()
	collected := healthNow.Add(-3 * time.Hour)
	s.LastCollectedAt = &collected

	s.RecordFailure(healthNow, "the collection failed")

	if !s.LastCollectedAt.Equal(collected) {
		t.Errorf("last collected = %v, want the earlier successful collection %v", s.LastCollectedAt, collected)
	}
}

func TestRecordFailureBacksOffAndIsCapped(t *testing.T) {
	s := schedulableSource()
	interval := s.FetchInterval()

	for _, want := range []time.Duration{interval, 2 * interval, 4 * interval} {
		s.RecordFailure(healthNow, "down")

		if got := s.NextScheduledAt.Sub(healthNow); got != want {
			t.Fatalf("after %d failures the retry is %s away, want %s", s.ConsecutiveFailures, got, want)
		}
	}

	// Enough failures to overshoot the cap many times over.
	s.ConsecutiveFailures = 40
	s.RecordFailure(healthNow, "down")

	if got := s.NextScheduledAt.Sub(healthNow); got != MaxCollectionBackoff {
		t.Errorf("backoff = %s, want it capped at %s", got, MaxCollectionBackoff)
	}
}

func TestRecordFailureBoundsTheReason(t *testing.T) {
	s := schedulableSource()

	s.RecordFailure(healthNow, strings.Repeat("b", MaxRunErrorLength+50))

	if len(s.LastError) > MaxRunErrorLength {
		t.Errorf("last error is %d bytes, want at most %d", len(s.LastError), MaxRunErrorLength)
	}
}

// Health transitions must leave the source in a state the model still accepts,
// because the repository replaces the whole document with it.
func TestHealthTransitionsKeepTheSourceValid(t *testing.T) {
	s, err := NewSource(SourceInput{
		Name:     "Mysuru Daily",
		FeedURL:  "https://news.example.com/feed.xml",
		Type:     SourceTypeRSS,
		Language: "en",
		Country:  "IN",
	}, healthNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	s.RecordFailure(healthNow, "the publisher answered HTTP 404")
	if err := s.Validate(); err != nil {
		t.Fatalf("after a failure: %v", err)
	}

	s.RecordSuccess(healthNow.Add(time.Hour))
	if err := s.Validate(); err != nil {
		t.Fatalf("after a success: %v", err)
	}
}

func TestNewFeedCacheEntryBoundsPublisherValues(t *testing.T) {
	entry := NewFeedCacheEntry("0198f3d2-1111-7000-8000-000000000001",
		strings.Repeat("e", maxValidatorLength+100), "  Fri, 22 Aug 2026 10:30:00 GMT  ", healthNow)

	if len(entry.ETag) > maxValidatorLength {
		t.Errorf("etag is %d bytes, want at most %d", len(entry.ETag), maxValidatorLength)
	}
	if entry.LastModified != "Fri, 22 Aug 2026 10:30:00 GMT" {
		t.Errorf("last modified = %q, want it trimmed", entry.LastModified)
	}
	if entry.IsEmpty() {
		t.Error("an entry with validators must not report itself empty")
	}
	if !NewFeedCacheEntry("x", "  ", "", healthNow).IsEmpty() {
		t.Error("an entry with no usable validator must report itself empty")
	}
}

func TestNewLockExpiresAfterItsTTL(t *testing.T) {
	lock := NewLock(SourceLockResource("0198f3d2-1111-7000-8000-000000000001"), "owner-1", healthNow, 5*time.Minute)

	if lock.Resource != "source:0198f3d2-1111-7000-8000-000000000001" {
		t.Errorf("resource = %q, want the source namespace", lock.Resource)
	}
	if !lock.ExpiresAt.Equal(healthNow.Add(5 * time.Minute)) {
		t.Errorf("expires at = %v, want the ttl past %v", lock.ExpiresAt, healthNow)
	}
}
