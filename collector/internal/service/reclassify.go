package service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/mhd-riaz/news-bot/collector/internal/classifier"
	"github.com/mhd-riaz/news-bot/collector/internal/domain"
)

// ReclassificationRepository reads articles labelled by an older model and
// conditionally replaces their topic outcome.
type ReclassificationRepository interface {
	ListForReclassification(context.Context, string, string, int) ([]domain.Article, error)
	ReclassifyIfCurrent(context.Context, string, int64, domain.Reclassification) (bool, error)
}

// ReclassificationDeps supplies persistence, classification and batch limits.
type ReclassificationDeps struct {
	Articles   ReclassificationRepository
	Classifier classifier.Client
	BatchSize  int
	BatchDelay time.Duration
	Clock      Clock
}

// ReclassificationService relabels classified and unsorted articles with the
// sidecar's current model. Pending, classifying and failed articles stay with
// the classification backlog worker.
type ReclassificationService struct {
	deps ReclassificationDeps
}

// ReclassificationResult counts work completed or deferred by one run.
// Classified and Unsorted count the new labels that were written.
type ReclassificationResult struct {
	Batches    int
	Scanned    int
	Updated    int
	Skipped    int
	Classified int
	Unsorted   int
}

// NewReclassificationService bounds batches to the sidecar's supported maximum.
func NewReclassificationService(deps ReclassificationDeps) *ReclassificationService {
	if deps.BatchSize <= 0 || deps.BatchSize > MaxDerivedBackfillBatchSize {
		deps.BatchSize = MaxDerivedBackfillBatchSize
	}
	if deps.Clock == nil {
		deps.Clock = time.Now
	}
	return &ReclassificationService{deps: deps}
}

// Run visits at most limit articles on an older model version. Articles that
// changed since they were read, or that the sidecar could not classify, are
// skipped and never marked failed.
func (s *ReclassificationService) Run(ctx context.Context, limit int) (ReclassificationResult, error) {
	if limit < 1 {
		return ReclassificationResult{}, fmt.Errorf("service: reclassify limit must be greater than zero")
	}
	if s.deps.Articles == nil || s.deps.Classifier == nil {
		return ReclassificationResult{}, fmt.Errorf("service: reclassify dependencies are required")
	}
	if s.deps.BatchDelay < 0 {
		return ReclassificationResult{}, fmt.Errorf("service: reclassify batch delay must not be negative")
	}
	batchSize := min(s.deps.BatchSize, s.deps.Classifier.BatchSize())
	if batchSize < 1 {
		return ReclassificationResult{}, fmt.Errorf("service: classifier batch size must be greater than zero")
	}

	// The target is read once, before any article, so a sidecar swapped mid-run is
	// detected by the per-batch version check instead of silently mixing models.
	metadata, err := s.deps.Classifier.Metadata(ctx)
	if err != nil {
		return ReclassificationResult{}, fmt.Errorf("reclassify: read target model version: %w", err)
	}
	target := metadata.ModelVersion
	if strings.TrimSpace(target) == "" {
		return ReclassificationResult{}, fmt.Errorf("reclassify: classifier reported an empty model version")
	}

	var result ReclassificationResult
	var afterID string
	for result.Scanned < limit {
		if err := ctx.Err(); err != nil {
			return result, err
		}
		requestSize := min(batchSize, limit-result.Scanned)
		articles, err := s.deps.Articles.ListForReclassification(ctx, afterID, target, requestSize)
		if err != nil {
			return result, fmt.Errorf("reclassify: list articles: %w", err)
		}
		if len(articles) == 0 {
			break
		}
		if len(articles) > requestSize {
			return result, fmt.Errorf(
				"reclassify: repository returned %d articles for limit %d",
				len(articles), requestSize,
			)
		}

		predictions, err := s.classifyBatch(ctx, articles, target)
		if err != nil {
			return result, err
		}

		result.Batches++
		for index, article := range articles {
			result.Scanned++
			prediction := predictions[index]
			if prediction == nil {
				result.Skipped++
				continue
			}
			status := domain.ClassificationStatusUnsorted
			if prediction.Filed {
				status = domain.ClassificationStatusClassified
			}
			updated, err := s.deps.Articles.ReclassifyIfCurrent(ctx, article.ID, article.ContentRev, domain.Reclassification{
				Status: status, Topic: prediction.Topic, Confidence: prediction.Confidence,
				ModelVersion: prediction.ModelVersion, At: s.deps.Clock(),
			})
			if err != nil {
				return result, fmt.Errorf("reclassify: update article %s: %w", article.ID, err)
			}
			if !updated {
				result.Skipped++
				continue
			}
			result.Updated++
			if status == domain.ClassificationStatusClassified {
				result.Classified++
			} else {
				result.Unsorted++
			}
		}
		afterID = articles[len(articles)-1].ID

		if result.Scanned < limit && len(articles) == requestSize && s.deps.BatchDelay > 0 {
			if err := waitForNextBatch(ctx, s.deps.BatchDelay); err != nil {
				return result, err
			}
		}
	}
	return result, nil
}

// classifyBatch returns one prediction per article, or nil where the sidecar
// declined the article. It errors, before anything is written, when the
// sidecar's answer does not match the request or the target model version.
func (s *ReclassificationService) classifyBatch(
	ctx context.Context, articles []domain.Article, target string,
) ([]*classifier.Result, error) {
	predictions := make([]*classifier.Result, len(articles))
	indexes := make([]int, len(articles))
	for index := range articles {
		indexes[index] = index
	}

	results, err := s.classifyIndexes(ctx, articles, indexes)
	var declined *classifier.ItemError
	if errors.As(err, &declined) {
		known := make(map[string]bool, len(articles))
		for _, article := range articles {
			known[article.ID] = true
		}
		skip := make(map[string]bool, len(declined.IDs))
		for _, id := range declined.IDs {
			if !known[id] {
				return nil, fmt.Errorf("reclassify: classifier declined unknown article %q", id)
			}
			skip[id] = true
		}
		// Resubmit only the rest of the batch; the declined articles stay unchanged.
		indexes = indexes[:0]
		for index, article := range articles {
			if !skip[article.ID] {
				indexes = append(indexes, index)
			}
		}
		if len(indexes) == 0 {
			return predictions, nil
		}
		results, err = s.classifyIndexes(ctx, articles, indexes)
	}
	if err != nil {
		return nil, fmt.Errorf("reclassify: classify batch: %w", err)
	}

	if len(results) != len(indexes) {
		return nil, fmt.Errorf(
			"reclassify: classifier returned %d results for %d articles", len(results), len(indexes),
		)
	}
	for position, index := range indexes {
		prediction := results[position]
		if prediction.ID != articles[index].ID {
			return nil, fmt.Errorf(
				"reclassify: classifier returned ID %q for article %q", prediction.ID, articles[index].ID,
			)
		}
		if prediction.ModelVersion != target {
			return nil, fmt.Errorf(
				"reclassify: classifier model version changed from %q to %q during the run",
				target, prediction.ModelVersion,
			)
		}
		predictions[index] = &results[position]
	}
	return predictions, nil
}

func (s *ReclassificationService) classifyIndexes(
	ctx context.Context, articles []domain.Article, indexes []int,
) ([]classifier.Result, error) {
	items := make([]classifier.Item, len(indexes))
	for position, index := range indexes {
		article := &articles[index]
		items[position] = classifier.Item{
			ID: article.ID, Title: article.Title, Summary: article.Summary,
			Body: article.Content, Source: article.SourceName,
		}
	}
	return s.deps.Classifier.Classify(ctx, items)
}

func waitForNextBatch(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
