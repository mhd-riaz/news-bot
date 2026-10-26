package service

import (
	"context"
	"fmt"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
)

const MaxDerivedBackfillBatchSize = 50

type DerivedFieldBackfillRepository interface {
	ListMissingContentRevision(context.Context, int) ([]domain.Article, error)
	BackfillDerivedFieldsIfMissing(
		context.Context, string, domain.ArticleDerivedFields,
	) (bool, error)
}

type DerivedFieldBackfillDeps struct {
	Articles   DerivedFieldBackfillRepository
	Classifier classifier.Client
	BatchSize  int
	BatchDelay time.Duration
}

type DerivedFieldBackfillService struct {
	deps DerivedFieldBackfillDeps
}

type DerivedFieldBackfillResult struct {
	Batches int
	Scanned int
	Updated int
	Skipped int
}

func NewDerivedFieldBackfillService(deps DerivedFieldBackfillDeps) *DerivedFieldBackfillService {
	if deps.BatchSize <= 0 || deps.BatchSize > MaxDerivedBackfillBatchSize {
		deps.BatchSize = MaxDerivedBackfillBatchSize
	}
	return &DerivedFieldBackfillService{deps: deps}
}

func (s *DerivedFieldBackfillService) Run(
	ctx context.Context, limit int,
) (DerivedFieldBackfillResult, error) {
	if limit < 1 {
		return DerivedFieldBackfillResult{}, fmt.Errorf("service: backfill limit must be greater than zero")
	}
	if s.deps.Articles == nil || s.deps.Classifier == nil {
		return DerivedFieldBackfillResult{}, fmt.Errorf("service: backfill dependencies are required")
	}
	if s.deps.BatchDelay < 0 {
		return DerivedFieldBackfillResult{}, fmt.Errorf("service: backfill batch delay must not be negative")
	}
	batchSize := min(s.deps.BatchSize, s.deps.Classifier.BatchSize())
	if batchSize < 1 {
		return DerivedFieldBackfillResult{}, fmt.Errorf("service: classifier batch size must be greater than zero")
	}

	var result DerivedFieldBackfillResult
	for result.Scanned < limit {
		if err := ctx.Err(); err != nil {
			return result, err
		}
		requestSize := min(batchSize, limit-result.Scanned)
		articles, err := s.deps.Articles.ListMissingContentRevision(ctx, requestSize)
		if err != nil {
			return result, fmt.Errorf("backfill: list missing articles: %w", err)
		}
		if len(articles) == 0 {
			break
		}
		if len(articles) > requestSize {
			return result, fmt.Errorf(
				"backfill: repository returned %d articles for limit %d",
				len(articles), requestSize,
			)
		}

		items := make([]classifier.Item, len(articles))
		for index := range articles {
			article := &articles[index]
			items[index] = classifier.Item{
				ID: article.ID, Title: article.Title, Summary: article.Summary,
				Body: article.Content, Source: article.SourceName,
			}
		}
		predictions, err := s.deps.Classifier.Classify(ctx, items)
		if err != nil {
			return result, fmt.Errorf("backfill: classify batch: %w", err)
		}
		if len(predictions) != len(articles) {
			return result, fmt.Errorf(
				"backfill: classifier returned %d results for %d articles",
				len(predictions), len(articles),
			)
		}
		for index, article := range articles {
			if predictions[index].ID != article.ID {
				return result, fmt.Errorf(
					"backfill: classifier returned ID %q for article %q",
					predictions[index].ID, article.ID,
				)
			}
		}

		result.Batches++
		for index, article := range articles {
			result.Scanned++
			prediction := predictions[index]
			fields := domain.ArticleDerivedFields{
				CleanTitle: prediction.CleanTitle, CleanSummary: prediction.CleanSummary,
				CleanBody: prediction.CleanBody, DetectedLanguage: prediction.DetectedLanguage,
				LanguageConfidence: prediction.LanguageConfidence,
				PublishedAtSource:  legacyDateSource(article),
			}
			fields.DateVerified = fields.PublishedAtSource != domain.PublicationDateSourceCollectedFallback
			updated, err := s.deps.Articles.BackfillDerivedFieldsIfMissing(ctx, article.ID, fields)
			if err != nil {
				return result, fmt.Errorf("backfill: update article %s: %w", article.ID, err)
			}
			if updated {
				result.Updated++
			} else {
				result.Skipped++
			}
		}

		if result.Scanned < limit && len(articles) == requestSize && s.deps.BatchDelay > 0 {
			timer := time.NewTimer(s.deps.BatchDelay)
			select {
			case <-ctx.Done():
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				return result, ctx.Err()
			case <-timer.C:
			}
		}
	}
	return result, nil
}

func legacyDateSource(article domain.Article) domain.PublicationDateSource {
	if article.PublishedAt.Equal(article.CollectedAt) {
		return domain.PublicationDateSourceCollectedFallback
	}
	return domain.PublicationDateSourceFeed
}
