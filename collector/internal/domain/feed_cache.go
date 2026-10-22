package domain

import "time"

// FeedCacheEntry is what the last collection of a source learned about caching
// it: the validators the publisher returned. Replaying them as If-None-Match
// and If-Modified-Since is what lets a publisher answer 304, which is the
// cheapest possible poll for both sides.
//
// It is kept out of the source document deliberately: it changes on every poll,
// while a source changes only when an operator edits it.
type FeedCacheEntry struct {
	SourceID     string    `bson:"source_id"`
	ETag         string    `bson:"etag,omitempty"`
	LastModified string    `bson:"last_modified,omitempty"`
	UpdatedAt    time.Time `bson:"updated_at"`
}

// maxValidatorLength bounds a validator. Both are publisher-supplied header
// values, so neither is trusted to be a sane length.
const maxValidatorLength = 512

// NewFeedCacheEntry bounds the publisher's validators and stamps them.
func NewFeedCacheEntry(sourceID, etag, lastModified string, now time.Time) FeedCacheEntry {
	return FeedCacheEntry{
		SourceID:     sourceID,
		ETag:         truncate(collapseSpace(etag), maxValidatorLength),
		LastModified: truncate(collapseSpace(lastModified), maxValidatorLength),
		UpdatedAt:    storedTime(now),
	}
}

// IsEmpty reports whether the publisher supplied no validator at all, in which
// case there is nothing worth storing.
func (e FeedCacheEntry) IsEmpty() bool {
	return e.ETag == "" && e.LastModified == ""
}
