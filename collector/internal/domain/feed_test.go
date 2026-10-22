package domain

import (
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func TestFeedItemNormalizeTidiesPublisherInput(t *testing.T) {
	published := time.Date(2025, 8, 12, 8, 15, 0, 123_456_789, time.FixedZone("IST", 5*3600+1800))

	item := FeedItem{
		Title:       "  Metro line\n\textension\r\n cleared  ",
		Link:        "  https://news.example.com/a  ",
		GUID:        " guid-1 ",
		Summary:     "  A summary.  ",
		Authors:     []string{" Anita Rao ", "anita rao", "", "Anita Rao"},
		Categories:  []string{"Transport", "  transport  ", "Infrastructure"},
		PublishedAt: &published,
	}
	item.Normalize()

	if item.Title != "Metro line extension cleared" {
		t.Errorf("Title = %q, want the whitespace collapsed", item.Title)
	}
	if item.Link != "https://news.example.com/a" || item.GUID != "guid-1" || item.Summary != "A summary." {
		t.Errorf("fields were not trimmed: %+v", item)
	}
	if len(item.Authors) != 1 || item.Authors[0] != "Anita Rao" {
		t.Errorf("Authors = %v, want the duplicates dropped case-insensitively", item.Authors)
	}
	if len(item.Categories) != 2 {
		t.Errorf("Categories = %v, want 2", item.Categories)
	}
	if item.PublishedAt.Location() != time.UTC || item.PublishedAt.Nanosecond()%int(time.Millisecond) != 0 {
		t.Errorf("PublishedAt = %s, want UTC at millisecond precision", item.PublishedAt)
	}
	if item.UpdatedAt != nil {
		t.Errorf("UpdatedAt = %v, want nil", item.UpdatedAt)
	}
}

func TestFeedItemNormalizeDropsZeroTimestamps(t *testing.T) {
	var zero time.Time
	item := FeedItem{Link: "https://news.example.com/a", PublishedAt: &zero}
	item.Normalize()

	if item.PublishedAt != nil {
		t.Errorf("PublishedAt = %v, want a zero time treated as absent", item.PublishedAt)
	}
}

func TestFeedItemNormalizeBoundsEveryField(t *testing.T) {
	item := FeedItem{
		Title:      strings.Repeat("t", MaxItemTitleLength+50),
		Link:       "https://news.example.com/" + strings.Repeat("l", MaxItemLinkLength),
		GUID:       strings.Repeat("g", MaxItemGUIDLength+10),
		Summary:    strings.Repeat("s", MaxItemSummaryLength+10),
		Content:    strings.Repeat("c", MaxItemContentLength+10),
		Authors:    make([]string, MaxItemAuthors+5),
		Categories: make([]string, MaxItemCategories+5),
	}
	for i := range item.Authors {
		// The distinguishing character goes first, so two entries stay distinct
		// after they are cut to the field bound.
		item.Authors[i] = string(rune('a'+i)) + strings.Repeat("a", MaxItemAuthorLength+5)
	}
	for i := range item.Categories {
		item.Categories[i] = string(rune('a'+i)) + strings.Repeat("c", MaxItemCategoryLength+5)
	}
	item.Normalize()

	if len(item.Title) > MaxItemTitleLength || len(item.Link) > MaxItemLinkLength ||
		len(item.GUID) > MaxItemGUIDLength || len(item.Summary) > MaxItemSummaryLength ||
		len(item.Content) > MaxItemContentLength {
		t.Errorf("a field exceeded its bound: %d/%d/%d/%d/%d",
			len(item.Title), len(item.Link), len(item.GUID), len(item.Summary), len(item.Content))
	}
	if len(item.Authors) != MaxItemAuthors || len(item.Categories) != MaxItemCategories {
		t.Errorf("list counts = %d authors, %d categories", len(item.Authors), len(item.Categories))
	}
}

func TestTruncateCutsOnARuneBoundary(t *testing.T) {
	// Each of these is three bytes, so a cut at 8 lands mid-rune.
	title := strings.Repeat("ಕ", 4)

	got := truncate(title, 8)
	if !utf8.ValidString(got) {
		t.Fatalf("truncate produced invalid UTF-8: %q", got)
	}
	if utf8.RuneCountInString(got) != 2 {
		t.Errorf("truncate kept %d runes, want 2", utf8.RuneCountInString(got))
	}
}

func TestFeedItemValidate(t *testing.T) {
	tests := []struct {
		name      string
		item      FeedItem
		wantField string
	}{
		{name: "absolute https link", item: FeedItem{Link: "https://news.example.com/a"}},
		{name: "absolute http link", item: FeedItem{Link: "http://news.example.com/a"}},
		{name: "missing link", item: FeedItem{}, wantField: "link"},
		{name: "relative link", item: FeedItem{Link: "/story/1"}, wantField: "link"},
		{name: "javascript link", item: FeedItem{Link: "javascript:alert(1)"}, wantField: "link"},
		{name: "data link", item: FeedItem{Link: "data:text/html,<h1>hi</h1>"}, wantField: "link"},
		{name: "credentials in link", item: FeedItem{Link: "https://u:p@news.example.com/a"}, wantField: "link"},
		{
			name:      "bad image url",
			item:      FeedItem{Link: "https://news.example.com/a", ImageURL: "javascript:alert(1)"},
			wantField: "image_url",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.item.Validate()
			if tc.wantField == "" {
				if err != nil {
					t.Fatalf("Validate = %v, want no error", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tc.wantField) {
				t.Fatalf("Validate = %v, want a %s violation", err, tc.wantField)
			}
		})
	}
}
