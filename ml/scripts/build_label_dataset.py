"""Build data/labels/ from the pooled V4 labels and the split of model v4-ai-072b01a9ceaf.

Standard library only. Run it from ml/ on the machine that holds the private,
git-ignored inputs:

  python3 scripts/build_label_dataset.py           # write labels.jsonl and manifest.json
  python3 scripts/build_label_dataset.py --check   # rebuild in memory and compare; write nothing

Each output row keeps only the article ID, topic, train-or-test split and topic-list
version, plus `aliases` (the article's other IDs) when it has any. No article text and
no per-row origin leaves the private pool. The checks stop the build if the row count
differs from the pool's manifest, an article is in both splits or in neither, an ID
repeats, the split counts differ from the model's manifest, or a historical
evaluation ID from protected-tests.json would land in the training split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_ROOT.parent
POOL = ML_ROOT / "artifacts" / "v4" / "v4-ai-pooled-20261122T000000Z"
MODEL = ML_ROOT / "models" / "classifier" / "v4-ai-072b01a9ceaf"
TAXONOMY = ML_ROOT / "taxonomy.yaml"
OUT = REPO_ROOT / "data" / "labels"
SPLITS = {"development": "train", "test": "test"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fail(message: str) -> None:
    raise SystemExit(f"check failed: {message}")


def build() -> tuple[bytes, dict]:
    pool_manifest = json.loads((POOL / "manifest.json").read_text(encoding="utf-8"))
    model_manifest = json.loads((MODEL / "manifest.json").read_text(encoding="utf-8"))
    pool_rows = jsonl(POOL / "labels.jsonl")
    split_rows = jsonl(MODEL / "split.jsonl")
    protected = set(json.loads((POOL / "protected-tests.json").read_text(encoding="utf-8"))["ids"])

    if sha256(POOL / "labels.jsonl") != pool_manifest["labels_sha256"]:
        fail("the pool's labels.jsonl does not match its manifest")
    if sha256(MODEL / "split.jsonl") != model_manifest["split"]["sha256"]:
        fail("the model's split.jsonl does not match its manifest")
    if sha256(POOL / "manifest.json") != model_manifest["dataset_manifest_sha256"]:
        fail("the model was not trained on this pool")
    if sha256(TAXONOMY) != pool_manifest["taxonomy_sha256"]:
        fail("ml/taxonomy.yaml is not the taxonomy the pool was labelled with")
    if len(pool_rows) != pool_manifest["selected"]:
        fail(f"{len(pool_rows)} pool rows, but the pool manifest selected {pool_manifest['selected']}")

    split_of: dict[str, str] = {}
    for row in split_rows:
        if row["article_id"] in split_of:
            fail(f"{row['article_id']} appears twice in the split file")
        split_of[row["article_id"]] = SPLITS[row["split"]]
    ids = [row["article_id"] for row in pool_rows]
    if len(ids) != len(set(ids)):
        fail("an article ID repeats in the pool")
    if set(ids) != set(split_of):
        fail("the pool and the split file do not hold the same articles")

    rows, seen = [], set(ids)
    for record in sorted(pool_rows, key=lambda row: row["article_id"]):
        row = {
            "article_id": record["article_id"],
            "topic": record["topic"],
            "split": split_of[record["article_id"]],
            "taxonomy_version": record["taxonomy_version"],
        }
        aliases = sorted(set(record.get("aliases", [])) - {record["article_id"]})
        if aliases:
            if seen & set(aliases):
                fail(f"an alias of {record['article_id']} is another row's ID")
            seen.update(aliases)
            row["aliases"] = aliases
        if row["split"] == "train" and protected & {row["article_id"], *aliases}:
            fail(f"historical evaluation article {row['article_id']} is in the training split")
        rows.append(row)

    splits = Counter(row["split"] for row in rows)
    expected = {"train": model_manifest["split"]["development"], "test": model_manifest["split"]["test"]}
    if dict(splits) != expected:
        fail(f"split counts {dict(splits)} differ from the model manifest {expected}")
    topics = Counter(row["topic"] for row in rows)
    if dict(topics) != pool_manifest["counts"]:
        fail("topic counts differ from the pool manifest")
    versions = {row["taxonomy_version"] for row in rows}
    if len(versions) != 1:
        fail(f"rows carry several taxonomy versions: {sorted(versions)}")

    data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    by_topic = {
        topic: {"train": sum(1 for row in rows if row["topic"] == topic and row["split"] == "train"),
                "test": sum(1 for row in rows if row["topic"] == topic and row["split"] == "test"),
                "total": topics[topic]}
        for topic in sorted(topics)
    }
    manifest = {
        "file": "labels.jsonl",
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": len(rows),
        "rows_with_aliases": sum(1 for row in rows if "aliases" in row),
        "taxonomy_version": versions.pop(),
        "taxonomy_sha256": pool_manifest["taxonomy_sha256"],
        "splits": {"train": splits["train"], "test": splits["test"]},
        "topics": by_topic,
        "sources": {
            "pool": {
                "name": POOL.name,
                "manifest_sha256": sha256(POOL / "manifest.json"),
                "labels_sha256": pool_manifest["labels_sha256"],
            },
            "split": {
                "model": model_manifest["model_version"],
                "file": "split.jsonl",
                "sha256": model_manifest["split"]["sha256"],
                "mapping": SPLITS,
            },
            "protected_tests_sha256": sha256(POOL / "protected-tests.json"),
        },
    }
    return data, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with data/labels/; write nothing")
    args = parser.parse_args(argv)
    data, manifest = build()
    text = json.dumps(manifest, indent=2) + "\n"
    if args.check:
        same = (OUT / "labels.jsonl").read_bytes() == data and (OUT / "manifest.json").read_text() == text
        print("data/labels matches its sources" if same else "data/labels differs from its sources")
        return 0 if same else 1
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "labels.jsonl").write_bytes(data)
    (OUT / "manifest.json").write_text(text, encoding="utf-8")
    print(f"wrote {manifest['rows']} rows ({manifest['splits']['train']} train, "
          f"{manifest['splits']['test']} test); sha256 {manifest['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
