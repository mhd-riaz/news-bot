package service

import (
	"context"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/extract"
	"github.com/riaz/newscollector/internal/httpclient"
)

// TestProcessBacklogKeepsMetadataFromShortPages preserves metadata without persisting unusable body text.
func TestProcessBacklogKeepsMetadataFromShortPages(t *testing.T) {
	now := time.Date(2026, 8, 31, 10, 0, 0, 0, time.UTC)
	published := now.Add(-time.Hour)
	repo := newFakeEnrichmentRepo(*enrichArticle())
	service := NewEnrichmentService(EnrichmentDeps{
		Articles: repo, Robots: &fakeRobots{decision: allowedDecision()}, Limiter: newTestLimiter(),
		Fetcher: &fakeFetcher{resp: &httpclient.Response{
			StatusCode: 200, ContentType: "text/html",
			FinalURL: "https://www.thehindu.com/news/cities/mumbai/article71380097.ece",
		}},
		Extractor: &fakeExtractor{
			result: extract.Result{Text: "Short teaser", PublishedAt: &published, ImageURL: "https://example.com/image.jpg"},
			err:    domain.ErrExtractionEmpty,
		},
		Clock: func() time.Time { return now },
	})
	result, err := service.ProcessBacklog(context.Background(), 1)
	if err != nil || result.Retrying != 1 {
		t.Fatalf("ProcessBacklog = %+v, %v", result, err)
	}
	stored, ok := repo.resultFor(enrichArticle().ID)
	if !ok || stored.Content != "" || stored.Status != domain.ScrapeStatusExtractFailed ||
		stored.PublishedAt == nil || !stored.PublishedAt.Equal(published) ||
		stored.ImageURL != "https://example.com/image.jpg" || stored.NextAt == nil {
		t.Fatalf("short-page result = %+v", stored)
	}
}
