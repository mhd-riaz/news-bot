"""Shared recommendation fixtures: synthetic artifacts, never a live DB.

Test modules cannot import each other under --import-mode=importlib, so the fixtures
used by more than one module live here.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from scipy import sparse
from sklearn.preprocessing import normalize

from newsrec import data
from newsrec.index import Index


def _save_documents(directory, rows):
    directory.mkdir()
    path = directory / "documents.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    data.write_json(directory / "manifest.json", {
        "snapshot_id": directory.name, "articles": len(rows),
        "documents_sha256": data.digest(path),
        "publication_range": ["2026-08-01", "2026-08-02"],
        "collected_before": "2026-08-03T00:00:00Z", "date_note": "Stored date, not verified.",
    })


@pytest.fixture
def index_dir(tmp_path):
    directory = tmp_path / "unit-index"
    rows = []
    for i, publisher in enumerate(("North", "Copy", "East", "South", "West", "North", "East", "West")):
        rows.append({
            "id": f"article-{i}", "title": f"Headline number {i}", "text": f"Article words {i}",
            "display_text": f"Stored text {i}", "display_kind": "Excerpt", "text_kind": "body",
            "publisher": publisher, "source_name": publisher, "url": f"https://example.test/{i}",
            "image_url": "", "published_at": "2026-08-01T00:00:00+00:00",
            "collected_at": "2026-08-02T00:00:00+00:00",
        })
    _save_documents(directory, rows)
    vectors = normalize(np.array([
        [1, 0, 0], [1, 0, 0], [.99, .1, 0], [0, 1, 0],
        [.9, .1, .1], [-1, 0, 0], [0, 0, 1], [.8, .2, 0],
    ], dtype=np.float32))
    sparse.save_npz(directory / "tfidf.npz", sparse.csr_matrix(vectors))
    for name in ("svd", "neural"):
        np.save(directory / f"{name}.npy", vectors, allow_pickle=False)
    data.write_json(directory / "groups.json", ["a", "a", "b", "c", "d", "e", "f", "g"])
    np.save(directory / "assignments.npy", np.array([0, 0, 0, 1, 0, 1, 1, 0]))
    data.write_json(directory / "topics.json", [
        {"id": "0", "label": "research", "keywords": ["research"], "count": 5,
         "representatives": ["article-0", "article-2", "article-4", "article-7"]},
        {"id": "1", "label": "society", "keywords": ["society"], "count": 3,
         "representatives": ["article-3", "article-5", "article-6"]},
    ])
    names = ["documents.jsonl", "groups.json", "tfidf.npz", "neural.npy", "svd.npy",
             "assignments.npy", "topics.json"]
    data.write_json(directory / "training.json", {
        "artifacts": {name: data.digest(directory / name) for name in names},
    })
    return directory


@pytest.fixture
def index(index_dir):
    return Index(index_dir)


@pytest.fixture
def save_documents():
    """Write a snapshot's documents.jsonl and the manifest that pins its digest."""
    return _save_documents
