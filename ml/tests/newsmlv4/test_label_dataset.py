"""data/labels/ holds IDs, topics and splits only, and matches its manifest (rule 11, roadmap D21)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from newsml.labels import load_taxonomy
from newsmlv4.sampling import REPO_ROOT, TAXONOMY_PATH

LABELS = REPO_ROOT / "data" / "labels"
COLUMNS = {"article_id", "topic", "split", "taxonomy_version", "aliases"}


@pytest.fixture(scope="module")
def manifest():
    return json.loads((LABELS / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows():
    text = (LABELS / "labels.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_labels_match_their_manifest(manifest, rows):
    assert hashlib.sha256((LABELS / "labels.jsonl").read_bytes()).hexdigest() == manifest["sha256"]
    assert len(rows) == manifest["rows"]
    assert Counter(row["split"] for row in rows) == Counter(manifest["splits"])
    counted = Counter((row["topic"], row["split"]) for row in rows)
    for topic, counts in manifest["topics"].items():
        assert (counted[topic, "train"], counted[topic, "test"]) == (counts["train"], counts["test"])


def test_rows_hold_only_ids_topics_and_one_split_each(rows):
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    ids = [article for row in rows for article in (row["article_id"], *row.get("aliases", []))]
    assert len(ids) == len(set(ids)), "an article appears in more than one row"
    for row in rows:
        assert set(row) <= COLUMNS, f"unexpected columns {set(row) - COLUMNS}"
        assert row["split"] in {"train", "test"}
        assert row["topic"] in taxonomy.ids and row["taxonomy_version"] == taxonomy.version
        assert "aliases" not in row or row["aliases"]
