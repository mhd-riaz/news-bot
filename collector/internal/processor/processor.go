// Package processor turns the items a collector read out of a feed into stored
// articles. It is the only place that decides whether something has been seen
// before, so the deduplication order lives here and in the index plan that
// enforces it, nowhere else.
package processor

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/riaz/newscollector/internal/classifier"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// Clock supplies the current time. Injecting it keeps behaviour deterministic
// under test instead of depending on the wall clock.
type Clock func() time.Time

// Result counts what one batch did. Unclassified overlaps with stored articles:
// classifier outages leave valid items pending and are not a storage failure.
type Result struct {
	Items                 int
	Stored                int
	Duplicates            int
	Invalid               int
	Unclassified          int
	Classified            int
	Unsorted              int
	ClassifierAvailable   bool
	ClassificationLatency time.Duration
}

// Processor stores collected items.
type Processor struct {
	articles   repository.ArticleRepository
	classifier classifier.Client
	clock      Clock
}

// New wires the processor. A nil clock defaults to time.Now; no client leaves
// classification pending so collection can continue during an outage.
func New(articles repository.ArticleRepository, clock Clock, clients ...classifier.Client) *Processor {
	if clock == nil {
		clock = time.Now
	}
	var client classifier.Client
	if len(clients) > 0 {
		client = clients[0]
	}
	return &Processor{articles: articles, classifier: client, clock: clock}
}

// Process normalises, deduplicates and stores a batch of items collected from
// src, in that order, one item at a time.
//
// Items are handled sequentially so that two entries duplicating each other
// within the same batch are caught by the same lookup that catches a duplicate
// of an earlier collection. An item the model rejects is counted and skipped,
// because one malformed entry must not cost the rest of the feed. A repository
// failure, on the other hand, stops the batch: it means the database is not
// answering, and the counts so far are returned with the error so the caller
// can record what did get through.
func (p *Processor) Process(ctx context.Context, src *domain.Source, items []domain.FeedItem) (Result, error) {
	result := Result{Items: len(items)}
	if src == nil {
		return result, errors.New("processor: nil source")
	}

	articles := make([]*domain.Article, 0, len(items))
	for _, item := range items {
		article, err := domain.NewArticle(*src, item, p.clock())
		if err != nil {
			if errors.Is(err, domain.ErrValidation) {
				result.Invalid++
				continue
			}
			return result, err
		}

		articles = append(articles, article)
	}

	p.classify(ctx, articles, &result)

	for _, article := range articles {
		stored, err := p.store(ctx, article)
		switch {
		case err != nil:
			return result, err
		case stored:
			result.Stored++
		default:
			result.Duplicates++
		}
	}

	return result, nil
}

// classify submits articles in chunks no larger than the client's configured
// batch size: a feed poll can collect more new items than one classify call
// accepts, and a batch that violated that limit would fail whole rather than
// only the items past the cut.
func (p *Processor) classify(ctx context.Context, articles []*domain.Article, result *Result) {
	if len(articles) == 0 {
		return
	}
	if p.classifier == nil {
		result.Unclassified += len(articles)
		return
	}
	size := p.classifier.BatchSize()
	if size <= 0 || size > len(articles) {
		size = len(articles)
	}
	for start := 0; start < len(articles); start += size {
		end := min(start+size, len(articles))
		p.classifyChunk(ctx, articles[start:end], result)
	}
}

func (p *Processor) classifyChunk(ctx context.Context, articles []*domain.Article, result *Result) {
	items := make([]classifier.Item, len(articles))
	for index, article := range articles {
		items[index] = classifier.Item{
			ID: article.ID, Title: article.Title, Summary: article.Summary,
			Body: article.Content, Source: article.SourceName,
		}
	}
	started := time.Now()
	classified, err := p.classifier.Classify(ctx, items)
	result.ClassificationLatency += time.Since(started)
	if err != nil {
		result.Unclassified += len(articles)
		return
	}
	result.ClassifierAvailable = true
	for index, prediction := range classified {
		article := articles[index]
		article.Topic = prediction.Topic
		article.Confidence = prediction.Confidence
		article.ModelVersion = prediction.ModelVersion
		article.CleanTitle = prediction.CleanTitle
		article.CleanSummary = prediction.CleanSummary
		article.CleanBody = prediction.CleanBody
		article.DetectedLanguage = prediction.DetectedLanguage
		article.LanguageConfidence = prediction.LanguageConfidence
		classifiedAt := p.clock()
		article.ClassifiedAt = &classifiedAt
		if prediction.Filed {
			article.ClassificationStatus = domain.ClassificationStatusClassified
			result.Classified++
		} else {
			article.ClassificationStatus = domain.ClassificationStatusUnsorted
			result.Unsorted++
		}
	}
}

// store reports whether the article was new. The lookup answers the common case
// without a write, and the unique indexes settle the race the lookup cannot:
// between the read and the insert, another collector may have stored the same
// article, and a duplicate key there is the expected outcome rather than a fault.
func (p *Processor) store(ctx context.Context, article *domain.Article) (bool, error) {
	_, err := p.articles.FindByIdentity(ctx, article.Identity())
	switch {
	case err == nil:
		return false, nil
	case !errors.Is(err, repository.ErrNotFound):
		return false, fmt.Errorf("processor: look up article: %w", err)
	}

	switch err := p.articles.Create(ctx, article); {
	case err == nil:
		return true, nil
	case errors.Is(err, repository.ErrDuplicate):
		return false, nil
	default:
		return false, fmt.Errorf("processor: store article: %w", err)
	}
}
