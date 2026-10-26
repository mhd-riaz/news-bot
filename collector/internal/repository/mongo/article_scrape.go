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
	changed := bson.A{}
	set := bson.D{
		{Key: "scrape_status", Value: result.Status},
		{Key: "scraped_at", Value: result.At},
	}
	if result.Content != "" {
		changed = append(changed, bson.D{{Key: "$ne", Value: bson.A{
			"$content", bson.D{{Key: "$literal", Value: result.Content}},
		}}})
		set = append(set, bson.E{
			Key: "content", Value: bson.D{{Key: "$literal", Value: result.Content}},
		})
	}
	validPageDate := result.PublishedAt != nil && !result.PublishedAt.IsZero() &&
		!result.PublishedAt.After(result.At.Add(time.Hour))
	if validPageDate {
		changed = append(changed,
			bson.D{{Key: "$ne", Value: bson.A{"$published_at", *result.PublishedAt}}},
			bson.D{{Key: "$ne", Value: bson.A{
				"$published_at_source", domain.PublicationDateSourcePage,
			}}},
			bson.D{{Key: "$ne", Value: bson.A{"$date_verified", true}}},
		)
		set = append(set,
			bson.E{Key: "published_at", Value: *result.PublishedAt},
			bson.E{Key: "published_at_source", Value: domain.PublicationDateSourcePage},
			bson.E{Key: "date_verified", Value: true},
		)
	}
	if result.ImageURL != "" {
		imageMissing := bson.D{{Key: "$eq", Value: bson.A{
			bson.D{{Key: "$ifNull", Value: bson.A{"$image_url", ""}}}, "",
		}}}
		changed = append(changed, bson.D{{Key: "$and", Value: bson.A{
			imageMissing,
			bson.D{{Key: "$ne", Value: bson.A{
				"$image_url", bson.D{{Key: "$literal", Value: result.ImageURL}},
			}}},
		}}})
		set = append(set, bson.E{
			Key: "image_url",
			Value: bson.D{{Key: "$cond", Value: bson.A{
				imageMissing, bson.D{{Key: "$literal", Value: result.ImageURL}}, "$image_url",
			}}},
		})
	}
	if result.Status.HasFullText() {
		set = append(set, bson.E{Key: "processing_status", Value: domain.ProcessingStatusEnriched})
	}
	if result.NextAt != nil {
		set = append(set, bson.E{Key: "next_scrape_at", Value: *result.NextAt})
	} else {
		set = append(set, bson.E{Key: "next_scrape_at", Value: "$$REMOVE"})
	}

	if len(changed) > 0 {
		conditional := bson.D{
			{Key: "classification_status", Value: domain.ClassificationStatusPending},
			{Key: "classification_attempts", Value: 0},
			{Key: "classification_claimed_at", Value: "$$REMOVE"},
			{Key: "content_rev", Value: bson.D{{Key: "$add", Value: bson.A{
				bson.D{{Key: "$ifNull", Value: bson.A{"$content_rev", int64(0)}}}, int64(1),
			}}}},
			{Key: "updated_at", Value: "$$NOW"},
		}
		for _, field := range conditional {
			set = append(set, bson.E{Key: field.Key, Value: bson.D{{Key: "$cond", Value: bson.A{
				bson.D{{Key: "$or", Value: changed}}, field.Value, "$" + field.Key,
			}}}})
		}
	}

	update := driver.Pipeline{bson.D{{Key: "$set", Value: set}}}
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
