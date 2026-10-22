//go:build integration

package mongo

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// explainList asks MongoDB how it would run the listing the repository builds,
// so the test checks the real query rather than a hand-written copy of it.
func explainList(ctx context.Context, repo *ArticleRepository, filter domain.ArticleFilter) (bson.Raw, error) {
	field := articleSortField(filter.Sort)

	return repo.coll.Database().RunCommand(ctx, bson.D{
		{Key: "explain", Value: bson.D{
			{Key: "find", Value: repo.coll.Name()},
			{Key: "filter", Value: articleQuery(filter, field)},
			{Key: "sort", Value: bson.D{{Key: field, Value: -1}, {Key: "_id", Value: -1}}},
			{Key: "limit", Value: int64(filter.Limit) + 1},
			{Key: "projection", Value: bson.D{{Key: "content", Value: 0}}},
		}},
		{Key: "verbosity", Value: "queryPlanner"},
	}).Raw()
}

// winningStage reports how MongoDB chose to answer the query. Only the winning
// plan is inspected: a rejected plan may legitimately be a collection scan.
//
// A blocking SORT is called out as well as a COLLSCAN, because it is the more
// insidious of the two — the query is indexed, but the database still has to
// read and order every matching article to hand back one page of them.
func winningStage(plan bson.Raw) string {
	winning, err := plan.LookupErr("queryPlanner", "winningPlan")
	if err != nil {
		return ""
	}

	described := winning.String()
	switch {
	case strings.Contains(described, "COLLSCAN"):
		return "COLLSCAN"
	case strings.Contains(described, `"SORT"`):
		return "SORT"
	default:
		return "IXSCAN"
	}
}

// seedSourceID is shared by every seeded article, because newArticle otherwise
// mints a fresh source for each one and no two would be attributable to the
// same feed.
const seedSourceID = "0198f3d2-1111-7000-8000-00000000aaaa"

// seedArticles stores n articles a minute apart, newest last, and returns them
// in the order a listing should hand them back: newest first.
func seedArticles(t *testing.T, repo *ArticleRepository, n int, mutate ...func(int, *domain.Article)) []domain.Article {
	t.Helper()
	ctx := testContext(t)

	base := time.Now().UTC().Add(-24 * time.Hour).Truncate(time.Millisecond)
	stored := make([]domain.Article, 0, n)

	for i := range n {
		a := newArticle(t, fmt.Sprintf("https://example.com/story/%d", i), fmt.Sprintf("story-%d", i))
		a.SourceID = seedSourceID
		a.PublishedAt = base.Add(time.Duration(i) * time.Minute)
		a.CollectedAt = base.Add(time.Duration(i) * time.Minute)
		for _, m := range mutate {
			m(i, a)
		}
		if err := repo.Create(ctx, a); err != nil {
			t.Fatalf("Create: %v", err)
		}
		stored = append(stored, *a)
	}

	// Reverse into newest-first order.
	for i, j := 0, len(stored)-1; i < j; i, j = i+1, j-1 {
		stored[i], stored[j] = stored[j], stored[i]
	}
	return stored
}

func TestArticleGetByID(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	a := newArticle(t, "https://example.com/story/one", "story-one")
	a.Content = "The full text of the article."
	if err := repo.Create(ctx, a); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.GetByID(ctx, a.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.ID != a.ID || got.Content != a.Content {
		t.Errorf("read back %+v, want the article in full", got)
	}

	if _, err := repo.GetByID(ctx, "0198f3d2-3333-7000-8000-000000000009"); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("GetByID of an unknown id = %v, want ErrNotFound", err)
	}
}

