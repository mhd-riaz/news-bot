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
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/repository"
)

// ArticleRepository stores collected articles in the articles collection.
type ArticleRepository struct {
	coll *driver.Collection
}

// NewArticleRepository binds the repository to the articles collection.
func NewArticleRepository(db *driver.Database) *ArticleRepository {
	return &ArticleRepository{coll: db.Collection(mongodb.CollectionArticles)}
}

var _ repository.ArticleRepository = (*ArticleRepository)(nil)

// Create inserts an article. Any of uq_dedup_id, uq_normalized_url and
// uq_source_feed_guid may reject it; all three mean the same thing to a caller,
// so all three come back as ErrDuplicate.
func (r *ArticleRepository) Create(ctx context.Context, a *domain.Article) error {
	now := time.Now().UTC().Truncate(time.Millisecond)
	a.InsertedAt = now
	a.UpdatedAt = now
	if _, err := r.coll.InsertOne(ctx, a); err != nil {
		if driver.IsDuplicateKeyError(err) {
			return repository.ErrDuplicate
		}
		return fmt.Errorf("mongo: insert article: %w", err)
	}
	return nil
}

// FindByIdentity looks the article up by each of its keys in turn and returns
// the first match.
//
// The keys are queried one at a time rather than combined into a single $or so
// the documented precedence is the precedence that actually runs, and so every
// query is served by exactly one index. The common case — a feed re-publishing
// an article this collector already has — matches on the first query.
func (r *ArticleRepository) FindByIdentity(ctx context.Context, identity domain.ArticleIdentity) (*domain.Article, error) {
	filters := make([]bson.D, 0, 4)

	if identity.NormalizedURL != "" {
		filters = append(filters, bson.D{{Key: "normalized_url", Value: identity.NormalizedURL}})
	}
	if identity.CanonicalURL != "" {
		filters = append(filters, bson.D{{Key: "canonical_url", Value: identity.CanonicalURL}})
	}
	if identity.SourceID != "" && identity.FeedGUID != "" {
		filters = append(filters, bson.D{
			{Key: "source_id", Value: identity.SourceID},
			{Key: "feed_guid", Value: identity.FeedGUID},
		})
	}
	// The content hash is only conclusive within one source: two sources may
	// legitimately syndicate the same story, and both are worth keeping.
	if identity.SourceID != "" && identity.ContentHash != "" {
		filters = append(filters, bson.D{
			{Key: "source_id", Value: identity.SourceID},
			{Key: "content_hash", Value: identity.ContentHash},
		})
	}

	for _, filter := range filters {
		a, err := r.findOne(ctx, filter)
		if err == nil {
			return a, nil
		}
		if !errors.Is(err, repository.ErrNotFound) {
			return nil, err
		}
	}
	return nil, repository.ErrNotFound
}

func (r *ArticleRepository) findOne(ctx context.Context, filter bson.D) (*domain.Article, error) {
	var a domain.Article
	if err := r.coll.FindOne(ctx, filter).Decode(&a); err != nil {
		if errors.Is(err, driver.ErrNoDocuments) {
			return nil, repository.ErrNotFound
		}
		return nil, fmt.Errorf("mongo: find article: %w", err)
	}
	return &a, nil
}

// GetByID returns one article in full, content included.
func (r *ArticleRepository) GetByID(ctx context.Context, id string) (*domain.Article, error) {
	return r.findOne(ctx, bson.D{{Key: "_id", Value: id}})
}

// GetByIDs hydrates a bounded ranked page in one query without transferring full bodies.
func (r *ArticleRepository) GetByIDs(ctx context.Context, ids []string) ([]domain.Article, error) {
	if len(ids) > 30 {
		return nil, errors.New("mongo: article batch must contain at most 30 IDs")
	}
	for _, id := range ids {
		if err := domain.ValidateID(id); err != nil {
			return nil, err
		}
	}
	if len(ids) == 0 {
		return []domain.Article{}, nil
	}
	cursor, err := r.coll.Find(ctx, bson.D{{Key: "_id", Value: bson.D{{Key: "$in", Value: ids}}}},
		options.Find().SetProjection(bson.D{{Key: "content", Value: 0}, {Key: "summary", Value: 0}}))
	if err != nil {
		return nil, fmt.Errorf("mongo: hydrate recommended articles: %w", err)
	}
	defer cursor.Close(ctx)
	var articles []domain.Article
	if err := cursor.All(ctx, &articles); err != nil {
		return nil, fmt.Errorf("mongo: decode recommended articles: %w", err)
	}
	return articles, nil
}

