"""Splits must be grouped AND temporal. Both are asserted, not eyeballed."""

from __future__ import annotations

from datetime import timedelta

from conftest import BASE

from newsml import splits
from newsml.splits import SplitRow


def _rows(count: int, group_size: int = 1) -> list[SplitRow]:
    return [
        SplitRow(
            article_id=f"a{i:04d}",
            group_id=f"g{i // group_size:04d}",
            published_at=BASE + timedelta(hours=i),
        )
        for i in range(count)
    ]


def test_no_story_group_spans_two_splits():
    """The criterion Phase 3's metrics depend on. A syndicated story on both
    sides of the split is memorisation reported as generalisation."""
    rows = _rows(300, group_size=5)
    assignment = splits.make_splits(rows)
    assert splits.groups_spanning_splits(rows, assignment) == set()


def test_every_test_article_is_newer_than_every_training_article():
    rows = _rows(300, group_size=5)
    assignment = splits.make_splits(rows)
    published = {r.article_id: r.published_at for r in rows}

    newest_train = max(published[a] for a in assignment.train)
    oldest_test = min(published[a] for a in assignment.test)
    assert oldest_test > newest_train


def test_validation_also_respects_the_temporal_boundary():
    rows = _rows(300, group_size=5)
    assignment = splits.make_splits(rows)
    published = {r.article_id: r.published_at for r in rows}

    assert min(published[a] for a in assignment.val) > max(published[a] for a in assignment.train)


def test_nothing_is_lost_or_duplicated():
    rows = _rows(300, group_size=5)
    assignment = splits.make_splits(rows)
    assigned = list(assignment.train) + list(assignment.val) + list(assignment.test) + list(assignment.dropped_at_boundary)

    assert assignment.total == len(rows)
    assert len(set(assigned)) == len(assigned), "an article landed in two splits"
    assert set(assigned) == {r.article_id for r in rows}


def test_straddling_groups_are_dropped_whole_not_truncated():
    """A group whose members bracket a cut point cannot satisfy both constraints.
    Dropping the whole group is the honest resolution; splitting it would put
    half a story in train and half in test."""
    rows = [
        SplitRow("early", "g0", BASE),
        SplitRow("late", "g0", BASE + timedelta(days=30)),
        SplitRow("middle", "g1", BASE + timedelta(days=1)),
        SplitRow("later", "g2", BASE + timedelta(days=2)),
    ]
    assignment = splits.make_splits(rows, train_fraction=0.5, val_fraction=0.25)
    assert assignment.total == len(rows)
    assert splits.groups_spanning_splits(rows, assignment) == set()
    assert set(assignment.dropped_at_boundary) == {"early", "late"}


def test_one_long_lived_group_does_not_empty_the_later_splits():
    """Regression: setting the boundary to max(published_at) over the whole train
    split let a single corpus-spanning group collapse val and test to nothing.
    Observed on the real corpus as train=721, val=0, test=1."""
    rows = _rows(300, group_size=1)
    rows.append(SplitRow("straggler_old", "spanning", BASE))
    rows.append(SplitRow("straggler_new", "spanning", BASE + timedelta(hours=299)))

    assignment = splits.make_splits(rows)

    assert len(assignment.val) > 0, "validation split was emptied by one spanning group"
    assert len(assignment.test) > 0, "test split was emptied by one spanning group"
    assert set(assignment.dropped_at_boundary) == {"straggler_old", "straggler_new"}


def test_result_is_independent_of_input_order():
    rows = _rows(120, group_size=4)
    assert splits.make_splits(rows) == splits.make_splits(list(reversed(rows)))


def test_empty_input():
    assignment = splits.make_splits([])
    assert assignment.total == 0


def test_single_group_corpus_degrades_predictably():
    """Everything in one story group cannot be split at all. It must not raise,
    and it must not silently break the grouping guarantee."""
    rows = [SplitRow(f"a{i}", "only", BASE + timedelta(hours=i)) for i in range(10)]
    assignment = splits.make_splits(rows)
    assert splits.groups_spanning_splits(rows, assignment) == set()
    assert assignment.total == 10
