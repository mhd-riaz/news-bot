package mongo

import (
	"context"
	"fmt"

	"go.mongodb.org/mongo-driver/v2/bson"
	driver "go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
	"github.com/riaz/newscollector/internal/repository"
)

// LockRepository issues leases from the application_locks collection.
//
// The resource name is the document's _id, so the primary key itself is what
// makes a lease exclusive — there is no window between checking for a holder
// and becoming one. The resource is also stored as an ordinary field, which is
// what the migration's ix_resource_expiry index covers, and the TTL index on
// expires_at reaps abandoned leases so a crashed collector cannot park a source
// forever.
type LockRepository struct {
	coll *driver.Collection
}

// NewLockRepository binds the repository to the application_locks collection.
func NewLockRepository(db *driver.Database) *LockRepository {
	return &LockRepository{coll: db.Collection(mongodb.CollectionLocks)}
}

var _ repository.LockRepository = (*LockRepository)(nil)

// Acquire takes the lease, or reports that somebody else holds it.
//
// One upsert decides all three cases: no lease exists, so it is inserted; a
// lease exists but has expired, so the filter matches and it is taken over; a
// live lease exists, so the filter does not match, the upsert tries to insert a
// second document under the same _id, and the duplicate key that comes back
// means the resource is held. That last case is the expected outcome of two
// collectors reaching one due source, not a fault.
func (r *LockRepository) Acquire(ctx context.Context, lock domain.Lock) (bool, error) {
	filter := bson.D{
		{Key: "_id", Value: lock.Resource},
		{Key: "expires_at", Value: bson.D{{Key: "$lte", Value: lock.AcquiredAt}}},
	}
	update := bson.D{{Key: "$set", Value: bson.D{
		{Key: "resource", Value: lock.Resource},
		{Key: "owner", Value: lock.Owner},
		{Key: "acquired_at", Value: lock.AcquiredAt},
		{Key: "expires_at", Value: lock.ExpiresAt},
	}}}

	_, err := r.coll.UpdateOne(ctx, filter, update, options.UpdateOne().SetUpsert(true))
	switch {
	case err == nil:
		return true, nil
	case driver.IsDuplicateKeyError(err):
		return false, nil
	default:
		return false, fmt.Errorf("mongo: acquire lock %q: %w", lock.Resource, err)
	}
}

// Release drops a lease.
//
// The owner is part of the filter, so a collector whose lease already expired
// and was taken over cannot delete the new holder's lease. That case comes back
// as ErrNotFound, which tells the caller its exclusivity had lapsed.
func (r *LockRepository) Release(ctx context.Context, resource, owner string) error {
	res, err := r.coll.DeleteOne(ctx, bson.D{
		{Key: "_id", Value: resource},
		{Key: "owner", Value: owner},
	})
	if err != nil {
		return fmt.Errorf("mongo: release lock %q: %w", resource, err)
	}
	if res.DeletedCount == 0 {
		return repository.ErrNotFound
	}
	return nil
}
