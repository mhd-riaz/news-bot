package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// ClassificationDeps is everything ClassificationService needs to recover pending work.
type ClassificationDeps struct {
	Articles    repository.ArticleRepository
	Classifier  classifier.Client
	MaxAttempts int
	ClaimTTL    time.Duration
	Clock       Clock
	Logger      *slog.Logger
}

// ClassificationService retries articles that could not be classified before storage.
type ClassificationService struct {
	deps ClassificationDeps
}

// NewClassificationService applies safe defaults for optional dependencies.
func NewClassificationService(deps ClassificationDeps) *ClassificationService {
	if deps.MaxAttempts < 1 {
		deps.MaxAttempts = 3
	}
	if deps.ClaimTTL <= 0 {
		deps.ClaimTTL = 5 * time.Minute
	}
	if deps.Clock == nil {
		deps.Clock = time.Now
	}
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	return &ClassificationService{deps: deps}
}

// ClassificationBacklogResult counts outcomes from one backlog run.
type ClassificationBacklogResult struct {
	Claimed             int
	Classified          int
	Unsorted            int
	Retrying            int
	Failed              int
	StaleClaimsReleased int64
	Attempts            int
	MaxBackfillLag      time.Duration
}

// ProcessBacklog recovers up to limit pending classification attempts.
func (s *ClassificationService) ProcessBacklog(ctx context.Context, limit int) (ClassificationBacklogResult, error) {
	if limit < 1 {
		return ClassificationBacklogResult{}, fmt.Errorf("service: classification backlog limit must be greater than zero, got %d", limit)
	}
	if s.deps.Articles == nil || s.deps.Classifier == nil {
		return ClassificationBacklogResult{}, errors.New("service: classification dependencies are required")
	}

	var result ClassificationBacklogResult
	staleReleased, err := s.deps.Articles.ReleaseStaleClassificationClaims(ctx, s.deps.Clock().Add(-s.deps.ClaimTTL))
	if err != nil {
		s.deps.Logger.WarnContext(ctx, "classification: release stale claims", "error", err)
	}
	result.StaleClaimsReleased = staleReleased
	for index := 0; index < limit; index++ {
		if err := ctx.Err(); err != nil {
			return result, err
		}
		now := s.deps.Clock()
		article, err := s.deps.Articles.ClaimForClassification(ctx, domain.ClassificationClaim{
			Now: now, MaxAttempts: s.deps.MaxAttempts,
		})
		if errors.Is(err, repository.ErrNotFound) {
			break
		}
		if err != nil {
			return result, fmt.Errorf("classification: claim article: %w", err)
		}
		result.Claimed++
		result.Attempts += article.ClassificationAttempts
		if lag := now.Sub(article.CollectedAt); lag > result.MaxBackfillLag {
			result.MaxBackfillLag = lag
		}

		update := s.classify(ctx, article, now)
		if err := s.deps.Articles.UpdateClassification(ctx, article.ID, update); err != nil {
			if errors.Is(err, repository.ErrNotFound) {
				continue
			}
			return result, fmt.Errorf("classification: update article %s: %w", article.ID, err)
		}
		switch update.Status {
		case domain.ClassificationStatusClassified:
			result.Classified++
		case domain.ClassificationStatusUnsorted:
			result.Unsorted++
		case domain.ClassificationStatusPending:
			result.Retrying++
		case domain.ClassificationStatusFailed:
			result.Failed++
		}
	}
	return result, nil
}

func (s *ClassificationService) classify(ctx context.Context, article *domain.Article, now time.Time) domain.ClassificationResult {
	claimedAt := now
	if article.ClassificationClaimedAt != nil {
		claimedAt = *article.ClassificationClaimedAt
	}
	results, err := s.deps.Classifier.Classify(ctx, []classifier.Item{{
		ID: article.ID, Title: article.Title, Summary: article.Summary, Body: article.Content,
		Source: article.SourceName,
	}})
	if err != nil || len(results) != 1 {
		status := domain.ClassificationStatusPending
		if article.ClassificationAttempts >= s.deps.MaxAttempts {
			status = domain.ClassificationStatusFailed
		}
		return domain.ClassificationResult{Status: status, At: now, ClaimedAt: claimedAt}
	}
	prediction := results[0]
	status := domain.ClassificationStatusUnsorted
	if prediction.Filed {
		status = domain.ClassificationStatusClassified
	}
	return domain.ClassificationResult{
		Status: status, Topic: prediction.Topic, Confidence: prediction.Confidence,
		ModelVersion: prediction.ModelVersion, CleanTitle: prediction.CleanTitle,
		CleanSummary: prediction.CleanSummary, CleanBody: prediction.CleanBody,
		DetectedLanguage:   prediction.DetectedLanguage,
		LanguageConfidence: prediction.LanguageConfidence,
		At:                 now, ClaimedAt: claimedAt,
	}
}
