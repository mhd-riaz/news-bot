//go:build integration

package mongo

import (
	"testing"

	"github.com/riaz/newscollector/internal/domain"
)

func TestDerivedFieldBackfillIsResumableAndLeavesTopicsAlone(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := newArticle(t, "https://example.com/backfill/1", "backfill-1")
	article.Topic = "existing-topic"
	if err := repo.Create(ctx, article); err != nil {
		t.Fatalf("Create: %v", err)
	}
	makeLegacyC1Regression(t, repo, article.ID)

	missing, err := repo.ListMissingDerivedFields(ctx, "", 50)
	if err != nil || len(missing) != 1 || missing[0].ID != article.ID {
		t.Fatalf("ListMissingDerivedFields = %#v, %v", missing, err)
	}
	fields := domain.ArticleDerivedFields{
		CleanTitle: "Clean headline", CleanSummary: "Clean summary", CleanBody: "Clean body",
		DetectedLanguage: "en", LanguageConfidence: 0.99,
		PublishedAtSource: domain.PublicationDateSourceFeed, DateVerified: true,
	}
	updated, err := repo.BackfillDerivedFieldsIfMissing(ctx, article.ID, 0, fields)
	if err != nil || !updated {
		t.Fatalf("BackfillDerivedFieldsIfMissing = %v, %v", updated, err)
	}
	updated, err = repo.BackfillDerivedFieldsIfMissing(ctx, article.ID, 0, fields)
	if err != nil || updated {
		t.Fatalf("repeated backfill = %v, %v; want no-op", updated, err)
	}

	got, err := repo.GetByID(ctx, article.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Topic != "existing-topic" {
		t.Errorf("backfill changed topic to %q", got.Topic)
	}
	if got.Title != article.Title || got.Content != article.Content || got.ContentHash != article.ContentHash {
		t.Error("backfill changed raw article text or identity")
	}
	if got.CleanTitle != fields.CleanTitle || got.CleanSummary != fields.CleanSummary ||
		got.CleanBody != fields.CleanBody || got.DetectedLanguage != fields.DetectedLanguage ||
		got.LanguageConfidence != fields.LanguageConfidence ||
		got.PublishedAtSource != fields.PublishedAtSource || !got.DateVerified {
		t.Errorf("backfilled fields = %+v", got)
	}
	if got.ContentRev != 1 || !got.UpdatedAt.After(article.UpdatedAt) {
		t.Errorf("backfill revision/timestamp = %d / %v", got.ContentRev, got.UpdatedAt)
	}
	if !got.InsertedAt.Equal(article.CollectedAt) {
		t.Errorf("legacy inserted_at = %v, want collected_at estimate %v", got.InsertedAt, article.CollectedAt)
	}
	missing, err = repo.ListMissingDerivedFields(ctx, "", 50)
	if err != nil || len(missing) != 0 {
		t.Errorf("remaining missing articles = %#v, %v", missing, err)
	}
	if updated, err := repo.BackfillDerivedFieldsIfMissing(ctx, "missing-id", 0, fields); err != nil || updated {
		t.Errorf("missing article backfill = %v, %v; want no-op", updated, err)
	}
}
