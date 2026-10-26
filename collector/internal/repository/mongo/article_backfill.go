package mongo

import (
	"context"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
)

// ListMissingContentRevision returns the oldest articles that have not yet
// received C1 backfill data.
func (r *ArticleRepository) ListMissingContentRevision(
	ctx context.Context, limit int,
) ([]domain.Article, error) {
	if limit < 1 {
		return nil, fmt.Errorf("mongo: backfill limit must be greater than zero")
	}
	filter := bson.D{{Key: "content_rev", Value: bson.D{{Key: "$exists", Value: false}}}}
	projection := bson.D{
		{Key: "_id", Value: 1},
		{Key: "source_name", Value: 1},
		{Key: "title", Value: 1},
		{Key: "summary", Value: 1},
		{Key: "content", Value: 1},
		{Key: "published_at", Value: 1},
		{Key: "collected_at", Value: 1},
	}
	cursor, err := r.coll.Find(ctx, filter, options.Find().
		SetProjection(projection).
		SetSort(bson.D{{Key: "_id", Value: 1}}).
		SetLimit(int64(limit)))
	if err != nil {
		return nil, fmt.Errorf("mongo: list articles missing C1 fields: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	var articles []domain.Article
	if err := cursor.All(ctx, &articles); err != nil {
		return nil, fmt.Errorf("mongo: decode articles missing C1 fields: %w", err)
	}
	return articles, nil
}

// BackfillDerivedFieldsIfMissing only fills C1 metadata on a legacy article.
// The content_rev predicate makes a completed backfill resumable and protects
// fields that another worker has already populated.
func (r *ArticleRepository) BackfillDerivedFieldsIfMissing(
	ctx context.Context, id string, fields domain.ArticleDerivedFields,
) (bool, error) {
	filter := bson.D{
		{Key: "_id", Value: id},
		{Key: "content_rev", Value: bson.D{{Key: "$exists", Value: false}}},
	}
	update := bson.D{
		{Key: "$set", Value: bson.D{
			{Key: "clean_title", Value: fields.CleanTitle},
			{Key: "clean_summary", Value: fields.CleanSummary},
			{Key: "clean_body", Value: fields.CleanBody},
			{Key: "detected_language", Value: fields.DetectedLanguage},
			{Key: "language_confidence", Value: fields.LanguageConfidence},
			{Key: "published_at_source", Value: fields.PublishedAtSource},
			{Key: "date_verified", Value: fields.DateVerified},
		}},
		{Key: "$inc", Value: bson.D{{Key: "content_rev", Value: 1}}},
		{Key: "$currentDate", Value: bson.D{{Key: "updated_at", Value: true}}},
	}
	result, err := r.coll.UpdateOne(ctx, filter, update)
	if err != nil {
		return false, fmt.Errorf("mongo: backfill C1 fields: %w", err)
	}
	if result.MatchedCount == 0 {
		return false, nil
	}
	if result.ModifiedCount != 1 {
		return false, fmt.Errorf("mongo: backfill C1 fields for %s matched without modifying", id)
	}
	return true, nil
}

var _ interface {
	ListMissingContentRevision(context.Context, int) ([]domain.Article, error)
	BackfillDerivedFieldsIfMissing(context.Context, string, domain.ArticleDerivedFields) (bool, error)
} = (*ArticleRepository)(nil)
