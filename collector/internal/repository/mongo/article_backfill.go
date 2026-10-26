package mongo

import (
	"context"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
)

// ListMissingDerivedFields returns incomplete C1 articles after the supplied ID.
func (r *ArticleRepository) ListMissingDerivedFields(
	ctx context.Context, afterID string, limit int,
) ([]domain.Article, error) {
	if limit < 1 {
		return nil, fmt.Errorf("mongo: backfill limit must be greater than zero")
	}
	filter := missingDerivedFieldsFilter()
	if afterID != "" {
		filter = append(filter, bson.E{Key: "_id", Value: bson.D{{Key: "$gt", Value: afterID}}})
	}
	projection := bson.D{
		{Key: "_id", Value: 1},
		{Key: "source_name", Value: 1},
		{Key: "title", Value: 1},
		{Key: "summary", Value: 1},
		{Key: "content", Value: 1},
		{Key: "published_at", Value: 1},
		{Key: "published_at_source", Value: 1},
		{Key: "collected_at", Value: 1},
		{Key: "content_rev", Value: 1},
	}
	cursor, err := r.coll.Find(ctx, filter, options.Find().
		SetProjection(projection).
		SetSort(bson.D{{Key: "_id", Value: 1}}).
		SetHint("_id_").
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

// BackfillDerivedFieldsIfMissing fills absent C1 fields only if the article's
// revision still matches the snapshot used to compute them.
func (r *ArticleRepository) BackfillDerivedFieldsIfMissing(
	ctx context.Context, id string, revision int64, fields domain.ArticleDerivedFields,
) (bool, error) {
	filter := append(missingDerivedFieldsFilter(),
		bson.E{Key: "_id", Value: id},
		bson.E{Key: "$expr", Value: bson.D{{Key: "$eq", Value: bson.A{
			bson.D{{Key: "$ifNull", Value: bson.A{"$content_rev", int64(0)}}}, revision,
		}}}},
	)
	values := bson.D{
		{Key: "clean_title", Value: fields.CleanTitle},
		{Key: "clean_summary", Value: fields.CleanSummary},
		{Key: "clean_body", Value: fields.CleanBody},
		{Key: "detected_language", Value: fields.DetectedLanguage},
		{Key: "language_confidence", Value: fields.LanguageConfidence},
		{Key: "published_at_source", Value: fields.PublishedAtSource},
		{Key: "date_verified", Value: fields.DateVerified},
	}
	set := bson.D{}
	for _, field := range values {
		set = append(set, bson.E{Key: field.Key, Value: bson.D{{Key: "$ifNull", Value: bson.A{
			"$" + field.Key, bson.D{{Key: "$literal", Value: field.Value}},
		}}}})
	}
	// ponytail: legacy insert times are unknown; recover original times from audit logs if available.
	set = append(set,
		bson.E{Key: "inserted_at", Value: bson.D{{Key: "$ifNull", Value: bson.A{"$inserted_at", "$collected_at"}}}},
		bson.E{Key: "content_rev", Value: bson.D{{Key: "$add", Value: bson.A{
			bson.D{{Key: "$ifNull", Value: bson.A{"$content_rev", int64(0)}}}, int64(1),
		}}}},
		bson.E{Key: "updated_at", Value: "$$NOW"},
	)
	update := driver.Pipeline{bson.D{{Key: "$set", Value: set}}}
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

func missingDerivedFieldsFilter() bson.D {
	missing := bson.A{}
	for _, field := range []string{
		"clean_title", "clean_summary", "clean_body", "detected_language", "language_confidence",
		"published_at_source", "date_verified", "content_rev", "inserted_at", "updated_at",
	} {
		// Equality to null matches both absent and explicitly null fields.
		missing = append(missing, bson.D{{Key: field, Value: nil}})
	}
	return bson.D{{Key: "$or", Value: missing}}
}

var _ interface {
	ListMissingDerivedFields(context.Context, string, int) ([]domain.Article, error)
	BackfillDerivedFieldsIfMissing(context.Context, string, int64, domain.ArticleDerivedFields) (bool, error)
} = (*ArticleRepository)(nil)
