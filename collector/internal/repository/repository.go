// Package repository declares the persistence contracts the application depends
// on, together with the storage-neutral errors those contracts may return.
// Implementations live in subpackages; nothing here imports a database driver,
// so services and CLIs can be tested against an in-memory fake.
package repository

import (
	"context"
	"errors"
	"time"

	"github.com/riaz/newscollector/internal/domain"
)

// Storage-neutral sentinels. Implementations must translate driver-specific
// failures into these so no caller has to recognise a MongoDB error code.
var (
	// ErrNotFound means no record matched the identifier or filter.
	ErrNotFound = errors.New("repository: not found")

	// ErrDuplicate means a unique constraint rejected the write. It is the
	// authority on duplicates: a read-then-write check would race.
	ErrDuplicate = errors.New("repository: duplicate key")
)

// SourceRepository persists configured feeds.
type SourceRepository interface {
	// Create stores a new source, returning ErrDuplicate if its feed URL is taken.
	Create(ctx context.Context, s *domain.Source) error

	// GetByID returns the source with the given id, or ErrNotFound.
	GetByID(ctx context.Context, id string) (*domain.Source, error)

	// GetByFeedURL returns the source registered for a feed URL, or ErrNotFound.
	GetByFeedURL(ctx context.Context, feedURL string) (*domain.Source, error)

	// List returns the page of sources matching filter, plus the total match count.
	List(ctx context.Context, filter domain.SourceFilter) (domain.SourcePage, error)

	// ListDue returns up to limit enabled sources whose next collection falls at
	// or before now, most important first. It is a read: two collectors may well
	// receive the same source, and the lease each one takes is what decides
	// which of them actually collects it.
	ListDue(ctx context.Context, now time.Time, limit int) ([]domain.Source, error)

	// Update replaces the stored source, returning ErrNotFound if the id is
	// unknown or ErrDuplicate if the new feed URL collides with another source.
	Update(ctx context.Context, s *domain.Source) error

	// UpdateCollectionState writes only the fields a collection owns: health,
	// failure history and schedule. A collection takes seconds, and an operator
	// may edit the source while one is in flight, so writing the whole document
	// back afterwards would silently revert that edit.
	UpdateCollectionState(ctx context.Context, s *domain.Source) error

	// Delete removes a source, returning ErrNotFound if the id is unknown.
	Delete(ctx context.Context, id string) error
}

