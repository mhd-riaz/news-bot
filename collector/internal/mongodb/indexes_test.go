package mongodb

import (
	"fmt"
	"testing"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

func resolveOptions(t *testing.T, m mongo.IndexModel) options.IndexOptions {
	t.Helper()
	var opts options.IndexOptions
	if m.Options == nil {
		return opts
	}
	for _, set := range m.Options.List() {
		if err := set(&opts); err != nil {
			t.Fatalf("apply index option: %v", err)
		}
	}
	return opts
}

func TestCollectionsAreUnique(t *testing.T) {
	seen := map[string]struct{}{}
	for _, name := range Collections() {
		if name == "" {
			t.Fatal("collection name must not be empty")
		}
		if _, dup := seen[name]; dup {
			t.Errorf("collection %q listed twice", name)
		}
		seen[name] = struct{}{}
	}

	if len(seen) != 6 {
		t.Errorf("expected 6 collections, got %d", len(seen))
	}
	for _, want := range []string{"sources", "articles", "collection_runs", "feed_cache_metadata", "application_locks", "read_events"} {
		if _, ok := seen[want]; !ok {
			t.Errorf("missing required collection %q", want)
		}
	}
}

// No index in the plan may still carry a name the plan itself declares
// obsolete, or the migration would drop what it is about to create.
func TestObsoleteIndexesAreNotAlsoPlanned(t *testing.T) {
	obsolete := ObsoleteIndexes()

	for _, ci := range IndexPlan() {
		retired := make(map[string]struct{}, len(obsolete[ci.Collection]))
		for _, name := range obsolete[ci.Collection] {
			retired[name] = struct{}{}
		}

		for _, m := range ci.Models {
			opts := resolveOptions(t, m)
			if opts.Name == nil {
				continue
			}
			if _, clash := retired[*opts.Name]; clash {
				t.Errorf("%s: index %q is both planned and declared obsolete", ci.Collection, *opts.Name)
			}
		}
	}
}

// Every index a listing sorts on must end in the _id tiebreaker, or one page of
// a filtered listing costs a sort of everything that matched.
func TestListingIndexesCarryTheCursorTiebreaker(t *testing.T) {
	cursorIndexes := map[string]struct{}{
		"ix_published_cursor":          {},
		"ix_collected_cursor":          {},
		"ix_source_published_cursor":   {},
		"ix_language_published_cursor": {},
		"ix_region_published_cursor":   {},
		"ix_topic_published_cursor":    {},
	}

	found := 0
	for _, ci := range IndexPlan() {
		if ci.Collection != CollectionArticles {
			continue
		}
		for _, m := range ci.Models {
			opts := resolveOptions(t, m)
			if opts.Name == nil {
				continue
			}
			if _, ok := cursorIndexes[*opts.Name]; !ok {
				continue
			}
			found++

			keys := m.Keys.(bson.D)
			if last := keys[len(keys)-1]; last.Key != "_id" || last.Value != -1 {
				t.Errorf("%s ends in %v, want {_id: -1}", *opts.Name, last)
			}
		}
	}

	if found != len(cursorIndexes) {
		t.Errorf("found %d of the %d listing indexes", found, len(cursorIndexes))
	}
}

func TestIndexPlanCoversEveryCollection(t *testing.T) {
	planned := map[string]int{}
	for _, ci := range IndexPlan() {
		planned[ci.Collection] = len(ci.Models)
	}

	for _, name := range Collections() {
		count, ok := planned[name]
		if !ok {
			t.Errorf("collection %q has no entry in the index plan", name)
			continue
		}
		if count == 0 {
			t.Errorf("collection %q has an empty index list", name)
		}
	}

	if len(planned) != len(Collections()) {
		t.Errorf("index plan covers %d collections, want %d", len(planned), len(Collections()))
	}
}

func TestIndexPlanKeysAreOrderPreservingAndNamed(t *testing.T) {
	for _, ci := range IndexPlan() {
		names := map[string]struct{}{}
		keySpecs := map[string]struct{}{}

		for i, m := range ci.Models {
			keys, ok := m.Keys.(bson.D)
			if !ok {
				t.Errorf("%s index %d: Keys must be bson.D to preserve order, got %T", ci.Collection, i, m.Keys)
				continue
			}
			if len(keys) == 0 {
				t.Errorf("%s index %d: Keys must not be empty", ci.Collection, i)
				continue
			}

			spec := fmt.Sprint(keys)
			if _, dup := keySpecs[spec]; dup {
				t.Errorf("%s: duplicate index key specification %s", ci.Collection, spec)
			}
			keySpecs[spec] = struct{}{}

			opts := resolveOptions(t, m)
			if opts.Name == nil || *opts.Name == "" {
				t.Errorf("%s index %s: every index must be explicitly named so migrations stay stable", ci.Collection, spec)
				continue
			}
			if _, dup := names[*opts.Name]; dup {
				t.Errorf("%s: duplicate index name %q", ci.Collection, *opts.Name)
			}
			names[*opts.Name] = struct{}{}
		}
	}
}

func TestArticleDeduplicationIndexesAreUnique(t *testing.T) {
	wantUnique := map[string]bool{
		"uq_dedup_id":         true,
		"uq_normalized_url":   true,
		"uq_source_feed_guid": true,
		"ix_content_hash":     false,
	}

	found := map[string]bool{}
	for _, ci := range IndexPlan() {
		if ci.Collection != CollectionArticles {
			continue
		}
		for _, m := range ci.Models {
			opts := resolveOptions(t, m)
			if opts.Name == nil {
				continue
			}
			if _, relevant := wantUnique[*opts.Name]; !relevant {
				continue
			}
			found[*opts.Name] = opts.Unique != nil && *opts.Unique
		}
	}

	for name, want := range wantUnique {
		got, ok := found[name]
		if !ok {
			t.Errorf("articles is missing the %q index required by the deduplication order", name)
			continue
		}
		if got != want {
			t.Errorf("index %q unique = %v, want %v", name, got, want)
		}
	}
}

func TestFeedGUIDUniquenessIsPartial(t *testing.T) {
	for _, ci := range IndexPlan() {
		if ci.Collection != CollectionArticles {
			continue
		}
		for _, m := range ci.Models {
			opts := resolveOptions(t, m)
			if opts.Name == nil || *opts.Name != "uq_source_feed_guid" {
				continue
			}
			if opts.PartialFilterExpression == nil {
				t.Fatal("uq_source_feed_guid must be partial, otherwise items without a GUID would collide")
			}
			return
		}
	}
	t.Fatal("uq_source_feed_guid not found in the index plan")
}

func TestLockCollectionHasTTLIndex(t *testing.T) {
	for _, ci := range IndexPlan() {
		if ci.Collection != CollectionLocks {
			continue
		}
		for _, m := range ci.Models {
			opts := resolveOptions(t, m)
			if opts.ExpireAfterSeconds != nil && *opts.ExpireAfterSeconds == 0 {
				return
			}
		}
	}
	t.Fatal("application_locks needs a TTL index so abandoned leases expire")
}

func TestConnectRejectsIncompleteSettings(t *testing.T) {
	tests := []struct {
		name string
		in   Settings
	}{
		{"missing uri", Settings{Database: "news"}},
		{"missing database", Settings{URI: "mongodb://localhost:27017"}},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := Connect(tc.in); err == nil {
				t.Fatal("expected an error for incomplete settings")
			}
		})
	}
}
