"""Snapshot invariants, checked against the real frozen dataset.

These run against `v2-001` if it exists, because the properties that matter (splits are
proportionate, no group straddles, the labelled reference actually drove the cuts) only
break on real data -- a synthetic fixture would have passed every one of them while the
real snapshot was silently cut on corpus-wide quantiles.
"""

from __future__ import annotations

import pandas as pd
import pytest

from newsmlv2 import config, snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
pytestmark = pytest.mark.skipif(
    not (config.SNAPSHOT_DIR / SNAPSHOT_ID).exists(),
    reason=f"snapshot {SNAPSHOT_ID} not cut yet",
)


@pytest.fixture(scope="module")
def snap():
    return snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)


@pytest.fixture(scope="module")
def labelled(snap):
    frame = snap.frame
    return frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]


def test_digests_still_match(snap):
    assert all(snapshot_mod.verify(snap.directory).values())


def test_fields_are_stored_separately(snap):
    for column in ("title", "summary", "body", "publisher", "story_group_id", "split"):
        assert column in snap.frame.columns


def test_the_labelled_split_is_roughly_seventy_fifteen_fifteen(labelled):
    """Caught a real bug: NaN topics counted as labelled and gave 79/12/9."""
    n = len(labelled)
    shares = {name: (labelled["split"] == name).sum() / n for name in ("train", "val", "test")}
    assert 0.65 <= shares["train"] <= 0.75, shares
    assert 0.11 <= shares["val"] <= 0.19, shares
    assert 0.11 <= shares["test"] <= 0.19, shares


def test_the_cuts_were_placed_on_labelled_rows(snap, labelled):
    """The boundary must sit at the labelled 70th percentile, not the corpus one."""
    boundary = pd.Timestamp(snap.manifest["split_boundaries"]["train_until"])
    expected = labelled["collected_at"].quantile(0.70)
    assert abs((boundary - expected).total_seconds()) < 6 * 3600


def test_no_story_group_spans_two_splits(snap):
    live = snap.frame[snap.frame["split"] != "dropped"]
    spanning = live.groupby("story_group_id")["split"].nunique()
    assert (spanning > 1).sum() == 0


def test_test_articles_are_collected_after_train_articles(snap):
    frame = snap.frame
    train_max = frame.loc[frame["split"] == "train", "collected_at"].max()
    test_min = frame.loc[frame["split"] == "test", "collected_at"].min()
    assert train_max <= test_min


def test_unsorted_is_never_counted_as_a_class(snap):
    assert config.UNSORTED not in snap.manifest["class_distribution"]


def test_all_thirteen_classes_are_present_in_train(labelled):
    train = labelled[labelled["split"] == "train"]
    assert train["topic"].nunique() == 13
    assert train["topic"].value_counts().min() >= 5


def test_the_manifest_pins_the_label_file_by_digest(snap):
    assert len(snap.manifest["label_digest"]) == 64
    assert snap.manifest["collected_before"] == config.COLLECTED_BEFORE


def test_text_variants_never_produce_the_string_none(snap):
    frame = snap.frame.head(200)
    for variant in ("title", "title_summary", "title_body", "full"):
        assert not any("None" == t.strip() for t in snap.texts(frame, variant))


def test_body_variant_falls_back_to_summary_when_there_is_no_body(snap):
    no_body = snap.frame[~snap.frame["has_body"]].head(20)
    if len(no_body):
        texts = snap.texts(no_body, "title_body")
        assert all(t.strip() for t in texts)
