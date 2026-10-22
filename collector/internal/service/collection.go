package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"time"

	"github.com/riaz/newscollector/internal/collector/rss"
	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/httpclient"
	"github.com/riaz/newscollector/internal/processor"
	"github.com/riaz/newscollector/internal/repository"
)

// ErrLocked means another collector holds the source's lease. It is a normal
// outcome rather than a failure: two collectors reaching the same due source is
// exactly what the lease exists to arbitrate.
var ErrLocked = errors.New("service: source is already being collected")

// ErrSourceDisabled means the source was asked for by name but is switched off.
var ErrSourceDisabled = errors.New("service: source is disabled")

// FeedCollector fetches and parses one source's feed. The service depends on
// the behaviour rather than the concrete collector, so its tests need no
// network.
type FeedCollector interface {
	Collect(ctx context.Context, src *domain.Source, prev rss.Validators) (rss.Result, error)
}

// ItemProcessor turns collected items into stored articles.
type ItemProcessor interface {
	Process(ctx context.Context, src *domain.Source, items []domain.FeedItem) (processor.Result, error)
}

// CollectionDeps is everything a CollectionService needs. It is a struct rather
// than a parameter list because there are eight of them and a positional call
// would be unreadable at the wiring site.
type CollectionDeps struct {
	Sources   repository.SourceRepository
	Runs      repository.CollectionRunRepository
	Cache     repository.FeedCacheRepository
	Locks     repository.LockRepository
	Collector FeedCollector
	Processor ItemProcessor

	// Owner identifies this process in every lease it takes, so one collector
	// can never release another's.
	Owner string

	// LockTTL is how long a lease is held. It must outlast a collection, or a
	// second collector could start one while the first is still running.
	LockTTL time.Duration

	Clock  Clock
	Logger *slog.Logger
}

// CollectionService performs one collection of one source, end to end: lease,
// conditional fetch, processing, validators, audit record and source health.
type CollectionService struct {
	deps CollectionDeps
}

// NewCollectionService wires the service. A nil clock defaults to time.Now and
// a nil logger to the default one.
func NewCollectionService(deps CollectionDeps) *CollectionService {
	if deps.Clock == nil {
		deps.Clock = time.Now
	}
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	return &CollectionService{deps: deps}
}

// Due returns the sources whose next collection has come round.
func (s *CollectionService) Due(ctx context.Context, limit int) ([]domain.Source, error) {
	if limit < 1 {
		return nil, fmt.Errorf("service: due limit must be greater than zero, got %d", limit)
	}
	sources, err := s.deps.Sources.ListDue(ctx, s.deps.Clock(), limit)
	if err != nil {
		return nil, translate(err)
	}
	return sources, nil
}

// CollectByID collects one source now, whatever its schedule says. A manual
// collection is an operator deciding the feed is worth reading right now, so it
// deliberately ignores next_scheduled_at — the lease still applies, so it
// cannot collide with a scheduled run of the same source.
//
// A disabled source is refused rather than collected: disabled has to mean the
// same thing everywhere, or turning a feed off would still leave one way to
// pull articles from it.
func (s *CollectionService) CollectByID(ctx context.Context, id string) (*domain.CollectionRun, error) {
	if err := domain.ValidateID(id); err != nil {
		return nil, err
	}

	src, err := s.deps.Sources.GetByID(ctx, id)
	if err != nil {
		return nil, translate(err)
	}
	if !src.Enabled {
		return nil, ErrSourceDisabled
	}
	return s.Collect(ctx, src)
}

// Collect performs one collection of src and returns the run it recorded.
//
// A feed that could not be read is not an error to the caller: it is a recorded
// failure, which is the whole point of the audit trail. The error return is
// reserved for the cases where this system, rather than the publisher, is
// broken — the lease could not be taken, or the run could not be stored.
func (s *CollectionService) Collect(ctx context.Context, src *domain.Source) (*domain.CollectionRun, error) {
	if src == nil {
		return nil, errors.New("service: nil source")
	}

	resource := domain.SourceLockResource(src.ID)
	acquired, err := s.deps.Locks.Acquire(ctx, domain.NewLock(resource, s.deps.Owner, s.deps.Clock(), s.deps.LockTTL))
	if err != nil {
		return nil, fmt.Errorf("service: acquire source lease: %w", err)
	}
	if !acquired {
		return nil, ErrLocked
	}
	defer s.release(ctx, resource)

	run, err := domain.NewCollectionRun(*src, s.deps.Clock())
	if err != nil {
		return nil, err
	}

	notModified, collectErr := s.fetch(ctx, src, run)
	completed := s.deps.Clock()
	if collectErr != nil {
		reason := describe(collectErr)
		s.deps.Logger.WarnContext(ctx, "collection failed",
			"source_id", src.ID, "reason", reason, "error", collectErr)

		run.Fail(reason, completed)
		src.RecordFailure(completed, reason)
	} else {
		run.Complete(completed, notModified)
		src.RecordSuccess(completed)
	}

	// The run is stored before the source: it is the record that the attempt
	// happened at all, and losing it to a failed source update would leave the
	// attempt invisible.
	if err := s.deps.Runs.Create(ctx, run); err != nil {
		return nil, fmt.Errorf("service: record collection run: %w", err)
	}
	// Only the fields a collection owns are written back: an operator may have
	// edited the source while the fetch was running.
	if err := s.deps.Sources.UpdateCollectionState(ctx, src); err != nil {
		return nil, fmt.Errorf("service: update source after collection: %w", err)
	}
	return run, nil
}

