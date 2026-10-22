//go:build integration

package mongo

import (
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func newTestArticleRepo(t *testing.T) *ArticleRepository {
	t.Helper()
	return NewArticleRepository(newTestDatabase(t, "art"))
}

func newArticle(t *testing.T, link, guid string, mutate ...func(*domain.FeedItem)) *domain.Article {
	t.Helper()

	src := newSource(t, "https://example.com/feed.rss")
	published := time.Now().UTC().Add(-time.Hour)
	item := domain.FeedItem{
		Title:       "Reservoir levels rise",
		Link:        link,
		GUID:        guid,
		Summary:     "Inflows crossed the seasonal average.",
		PublishedAt: &published,
	}
	for _, m := range mutate {
		m(&item)
	}

	a, err := domain.NewArticle(*src, item, time.Now().UTC())
	if err != nil {
		t.Fatalf("NewArticle: %v", err)
	}
	return a
}

func TestArticleCreateAndReadBack(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	a := newArticle(t, "https://example.com/story/1", "story-1")

	if err := repo.Create(ctx, a); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.FindByIdentity(ctx, a.Identity())
	if err != nil {
		t.Fatalf("FindByIdentity: %v", err)
	}
	if got.ID != a.ID || got.NormalizedURL != a.NormalizedURL || got.DedupID != a.DedupID {
		t.Errorf("read back %+v, want %+v", got, a)
	}
	if got.Title != a.Title || got.SourceName != a.SourceName || got.City != a.City {
		t.Errorf("denormalised fields did not survive: %+v", got)
	}
	if !got.PublishedAt.Equal(a.PublishedAt) || !got.CollectedAt.Equal(a.CollectedAt) {
		t.Errorf("timestamps read back as %v / %v", got.PublishedAt, got.CollectedAt)
	}
	if got.ProcessingStatus != domain.ProcessingStatusCollected {
		t.Errorf("processing_status = %q", got.ProcessingStatus)
	}
}

// Each unique index must be what rejects a duplicate, so two collectors racing
// on the same article cannot both win.
func TestArticleCreateIsRejectedByEveryUniqueIndex(t *testing.T) {
	tests := []struct {
		name  string
		build func(t *testing.T) *domain.Article
	}{
		{
			name:  "same normalized url and dedup id",
			build: func(t *testing.T) *domain.Article { return newArticle(t, "https://example.com/story/1", "other-guid") },
		},
		{
			name: "same link wearing a tracking parameter",
			build: func(t *testing.T) *domain.Article {
				return newArticle(t, "https://example.com/story/1?utm_source=x", "other-guid")
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			repo := newTestArticleRepo(t)
			ctx := testContext(t)

			first := newArticle(t, "https://example.com/story/1", "story-1")
			if err := repo.Create(ctx, first); err != nil {
				t.Fatalf("Create: %v", err)
			}

			second := tc.build(t)
			second.SourceID = first.SourceID
			if err := repo.Create(ctx, second); !errors.Is(err, repository.ErrDuplicate) {
				t.Fatalf("Create = %v, want ErrDuplicate", err)
			}
		})
	}
}

func TestArticleCreateRejectsARepeatedFeedGUID(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	first := newArticle(t, "https://example.com/story/1", "story-1")
	if err := repo.Create(ctx, first); err != nil {
		t.Fatalf("Create: %v", err)
	}

	// A different URL, but the same identifier from the same publisher.
	second := newArticle(t, "https://example.com/story/1-amp", "story-1", func(i *domain.FeedItem) {
		i.Title = "Reservoir levels rise, updated"
	})
	second.SourceID = first.SourceID

	if err := repo.Create(ctx, second); !errors.Is(err, repository.ErrDuplicate) {
		t.Fatalf("Create = %v, want ErrDuplicate", err)
	}
}

// The GUID index is partial, so the articles that have no publisher identifier
// must not collide with each other on an empty one.
func TestArticleCreateAllowsManyArticlesWithoutAFeedGUID(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	for _, link := range []string{"https://example.com/a", "https://example.com/b"} {
		a := newArticle(t, link, "", func(i *domain.FeedItem) { i.Title = "Headline for " + link })
		if err := repo.Create(ctx, a); err != nil {
			t.Fatalf("Create(%s): %v", link, err)
		}
	}
}

func TestArticleFindByIdentityTriesEveryKey(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	stored := newArticle(t, "https://example.com/story/1", "https://example.com/permalink/1")
	if err := repo.Create(ctx, stored); err != nil {
		t.Fatalf("Create: %v", err)
	}

	tests := []struct {
		name     string
		identity domain.ArticleIdentity
	}{
		{name: "normalized url", identity: domain.ArticleIdentity{NormalizedURL: stored.NormalizedURL}},
		{
			name:     "canonical url",
			identity: domain.ArticleIdentity{NormalizedURL: "https://example.com/elsewhere", CanonicalURL: stored.CanonicalURL},
		},
		{
			name: "source and feed guid",
			identity: domain.ArticleIdentity{
				NormalizedURL: "https://example.com/elsewhere",
				SourceID:      stored.SourceID,
				FeedGUID:      stored.FeedGUID,
			},
		},
		{
			name: "content hash within the source",
			identity: domain.ArticleIdentity{
				NormalizedURL: "https://example.com/elsewhere",
				SourceID:      stored.SourceID,
				ContentHash:   stored.ContentHash,
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := repo.FindByIdentity(ctx, tc.identity)
			if err != nil {
				t.Fatalf("FindByIdentity: %v", err)
			}
			if got.ID != stored.ID {
				t.Errorf("found %s, want %s", got.ID, stored.ID)
			}
		})
	}
}

func TestArticleFindByIdentityReportsNoMatch(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	_, err := repo.FindByIdentity(ctx, domain.ArticleIdentity{
		NormalizedURL: "https://example.com/absent",
		SourceID:      "018f3f7e-1c2a-7f24-9a3f-8f9f2a0a5c11",
		ContentHash:   "nothing",
	})
	if !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("FindByIdentity = %v, want ErrNotFound", err)
	}
}

// Two sources may legitimately syndicate the same story, which is why the
// content-hash index is not unique and the lookup is scoped to one source.
func TestArticleContentHashDoesNotCollapseTwoSources(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	first := newArticle(t, "https://example.com/story/1", "story-1")
	if err := repo.Create(ctx, first); err != nil {
		t.Fatalf("Create: %v", err)
	}

	syndicated := newArticle(t, "https://mirror.example.net/story/1", "mirror-1")
	if syndicated.ContentHash != first.ContentHash {
		t.Fatalf("the fixtures should share a content hash: %q vs %q", syndicated.ContentHash, first.ContentHash)
	}

	if _, err := repo.FindByIdentity(ctx, syndicated.Identity()); !errors.Is(err, repository.ErrNotFound) {
		t.Fatalf("FindByIdentity = %v, want ErrNotFound for another source's copy", err)
	}
	if err := repo.Create(ctx, syndicated); err != nil {
		t.Fatalf("Create: %v", err)
	}
}