func TestArticleListIsNewestFirstWithoutContent(t *testing.T) {
	repo := newTestArticleRepo(t)
	want := seedArticles(t, repo, 3, func(_ int, a *domain.Article) {
		a.Content = "The full text of the article."
	})

	filter := domain.ArticleFilter{Limit: 10, Sort: domain.SortPublishedAt}
	page, err := repo.List(testContext(t), filter)
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	if len(page.Items) != 3 || page.HasMore || page.NextCursor != "" {
		t.Fatalf("page = %d items, has_more=%v, want all three and no continuation", len(page.Items), page.HasMore)
	}
	for i, got := range page.Items {
		if got.ID != want[i].ID {
			t.Fatalf("position %d = %q, want %q: the listing is not newest first", i, got.Title, want[i].Title)
		}
		if got.Content != "" {
			t.Errorf("position %d carries its content; a listing must project it away", i)
		}
		if got.Title == "" || got.SourceName == "" {
			t.Errorf("position %d lost fields the projection should have kept: %+v", i, got)
		}
	}
}

// The cursor must walk every article exactly once, which is the whole reason it
// exists rather than an offset.
func TestArticleListPagesWithACursor(t *testing.T) {
	repo := newTestArticleRepo(t)
	want := seedArticles(t, repo, 7)
	ctx := testContext(t)

	seen := make([]string, 0, len(want))
	filter := domain.ArticleFilter{Limit: 2, Sort: domain.SortPublishedAt}

	for range 10 {
		page, err := repo.List(ctx, filter)
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		for _, a := range page.Items {
			seen = append(seen, a.ID)
		}
		if !page.HasMore {
			break
		}

		cursor, err := domain.ParseArticleCursor(page.NextCursor)
		if err != nil {
			t.Fatalf("ParseArticleCursor: %v", err)
		}
		filter.Cursor = cursor
	}

	if len(seen) != len(want) {
		t.Fatalf("walked %d articles, want %d exactly once each", len(seen), len(want))
	}
	for i, id := range seen {
		if id != want[i].ID {
			t.Fatalf("position %d = %s, want %s: paging lost the order", i, id, want[i].ID)
		}
	}
}

// Two articles sharing a publication timestamp must not make one of them
// invisible, or a burst of same-second entries would be silently dropped.
func TestArticleListPagesPastATimestampTie(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	shared := time.Now().UTC().Add(-time.Hour).Truncate(time.Millisecond)

	for i := range 4 {
		a := newArticle(t, fmt.Sprintf("https://example.com/tie/%d", i), fmt.Sprintf("tie-%d", i))
		a.PublishedAt = shared
		if err := repo.Create(ctx, a); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}

	seen := make(map[string]struct{}, 4)
	filter := domain.ArticleFilter{Limit: 1, Sort: domain.SortPublishedAt}

	for range 6 {
		page, err := repo.List(ctx, filter)
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		for _, a := range page.Items {
			if _, dup := seen[a.ID]; dup {
				t.Fatalf("article %s was returned twice", a.ID)
			}
			seen[a.ID] = struct{}{}
		}
		if !page.HasMore {
			break
		}
		cursor, err := domain.ParseArticleCursor(page.NextCursor)
		if err != nil {
			t.Fatalf("ParseArticleCursor: %v", err)
		}
		filter.Cursor = cursor
	}

	if len(seen) != 4 {
		t.Fatalf("walked %d of 4 articles that share a timestamp", len(seen))
	}
}

func TestArticleListFilters(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	stored := seedArticles(t, repo, 4, func(i int, a *domain.Article) {
		if i%2 == 0 {
			a.City = "Mysuru"
			a.Language = "kn"
		}
	})
	// stored is newest first; the even-indexed originals are the Mysuru ones.
	sourceID := stored[0].SourceID
	tests := []struct {
		name   string
		filter domain.ArticleFilter
		want   int
	}{
		{"by source", domain.ArticleFilter{SourceID: sourceID, Limit: 10}, 4},
		{"by unknown source", domain.ArticleFilter{SourceID: "0198f3d2-1111-7000-8000-0000000000ff", Limit: 10}, 0},
		{"by city", domain.ArticleFilter{City: "Mysuru", Limit: 10}, 2},
		{"by language", domain.ArticleFilter{Language: "kn", Limit: 10}, 2},
		{"by country and state", domain.ArticleFilter{Country: "IN", State: "Karnataka", Limit: 10}, 4},
		{"by a region nothing is in", domain.ArticleFilter{Country: "US", Limit: 10}, 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.filter.Sort = domain.SortPublishedAt
			page, err := repo.List(ctx, tt.filter)
			if err != nil {
				t.Fatalf("List: %v", err)
			}
			if len(page.Items) != tt.want {
				t.Fatalf("matched %d articles, want %d", len(page.Items), tt.want)
			}
		})
	}
}

