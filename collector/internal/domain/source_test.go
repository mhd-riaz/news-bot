package domain

import (
	"errors"
	"strings"
	"testing"
	"time"
)

var fixedNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func ptr[T any](v T) *T { return &v }

// validInput is the minimum payload that must always be accepted. Tests mutate
// a copy of it so each case states only the field under test.
func validInput() SourceInput {
	return SourceInput{
		Name:     "The Hindu — Bengaluru",
		FeedURL:  "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
		Type:     SourceTypeRSS,
		Language: "en",
		Country:  "IN",
		State:    "Karnataka",
		City:     "Bengaluru",
	}
}

// fieldsOf collects the field names reported by a validation error.
func fieldsOf(t *testing.T, err error) []string {
	t.Helper()
	var ve *ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("error %v is not a *ValidationError", err)
	}
	names := make([]string, 0, len(ve.Fields))
	for _, f := range ve.Fields {
		names = append(names, f.Field)
	}
	return names
}

func hasField(fields []string, want string) bool {
	for _, f := range fields {
		if f == want {
			return true
		}
	}
	return false
}

func TestNewSourceAppliesDefaults(t *testing.T) {
	src, err := NewSource(validInput(), fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	if !src.Enabled {
		t.Error("enabled = false, want true by default")
	}
	if src.Priority != DefaultPriority {
		t.Errorf("priority = %d, want %d", src.Priority, DefaultPriority)
	}
	if src.FetchIntervalSeconds != DefaultFetchIntervalSeconds {
		t.Errorf("fetch_interval_seconds = %d, want %d", src.FetchIntervalSeconds, DefaultFetchIntervalSeconds)
	}
	if src.HealthStatus != HealthUnknown {
		t.Errorf("health_status = %q, want %q", src.HealthStatus, HealthUnknown)
	}
	if src.ConsecutiveFailures != 0 {
		t.Errorf("consecutive_failures = %d, want 0", src.ConsecutiveFailures)
	}
	// A new source must be collectable immediately rather than after one interval.
	if !src.NextScheduledAt.Equal(fixedNow) {
		t.Errorf("next_scheduled_at = %v, want %v", src.NextScheduledAt, fixedNow)
	}
	if !src.CreatedAt.Equal(fixedNow) || !src.UpdatedAt.Equal(fixedNow) {
		t.Errorf("timestamps = %v/%v, want %v", src.CreatedAt, src.UpdatedAt, fixedNow)
	}
	if src.FetchInterval() != time.Duration(DefaultFetchIntervalSeconds)*time.Second {
		t.Errorf("FetchInterval() = %v", src.FetchInterval())
	}
}

func TestNewSourceHonoursExplicitZeroValues(t *testing.T) {
	in := validInput()
	in.Enabled = ptr(false)
	in.Priority = ptr(0)

	src, err := NewSource(in, fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	if src.Enabled {
		t.Error("enabled = true, want the explicit false to win over the default")
	}
	if src.Priority != 0 {
		t.Errorf("priority = %d, want the explicit 0 to win over the default", src.Priority)
	}
}

func TestNewSourceGeneratesDistinctIdentifiers(t *testing.T) {
	first, err := NewSource(validInput(), fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	second, err := NewSource(validInput(), fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	if first.ID == second.ID {
		t.Errorf("both sources got id %q, want distinct identifiers", first.ID)
	}
	if err := ValidateID(first.ID); err != nil {
		t.Errorf("generated id %q is not a valid UUID: %v", first.ID, err)
	}
}

func TestNormalizeCanonicalisesFields(t *testing.T) {
	in := validInput()
	in.Name = "  Deccan Herald  "
	in.Type = SourceType("  RSS ")
	in.Language = " EN "
	in.Country = " in "
	in.State = "  Karnataka "
	in.City = " Mysuru "

	src, err := NewSource(in, fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	if src.Name != "Deccan Herald" {
		t.Errorf("name = %q, want %q", src.Name, "Deccan Herald")
	}
	if src.Type != SourceTypeRSS {
		t.Errorf("type = %q, want %q", src.Type, SourceTypeRSS)
	}
	if src.Language != "en" {
		t.Errorf("language = %q, want %q", src.Language, "en")
	}
	if src.Country != "IN" {
		t.Errorf("country = %q, want %q", src.Country, "IN")
	}
	if src.State != "Karnataka" || src.City != "Mysuru" {
		t.Errorf("region = %q/%q, want trimmed values", src.State, src.City)
	}
}

func TestNewSourceRejectsInvalidInput(t *testing.T) {
	tests := []struct {
		name      string
		mutate    func(*SourceInput)
		wantField string
	}{
		{"empty name", func(in *SourceInput) { in.Name = "   " }, "name"},
		{"name too long", func(in *SourceInput) { in.Name = strings.Repeat("a", MaxNameLength+1) }, "name"},
		{"empty feed url", func(in *SourceInput) { in.FeedURL = "" }, "feed_url"},
		{"feed url too long", func(in *SourceInput) {
			in.FeedURL = "https://example.com/" + strings.Repeat("a", MaxFeedURLLength)
		}, "feed_url"},
		{"file scheme", func(in *SourceInput) { in.FeedURL = "file:///etc/passwd" }, "feed_url"},
		{"gopher scheme", func(in *SourceInput) { in.FeedURL = "gopher://example.com/feed" }, "feed_url"},
		{"javascript scheme", func(in *SourceInput) { in.FeedURL = "javascript:alert(1)" }, "feed_url"},
		{"no host", func(in *SourceInput) { in.FeedURL = "https:///feed.xml" }, "feed_url"},
		{"embedded credentials", func(in *SourceInput) { in.FeedURL = "https://user:pass@example.com/feed" }, "feed_url"},
		{"whitespace in url", func(in *SourceInput) { in.FeedURL = "https://example.com/a b" }, "feed_url"},
		{"control character in url", func(in *SourceInput) { in.FeedURL = "https://example.com/\nfeed" }, "feed_url"},
		{"unknown type", func(in *SourceInput) { in.Type = SourceType("json") }, "type"},
		{"empty type", func(in *SourceInput) { in.Type = "" }, "type"},
		{"priority below range", func(in *SourceInput) { in.Priority = ptr(MinPriority - 1) }, "priority"},
		{"priority above range", func(in *SourceInput) { in.Priority = ptr(MaxPriority + 1) }, "priority"},
		{"interval too small", func(in *SourceInput) {
			in.FetchIntervalSeconds = ptr(MinFetchIntervalSeconds - 1)
		}, "fetch_interval_seconds"},
		{"interval too large", func(in *SourceInput) {
			in.FetchIntervalSeconds = ptr(MaxFetchIntervalSeconds + 1)
		}, "fetch_interval_seconds"},
		{"language wrong length", func(in *SourceInput) { in.Language = "eng" }, "language"},
		{"language not alphabetic", func(in *SourceInput) { in.Language = "e1" }, "language"},
		{"country wrong length", func(in *SourceInput) { in.Country = "IND" }, "country"},
		{"country missing", func(in *SourceInput) { in.Country = "" }, "country"},
		{"state too long", func(in *SourceInput) { in.State = strings.Repeat("s", MaxRegionLength+1) }, "state"},
		{"city too long", func(in *SourceInput) { in.City = strings.Repeat("c", MaxRegionLength+1) }, "city"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			in := validInput()
			tc.mutate(&in)

			src, err := NewSource(in, fixedNow)
			if err == nil {
				t.Fatalf("NewSource accepted invalid input, got source %+v", src)
			}
			if !errors.Is(err, ErrValidation) {
				t.Fatalf("error %v does not wrap ErrValidation", err)
			}
			if fields := fieldsOf(t, err); !hasField(fields, tc.wantField) {
				t.Errorf("reported fields = %v, want one named %q", fields, tc.wantField)
			}
		})
	}
}

func TestValidationReportsEveryBrokenRuleAtOnce(t *testing.T) {
	in := validInput()
	in.Name = ""
	in.FeedURL = "file:///etc/passwd"
	in.Type = SourceType("json")
	in.Country = "IND"

	_, err := NewSource(in, fixedNow)
	if err == nil {
		t.Fatal("NewSource accepted input breaking four rules")
	}

	fields := fieldsOf(t, err)
	for _, want := range []string{"country", "feed_url", "name", "type"} {
		if !hasField(fields, want) {
			t.Errorf("reported fields = %v, missing %q", fields, want)
		}
	}
	// Sorted output keeps the API response and these assertions deterministic.
	if fields[0] != "country" {
		t.Errorf("fields = %v, want them sorted by name", fields)
	}
}

func TestApplyPatchesOnlySuppliedFields(t *testing.T) {
	src, err := NewSource(validInput(), fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	later := fixedNow.Add(time.Hour)

	if err := src.Apply(SourcePatch{Priority: ptr(90)}, later); err != nil {
		t.Fatalf("Apply: %v", err)
	}

	if src.Priority != 90 {
		t.Errorf("priority = %d, want 90", src.Priority)
	}
	if src.Name != validInput().Name {
		t.Errorf("name = %q, want it untouched", src.Name)
	}
	if !src.UpdatedAt.Equal(later) {
		t.Errorf("updated_at = %v, want %v", src.UpdatedAt, later)
	}
	if !src.CreatedAt.Equal(fixedNow) {
		t.Errorf("created_at = %v, want it untouched", src.CreatedAt)
	}
}

func TestApplyRevalidatesTheWholeSource(t *testing.T) {
	src, err := NewSource(validInput(), fixedNow)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	err = src.Apply(SourcePatch{FeedURL: ptr("file:///etc/passwd")}, fixedNow)
	if err == nil {
		t.Fatal("Apply accepted a feed URL the model forbids")
	}
	if !errors.Is(err, ErrValidation) {
		t.Errorf("error %v does not wrap ErrValidation", err)
	}
}

func TestValidationErrorMessageNamesEveryField(t *testing.T) {
	in := validInput()
	in.Name = ""
	in.Country = "XYZ"

	_, err := NewSource(in, fixedNow)
	if err == nil {
		t.Fatal("NewSource accepted invalid input")
	}
	msg := err.Error()
	if !strings.Contains(msg, "name") || !strings.Contains(msg, "country") {
		t.Errorf("error message = %q, want it to name both fields", msg)
	}
}

// BSON stores milliseconds. Keeping sub-millisecond precision would make the
// value returned on a write differ from the one a later read returns.
func TestTimestampsUseTheStorablePrecision(t *testing.T) {
	messy := time.Date(2026, 8, 22, 10, 30, 0, 300127456, time.UTC)

	src, err := NewSource(validInput(), messy)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}

	want := messy.Truncate(time.Millisecond)
	for name, got := range map[string]time.Time{
		"created_at":        src.CreatedAt,
		"updated_at":        src.UpdatedAt,
		"next_scheduled_at": src.NextScheduledAt,
	} {
		if !got.Equal(want) {
			t.Errorf("%s = %v, want %v", name, got, want)
		}
	}

	if err := src.Apply(SourcePatch{Priority: ptr(80)}, messy.Add(time.Hour)); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if got := src.UpdatedAt; got.Nanosecond()%int(time.Millisecond) != 0 {
		t.Errorf("updated_at = %v, want millisecond precision after a patch", got)
	}
}

// A caller in another zone must not shift the stored instant.
func TestTimestampsAreNormalisedToUTC(t *testing.T) {
	ist := time.FixedZone("IST", 5*60*60+30*60)
	local := time.Date(2026, 8, 22, 16, 0, 0, 0, ist)

	src, err := NewSource(validInput(), local)
	if err != nil {
		t.Fatalf("NewSource: %v", err)
	}
	if src.CreatedAt.Location() != time.UTC {
		t.Errorf("created_at location = %v, want UTC", src.CreatedAt.Location())
	}
	if !src.CreatedAt.Equal(local) {
		t.Errorf("created_at = %v, want the same instant as %v", src.CreatedAt, local)
	}
}
