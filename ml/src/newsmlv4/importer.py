"""Import V4 sheets using the export-time database check (roadmap D14).

Round 1 was later confirmed AI-generated (D16, 22 Nov 2026). Its legacy
``gold.jsonl`` name and human-origin metadata are superseded, not proof of
human review. This validator checks text and agreement, not authorship.

`make ml4-labels-import` re-checks every candidate against the live local database by
ID and then calls `newsml import-labels`, which refuses any ID the database does not
hold. On 21 Nov the local database that round 1 was exported from had been replaced by
a production copy that holds none of its IDs, so that path cannot run. The owner
accepted the export-time database check instead. This path:

* proves the sheets still carry exactly the text `selection.jsonl` fingerprinted from
  the database at export, with every candidate labelled and no conflicting overlaps;
* looks each candidate up in today's database by content hash or title with the same
  fingerprint, and records what it finds rather than requiring it;
* writes annotations in the legacy `newsml import-labels` format without overwriting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from newsml.annotate import disagreements, read_sheet, read_sheet_texts
from newsml.labels import Taxonomy, load_taxonomy

from .cli import local_uri
from .sampling import DATA_ROOT, PROJECTION, TAXONOMY_PATH, unescape_cell
from .verify import compare_sheets, load_selection, sheet_digest

GOLD = "gold.jsonl"
CURRENT_IDS = "current-ids.jsonl"
RECORD = "import.json"
CHUNK = 500


def _find(collection: Collection[dict[str, Any]], field: str, values: list[str]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for start in range(0, len(values), CHUNK):
        cursor = collection.find(
            {field: {"$in": values[start:start + CHUNK]}},
            PROJECTION,
            batch_size=128,
            max_time_ms=30_000,
        )
        try:
            documents.extend(cursor)
        finally:
            cursor.close()
    return documents


def recheck(
    collection: Collection[dict[str, Any]],
    selection: dict[str, dict[str, Any]],
    titles: dict[str, str],
) -> dict[str, str]:
    """Today's ID for every candidate whose exported text is still in the database.

    IDs do not survive a database rebuilt by another collector, but text does. A
    candidate counts as found only when an article with the same content hash or the
    same title has the identical sheet fingerprint.
    """
    by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    hashes = sorted({str(r["content_hash"]) for r in selection.values() if r.get("content_hash")})
    for doc in _find(collection, "content_hash", hashes):
        by_key[("hash", str(doc.get("content_hash")))].append(doc)
    for doc in _find(collection, "title", sorted(set(titles.values()))):
        by_key[("title", str(doc.get("title")))].append(doc)

    found: dict[str, str] = {}
    for article_id, record in sorted(selection.items()):
        candidates = by_key[("hash", str(record.get("content_hash")))] + by_key[("title", titles.get(article_id, ""))]
        matches = sorted({
            str(doc["_id"]) for doc in candidates if sheet_digest(doc) == record["sheet_text_sha256"]
        })
        if matches:
            found[article_id] = matches[0]
    return found


def _write_atomic(path: Path, lines: Iterable[str]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
    temporary.replace(path)


def import_gold(
    run: Path,
    collection: Collection[dict[str, Any]],
    *,
    taxonomy: Taxonomy,
    data_root: Path = DATA_ROOT,
) -> dict[str, Any]:
    """Validate sheet text, record today's re-check and write legacy-format annotations."""
    if (run / GOLD).exists():
        raise FileExistsError(f"refusing to overwrite {run / GOLD}")
    selection = load_selection(run, data_root)
    _, missing, changed, conflicts = compare_sheets(run, selection)
    if missing or changed or conflicts:
        raise ValueError(
            f"sheets differ from the export: {missing} missing, {changed} changed, "
            f"{conflicts} conflicting"
        )

    sheets = sorted(run.glob("*.csv"))
    labels = []
    problems = []
    for path in sheets:
        found, issues = read_sheet(path, taxonomy, known_ids=frozenset(selection), annotator=path.stem)
        labels.extend(found)
        problems.extend(issues)
    if problems:
        first = problems[0]
        raise ValueError(f"{len(problems)} sheet problems, first {first.sheet}:{first.row} {first.detail}")
    gold = {label.article_id: label.topic for label in labels}
    if unlabelled := set(selection) - set(gold):
        raise ValueError(f"{len(unlabelled)} exported candidates have no label")
    if disputed := disagreements(labels):
        raise ValueError(f"{len(disputed)} articles have conflicting labels; adjudicate them first")

    texts = read_sheet_texts(sheets)
    current = recheck(collection, selection, {a: unescape_cell(t) for a, (t, _) in texts.items()})
    not_rechecked = sorted(set(selection) - set(current))
    gold_lines = [
        json.dumps({
            "article_id": label.article_id,
            "topic": label.topic,
            "label_source": str(label.source),
            "annotator": label.detail,
            "taxonomy_version": taxonomy.version,
        }, sort_keys=True) + "\n"
        for label in sorted(labels, key=lambda x: (x.article_id, x.detail))
    ]
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    record = {
        "run": run.name,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": "roadmap D14: import on the export-time database check",
        "database_check_of_record": f"at export (cut {manifest.get('cut')})",
        "sheets_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sheets},
        "labels": len(labels),
        "articles": len(gold),
        "distribution": dict(sorted(Counter(gold.values()).items())),
        "current_database": {
            "identical_text": len(current),
            "not_rechecked": len(not_rechecked),
            "not_rechecked_by_label": dict(sorted(Counter(gold[a] for a in not_rechecked).items())),
        },
        "gold_sha256": hashlib.sha256("".join(gold_lines).encode("utf-8")).hexdigest(),
    }

    _write_atomic(run / CURRENT_IDS, (
        json.dumps({"article_id": a, "current_id": c}, sort_keys=True) + "\n"
        for a, c in sorted(current.items())
    ))
    _write_atomic(run / RECORD, [json.dumps(record, indent=2, sort_keys=True) + "\n"])
    _write_atomic(run / GOLD, gold_lines)  # last: its presence marks a finished import
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import V4 annotations using the export-time database check (D14); text checks do not certify human authorship"
    )
    parser.add_argument("--run", required=True, type=Path, help="directory inside ml/artifacts/v4/")
    args = parser.parse_args(argv)
    try:
        uri = local_uri()
        os.umask(0o077)
        with MongoClient(uri) as client:
            record = import_gold(
                args.run,
                client.get_database("news").get_collection("articles"),
                taxonomy=load_taxonomy(TAXONOMY_PATH),
            )
    except (ValueError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"V4 import refused: {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        print(f"V4 local MongoDB read failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    current = record["current_database"]
    print(f"{record['labels']} labels over {record['articles']} articles; "
          f"distribution {record['distribution']}")
    print(f"Today's database: {current['identical_text']} with identical text, "
          f"{current['not_rechecked']} not re-checked {current['not_rechecked_by_label']}")
    print(f"gold -> {args.run / GOLD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
