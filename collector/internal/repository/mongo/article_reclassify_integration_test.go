//go:build integration

package mongo

import (
	"reflect"
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"github.com/riaz/newscollector/internal/domain"
)

const reclassifyTarget = "v4-test-hybrid"

// classifiedArticle stores an article, then forces its classification state the
// way earlier model versions left it.
func classifiedArticle(
	t *testing.T, repo *ArticleRepository, guid string, set bson.D, unset ...string,
) *domain.Article {
	t.Helper()
	article := newArticle(t, "https://example.com/reclassify/"+guid, guid)
	if err := repo.Create(testContext(t), article); err != nil {
		t.Fatalf("Create: %v", err)
	}
	update := bson.D{{Key: "$set", Value: set}}
	if len(unset) > 0 {
		unsetDoc := bson.D{}
		dropped := make(map[string]bool, len(unset))
		for _, field := range unset {
			unsetDoc = append(unsetDoc, bson.E{Key: field, Value: ""})
			dropped[field] = true
		}
		kept := bson.D{}
		for _, element := range set {
			if !dropped[element.Key] {
				kept = append(kept, element)
			}
		}
		update = bson.D{{Key: "$set", Value: kept}, {Key: "$unset", Value: unsetDoc}}
	}
	if _, err := repo.coll.UpdateByID(testContext(t), article.ID, update); err != nil {
		t.Fatal(err)
	}
	return article
}

func oldLabel(status domain.ClassificationStatus, model string) bson.D {
	return bson.D{
		{Key: "classification_status", Value: status},
		{Key: "topic", Value: "old-topic"},
		{Key: "confidence", Value: 0.5},
		{Key: "model_version", Value: model},
		{Key: "classified_at", Value: time.Now().UTC().Add(-48 * time.Hour).Truncate(time.Millisecond)},
		{Key: "clean_title", Value: "Clean headline"},
		{Key: "clean_body", Value: "Clean body"},
		{Key: "detected_language", Value: "en"},
		{Key: "language_confidence", Value: 0.97},
	}
}

func TestListForReclassificationSelectsOnlyOlderLabelledArticles(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)

	want := map[string]bool{
		classifiedArticle(t, repo, "old", oldLabel(domain.ClassificationStatusClassified, "v2-001")).ID:                       true,
		classifiedArticle(t, repo, "no-version", oldLabel(domain.ClassificationStatusUnsorted, "v2-001"), "model_version").ID: true,
		classifiedArticle(t, repo, "empty-version", oldLabel(domain.ClassificationStatusClassified, "")).ID:                   true,
	}
	for guid, set := range map[string]bson.D{
		"current":     oldLabel(domain.ClassificationStatusClassified, reclassifyTarget),
		"pending":     oldLabel(domain.ClassificationStatusPending, "v2-001"),
		"classifying": oldLabel(domain.ClassificationStatusClassifying, "v2-001"),
		"failed":      oldLabel(domain.ClassificationStatusFailed, "v2-001"),
	} {
		classifiedArticle(t, repo, guid, set)
	}

	got, err := repo.ListForReclassification(ctx, "", reclassifyTarget, 50)
	if err != nil {
		t.Fatalf("ListForReclassification: %v", err)
	}
	if len(got) != len(want) {
		t.Fatalf("candidates = %d, want %d", len(got), len(want))
	}
	for index, article := range got {
		if !want[article.ID] {
			t.Errorf("unexpected candidate %s", article.ID)
		}
		if index > 0 && got[index-1].ID >= article.ID {
			t.Errorf("candidates are not in ascending _id order at %d", index)
		}
		if article.ContentRev != 1 || article.Title == "" || article.SourceName == "" {
			t.Errorf("candidate %s lacks classifier input or revision: %+v", article.ID, article)
		}
	}

	after, err := repo.ListForReclassification(ctx, got[0].ID, reclassifyTarget, 1)
	if err != nil || len(after) != 1 || after[0].ID != got[1].ID {
		t.Errorf("ListForReclassification after cursor = %#v, %v; want only %s", after, err, got[1].ID)
	}
	if _, err := repo.ListForReclassification(ctx, "", reclassifyTarget, 0); err == nil {
		t.Error("zero limit was accepted")
	}
	if _, err := repo.ListForReclassification(ctx, "", "", 10); err == nil {
		t.Error("empty target model version was accepted")
	}
}

