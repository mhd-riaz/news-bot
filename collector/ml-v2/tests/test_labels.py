"""The vendored taxonomy and gold labels must stay internally consistent.

These are cheap invariants that have each already failed somewhere in v1's history.
"""

from datetime import UTC, datetime

import pytest

from newsmlv2 import config, labels


@pytest.fixture(scope="module")
def taxonomy():
    return labels.read_taxonomy()


@pytest.fixture(scope="module")
def gold():
    return labels.read_gold()


def test_taxonomy_is_the_flat_13_class_v4(taxonomy):
    assert taxonomy.version == 4
    assert len(taxonomy.classes) == 13
    assert config.UNSORTED not in taxonomy.classes


def test_every_gold_label_is_a_known_class_or_unsorted(taxonomy, gold):
    unknown = {t for t in gold.values() if t != config.UNSORTED and t not in taxonomy}
    assert not unknown, f"gold references classes not in the taxonomy: {unknown}"


def test_unsorted_is_removed_before_any_class_is_counted(taxonomy, gold):
    """The floor is derived from the smallest class, so `unsorted` must go first.

    Leaving its 63 rows in would set the floor to 63 and start training the sentinel
    as a 14th class -- the exact opposite of it being an abstention outcome.
    """
    trainable = labels.trainable(gold, taxonomy)
    assert config.UNSORTED not in set(trainable.values())
    assert len(labels.abstention_set(gold)) == len(gold) - len(trainable)


def test_all_thirteen_classes_survive_the_derived_floor(taxonomy, gold):
    """No class is ever dropped: the floor is the smallest class, by construction."""
    counts: dict[str, int] = {}
    for topic in labels.trainable(gold, taxonomy).values():
        counts[topic] = counts.get(topic, 0) + 1
    assert len(counts) == 13
    assert min(counts.values()) >= 5, "a class below 5 breaks StratifiedGroupKFold(5)"


def test_corpus_cut_is_in_the_past(taxonomy):
    """A cut in the future keeps admitting articles, so snapshots stop reproducing."""
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    assert cut < datetime.now(UTC)


def test_publisher_holdouts_are_publishers_not_section_feeds():
    for name in config.PUBLISHER_HOLDOUTS:
        assert "—" not in name and " - " not in name