// ArticleRepository persists collected articles.
type ArticleRepository interface {
	// Create stores a new article, returning ErrDuplicate when a unique index
	// rejects it. Two collectors racing on the same article both call this; the
	// index, not a prior read, is what decides which one wins.
	Create(ctx context.Context, a *domain.Article) error

	// FindByIdentity returns the stored article matching any of the identity's
	// keys, or ErrNotFound. Keys are tried in the deduplication order:
	// normalized URL, canonical URL, source plus feed GUID, then the content
	// hash within the same source.
	FindByIdentity(ctx context.Context, identity domain.ArticleIdentity) (*domain.Article, error)

	// GetByID returns one article in full, or ErrNotFound.
	GetByID(ctx context.Context, id string) (*domain.Article, error)

	// List returns the page of articles matching filter, newest first. The page
	// carries the cursor that resumes it rather than a total, and its items
	// carry no content: a listing of fifty full articles is megabytes nobody
	// asked for.
	List(ctx context.Context, filter domain.ArticleFilter) (domain.ArticlePage, error)

	// DeleteOlderThan removes every article published before the deletion's
	// bound and returns how many went, which may be zero. Matching nothing is
	// not ErrNotFound: a retention sweep that finds the collection already
	// tidy has succeeded.
	DeleteOlderThan(ctx context.Context, d domain.ArticleDeletion) (int64, error)

	// ClaimForScraping takes the article that has waited longest for full-text
	// enrichment and marks it in flight, returning ErrNotFound when the backlog
	// is empty. Claiming is a single atomic write rather than a read followed by
	// one, because that is what stops two workers fetching the same article.
	//
	// The attempt counter is raised here, not when the attempt reports back: a
	// worker that dies mid-fetch has still spent an attempt, and counting only
	// completed attempts would let a article that reliably kills its worker be
	// retried until the end of time.
	ClaimForScraping(ctx context.Context, claim domain.ScrapeClaim) (*domain.Article, error)

	// UpdateScrapeResult writes one finished attempt. Content, status and
	// schedule go in a single update so a reader can never observe text that
	// disagrees with the status describing it. It returns ErrNotFound if the
	// article has since been deleted, which a retention sweep may legitimately
	// have done while the fetch was in flight.
	UpdateScrapeResult(ctx context.Context, id string, result domain.ScrapeResult) error

	// ReleaseStaleScrapeClaims returns articles claimed before the given instant
	// to the backlog and reports how many were freed. A claim outlives its
	// worker only when that worker died, so this is how the backlog recovers
	// from a crash or an evicted pod.
	ReleaseStaleScrapeClaims(ctx context.Context, claimedBefore time.Time) (int64, error)

	// ClaimForClassification atomically takes the longest-waiting pending
	// article, returning ErrNotFound when the classification backlog is empty.
	ClaimForClassification(ctx context.Context, claim domain.ClassificationClaim) (*domain.Article, error)

	// UpdateClassification writes only the fields owned by model classification.
	UpdateClassification(ctx context.Context, id string, result domain.ClassificationResult) error

	// ReleaseStaleClassificationClaims returns abandoned classification claims to
	// the pending backlog and reports how many were freed.
	ReleaseStaleClassificationClaims(ctx context.Context, claimedBefore time.Time) (int64, error)
}

// CollectionRunRepository persists the audit record of every collection
// attempt. Runs are written once and never updated: a run describes an attempt
// that has already finished.
type CollectionRunRepository interface {
	// Create stores a finished run.
	Create(ctx context.Context, run *domain.CollectionRun) error

	// GetByID returns one run, or ErrNotFound.
	GetByID(ctx context.Context, id string) (*domain.CollectionRun, error)

	// List returns the page of runs matching filter, plus the total match count.
	List(ctx context.Context, filter domain.CollectionRunFilter) (domain.CollectionRunPage, error)
}

// FeedCacheRepository persists the HTTP validators of each source's last
// collection, so the next one can be conditional.
type FeedCacheRepository interface {
	// Get returns the stored validators for a source, or ErrNotFound when the
	// source has never been collected or the publisher supplied none.
	Get(ctx context.Context, sourceID string) (*domain.FeedCacheEntry, error)

	// Save stores the validators, replacing whatever was held before.
	Save(ctx context.Context, entry domain.FeedCacheEntry) error
}

// LockRepository issues the time-limited leases that stop two collectors
// working the same source at the same moment.
type LockRepository interface {
	// Acquire reports whether the lease was taken. A lease already held by
	// somebody else is a false, not an error: it is the normal outcome of two
	// collectors reaching the same due source, and the caller simply moves on.
	Acquire(ctx context.Context, lock domain.Lock) (bool, error)

	// Release drops a lease this owner holds. ErrNotFound means the lease had
	// already expired and possibly been taken by somebody else, so the caller
	// must not assume its work was still exclusive.
	Release(ctx context.Context, resource, owner string) error
}

// ReadEventRepository persists what a reader did with the feed.
//
// There is no read method: read events are consumed offline by the training
// pipeline, which reads the collection directly, and an HTTP listing nobody
// calls is a surface to defend for no gain.
type ReadEventRepository interface {
	// CreateMany stores a batch and reports how many were written. A batch is
	// one flush from one page, so it is written unordered: a single rejected
	// event must not discard the ones behind it.
	CreateMany(ctx context.Context, events []domain.ReadEvent) (int64, error)
}