func TestArticleListBoundsThePublicationRange(t *testing.T) {
	repo := newTestArticleRepo(t)
	stored := seedArticles(t, repo, 5)

	// stored is newest first, so [3] and [1] bound the middle three.
	from := stored[3].PublishedAt
	to := stored[1].PublishedAt

	page, err := repo.List(testContext(t), domain.ArticleFilter{
		PublishedFrom: &from,
		PublishedTo:   &to,
		Limit:         10,
		Sort:          domain.SortPublishedAt,
	})
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	if len(page.Items) != 3 {
		t.Fatalf("matched %d articles, want the three inside the range", len(page.Items))
	}
	for _, a := range page.Items {
		if a.PublishedAt.Before(from) || a.PublishedAt.After(to) {
			t.Errorf("article published %v fell outside %v..%v", a.PublishedAt, from, to)
		}
	}
}

// Sorting by collection time is what a caller polling for new arrivals uses, so
// a back-dated article must still appear at the top of that timeline.
func TestArticleListSortsByCollectionTime(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	now := time.Now().UTC().Truncate(time.Millisecond)

	old := newArticle(t, "https://example.com/backdated", "backdated")
	old.PublishedAt = now.Add(-72 * time.Hour)
	old.CollectedAt = now

	recent := newArticle(t, "https://example.com/recent", "recent")
	recent.PublishedAt = now.Add(-time.Hour)
	recent.CollectedAt = now.Add(-30 * time.Minute)

	for _, a := range []*domain.Article{old, recent} {
		if err := repo.Create(ctx, a); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}

	byPublished, err := repo.List(ctx, domain.ArticleFilter{Limit: 10, Sort: domain.SortPublishedAt})
	if err != nil {
		t.Fatalf("List by published: %v", err)
	}
	byCollected, err := repo.List(ctx, domain.ArticleFilter{Limit: 10, Sort: domain.SortCollectedAt})
	if err != nil {
		t.Fatalf("List by collected: %v", err)
	}

	if byPublished.Items[0].ID != recent.ID {
		t.Errorf("published timeline starts with %q, want the recently published one", byPublished.Items[0].Title)
	}
	if byCollected.Items[0].ID != old.ID {
		t.Errorf("collected timeline starts with %q, want the just-collected one", byCollected.Items[0].Title)
	}
}

// Every listing shape must be answered from an index alone — no collection
// scan, and no blocking sort either: one page must not cost a read of every
// article that matched.
func TestArticleListQueriesAreIndexed(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	seedArticles(t, repo, 3)

	cursor := domain.ArticleCursor{Value: time.Now().UTC(), ID: "0198f3d2-3333-7000-8000-000000000001"}

	tests := []struct {
		name   string
		filter domain.ArticleFilter
	}{
		{"unfiltered", domain.ArticleFilter{}},
		{"by source", domain.ArticleFilter{SourceID: seedSourceID}},
		{"by language", domain.ArticleFilter{Language: "en"}},
		{"by region", domain.ArticleFilter{Country: "IN", State: "Karnataka", City: "Bengaluru"}},
		{"by collection time", domain.ArticleFilter{Sort: domain.SortCollectedAt}},
		{"with a cursor", domain.ArticleFilter{Cursor: &cursor}},
		{"by source with a cursor", domain.ArticleFilter{SourceID: seedSourceID, Cursor: &cursor}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			filter := tt.filter
			filter.Normalize()

			plan, err := explainList(ctx, repo, filter)
			if err != nil {
				t.Fatalf("explain: %v", err)
			}
			if stage := winningStage(plan); stage != "IXSCAN" {
				t.Fatalf("query plan is a %s, want an index-only plan: %s", stage, plan)
			}
		})
	}
}
