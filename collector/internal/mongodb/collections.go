package mongodb

// Canonical collection names. Every repository must use these constants rather
// than string literals so the migration and the queries cannot drift apart.
const (
	CollectionSources        = "sources"
	CollectionArticles       = "articles"
	CollectionCollectionRuns = "collection_runs"
	CollectionFeedCache      = "feed_cache_metadata"
	CollectionLocks          = "application_locks"
	CollectionReadEvents     = "read_events"
)

// Collections lists every collection the application owns, in creation order.
func Collections() []string {
	return []string{
		CollectionSources,
		CollectionArticles,
		CollectionCollectionRuns,
		CollectionFeedCache,
		CollectionLocks,
		CollectionReadEvents,
	}
}
