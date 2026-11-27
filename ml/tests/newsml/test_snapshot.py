"""A snapshot must rebuild byte-identically, or it is not a snapshot."""

from __future__ import annotations

import json
import random

from newsml import snapshot
from newsml.config import CLEANING_VERSION


# Synthetic vocabulary rather than prose: two articles must be reliably
# *dissimilar* unless the test intends otherwise, and sampling disjoint tokens
# guarantees that in a way hand-written sentences do not.
VOCAB = [f"token{n:03d}" for n in range(400)]

# 60 tokens approximates a real summary. Length matters here: on a very short
# document a reworded headline is a large share of the shingles and drags
# similarity under the threshold on its own.
SUMMARY_TOKENS = 60


def _summary(i: int) -> str:
    return " ".join(random.Random(2026 + i).sample(VOCAB, SUMMARY_TOKENS))


def _corpus(make_article):
    """A small corpus with a syndicated pair, a reject, and enough spread to split."""
    articles = [
        make_article(f"a{i:02d}", title=f"Report number {i} from the desk", summary=_summary(i),
                     source_id=f"src-{i % 3}", minutes=i * 90)
        for i in range(24)
    ]

    # A syndicated reprint of a01: the same body with the tail reworded and a new
    # headline, which is what a wire pickup actually looks like. Jaccard stays
    # well above the grouping threshold, so the pair must share a story group.
    reprint = " ".join(_summary(1).split()[:-2] + ["token398", "token399"])
    articles.append(make_article("a99", title="Wire copy of report one", summary=reprint,
                                 source_id="src-2", minutes=95))

    # An article that must be rejected, so the rejection log is exercised.
    articles.append(make_article("bad", title="", summary="", source_id="src-0", minutes=10))
    return articles


def test_snapshot_rebuilds_byte_identically(tmp_path, make_article):
    articles = _corpus(make_article)
    kwargs = dict(out_root=tmp_path, variant="title_summary", repo=tmp_path, check_language=False)

    first = snapshot.build(articles, snapshot_id="run-a", **kwargs)
    second = snapshot.build(articles, snapshot_id="run-b", **kwargs)

    assert first.manifest["digests"] == second.manifest["digests"]


def test_rebuild_is_stable_under_input_reordering(tmp_path, make_article):
    """MongoDB returns a sorted cursor, but the guarantee should not rest on that."""
    articles = _corpus(make_article)
    kwargs = dict(out_root=tmp_path, variant="title_summary", repo=tmp_path, check_language=False)

    forward = snapshot.build(articles, snapshot_id="fwd", **kwargs)
    reverse = snapshot.build(list(reversed(articles)), snapshot_id="rev", **kwargs)

    assert forward.manifest["digests"] == reverse.manifest["digests"]


def test_manifest_records_full_provenance(tmp_path, make_article):
    result = snapshot.build(_corpus(make_article), snapshot_id="prov", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)
    manifest = result.manifest

    assert manifest["cleaning_version"] == CLEANING_VERSION
    assert manifest["text_variant"] == "title_summary"
    assert set(manifest["digests"]) == {"articles.jsonl", "rejections.jsonl", "labels.jsonl"}
    for key in ("input", "admitted", "rejected", "story_groups", "train", "val", "test"):
        assert key in manifest["counts"]


def test_counts_balance(tmp_path, make_article):
    articles = _corpus(make_article)
    result = snapshot.build(articles, snapshot_id="bal", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)
    counts = result.manifest["counts"]

    assert counts["input"] == len(articles)
    assert counts["admitted"] + counts["rejected"] == counts["input"]
    assert counts["train"] + counts["val"] + counts["test"] + counts["dropped_at_boundary"] == counts["admitted"]
    assert sum(result.manifest["rejection_reasons"].values()) == counts["rejected"]


def test_written_files_are_complete_and_parseable(tmp_path, make_article):
    result = snapshot.build(_corpus(make_article), snapshot_id="files", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)
    directory = result.directory

    for name in ("articles.jsonl", "rejections.jsonl", "manifest.json", "data-card.md"):
        assert (directory / name).exists(), name

    rows = [json.loads(line) for line in (directory / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == result.manifest["counts"]["admitted"]
    assert [r["article_id"] for r in rows] == sorted(r["article_id"] for r in rows)
    assert all(r["split"] in {"train", "val", "test", "dropped_at_boundary"} for r in rows)


def test_syndicated_pair_shares_a_story_group(tmp_path, make_article):
    result = snapshot.build(_corpus(make_article), snapshot_id="group", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)
    rows = {
        json.loads(line)["article_id"]: json.loads(line)
        for line in (result.directory / "articles.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert rows["a99"]["story_group_id"] == rows["a01"]["story_group_id"]


def test_data_card_states_the_limitations(tmp_path, make_article):
    result = snapshot.build(_corpus(make_article), snapshot_id="card", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)
    card = (result.directory / "data-card.md").read_text(encoding="utf-8")

    assert "Known limitations" in card
    assert "language_declared" in card
    assert CLEANING_VERSION in card


def test_labels_are_frozen_with_the_corpus_they_belong_to(tmp_path, make_article):
    """The snapshot id has to name one exact pairing of corpus and labels."""
    result = snapshot.build(
        _corpus(make_article), snapshot_id="lab", out_root=tmp_path, variant="title_summary",
        repo=tmp_path, check_language=False, gold={"a01": "politics", "a02": "sport"}, taxonomy_version=4,
    )

    snap = snapshot.read(result.directory)

    assert snap.labels == {"a01": "politics", "a02": "sport"}
    assert snap.provenance["taxonomy_version"] == 4
    assert snap.manifest["counts"]["labelled"] == 2


def test_a_label_whose_article_was_rejected_is_not_written(tmp_path, make_article):
    """Writing it would claim a label the snapshot cannot join to a row."""
    result = snapshot.build(
        _corpus(make_article), snapshot_id="orphan", out_root=tmp_path, variant="title_summary",
        repo=tmp_path, check_language=False,
        gold={"a01": "politics", "bad": "sport", "never-collected": "health"},
    )

    snap = snapshot.read(result.directory)

    assert set(snap.labels) == {"a01"}
    assert snap.manifest["counts"]["labels_offered"] == 3


def test_reading_a_snapshot_returns_the_rows_that_were_written(tmp_path, make_article):
    result = snapshot.build(_corpus(make_article), snapshot_id="rt", out_root=tmp_path,
                            variant="title_summary", repo=tmp_path, check_language=False)

    snap = snapshot.read(result.directory)

    assert len(snap.rows) == result.manifest["counts"]["admitted"]
    assert snap.snapshot_id == "rt"
    assert all(row.text for row in snap.rows), "text is already cleaned; nothing re-cleans it"
