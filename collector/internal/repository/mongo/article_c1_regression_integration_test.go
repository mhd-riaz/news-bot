//go:build integration

package mongo

import (
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"github.com/riaz/newscollector/internal/domain"
)

func makeLegacyC1Regression(t *testing.T, repo *ArticleRepository, id string) {
	t.Helper()
	unset := bson.D{}
	for _, field := range []string{
		"clean_title", "clean_summary", "clean_body", "detected_language", "language_confidence",
		"published_at_source", "date_verified", "content_rev", "inserted_at", "updated_at",
	} {
		unset = append(unset, bson.E{Key: field, Value: ""})
	}
	if _, err := repo.coll.UpdateByID(testContext(t), id, bson.D{{Key: "$unset", Value: unset}}); err != nil {
		t.Fatal(err)
	}
}

// TestC1RegressionEnrichmentResetIsClaimable exercises exhausted retry budgets after a material text change.
func TestC1RegressionEnrichmentResetIsClaimable(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := pendingArticle(t, repo, "https://example.com/r1", "r1")
	if _, err := repo.coll.UpdateByID(ctx, article.ID, bson.D{{Key: "$set", Value: bson.D{
		{Key: "classification_status", Value: domain.ClassificationStatusFailed},
		{Key: "classification_attempts", Value: 3},
	}}}); err != nil {
		t.Fatal(err)
	}
	now := dueAfter(article)
	if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
		t.Fatal(err)
	}
	if err := repo.UpdateScrapeResult(ctx, article.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusSuccess, Content: longBody(240), At: now,
	}); err != nil {
		t.Fatal(err)
	}
	claimed, err := repo.ClaimForClassification(ctx, classificationClaim(now.Add(time.Second)))
	if err != nil {
		t.Fatalf("re-pended article cannot be claimed: %v", err)
	}
	if claimed.ClassificationAttempts != 1 {
		t.Errorf("attempts after fresh claim = %d, want 1", claimed.ClassificationAttempts)
	}
}

// TestC1RegressionLegacyBackfillAfterLiveWrite checks both writers and page-date enrichment through completion.
func TestC1RegressionLegacyBackfillAfterLiveWrite(t *testing.T) {
	for _, path := range []string{"classification", "enrichment", "enrichment-with-page-date"} {
		t.Run(path, func(t *testing.T) {
			repo := newTestArticleRepo(t)
			ctx := testContext(t)
			article := pendingArticle(t, repo, "https://example.com/"+path, path)
			makeLegacyC1Regression(t, repo, article.ID)
			now := dueAfter(article)
			if path == "classification" {
				claimed, err := repo.ClaimForClassification(ctx, classificationClaim(now))
				if err != nil {
					t.Fatal(err)
				}
				if err := repo.UpdateClassification(ctx, article.ID, domain.ClassificationResult{
					Status: domain.ClassificationStatusClassified, Topic: "politics", Confidence: 0.9,
					ModelVersion: "v2-001", At: now, ClaimedAt: *claimed.ClassificationClaimedAt,
					CleanTitle: "$live-title", CleanSummary: "", CleanBody: "Live body",
					DetectedLanguage: "en", LanguageConfidence: 0.99,
				}); err != nil {
					t.Fatal(err)
				}
			} else {
				if _, err := repo.ClaimForScraping(ctx, defaultClaim(now)); err != nil {
					t.Fatal(err)
				}
				result := domain.ScrapeResult{
					Status: domain.ScrapeStatusSuccess, Content: longBody(240), At: now,
				}
				if path == "enrichment-with-page-date" {
					published := article.PublishedAt.Add(-time.Hour)
					result.PublishedAt = &published
				}
				if err := repo.UpdateScrapeResult(ctx, article.ID, result); err != nil {
					t.Fatal(err)
				}
			}

			candidates, err := repo.ListMissingDerivedFields(ctx, "", 50)
			if err != nil || len(candidates) != 1 {
				t.Fatalf("backfill candidates = %d, %v; want 1", len(candidates), err)
			}
			fields := domain.ArticleDerivedFields{
				CleanTitle: "$backfill-title", CleanSummary: "", CleanBody: "Backfill body",
				DetectedLanguage: "en", LanguageConfidence: 0.9,
				PublishedAtSource: domain.PublicationDateSourceFeed, DateVerified: true,
			}
			updated, err := repo.BackfillDerivedFieldsIfMissing(ctx, article.ID, candidates[0].ContentRev, fields)
			if err != nil || !updated {
				t.Fatalf("backfill = %v, %v", updated, err)
			}
			stored, err := repo.GetByID(ctx, article.ID)
			if err != nil {
				t.Fatal(err)
			}
			if !stored.InsertedAt.Equal(article.CollectedAt) || stored.UpdatedAt.IsZero() || stored.ContentRev != 2 {
				t.Errorf("C1 timestamps/revision = %v / %v / %d", stored.InsertedAt, stored.UpdatedAt, stored.ContentRev)
			}
			if path == "classification" {
				if stored.CleanTitle != "$live-title" || stored.CleanBody != "Live body" ||
					stored.Topic != "politics" || stored.LanguageConfidence != 0.99 {
					t.Errorf("backfill replaced live classification: %+v", stored)
				}
			} else if stored.CleanTitle != fields.CleanTitle || stored.CleanBody != fields.CleanBody {
				t.Errorf("missing cleaned text was not filled: %+v", stored)
			}
			if path == "enrichment-with-page-date" && stored.PublishedAtSource != domain.PublicationDateSourcePage {
				t.Errorf("backfill replaced page provenance with %q", stored.PublishedAtSource)
			}
			remaining, err := repo.ListMissingDerivedFields(ctx, "", 50)
			if err != nil || len(remaining) != 0 {
				t.Fatalf("remaining backfill candidates = %d, %v", len(remaining), err)
			}
		})
	}
}