// fetch runs the collection itself and fills in the run's counts, reporting
// whether the publisher answered 304. The counts are recorded as they are
// learned, so a processing failure halfway through a batch still reports what
// it managed to store.
func (s *CollectionService) fetch(ctx context.Context, src *domain.Source, run *domain.CollectionRun) (notModified bool, err error) {
	result, err := s.deps.Collector.Collect(ctx, src, s.validators(ctx, src.ID))
	if err != nil {
		return false, err
	}

	run.FeedType = result.FeedType
	run.ItemsFound = result.ItemsFound
	run.ItemsSkipped = result.ItemsSkipped
	run.Truncated = result.Truncated

	s.saveValidators(ctx, src.ID, result.Validators)

	if result.NotModified {
		return true, nil
	}

	processed, err := s.deps.Processor.Process(ctx, src, result.Items)
	run.ItemsStored = processed.Stored
	run.ItemsDuplicate = processed.Duplicates
	run.ItemsInvalid = processed.Invalid
	s.deps.Logger.InfoContext(ctx, "collection classification completed",
		"batch_size", len(result.Items),
		"classifier_available", processed.ClassifierAvailable,
		"classification_latency", processed.ClassificationLatency,
		"classified", processed.Classified,
		"unsorted", processed.Unsorted,
		"pending", processed.Unclassified,
	)
	return false, err
}

// validators returns the stored cache validators for a source. A cache that
// cannot be read only costs a conditional request, so a failure here is logged
// and the fetch proceeds unconditionally rather than being abandoned.
func (s *CollectionService) validators(ctx context.Context, sourceID string) rss.Validators {
	entry, err := s.deps.Cache.Get(ctx, sourceID)
	switch {
	case err == nil:
		return rss.Validators{ETag: entry.ETag, LastModified: entry.LastModified}
	case errors.Is(err, repository.ErrNotFound):
		return rss.Validators{}
	default:
		s.deps.Logger.WarnContext(ctx, "reading feed cache failed; fetching unconditionally",
			"source_id", sourceID, "error", err)
		return rss.Validators{}
	}
}

// saveValidators stores what the publisher returned. Like reading them, failing
// to store them costs only the next conditional request, so it never fails a
// collection whose articles are already safely stored.
func (s *CollectionService) saveValidators(ctx context.Context, sourceID string, v rss.Validators) {
	entry := domain.NewFeedCacheEntry(sourceID, v.ETag, v.LastModified, s.deps.Clock())
	if entry.IsEmpty() {
		return
	}
	if err := s.deps.Cache.Save(ctx, entry); err != nil {
		s.deps.Logger.WarnContext(ctx, "storing feed cache failed; the next fetch will be unconditional",
			"source_id", sourceID, "error", err)
	}
}

// release drops the lease. It uses a context detached from the collection's, so
// a cancelled or timed-out collection still gives the source back instead of
// leaving it parked until the lease expires.
func (s *CollectionService) release(ctx context.Context, resource string) {
	releaseCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), releaseTimeout)
	defer cancel()

	err := s.deps.Locks.Release(releaseCtx, resource, s.deps.Owner)
	switch {
	case err == nil:
	case errors.Is(err, repository.ErrNotFound):
		// The lease expired mid-collection, so another collector may have been
		// working the same source. The article indexes make that safe, but a
		// lease shorter than a collection is a misconfiguration worth seeing.
		s.deps.Logger.WarnContext(ctx, "source lease expired before the collection finished",
			"resource", resource, "lock_ttl", s.deps.LockTTL)
	default:
		s.deps.Logger.ErrorContext(ctx, "releasing source lease failed", "resource", resource, "error", err)
	}
}

// releaseTimeout bounds the lease release of an already-cancelled collection.
const releaseTimeout = 5 * time.Second

// ListRuns returns the page of collection runs matching filter.
func (s *CollectionService) ListRuns(ctx context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error) {
	filter.Normalize()
	if err := filter.Validate(); err != nil {
		return domain.CollectionRunPage{}, err
	}

	page, err := s.deps.Runs.List(ctx, filter)
	if err != nil {
		return domain.CollectionRunPage{}, translate(err)
	}
	return page, nil
}

// GetRun returns one collection run.
func (s *CollectionService) GetRun(ctx context.Context, id string) (*domain.CollectionRun, error) {
	if err := domain.ValidateID(id); err != nil {
		return nil, err
	}

	run, err := s.deps.Runs.GetByID(ctx, id)
	if err != nil {
		return nil, translate(err)
	}
	return run, nil
}

// describe turns a collection failure into the fixed phrase stored on the run
// and on the source.
//
// The phrases are deliberately coarse. Both fields are served by the API, and a
// raw error here would publish a DNS message, a driver error or an internal
// host name to anyone who can list sources. The full error is logged instead.
func describe(err error) string {
	var status *httpclient.StatusError
	if errors.As(err, &status) {
		return fmt.Sprintf("the publisher answered HTTP %d", status.StatusCode)
	}

	var netErr net.Error
	switch {
	case errors.Is(err, httpclient.ErrBlockedAddress):
		return "the feed resolves to an address this collector refuses to contact"
	case errors.Is(err, httpclient.ErrInvalidURL):
		return "the feed URL cannot be fetched as written"
	case errors.Is(err, httpclient.ErrTooManyRedirects):
		return "the feed redirected too many times"
	case errors.Is(err, httpclient.ErrResponseTooLarge):
		return "the feed response is larger than this collector accepts"
	case errors.Is(err, rss.ErrParse):
		return "the feed could not be parsed as RSS, RDF or Atom"
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		return "the collection ran out of time"
	case errors.As(err, &netErr) && netErr.Timeout():
		return "the publisher did not answer in time"
	case errors.Is(err, repository.ErrNotFound), errors.Is(err, repository.ErrDuplicate):
		return "the collected articles could not be stored"
	default:
		return "the collection failed"
	}
}
