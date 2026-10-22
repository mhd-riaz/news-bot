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

// ClaimForClassification atomically takes the oldest pending article.
func (r *ArticleRepository) ClaimForClassification(ctx context.Context, claim domain.ClassificationClaim) (*domain.Article, error) {
	filter := bson.D{
		{Key: "classification_status", Value: bson.D{{Key: "$in", Value: domain.RetryableClassificationStatuses()}}},
		{Key: "classification_attempts", Value: bson.D{{Key: "$lt", Value: claim.MaxAttempts}}},
	}
	if !claim.PublishedAfter.IsZero() {
		filter = append(filter, bson.E{Key: "published_at", Value: bson.D{{Key: "$gte", Value: claim.PublishedAfter}}})
	}

	update := bson.D{
		{Key: "$set", Value: bson.D{
			{Key: "classification_status", Value: domain.ClassificationStatusClassifying},
			{Key: "classification_claimed_at", Value: claim.Now},
		}},
		{Key: "$inc", Value: bson.D{{Key: "classification_attempts", Value: 1}}},
	}
	opts := options.FindOneAndUpdate().
		SetSort(bson.D{{Key: "collected_at", Value: 1}}).
		SetReturnDocument(options.After)

	var article domain.Article
	if err := r.coll.FindOneAndUpdate(ctx, filter, update, opts).Decode(&article); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: claim article for classification: %w", err)
	}
	return &article, nil
}

// UpdateClassification writes a result only while the claiming worker owns it.
func (r *ArticleRepository) UpdateClassification(ctx context.Context, id string, result domain.ClassificationResult) error {
	set := bson.D{{Key: "classification_status", Value: result.Status}}
	if result.Status == domain.ClassificationStatusClassified || result.Status == domain.ClassificationStatusUnsorted {
		set = append(set,
			bson.E{Key: "classified_at", Value: result.At},
			bson.E{Key: "topic", Value: result.Topic},
			bson.E{Key: "confidence", Value: result.Confidence},
			bson.E{Key: "model_version", Value: result.ModelVersion},
		)
	}

	filter := bson.D{{Key: "_id", Value: id}, {Key: "classification_status", Value: domain.ClassificationStatusClassifying}}
	if !result.ClaimedAt.IsZero() {
		filter = append(filter, bson.E{Key: "classification_claimed_at", Value: result.ClaimedAt})
	}
	update := bson.D{
		{Key: "$set", Value: set},
		{Key: "$unset", Value: bson.D{{Key: "classification_claimed_at", Value: ""}}},
	}

	res, err := r.coll.UpdateOne(ctx, filter, update)
	if err != nil {
		return fmt.Errorf("mongo: update classification: %w", err)
	}
	if res.MatchedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}

// ReleaseStaleClassificationClaims returns abandoned claims to the backlog.
func (r *ArticleRepository) ReleaseStaleClassificationClaims(ctx context.Context, claimedBefore time.Time) (int64, error) {
	filter := bson.D{
		{Key: "classification_status", Value: domain.ClassificationStatusClassifying},
		{Key: "classification_claimed_at", Value: bson.D{{Key: "$lt", Value: claimedBefore}}},
	}
	update := bson.D{
		{Key: "$set", Value: bson.D{{Key: "classification_status", Value: domain.ClassificationStatusPending}}},
		{Key: "$unset", Value: bson.D{{Key: "classification_claimed_at", Value: ""}}},
	}
	res, err := r.coll.UpdateMany(ctx, filter, update)
	if err != nil {
		return 0, fmt.Errorf("mongo: release stale classification claims: %w", err)
	}
	return res.ModifiedCount, nil
}