// TestC1RegressionBackfillRejectsChangedSnapshot proves stale batch results cannot overwrite newer text-derived data.
func TestC1RegressionBackfillRejectsChangedSnapshot(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := pendingArticle(t, repo, "https://example.com/stale-backfill", "stale-backfill")
	makeLegacyC1Regression(t, repo, article.ID)
	snapshot, err := repo.ListMissingDerivedFields(ctx, "", 1)
	if err != nil || len(snapshot) != 1 {
		t.Fatalf("snapshot = %+v, %v", snapshot, err)
	}
	if err := repo.UpdateScrapeResult(ctx, article.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusSuccess, Content: longBody(240), At: dueAfter(article),
	}); err != nil {
		t.Fatal(err)
	}
	updated, err := repo.BackfillDerivedFieldsIfMissing(ctx, article.ID, snapshot[0].ContentRev, domain.ArticleDerivedFields{
		CleanTitle: "Stale title", CleanBody: "Stale body",
		DetectedLanguage: "en", LanguageConfidence: 0.99,
		PublishedAtSource: domain.PublicationDateSourceFeed, DateVerified: true,
	})
	if err != nil || updated {
		t.Fatalf("stale backfill = %v, %v; want no write", updated, err)
	}
	stored, err := repo.GetByID(ctx, article.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.CleanTitle != "" || stored.Content != longBody(240) || stored.ContentRev != 1 {
		t.Errorf("stale backfill changed live article: %+v", stored)
	}
}

// TestC1RegressionUnchangedEmptyDerivedFieldsKeepRevision checks BSON round-trip of legitimate empty and zero values.
func TestC1RegressionUnchangedEmptyDerivedFieldsKeepRevision(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := newArticle(t, "https://example.com/r4", "r4")
	article.CleanTitle, article.CleanSummary, article.CleanBody = article.Title, "", "Clean body"
	article.DetectedLanguage, article.LanguageConfidence = "und", 0
	if err := repo.Create(ctx, article); err != nil {
		t.Fatal(err)
	}
	now := article.CollectedAt.Add(time.Second)
	claimed, err := repo.ClaimForClassification(ctx, classificationClaim(now))
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.UpdateClassification(ctx, article.ID, domain.ClassificationResult{
		Status: domain.ClassificationStatusUnsorted, Topic: "unsorted", Confidence: 0.4,
		ModelVersion: "v2-001", At: now, ClaimedAt: *claimed.ClassificationClaimedAt,
		CleanTitle: article.CleanTitle, CleanBody: article.CleanBody, DetectedLanguage: "und",
	}); err != nil {
		t.Fatal(err)
	}
	stored, err := repo.GetByID(ctx, article.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.ContentRev != 1 || !stored.UpdatedAt.Equal(article.UpdatedAt) {
		t.Errorf("unchanged derived fields changed revision/time: %d / %v", stored.ContentRev, stored.UpdatedAt)
	}
}

// TestC1RegressionUnchangedScrapePreservesClassification checks the false branch of the conditional pipeline.
func TestC1RegressionUnchangedScrapePreservesClassification(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := newArticle(t, "https://example.com/unchanged-scrape", "unchanged-scrape", func(item *domain.FeedItem) {
		item.Content = "The same stored body."
	})
	article.ClassificationStatus = domain.ClassificationStatusClassifying
	article.ClassificationAttempts = 3
	article.ClassificationClaimedAt = &article.CollectedAt
	if err := repo.Create(ctx, article); err != nil {
		t.Fatal(err)
	}
	if err := repo.UpdateScrapeResult(ctx, article.ID, domain.ScrapeResult{
		Status: domain.ScrapeStatusNoNewContent, Content: article.Content, At: dueAfter(article),
	}); err != nil {
		t.Fatal(err)
	}
	stored, err := repo.GetByID(ctx, article.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.ClassificationStatus != domain.ClassificationStatusClassifying || stored.ClassificationAttempts != 3 ||
		stored.ClassificationClaimedAt == nil || !stored.ClassificationClaimedAt.Equal(article.CollectedAt) ||
		stored.ContentRev != 1 || !stored.UpdatedAt.Equal(article.UpdatedAt) {
		t.Errorf("unchanged scrape invalidated classification: %+v", stored)
	}
}

// TestC1RegressionBackfillCursorAndLimit checks keyset bounds and invalid batch limits.
func TestC1RegressionBackfillCursorAndLimit(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	for _, suffix := range []string{"a", "b", "c"} {
		article := pendingArticle(t, repo, "https://example.com/cursor/"+suffix, "cursor-"+suffix)
		makeLegacyC1Regression(t, repo, article.ID)
	}
	first, err := repo.ListMissingDerivedFields(ctx, "", 1)
	if err != nil || len(first) != 1 {
		t.Fatalf("first page = %+v, %v", first, err)
	}
	remaining, err := repo.ListMissingDerivedFields(ctx, first[0].ID, 50)
	if err != nil || len(remaining) != 2 {
		t.Fatalf("cursor page = %+v, %v", remaining, err)
	}
	for _, article := range remaining {
		if article.ID <= first[0].ID {
			t.Errorf("cursor returned already-scanned ID %q", article.ID)
		}
	}
	for _, limit := range []int{0, -1} {
		if _, err := repo.ListMissingDerivedFields(ctx, "", limit); err == nil {
			t.Errorf("limit %d was accepted", limit)
		}
	}
}