// List returns a page of articles, newest first.
//
// One more article than the caller asked for is read, which is how the page
// knows whether another one follows without counting the whole match. The
// content is projected away: fifty articles at up to 200 KB each is a response
// nobody wants, and a caller who needs the text reads the article itself.
func (r *ArticleRepository) List(ctx context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error) {
	field := articleSortField(filter.Sort)

	opts := options.Find().
		SetSort(bson.D{{Key: field, Value: -1}, {Key: "_id", Value: -1}}).
		SetLimit(int64(filter.Limit) + 1).
		SetProjection(bson.D{{Key: "content", Value: 0}})

	cursor, err := r.coll.Find(ctx, articleQuery(filter, field), opts)
	if err != nil {
		return domain.ArticlePage{}, fmt.Errorf("mongo: find articles: %w", err)
	}
	defer func() { _ = cursor.Close(ctx) }()

	items := make([]domain.Article, 0, filter.Limit+1)
	if err := cursor.All(ctx, &items); err != nil {
		return domain.ArticlePage{}, fmt.Errorf("mongo: decode articles: %w", err)
	}

	page := domain.ArticlePage{Limit: filter.Limit}
	if len(items) > filter.Limit {
		items = items[:filter.Limit]
		page.HasMore = true
		page.NextCursor = filter.CursorFor(items[len(items)-1])
	}
	page.Items = items
	return page, nil
}

// DeleteOlderThan removes the articles the deletion selects.
//
// The whole match goes in one DeleteMany rather than in batches: the bound is
// on published_at, which is indexed, and a sweep run on a schedule has no
// reader waiting on it.
func (r *ArticleRepository) DeleteOlderThan(ctx context.Context, d domain.ArticleDeletion) (int64, error) {
	res, err := r.coll.DeleteMany(ctx, articleDeletionQuery(d))
	if err != nil {
		return 0, fmt.Errorf("mongo: delete articles: %w", err)
	}
	return res.DeletedCount, nil
}

// articleDeletionQuery builds the sweep's filter from typed, already-validated
// values, the same way articleQuery does. The bound is exclusive, so an article
// published exactly at it survives and a caller can sweep the same instant
// twice without the second run taking anything the first left on purpose.
func articleDeletionQuery(d domain.ArticleDeletion) bson.D {
	query := bson.D{{Key: "published_at", Value: bson.D{{Key: "$lt", Value: d.OlderThan}}}}

	if d.SourceID != "" {
		query = append(query, bson.E{Key: "source_id", Value: d.SourceID})
	}
	if d.SourceName != "" {
		query = append(query, bson.E{Key: "source_name", Value: d.SourceName})
	}

	return query
}

// articleSortField maps the requested order onto the field that carries it. The
// enum is validated in the domain, so anything unexpected here means a caller
// inside this process got it wrong, and the safe default is the published
// timeline rather than an unindexed field name.
func articleSortField(sort domain.ArticleSort) string {
	if sort == domain.SortCollectedAt {
		return "collected_at"
	}
	return "published_at"
}

// articleQuery builds the filter document field by field from typed,
// already-validated values. Nothing the caller supplied is ever spliced in as a
// document, so a crafted parameter or cursor cannot inject a query operator.
func articleQuery(f domain.ArticleFilter, sortField string) bson.D {
	query := bson.D{}

	if f.SourceID != "" {
		query = append(query, bson.E{Key: "source_id", Value: f.SourceID})
	}
	if f.Language != "" {
		query = append(query, bson.E{Key: "language", Value: f.Language})
	}
	if f.Country != "" {
		query = append(query, bson.E{Key: "country", Value: f.Country})
	}
	if f.State != "" {
		query = append(query, bson.E{Key: "state", Value: f.State})
	}
	if f.City != "" {
		query = append(query, bson.E{Key: "city", Value: f.City})
	}
	if f.Topic != "" {
		query = append(query, bson.E{Key: "topic", Value: f.Topic})
	}

	if bounds := publishedBounds(f); len(bounds) > 0 {
		query = append(query, bson.E{Key: "published_at", Value: bounds})
	}

	// Resume strictly after the last article of the previous page. Both arms
	// are served by the same (sort field, _id) index, and because an article id
	// is a UUIDv7 its lexicographic order is chronological, so the tiebreaker
	// orders ties the same way the sort field would have.
	if c := f.Cursor; c != nil {
		query = append(query, bson.E{Key: "$or", Value: bson.A{
			bson.D{{Key: sortField, Value: bson.D{{Key: "$lt", Value: c.Value}}}},
			bson.D{
				{Key: sortField, Value: c.Value},
				{Key: "_id", Value: bson.D{{Key: "$lt", Value: c.ID}}},
			},
		}})
	}

	return query
}

func publishedBounds(f domain.ArticleFilter) bson.D {
	bounds := bson.D{}
	if f.PublishedFrom != nil {
		bounds = append(bounds, bson.E{Key: "$gte", Value: *f.PublishedFrom})
	}
	if f.PublishedTo != nil {
		bounds = append(bounds, bson.E{Key: "$lte", Value: *f.PublishedTo})
	}
	return bounds
}
