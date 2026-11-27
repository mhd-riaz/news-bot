package mongodb

// Canonical collection names. Every repository must use these constants rather
// than string literals so the migration and the queries cannot drift apart.
// readers and reader_sessions are owned by the Python server (server/); they are
// declared here because the collector alone holds DDL (roadmap C14).
const (
	CollectionSources        = "sources"
	CollectionArticles       = "articles"
	CollectionCollectionRuns = "collection_runs"
	CollectionFeedCache      = "feed_cache_metadata"
	CollectionLocks          = "application_locks"
	CollectionReadEvents     = "read_events"
	CollectionReaders        = "readers"
	CollectionReaderSessions = "reader_sessions"
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
		CollectionReaders,
		CollectionReaderSessions,
	}
}
