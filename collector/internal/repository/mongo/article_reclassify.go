package mongo

import (
	"context"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/mhd-riaz/news-bot/collector/internal/domain"
)

// ListForReclassification returns classified or unsorted articles whose model
// version differs from the target, after the supplied ID. A missing or empty
// model_version counts as different. Pending, classifying and failed articles
// belong to the classification backlog and are never returned.
func (r *ArticleRepository) ListForReclassification(
	ctx context.Context, afterID, targetModelVersion string, limit int,
) ([]domain.Article, error) {
	if limit < 1 {
		return nil, fmt.Errorf("mongo: reclassification limit must be greater than zero")
	}
	if targetModelVersion == "" {
		return nil, fmt.Errorf("mongo: reclassification target model version is required")
	}
	filter := reclassifiableFilter(targetModelVersion)
	if afterID != "" {
		filter = append(filter, bson.E{Key: "_id", Value: bson.D{{Key: "$gt", Value: afterID}}})
	}
	projection := bson.D{
		{Key: "_id", Value: 1},
		{Key: "source_name", Value: 1},
		{Key: "title", Value: 1},
		{Key: "summary", Value: 1},
		{Key: "content", Value: 1},
		{Key: "content_rev", Value: 1},
	}
	cursor, err := r.coll.Find(ctx, filter, options.Find().
		SetProjection(projection).
		SetSort(bson.D{{Key: "_id", Value: 1}}).
		SetHint("_id_").
		SetLimit(int64(limit)))
	if err != nil {
		return nil, fmt.Errorf("mongo: list articles for reclassification: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	var articles []domain.Article
	if err := cursor.All(ctx, &articles); err != nil {
		return nil, fmt.Errorf("mongo: decode articles for reclassification: %w", err)
	}
	return articles, nil
}

// ReclassifyIfCurrent replaces the topic outcome only if the article is still
// classified or unsorted, still on an older model version and still at the
// content revision the caller read. It reports false when nothing matched.
//
// Like UpdateClassification, it leaves content_rev and updated_at alone because
// no clean text or language field changes; only those bump the revision.
func (r *ArticleRepository) ReclassifyIfCurrent(
	ctx context.Context, id string, revision int64, result domain.Reclassification,
) (bool, error) {
	if result.Status != domain.ClassificationStatusClassified &&
		result.Status != domain.ClassificationStatusUnsorted {
		return false, fmt.Errorf("mongo: reclassification status %q is not classified or unsorted", result.Status)
	}
	if result.Topic == "" || result.ModelVersion == "" || result.At.IsZero() ||
		result.Confidence < 0 || result.Confidence > 1 {
		return false, fmt.Errorf("mongo: reclassification result for %s is incomplete", id)
	}

	filter := append(reclassifiableFilter(result.ModelVersion),
		bson.E{Key: "_id", Value: id},
		bson.E{Key: "$expr", Value: bson.D{{Key: "$eq", Value: bson.A{
			bson.D{{Key: "$ifNull", Value: bson.A{"$content_rev", int64(0)}}}, revision,
		}}}},
	)
	update := bson.D{{Key: "$set", Value: bson.D{
		{Key: "topic", Value: result.Topic},
		{Key: "confidence", Value: result.Confidence},
		{Key: "model_version", Value: result.ModelVersion},
		{Key: "classification_status", Value: result.Status},
		{Key: "classified_at", Value: result.At},
	}}}
	res, err := r.coll.UpdateOne(ctx, filter, update)
	if err != nil {
		return false, fmt.Errorf("mongo: reclassify article: %w", err)
	}
	if res.MatchedCount == 0 {
		return false, nil
	}
	if res.ModifiedCount != 1 {
		return false, fmt.Errorf("mongo: reclassify article %s matched without modifying", id)
	}
	return true, nil
}

func reclassifiableFilter(targetModelVersion string) bson.D {
	return bson.D{
		{Key: "classification_status", Value: bson.D{{Key: "$in", Value: bson.A{
			domain.ClassificationStatusClassified, domain.ClassificationStatusUnsorted,
		}}}},
		// $ne also matches an absent, null or empty model_version.
		{Key: "model_version", Value: bson.D{{Key: "$ne", Value: targetModelVersion}}},
	}
}

var _ interface {
	ListForReclassification(context.Context, string, string, int) ([]domain.Article, error)
	ReclassifyIfCurrent(context.Context, string, int64, domain.Reclassification) (bool, error)
} = (*ArticleRepository)(nil)
