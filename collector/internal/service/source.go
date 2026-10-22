// Package service orchestrates the application's use cases. It owns the rules
// that span more than one entity or need the clock, delegates persistence to
// repository interfaces, and knows nothing about HTTP or MongoDB.
package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

// Service-level sentinels. They exist so callers depend only on this package
// rather than reaching past it into the persistence contracts.
var (
	// ErrNotFound means the requested record does not exist.
	ErrNotFound = errors.New("service: not found")

	// ErrConflict means the request collided with an existing record.
	ErrConflict = errors.New("service: conflict")
)

// Clock supplies the current time. Injecting it keeps behaviour deterministic
// under test instead of depending on the wall clock.
type Clock func() time.Time

// SourceService implements source management.
type SourceService struct {
	repo  repository.SourceRepository
	clock Clock
}

// NewSourceService wires the service. A nil clock defaults to time.Now.
func NewSourceService(repo repository.SourceRepository, clock Clock) *SourceService {
	if clock == nil {
		clock = time.Now
	}
	return &SourceService{repo: repo, clock: clock}
}

// Create registers a new feed. A feed URL already in use is a conflict, decided
// by the unique index rather than by a prior read, so concurrent creates are safe.
func (s *SourceService) Create(ctx context.Context, in domain.SourceInput) (*domain.Source, error) {
	src, err := domain.NewSource(in, s.clock())
	if err != nil {
		return nil, err
	}

	if err := s.repo.Create(ctx, src); err != nil {
		if errors.Is(err, repository.ErrDuplicate) {
			return nil, fmt.Errorf("%w: a source with this feed URL already exists", ErrConflict)
		}
		return nil, err
	}
	return src, nil
}

// Get returns one source by identifier.
func (s *SourceService) Get(ctx context.Context, id string) (*domain.Source, error) {
	if err := domain.ValidateID(id); err != nil {
		return nil, err
	}

	src, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return nil, translate(err)
	}
	return src, nil
}

// List returns the page of sources matching filter.
func (s *SourceService) List(ctx context.Context, filter domain.SourceFilter) (domain.SourcePage, error) {
	filter.Normalize()
	if err := filter.Validate(); err != nil {
		return domain.SourcePage{}, err
	}

	page, err := s.repo.List(ctx, filter)
	if err != nil {
		return domain.SourcePage{}, translate(err)
	}
	return page, nil
}

// Update applies a partial change. The stored source is loaded, patched and
// re-validated as a whole, so no partial update can bypass a model rule.
func (s *SourceService) Update(ctx context.Context, id string, patch domain.SourcePatch) (*domain.Source, error) {
	if err := domain.ValidateID(id); err != nil {
		return nil, err
	}

	src, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return nil, translate(err)
	}
	if err := src.Apply(patch, s.clock()); err != nil {
		return nil, err
	}

	if err := s.repo.Update(ctx, src); err != nil {
		if errors.Is(err, repository.ErrDuplicate) {
			return nil, fmt.Errorf("%w: a source with this feed URL already exists", ErrConflict)
		}
		return nil, translate(err)
	}
	return src, nil
}

// Delete removes a source.
func (s *SourceService) Delete(ctx context.Context, id string) error {
	if err := domain.ValidateID(id); err != nil {
		return err
	}
	return translate(s.repo.Delete(ctx, id))
}

// Ensure makes the stored source match in, keyed on the feed URL, and reports
// whether it had to create one. Seeding needs to be repeatable, so this is
// deliberately idempotent rather than failing on a feed that already exists.
func (s *SourceService) Ensure(ctx context.Context, in domain.SourceInput) (src *domain.Source, created bool, err error) {
	src, err = domain.NewSource(in, s.clock())
	if err != nil {
		return nil, false, err
	}

	err = s.repo.Create(ctx, src)
	switch {
	case err == nil:
		return src, true, nil
	case !errors.Is(err, repository.ErrDuplicate):
		return nil, false, err
	}

	// Lost the race, or the feed was already configured: patch the existing one.
	existing, err := s.repo.GetByFeedURL(ctx, src.FeedURL)
	if err != nil {
		return nil, false, translate(err)
	}
	if err := existing.Apply(patchFromInput(in), s.clock()); err != nil {
		return nil, false, err
	}
	if err := s.repo.Update(ctx, existing); err != nil {
		return nil, false, translate(err)
	}
	return existing, false, nil
}

// patchFromInput converts a full input into a patch. Fields the operator left
// unset stay unset, so seeding never silently resets a hand-tuned value back to
// its default.
func patchFromInput(in domain.SourceInput) domain.SourcePatch {
	patch := domain.SourcePatch{
		Enabled:              in.Enabled,
		Priority:             in.Priority,
		FetchIntervalSeconds: in.FetchIntervalSeconds,
	}
	if in.Name != "" {
		patch.Name = &in.Name
	}
	if in.Type != "" {
		patch.Type = &in.Type
	}
	if in.Language != "" {
		patch.Language = &in.Language
	}
	if in.Country != "" {
		patch.Country = &in.Country
	}
	if in.State != "" {
		patch.State = &in.State
	}
	if in.City != "" {
		patch.City = &in.City
	}
	return patch
}

// translate maps persistence sentinels onto service sentinels, leaving any other
// error to travel unchanged for the caller to log and report as internal.
func translate(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, repository.ErrNotFound):
		return ErrNotFound
	case errors.Is(err, repository.ErrDuplicate):
		return ErrConflict
	default:
		return err
	}
}
