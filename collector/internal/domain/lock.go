package domain

import "time"

// Lock is a time-limited lease over a named resource. It is what stops two
// collectors polling the same feed at the same moment and racing each other
// into the article deduplication indexes.
//
// The lease expires rather than being held until released, so a collector that
// crashes mid-collection cannot park a source forever.
type Lock struct {
	Resource   string    `bson:"resource"`
	Owner      string    `bson:"owner"`
	AcquiredAt time.Time `bson:"acquired_at"`
	ExpiresAt  time.Time `bson:"expires_at"`
}

// NewLock builds a lease held by owner from now until now+ttl.
func NewLock(resource, owner string, now time.Time, ttl time.Duration) Lock {
	now = storedTime(now)
	return Lock{
		Resource:   resource,
		Owner:      owner,
		AcquiredAt: now,
		ExpiresAt:  now.Add(ttl),
	}
}

// SourceLockResource names the lease covering one source's collection. The
// prefix keeps it distinct from any other kind of lease the same collection
// may hold later.
func SourceLockResource(sourceID string) string {
	return "source:" + sourceID
}
