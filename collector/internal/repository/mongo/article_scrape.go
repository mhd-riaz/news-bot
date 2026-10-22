package mongo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// ClaimForScraping takes the longest-waiting eligible article and marks it in
// flight in one round trip.
//
// FindOneAndUpdate is what makes the claim safe: the match and the write happen
// under the same document lock, so of two workers reaching the same article
// exactly one sees it as claimable. A find followed by an update would let both
// pass the find and both fetch the page.
func (r *ArticleRepository) ClaimForScraping(ctx context.Context, claim domain.ScrapeClaim) (*domain.Article, error) {
	statuses := domain.RetryableScrapeStatuses()

	filter := bson.D{
		{Key: "scrape_status", Value: bson.D{{Key: "$in", Value: statuses}}},
		{Key: "next_scrape_at", Value: bson.D{{Key: "$lte", Value: claim.Now}}},
		{Key: "scrape_attempts", Value: bson.D{{Key: "$lt", Value: claim.MaxAttempts}}},
	}
	// A zero bound means "no age limit", which is what a backfill wants.
	if !claim.PublishedAfter.IsZero() {
		filter = append(filter, bson.E{
			Key:   "published_at",
			Value: bson.D{{Key: "$gte", Value: claim.PublishedAfter}},
		})
	}

	update := bson.D{
		{Key: "$set", Value: bson.D{
			{Key: "scrape_status", Value: domain.ScrapeStatusScraping},
			{Key: "scraped_at", Value: claim.Now},
		}},
		{Key: "$inc", Value: bson.D{{Key: "scrape_attempts", Value: 1}}},
	}

	opts := options.FindOneAndUpdate().
		// Oldest due first, so a backlog drains in the order it built up rather
		// than starving whatever was queued while the run was behind.
		SetSort(bson.D{{Key: "next_scrape_at", Value: 1}}).
		SetReturnDocument(options.After)

	var a domain.Article
	if err := r.coll.FindOneAndUpdate(ctx, filter, update, opts).Decode(&a); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: claim article for scraping: %w", err)
	}
	return &a, nil
}

// UpdateScrapeResult writes one finished attempt as a single update.
//
// Only the fields the attempt owns are touched. The article was read minutes
// ago and the whole document written back would revert anything that changed in
// between; more to the point, content_hash and the identity keys are not the
// enrichment stage's to rewrite.
func (r *ArticleRepository) UpdateScrapeResult(ctx context.Context, id string, result domain.ScrapeResult) error {
	set := bson.D{
		{Key: "scrape_status", Value: result.Status},
		{Key: "scraped_at", Value: result.At},
	}

	// An empty body means the attempt found nothing worth storing, so the text
	// already held is left where it is rather than being blanked.
	if result.Content != "" {
		set = append(set, bson.E{Key: "content", Value: result.Content})
	}
	// The article is promoted only once its stored text is the whole story.
	// A failure leaves it "collected", which describes what is held honestly.
	if result.Status.HasFullText() {
		set = append(set, bson.E{Key: "processing_status", Value: domain.ProcessingStatusEnriched})
	}
	if result.NextAt != nil {
		set = append(set, bson.E{Key: "next_scrape_at", Value: *result.NextAt})
	}

	update := bson.D{{Key: "$set", Value: set}}
	if result.NextAt == nil {
		// Removing the field, rather than leaving a stale instant behind, is
		// what keeps a terminal article out of every future backlog query.
		update = append(update, bson.E{
			Key:   "$unset",
			Value: bson.D{{Key: "next_scrape_at", Value: ""}},
		})
	}

	res, err := r.coll.UpdateByID(ctx, id, update)
	if err != nil {
		return fmt.Errorf("mongo: update scrape result: %w", err)
	}
	if res.MatchedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}

// ReleaseStaleScrapeClaims returns abandoned claims to the backlog.
//
// A claim is only stale because the worker holding it died: a live one always
// writes a result. The articles are made due immediately rather than at some
// future instant, since the wait they already served was not a backoff.
func (r *ArticleRepository) ReleaseStaleScrapeClaims(ctx context.Context, claimedBefore time.Time) (int64, error) {
	filter := bson.D{
		{Key: "scrape_status", Value: domain.ScrapeStatusScraping},
		{Key: "scraped_at", Value: bson.D{{Key: "$lt", Value: claimedBefore}}},
	}
	update := bson.D{{Key: "$set", Value: bson.D{
		{Key: "scrape_status", Value: domain.ScrapeStatusPending},
		{Key: "next_scrape_at", Value: claimedBefore},
	}}}

	res, err := r.coll.UpdateMany(ctx, filter, update)
	if err != nil {
		return 0, fmt.Errorf("mongo: release stale scrape claims: %w", err)
	}
	return res.ModifiedCount, nil
}
