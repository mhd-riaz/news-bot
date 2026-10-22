package domain

import (
	"errors"
	"strings"
	"testing"
	"time"
)

var filterNow = time.Date(2026, 8, 22, 10, 30, 0, 0, time.UTC)

func TestArticleFilterNormalizeAppliesDefaults(t *testing.T) {
	filter := ArticleFilter{
		SourceID: "  0198f3d2-1111-7000-8000-000000000001  ",
		Language: " EN ",
		Country:  " in ",
		State:    "  Karnataka ",
		City:     " Bengaluru  ",
		Topic:    " Politics ",
	}

	filter.Normalize()

	if filter.Limit != DefaultListLimit {
		t.Errorf("limit = %d, want the default %d", filter.Limit, DefaultListLimit)
	}
	if filter.Sort != SortPublishedAt {
		t.Errorf("sort = %q, want the published timeline by default", filter.Sort)
	}
	if filter.Language != "en" || filter.Country != "IN" {
		t.Errorf("language/country = %q/%q, want them case-folded the way the model stores them", filter.Language, filter.Country)
	}
	if filter.State != "Karnataka" || filter.City != "Bengaluru" || filter.Topic != "politics" || strings.HasPrefix(filter.SourceID, " ") {
		t.Errorf("filter = %+v, want every field trimmed", filter)
	}
	if err := filter.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

func TestArticleFilterRejectsBadInput(t *testing.T) {
	from := filterNow
	to := filterNow.Add(-time.Hour)

	filter := ArticleFilter{
		SourceID:      "'; drop everything",
		Language:      "english",
		Country:       "IND",
		State:         strings.Repeat("s", MaxRegionLength+1),
		City:          strings.Repeat("c", MaxRegionLength+1),
		Topic:         strings.Repeat("t", MaxRegionLength+1),
		Sort:          ArticleSort("relevance"),
		Limit:         MaxListLimit + 1,
		PublishedFrom: &from,
		PublishedTo:   &to,
	}

	err := filter.Validate()

	var ve *ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("Validate error = %v, want a validation error", err)
	}
	if len(ve.Fields) != 9 {
		t.Fatalf("fields = %+v, want all nine problems reported at once", ve.Fields)
	}
	if !errors.Is(err, ErrValidation) {
		t.Error("a validation error must match ErrValidation")
	}
}

func TestArticleFilterAcceptsAnOpenEndedRange(t *testing.T) {
	from := filterNow
	filter := ArticleFilter{PublishedFrom: &from}
	filter.Normalize()

	if err := filter.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

// A deletion with no bound would empty the collection, so the zero value must
// never be a usable sweep.
func TestArticleDeletionRequiresABound(t *testing.T) {
	deletion := ArticleDeletion{}
	deletion.Normalize()

	err := deletion.Validate()

	var ve *ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("Validate error = %v, want a validation error", err)
	}
	if len(ve.Fields) != 1 || ve.Fields[0].Field != "delete_older_than" {
		t.Fatalf("fields = %+v, want the missing bound reported", ve.Fields)
	}
}

func TestArticleDeletionNormalizesTheSource(t *testing.T) {
	deletion := ArticleDeletion{
		OlderThan:  filterNow.In(time.FixedZone("IST", 5*60*60+30*60)),
		SourceID:   "  0198f3d2-1111-7000-8000-000000000001  ",
		SourceName: "  The   Hindu — Bengaluru  ",
	}

	deletion.Normalize()

	if deletion.SourceName != "The Hindu — Bengaluru" {
		t.Errorf("source_name = %q, want it collapsed the way the article stores it", deletion.SourceName)
	}
	if deletion.SourceID != "0198f3d2-1111-7000-8000-000000000001" {
		t.Errorf("source_id = %q, want it trimmed", deletion.SourceID)
	}
	if deletion.OlderThan.Location() != time.UTC || !deletion.OlderThan.Equal(filterNow) {
		t.Errorf("older_than = %v, want the same instant in UTC", deletion.OlderThan)
	}
	if err := deletion.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

func TestArticleDeletionRejectsASourceIDThatIsNotAUUID(t *testing.T) {
	deletion := ArticleDeletion{OlderThan: filterNow, SourceID: "'; drop everything"}

	if err := deletion.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("Validate error = %v, want a validation error", err)
	}
}

func TestCursorRoundTrips(t *testing.T) {
	original := ArticleCursor{Value: filterNow, ID: "0198f3d2-3333-7000-8000-000000000001"}

	decoded, err := ParseArticleCursor(original.Encode())
	if err != nil {
		t.Fatalf("ParseArticleCursor: %v", err)
	}

	if !decoded.Value.Equal(original.Value) || decoded.ID != original.ID {
		t.Fatalf("decoded = %+v, want %+v", decoded, original)
	}
}

// A cursor is opaque so that nobody builds against its shape, but it must still
// survive a URL round trip untouched.
func TestCursorIsUrlSafeAndOpaque(t *testing.T) {
	token := ArticleCursor{Value: filterNow, ID: "0198f3d2-3333-7000-8000-000000000001"}.Encode()

	if strings.ContainsAny(token, "+/=&?#") {
		t.Errorf("cursor %q contains characters that need escaping in a query string", token)
	}
	if strings.Contains(token, "0198f3d2") {
		t.Errorf("cursor %q exposes the identifier verbatim", token)
	}
}

func TestParseArticleCursorRejectsRubbish(t *testing.T) {
	tests := []struct {
		name  string
		token string
	}{
		{"not base64", "not base64!!"},
		{"no separator", "YWJjZGVm"},
		{"timestamp is not a number", "d2hlbmV2ZXIuMDE5OGYzZDItMzMzMy03MDAwLTgwMDAtMDAwMDAwMDAwMDAx"},
		{"identifier is not a uuid", "MTIzNDU2Nzg5MC57JG5lOjF9"},
		{"empty", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cursor, err := ParseArticleCursor(tt.token)

			if cursor != nil {
				t.Fatalf("cursor = %+v, want none", cursor)
			}
			if !errors.Is(err, ErrValidation) {
				t.Fatalf("error = %v, want a validation error", err)
			}
		})
	}
}

func TestCursorForUsesTheSortedField(t *testing.T) {
	article := Article{
		ID:          "0198f3d2-3333-7000-8000-000000000001",
		PublishedAt: filterNow.Add(-24 * time.Hour),
		CollectedAt: filterNow,
	}

	published, err := ParseArticleCursor(ArticleFilter{Sort: SortPublishedAt}.CursorFor(article))
	if err != nil {
		t.Fatalf("ParseArticleCursor: %v", err)
	}
	collected, err := ParseArticleCursor(ArticleFilter{Sort: SortCollectedAt}.CursorFor(article))
	if err != nil {
		t.Fatalf("ParseArticleCursor: %v", err)
	}

	if !published.Value.Equal(article.PublishedAt) {
		t.Errorf("published cursor = %v, want %v", published.Value, article.PublishedAt)
	}
	if !collected.Value.Equal(article.CollectedAt) {
		t.Errorf("collected cursor = %v, want %v", collected.Value, article.CollectedAt)
	}
}
