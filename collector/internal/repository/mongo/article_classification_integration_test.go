//go:build integration

package mongo

import (
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

func pendingClassificationArticle(t *testing.T, repo *ArticleRepository, link, guid string) *domain.Article {
	t.Helper()
	article := newArticle(t, link, guid)
	if err := repo.Create(testContext(t), article); err != nil {
		t.Fatalf("Create: %v", err)
	}
	return article
}

func classificationClaim(now time.Time) domain.ClassificationClaim {
	return domain.ClassificationClaim{Now: now, MaxAttempts: 3}
}

func TestClassificationClaimIsExclusiveAndCountsAttempts(t *testing.T) {
	repo := newTestArticleRepo(t)
	article := pendingClassificationArticle(t, repo, "https://example.com/classification/1", "classification-1")
	now := article.CollectedAt.Add(time.Second)

	claimed, err := repo.ClaimForClassification(testContext(t), classificationClaim(now))
	if err != nil {
		t.Fatalf("ClaimForClassification: %v", err)
	}
	if claimed.ID != article.ID || claimed.ClassificationStatus != domain.ClassificationStatusClassifying || claimed.ClassificationAttempts != 1 || claimed.ClassificationClaimedAt == nil {
		t.Errorf("unexpected claim result: %+v", claimed)
	}
	if _, err := repo.ClaimForClassification(testContext(t), classificationClaim(now)); !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("second claim error = %v, want ErrNotFound", err)
	}
}

func TestUpdateClassificationPreservesArticleContentAndClaimOwnership(t *testing.T) {
	repo := newTestArticleRepo(t)
	article := pendingClassificationArticle(t, repo, "https://example.com/classification/1", "classification-1")
	now := article.CollectedAt.Add(time.Second)
	claimed, err := repo.ClaimForClassification(testContext(t), classificationClaim(now))
	if err != nil {
		t.Fatalf("ClaimForClassification: %v", err)
	}
	if err := repo.UpdateClassification(testContext(t), article.ID, domain.ClassificationResult{
		Status: domain.ClassificationStatusClassified, Topic: "politics", Confidence: 0.9,
		ModelVersion: "v2-001", At: now, ClaimedAt: *claimed.ClassificationClaimedAt,
	}); err != nil {
		t.Fatalf("UpdateClassification: %v", err)
	}
	got, err := repo.GetByID(testContext(t), article.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Content != article.Content || got.ContentHash != article.ContentHash {
		t.Error("classification update rewrote article content or identity")
	}
	if got.Topic != "politics" || got.ClassificationClaimedAt != nil || got.ClassifiedAt == nil {
		t.Errorf("stored classification = %+v", got)
	}
	if err := repo.UpdateClassification(testContext(t), article.ID, domain.ClassificationResult{
		Status: domain.ClassificationStatusFailed, At: now, ClaimedAt: now,
	}); !errors.Is(err, repository.ErrNotFound) {
		t.Errorf("stale owner update error = %v, want ErrNotFound", err)
	}
}

func TestReleaseStaleClassificationClaims(t *testing.T) {
	repo := newTestArticleRepo(t)
	article := pendingClassificationArticle(t, repo, "https://example.com/classification/1", "classification-1")
	now := article.CollectedAt.Add(time.Second)
	if _, err := repo.ClaimForClassification(testContext(t), classificationClaim(now)); err != nil {
		t.Fatalf("ClaimForClassification: %v", err)
	}
	freed, err := repo.ReleaseStaleClassificationClaims(testContext(t), now.Add(time.Second))
	if err != nil || freed != 1 {
		t.Fatalf("ReleaseStaleClassificationClaims = %d, %v; want 1, nil", freed, err)
	}
	if _, err := repo.ClaimForClassification(testContext(t), classificationClaim(now.Add(2*time.Second))); err != nil {
		t.Errorf("reclaimed article was not pending: %v", err)
	}
}
