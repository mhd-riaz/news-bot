package service

import (
	"context"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// ArticleService reads collected articles and expires old ones. Articles are
// written only by the collection pipeline, so there is no way to create or edit
// one through this service; the single write it offers is the retention sweep
// that stops the collection growing without bound.
type ArticleService struct {
	repo repository.ArticleRepository
}

// NewArticleService wires the service.
func NewArticleService(repo repository.ArticleRepository) *ArticleService {
	return &ArticleService{repo: repo}
}

// List returns the page of articles matching filter, newest first.
func (s *ArticleService) List(ctx context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error) {
	filter.Normalize()
	if err := filter.Validate(); err != nil {
		return domain.ArticlePage{}, err
	}

	page, err := s.repo.List(ctx, filter)
	if err != nil {
		return domain.ArticlePage{}, translate(err)
	}
	return page, nil
}

// Get returns one article in full.
func (s *ArticleService) Get(ctx context.Context, id string) (*domain.Article, error) {
	if err := domain.ValidateID(id); err != nil {
		return nil, err
	}

	article, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return nil, translate(err)
	}
	return article, nil
}

// DeleteOlderThan expires the articles the deletion selects and reports how
// many went. A sweep that matches nothing is a success, not a not-found.
func (s *ArticleService) DeleteOlderThan(ctx context.Context, d domain.ArticleDeletion) (int64, error) {
	d.Normalize()
	if err := d.Validate(); err != nil {
		return 0, err
	}

	deleted, err := s.repo.DeleteOlderThan(ctx, d)
	if err != nil {
		return 0, translate(err)
	}
	return deleted, nil
}
