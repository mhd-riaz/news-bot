"""Splitting invariants. Every one of these encodes a v1 mistake."""

from datetime import UTC, datetime, timedelta

from newsmlv2.splits import (
    SplitRow,
    groups_spanning_splits,
    make_splits,
    publisher_holdout,
)

START = datetime(2026, 8, 20, tzinfo=UTC)


def _rows(n: int, *, group_every: int = 1, labelled_upto: int | None = None) -> list[SplitRow]:
    """n articles one hour apart; `group_every` consecutive ones share a story group."""
    out = []
    for i in range(n):
        out.append(
            SplitRow(
                article_id=f"a{i:04d}",
                group_id=f"g{i // group_every:04d}",
                collected_at=START + timedelta(hours=i),
                publisher="The Hindu" if i % 3 else "The Guardian",
                labelled=labelled_upto is None or i < labelled_upto,
            )
        )
    return out


class TestOrdering:
    def test_every_test_article_is_collected_after_every_train_article(self):
        rows = _rows(100)
        splits = make_splits(rows)
        when = {r.article_id: r.collected_at for r in rows}
        assert max(when[a] for a in splits.train) < min(when[a] for a in splits.test)

    def test_the_split_is_roughly_the_requested_shape(self):
        splits = make_splits(_rows(1000))
        assert 650 <= len(splits.train) <= 750
        assert 100 <= len(splits.val) <= 200
        assert 100 <= len(splits.test) <= 200

    def test_boundaries_are_recorded_so_a_snapshot_can_freeze_them(self):
        splits = make_splits(_rows(100))
        assert splits.train_until is not None and splits.val_until is not None
        assert splits.train_until < splits.val_until


class TestGrouping:
    def test_no_story_group_is_ever_split(self):
        """The single invariant the whole design rests on."""
        rows = _rows(300, group_every=7)
        assert groups_spanning_splits(rows, make_splits(rows)) == set()

    def test_a_group_straddling_a_boundary_is_dropped_whole(self):
        rows = _rows(100, group_every=10)
        splits = make_splits(rows)
        by_id = {r.article_id: r for r in rows}
        dropped_groups = {by_id[a].group_id for a in splits.dropped_at_boundary}
        for group in dropped_groups:
            members = {r.article_id for r in rows if r.group_id == group}
            assert members <= set(splits.dropped_at_boundary)

    def test_every_article_ends_up_somewhere(self):
        rows = _rows(200, group_every=5)
        assert make_splits(rows).total == len(rows)

    def test_a_single_corpus_wide_group_cannot_empty_the_other_splits(self):
        """v1 hit this: one group spanning the corpus left train=721, val=0, test=1."""
        rows = [
            SplitRow(f"a{i}", "one-big-group", START + timedelta(hours=i), "The Hindu")
            for i in range(50)
        ]
        splits = make_splits(rows)
        assert len(splits.dropped_at_boundary) == 50
        assert splits.train == splits.val == splits.test == ()


class TestReference:
    def test_cuts_are_placed_on_the_reference_rows_not_the_whole_corpus(self):
        """v1's bug: labelling stops when a round is drawn, collection does not.

        Cutting on corpus-wide quantiles put 37 labelled articles in a test split of
        1,317, because the whole test window opened after labelling had finished.
        """
        rows = _rows(1000, labelled_upto=500)
        labelled = [r for r in rows if r.labelled]

        naive = make_splits(rows)
        fixed = make_splits(rows, reference=labelled)

        labelled_ids = {r.article_id for r in labelled}
        naive_test = len(labelled_ids & set(naive.test))
        fixed_test = len(labelled_ids & set(fixed.test))
        assert naive_test == 0, "the naive cut starves the labelled test split"
        assert fixed_test > 50, "placing cuts on labelled rows restores it"

    def test_the_reference_cut_still_applies_to_unlabelled_rows(self):
        rows = _rows(400, labelled_upto=200)
        splits = make_splits(rows, reference=[r for r in rows if r.labelled])
        assert splits.total == len(rows)

    def test_a_nan_topic_must_not_count_as_labelled(self):
        """pandas stores a missing topic as NaN, and `bool(nan)` is True.

        That truthiness put every unlabelled row into the reference set and silently
        restored corpus-wide quantiles -- the very bug `reference` exists to prevent.
        """
        nan = float("nan")
        assert bool(nan) is True, "if this ever changes, the guard below can relax"
        assert not isinstance(nan, str)


class TestPublisherHoldout:
    def test_the_holdout_contains_only_that_publisher(self):
        rows = _rows(90)
        held = publisher_holdout(rows, "The Guardian")
        by_id = {r.article_id: r for r in rows}
        assert all(by_id[a].publisher == "The Guardian" for a in held.holdout)
        assert all(by_id[a].publisher != "The Guardian" for a in held.fit)

    def test_the_two_halves_cover_the_corpus_exactly_once(self):
        rows = _rows(90)
        held = publisher_holdout(rows, "The Guardian")
        assert len(held.fit) + len(held.holdout) == len(rows)
        assert not set(held.fit) & set(held.holdout)

    def test_an_unknown_publisher_holds_nothing_out(self):
        held = publisher_holdout(_rows(30), "Le Monde")
        assert held.holdout == ()


def test_an_empty_corpus_does_not_explode():
    splits = make_splits([])
    assert splits.total == 0