func TestReclassifyIfCurrentChangesOnlyTheFiveTopicFields(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	article := classifiedArticle(t, repo, "target", oldLabel(domain.ClassificationStatusClassified, "v2-001"))
	at := time.Now().UTC().Truncate(time.Millisecond)
	result := domain.Reclassification{
		Status: domain.ClassificationStatusUnsorted, Topic: "unsorted", Confidence: 0.31,
		ModelVersion: reclassifyTarget, At: at,
	}

	rawDocument := func() bson.M {
		var document bson.M
		if err := repo.coll.FindOne(ctx, bson.D{{Key: "_id", Value: article.ID}}).Decode(&document); err != nil {
			t.Fatalf("read raw article: %v", err)
		}
		return document
	}
	before := rawDocument()

	if updated, err := repo.ReclassifyIfCurrent(ctx, article.ID, 0, result); err != nil || updated {
		t.Fatalf("stale revision = %v, %v; want skipped", updated, err)
	}
	if !reflect.DeepEqual(before, rawDocument()) {
		t.Fatal("a skipped update changed the article")
	}

	if updated, err := repo.ReclassifyIfCurrent(ctx, article.ID, 1, result); err != nil || !updated {
		t.Fatalf("ReclassifyIfCurrent = %v, %v", updated, err)
	}
	after := rawDocument()
	for _, field := range []string{"topic", "confidence", "model_version", "classification_status", "classified_at"} {
		if reflect.DeepEqual(before[field], after[field]) {
			t.Errorf("%s was not changed", field)
		}
		delete(before, field)
		delete(after, field)
	}
	if !reflect.DeepEqual(before, after) {
		t.Errorf("fields outside the topic outcome changed:\nbefore %v\nafter  %v", before, after)
	}

	got, err := repo.GetByID(ctx, article.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Topic != "unsorted" || got.Confidence != 0.31 || got.ModelVersion != reclassifyTarget ||
		got.ClassificationStatus != domain.ClassificationStatusUnsorted || got.ClassifiedAt == nil ||
		!got.ClassifiedAt.Equal(at) {
		t.Errorf("stored outcome = %+v", got)
	}
	if got.ContentRev != 1 {
		t.Errorf("topic-only relabel bumped content_rev to %d", got.ContentRev)
	}

	if updated, err := repo.ReclassifyIfCurrent(ctx, article.ID, 1, result); err != nil || updated {
		t.Errorf("repeat on target version = %v, %v; want skipped", updated, err)
	}
	if updated, err := repo.ReclassifyIfCurrent(ctx, "missing-id", 1, result); err != nil || updated {
		t.Errorf("missing article = %v, %v; want skipped", updated, err)
	}
}

func TestReclassifyIfCurrentSkipsBacklogStatesAndRejectsBadResults(t *testing.T) {
	repo := newTestArticleRepo(t)
	ctx := testContext(t)
	good := domain.Reclassification{
		Status: domain.ClassificationStatusClassified, Topic: "ai", Confidence: 0.9,
		ModelVersion: reclassifyTarget, At: time.Now().UTC(),
	}
	for _, status := range []domain.ClassificationStatus{
		domain.ClassificationStatusPending, domain.ClassificationStatusClassifying, domain.ClassificationStatusFailed,
	} {
		article := classifiedArticle(t, repo, string(status), oldLabel(status, "v2-001"))
		if updated, err := repo.ReclassifyIfCurrent(ctx, article.ID, 1, good); err != nil || updated {
			t.Errorf("%s article = %v, %v; want skipped", status, updated, err)
		}
	}

	legacy := classifiedArticle(t, repo, "legacy", oldLabel(domain.ClassificationStatusClassified, "v2-001"), "content_rev")
	if updated, err := repo.ReclassifyIfCurrent(ctx, legacy.ID, 0, good); err != nil || !updated {
		t.Errorf("legacy article without content_rev = %v, %v; want updated", updated, err)
	}

	for name, mutate := range map[string]func(*domain.Reclassification){
		"failed status": func(r *domain.Reclassification) { r.Status = domain.ClassificationStatusFailed },
		"empty topic":   func(r *domain.Reclassification) { r.Topic = "" },
		"empty version": func(r *domain.Reclassification) { r.ModelVersion = "" },
		"confidence":    func(r *domain.Reclassification) { r.Confidence = 1.5 },
		"zero time":     func(r *domain.Reclassification) { r.At = time.Time{} },
	} {
		bad := good
		mutate(&bad)
		if _, err := repo.ReclassifyIfCurrent(ctx, legacy.ID, 0, bad); err == nil {
			t.Errorf("%s was accepted", name)
		}
	}
}
