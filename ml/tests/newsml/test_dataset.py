"""The dataset contract, and the holdout arrangement the honest number rests on."""

from __future__ import annotations

import pytest

from newsml import dataset, snapshot


def _corpus(make_article, spec):
    """`spec` is (article_id, category, title) triples.

    The summary is built from the article's own title, so two articles group as
    near-duplicates exactly when their titles match and not otherwise. The shared
    default summary this used to rely on made every article a near-duplicate of
    every other once the grouping threshold came down to its calibrated 0.44.
    """
    return [
        make_article(
            article_id,
            categories=(category,),
            title=title,
            summary=" ".join(title.split() * 4),
            minutes=index * 90,
        )
        for index, (article_id, category, title) in enumerate(spec)
    ]


SPEC = [
    ("s1", "sport", "India beat Australia by six wickets in the opening Test at Galle"),
    ("s2", "sport", "City sign a midfielder from Porto for a reported forty million"),
    ("s3", "sport", "Marathon world record falls again in Berlin on a fast morning"),
    ("h1", "health", "Trial finds the new vaccine cuts recurrence of melanoma sharply"),
    ("h2", "health", "Hospitals report a rise in seasonal influenza admissions this week"),
    ("h3", "health", "Researchers link poor sleep to higher blood pressure in adults"),
]


def test_a_held_out_article_is_scored_but_never_trained_on(make_article, taxonomy):
    articles = _corpus(make_article, SPEC)
    data = dataset.build(articles, taxonomy, min_per_class=1, holdout={"s1": "sport"})

    trained = {e.article_id for e in (*data.train, *data.val, *data.test)}
    assert "s1" not in trained
    assert [e.article_id for e in data.gold] == ["s1"]
    assert data.gold[0].label_source == "human"


def test_the_whole_story_group_of_a_held_out_article_is_withheld(make_article, taxonomy):
    twin = "India beat Australia by six wickets in the opening Test at Galle"
    articles = _corpus(make_article, [*SPEC, ("s1b", "sport", twin)])
    data = dataset.build(articles, taxonomy, min_per_class=1, holdout={"s1": "sport"})

    trained = {e.article_id for e in (*data.train, *data.val, *data.test)}
    assert {"s1", "s1b"}.isdisjoint(trained), "a near-duplicate of a scored article leaked into training"
    assert data.withheld_for_gold == 1


def test_a_gold_class_the_weak_labels_never_taught_is_reported_as_unreachable(make_article, taxonomy):
    articles = _corpus(make_article, SPEC)
    data = dataset.build(articles, taxonomy, min_per_class=1, holdout={"s1": "conflict_war"})

    assert "conflict_war" not in data.classes
    assert data.unreachable == {"conflict_war": 1}


def test_a_gold_label_naming_a_fixed_group_is_used_as_is(make_article, taxonomy):
    """v4 is flat: there is no child level left to collapse, so a human label
    naming one of the 13 groups passes straight through."""
    articles = _corpus(make_article, SPEC)
    data = dataset.build(articles, taxonomy, min_per_class=1, holdout={"h1": "crime_justice"})

    assert data.gold[0].topic == "crime_justice"


def test_an_unsorted_gold_label_is_not_scored(make_article, taxonomy):
    """It is the absence of a class; scoring it adds a guaranteed zero."""
    articles = _corpus(make_article, SPEC)
    data = dataset.build(articles, taxonomy, min_per_class=1, holdout={"s1": "unsorted"})

    assert data.gold == ()
    assert data.withheld_for_gold == 1


def test_one_article_cannot_both_teach_and_score(make_article, taxonomy):
    articles = _corpus(make_article, SPEC)
    with pytest.raises(ValueError, match="both gold and holdout"):
        dataset.build(articles, taxonomy, gold={"s1": "sport"}, holdout={"s1": "sport"})


def test_disjoint_human_labels_may_teach_and_score_in_one_build(make_article, taxonomy):
    """The shipped arrangement: rare classes are taught by one slice, scored by another."""
    articles = _corpus(make_article, SPEC)
    data = dataset.build(
        articles,
        taxonomy,
        min_per_class=1,
        gold={"h1": "conflict_war", "h2": "conflict_war"},
        holdout={"s1": "conflict_war"},
    )

    taught = {e.article_id: e.topic for e in data.train}
    assert taught.get("h1") == "conflict_war", "the human label did not override the weak one"
    assert "conflict_war" in data.classes, "a class only humans can teach never reached the class list"
    assert [e.article_id for e in data.gold] == ["s1"]


def test_without_a_holdout_nothing_changes(make_article, taxonomy):
    articles = _corpus(make_article, SPEC)
    data = dataset.build(articles, taxonomy, min_per_class=1)

    assert data.gold == () and data.withheld_for_gold == 0
    assert len(data.train) + len(data.val) + len(data.test) == len(articles) - data.dropped_at_boundary


