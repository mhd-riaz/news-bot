package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestFilterNormalizeAppliesDefaultLimit(t *testing.T) {
	f := SourceFilter{}
	f.Normalize()

	if f.Limit != DefaultListLimit {
		t.Errorf("limit = %d, want the default %d", f.Limit, DefaultListLimit)
	}
	if f.Offset != 0 {
		t.Errorf("offset = %d, want 0", f.Offset)
	}
}

func TestFilterNormalizeCanonicalisesValues(t *testing.T) {
	f := SourceFilter{
		Country:      " in ",
		State:        " Karnataka ",
		City:         " Mysuru ",
		Type:         ptr(SourceType(" RSS ")),
		HealthStatus: ptr(HealthStatus(" HEALTHY ")),
	}
	f.Normalize()

	if f.Country != "IN" {
		t.Errorf("country = %q, want %q", f.Country, "IN")
	}
	if f.State != "Karnataka" || f.City != "Mysuru" {
		t.Errorf("region = %q/%q, want trimmed values", f.State, f.City)
	}
	if *f.Type != SourceTypeRSS {
		t.Errorf("type = %q, want %q", *f.Type, SourceTypeRSS)
	}
	if *f.HealthStatus != HealthHealthy {
		t.Errorf("health_status = %q, want %q", *f.HealthStatus, HealthHealthy)
	}
}

func TestFilterValidate(t *testing.T) {
	tests := []struct {
		name      string
		filter    SourceFilter
		wantField string
	}{
		{"limit zero", SourceFilter{Limit: 0}, "limit"},
		{"limit negative", SourceFilter{Limit: -1}, "limit"},
		{"limit above cap", SourceFilter{Limit: MaxListLimit + 1}, "limit"},
		{"offset negative", SourceFilter{Limit: 10, Offset: -1}, "offset"},
		{"unknown type", SourceFilter{Limit: 10, Type: ptr(SourceType("json"))}, "type"},
		{"unknown health", SourceFilter{Limit: 10, HealthStatus: ptr(HealthStatus("broken"))}, "health_status"},
		{"bad country", SourceFilter{Limit: 10, Country: "IND"}, "country"},
		{"state too long", SourceFilter{Limit: 10, State: strings.Repeat("s", MaxRegionLength+1)}, "state"},
		{"city too long", SourceFilter{Limit: 10, City: strings.Repeat("c", MaxRegionLength+1)}, "city"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.filter.Validate()
			if err == nil {
				t.Fatalf("Validate accepted %+v", tc.filter)
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

// A caller must not be able to page past the cap by asking for a larger limit.
func TestFilterRejectsRatherThanSilentlyCappingLimit(t *testing.T) {
	f := SourceFilter{Limit: 5000}
	f.Normalize()

	if err := f.Validate(); err == nil {
		t.Fatal("Validate accepted a limit above the cap, want an error rather than a silent truncation")
	}
	if f.Limit != 5000 {
		t.Errorf("limit = %d, want the requested value left untouched for the error message", f.Limit)
	}
}

func TestFilterAcceptsValidValues(t *testing.T) {
	f := SourceFilter{
		Enabled:      ptr(true),
		Type:         ptr(SourceTypeAtom),
		HealthStatus: ptr(HealthFailing),
		Country:      "IN",
		Limit:        MaxListLimit,
		Offset:       200,
	}
	f.Normalize()

	if err := f.Validate(); err != nil {
		t.Fatalf("Validate rejected a valid filter: %v", err)
	}
}

func TestFieldErrorsSharesTheDomainShape(t *testing.T) {
	var fe FieldErrors
	if err := fe.Err(); err != nil {
		t.Fatalf("empty FieldErrors returned %v, want nil", err)
	}

	fe.Add("limit", "must be an integer")
	err := fe.Err()
	if !errors.Is(err, ErrValidation) {
		t.Fatalf("error %v does not wrap ErrValidation", err)
	}
	if fields := fieldsOf(t, err); !hasField(fields, "limit") {
		t.Errorf("reported fields = %v, want one named %q", fields, "limit")
	}
}
