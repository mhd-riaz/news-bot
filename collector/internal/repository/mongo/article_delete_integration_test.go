//go:build integration

package mongo

import (
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
)

// seedAged stores one article published at the given age, attributed to the
// named source. The identifiers are derived from age so no two seeded articles
// collide on a unique index.
func seedAged(t *testing.T, repo *ArticleRepository, sourceID, sourceName string, age time.Duration) *domain.Article {
	t.Helper()

	slug := age.String()
	published := time.Now().UTC().Add(-age)
	a := newArticle(t, "https://example.com/story/"+slug, "story-"+slug, func(item *domain.FeedItem) {
		item.PublishedAt = &published
	})
	a.SourceID = sourceID
	a.SourceName = sourceName

	if err := repo.Create(testContext(t), a); err != nil {
		t.Fatalf("Create: %v", err)
	}
	return a
}

func remaining(t *testing.T, repo *ArticleRepository) []domain.Article {
	t.Helper()

	page, err := repo.List(testContext(t), domain.ArticleFilter{Limit: domain.MaxListLimit, Sort: domain.SortPublishedAt})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	return page.Items
}

func TestArticleDeleteOlderThanKeepsTheBoundItself(t *testing.T) {
	repo := newTestArticleRepo(t)
	sourceID := "0198f3d2-1111-7000-8000-000000000001"

	seedAged(t, repo, sourceID, "The Hindu", 72*time.Hour)
	recent := seedAged(t, repo, sourceID, "The Hindu", time.Hour)

	// The bound is exclusive, so the article published exactly at it survives.
	deleted, err := repo.DeleteOlderThan(testContext(t), domain.ArticleDeletion{OlderThan: recent.PublishedAt})
	if err != nil {
		t.Fatalf("DeleteOlderThan: %v", err)
	}

	if deleted != 1 {
		t.Fatalf("deleted = %d, want only the older article", deleted)
	}
	left := remaining(t, repo)
	if len(left) != 1 || left[0].ID != recent.ID {
		t.Fatalf("remaining = %+v, want only the recent article", left)
	}
}

func TestArticleDeleteOlderThanNarrowsToOneSource(t *testing.T) {
	repo := newTestArticleRepo(t)
	keptID := "0198f3d2-1111-7000-8000-000000000002"
	sweptID := "0198f3d2-1111-7000-8000-000000000001"
	bound := time.Now().UTC()

	kept := seedAged(t, repo, keptID, "Deccan Herald", 72*time.Hour)
	seedAged(t, repo, sweptID, "The Hindu", 96*time.Hour)

	deleted, err := repo.DeleteOlderThan(testContext(t), domain.ArticleDeletion{OlderThan: bound, SourceID: sweptID})
	if err != nil {
		t.Fatalf("DeleteOlderThan: %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}

	left := remaining(t, repo)
	if len(left) != 1 || left[0].ID != kept.ID {
		t.Fatalf("remaining = %+v, want the other source's article untouched", left)
	}
}

func TestArticleDeleteOlderThanNarrowsBySourceName(t *testing.T) {
	repo := newTestArticleRepo(t)
	bound := time.Now().UTC()

	kept := seedAged(t, repo, "0198f3d2-1111-7000-8000-000000000002", "Deccan Herald", 72*time.Hour)
	seedAged(t, repo, "0198f3d2-1111-7000-8000-000000000001", "The Hindu", 96*time.Hour)

	deleted, err := repo.DeleteOlderThan(testContext(t), domain.ArticleDeletion{OlderThan: bound, SourceName: "The Hindu"})
	if err != nil {
		t.Fatalf("DeleteOlderThan: %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}

	left := remaining(t, repo)
	if len(left) != 1 || left[0].ID != kept.ID {
		t.Fatalf("remaining = %+v, want only the named source swept", left)
	}
}

// A sweep that finds the collection already tidy has succeeded.
func TestArticleDeleteOlderThanReportsZeroWhenNothingMatches(t *testing.T) {
	repo := newTestArticleRepo(t)
	seedAged(t, repo, "0198f3d2-1111-7000-8000-000000000001", "The Hindu", time.Hour)

	deleted, err := repo.DeleteOlderThan(testContext(t), domain.ArticleDeletion{
		OlderThan: time.Now().UTC().Add(-365 * 24 * time.Hour),
	})
	if err != nil {
		t.Fatalf("DeleteOlderThan: %v", err)
	}
	if deleted != 0 {
		t.Errorf("deleted = %d, want 0", deleted)
	}
}