def test_dropping_weak_labels_leaves_only_the_hand_labelled_articles(make_article, taxonomy):
    articles = _corpus(make_article, SPEC)
    gold = {"s1": "sport", "s2": "sport"}

    data = dataset.build(
        articles, taxonomy, min_per_class=1, gold=gold, use_weak_labels=False
    )

    kept = {e.article_id for e in (*data.train, *data.val, *data.test)}
    assert kept == set(gold), f"an article with no human label was trained on: {kept - set(gold)}"
    assert all(e.label_source == "human" for e in data.train)
    assert data.unlabelled == len(articles) - len(gold)


def _snapshot(tmp_path, make_article, gold, taxonomy):
    articles = _corpus(make_article, SPEC)
    result = snapshot.build(
        articles, snapshot_id="s", out_root=tmp_path, variant="title_summary", repo=tmp_path,
        check_language=False, apply_boilerplate=False, gold=gold, taxonomy_version=taxonomy.version,
    )
    return snapshot.read(result.directory)


def test_a_snapshot_dataset_uses_the_split_the_snapshot_already_decided(tmp_path, make_article, taxonomy):
    """No re-cleaning, no re-grouping, no re-cutting. That is the whole point."""
    gold = {"s1": "sport", "s2": "sport", "h1": "health", "h2": "health"}
    snap = _snapshot(tmp_path, make_article, gold, taxonomy)

    data = dataset.from_snapshot(snap, taxonomy, min_per_class=1)

    split_of = {row.article_id: row.split for row in snap.rows}
    for example in (*data.train, *data.val, *data.test):
        assert example.text == next(r.text for r in snap.rows if r.article_id == example.article_id)
    for name in ("train", "val", "test"):
        assert all(split_of[e.article_id] == name for e in getattr(data, name))


def test_the_split_boundary_is_frozen_in_the_snapshot(tmp_path, make_article, taxonomy):
    """The boundary is a recorded publication time, not a side effect of the run."""
    gold = {"s1": "sport", "s2": "sport", "s3": "sport", "h1": "health", "h2": "health"}
    snap = _snapshot(tmp_path, make_article, gold, taxonomy)

    boundaries = snap.manifest["split_boundaries"]

    assert boundaries["placed_by"] == "labelled articles"
    assert boundaries["train_until"] and boundaries["val_until"]
    assert dataset.from_snapshot(snap, taxonomy, min_per_class=1).train


def test_the_cut_follows_the_labels_not_the_unlabelled_bulk(tmp_path, make_article, taxonomy):
    """Labelling stops when the round was drawn; everything collected after it is
    unlabelled. Cutting over the whole corpus put 37 of 1,317 labelled articles in
    the real test split, which is not a test split."""
    labelled = _corpus(make_article, SPEC)
    later = [
        make_article(f"u{i}", categories=("sport",), title=f"Unlabelled later story {i}", minutes=5000 + i * 90)
        for i in range(30)
    ]
    result = snapshot.build(
        [*labelled, *later], snapshot_id="cut", out_root=tmp_path, variant="title_summary",
        repo=tmp_path, check_language=False, apply_boilerplate=False, taxonomy_version=taxonomy.version,
        gold={a.id: "sport" if a.id.startswith("s") else "health" for a in labelled},
    )

    snap = snapshot.read(result.directory)
    data = dataset.from_snapshot(snap, taxonomy, min_per_class=1)

    assert data.test, "the later unlabelled articles swallowed the whole test window"
    assert snap.manifest["labelled_by_split"].get("test", 0) > 0


def test_every_snapshot_label_is_human_and_carries_its_provenance(tmp_path, make_article, taxonomy):
    snap = _snapshot(tmp_path, make_article, {"s1": "sport", "s2": "sport"}, taxonomy)

    data = dataset.from_snapshot(snap, taxonomy, min_per_class=1)

    assert {e.label_source for e in (*data.train, *data.val, *data.test)} == {"human"}
    assert data.provenance["snapshot_id"] == "s"
    assert data.provenance["taxonomy_version"] == taxonomy.version


def test_an_unlabelled_snapshot_row_is_counted_not_guessed(tmp_path, make_article, taxonomy):
    snap = _snapshot(tmp_path, make_article, {"s1": "sport", "h1": "unsorted"}, taxonomy)

    data = dataset.from_snapshot(snap, taxonomy, min_per_class=1)

    assert data.unlabelled == len(snap.rows) - 1, "`unsorted` is the absence of a class, not a class"
    assert {e.article_id for e in (*data.train, *data.val, *data.test)} == {"s1"}
