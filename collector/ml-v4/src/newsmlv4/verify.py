from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from newsml.annotate import COLUMNS

from .cli import local_uri
from .sampling import (
    DATA_ROOT,
    PROJECTION,
    SOURCES_PATH,
    TAXONOMY_PATH,
    _article,
    _records,
    safe_cell,
)


def load_selection(run: Path, data_root: Path = DATA_ROOT) -> dict[str, dict[str, Any]]:
    root = data_root.resolve()
    if run.resolve().parent != root or not run.is_dir():
        raise ValueError(f"run must be a directory directly inside {data_root}")
    manifest_path = run / "manifest.json"
    selection_path = run / "selection.jsonl"
    if any(not path.resolve().is_relative_to(root) for path in (manifest_path, selection_path)):
        raise ValueError("a candidate file points outside the private data directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "unlabeled_candidates_not_gold":
        raise ValueError("not a V4 candidate manifest")
    for key, path in (
        ("taxonomy_sha256", TAXONOMY_PATH),
        ("sources_sha256", SOURCES_PATH),
    ):
        if manifest.get(key) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"{key} changed since the candidate export")
    selection: dict[str, dict[str, Any]] = {}
    for path, number, record in _records((selection_path,)):
        article_id = record.get("article_id")
        if not isinstance(article_id, str) or not article_id or article_id in selection:
            raise ValueError(f"{path}:{number}: invalid or duplicate article_id")
        if not isinstance(record.get("content_hash"), str) or not isinstance(
            record.get("sheet_text_sha256"), str
        ):
            raise ValueError(f"{path}:{number}: missing candidate fingerprints")
        selection[article_id] = record
    digest = hashlib.sha256("\n".join(sorted(selection)).encode("utf-8")).hexdigest()
    if manifest.get("selected_digest") != digest:
        raise ValueError("candidate IDs do not match the manifest digest")
    return selection


def sheet_digest(doc: dict[str, Any]) -> str:
    """Fingerprint of a database article's text exactly as the export writes it to a sheet."""
    article = _article(doc)
    sheet = replace(article, title=safe_cell(article.title), summary=safe_cell(article.summary))
    return hashlib.sha256((sheet.title + "\n" + sheet.lede).encode("utf-8")).hexdigest()


def compare_documents(
    selection: dict[str, dict[str, Any]], documents: Iterable[dict[str, Any]]
) -> tuple[int, int, int]:
    seen: set[str] = set()
    changed = 0
    for doc in documents:
        article = _article(doc)
        if article.id not in selection or article.id in seen:
            raise ValueError("local MongoDB returned an unexpected or duplicate candidate ID")
        seen.add(article.id)
        digest = sheet_digest(doc)
        expected = selection[article.id]
        if article.content_hash != expected["content_hash"] or digest != expected["sheet_text_sha256"]:
            changed += 1
    return len(seen), len(selection) - len(seen), changed


def compare_sheets(
    run: Path, selection: dict[str, dict[str, Any]]
) -> tuple[int, int, int, int]:
    sheets = sorted(run.glob("*.csv"))
    if not sheets:
        raise ValueError("no candidate CSV sheets found in the run directory")
    seen: set[str] = set()
    changed: set[str] = set()
    conflicts: set[str] = set()
    labels: dict[str, str] = {}
    for path in sheets:
        if not path.resolve().is_relative_to(run.resolve()):
            raise ValueError("a candidate sheet points outside the private run directory")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(COLUMNS):
                raise ValueError(f"{path}: unexpected CSV columns")
            for number, row in enumerate(reader, start=2):
                article_id = row.get("article_id")
                if not isinstance(article_id, str) or article_id not in selection:
                    raise ValueError(f"{path}:{number}: unknown article_id")
                title, summary, label = row.get("title"), row.get("summary"), row.get("label")
                if (
                    not isinstance(title, str)
                    or not isinstance(summary, str)
                    or not isinstance(label, str)
                ):
                    raise ValueError(f"{path}:{number}: malformed CSV row")
                seen.add(article_id)
                digest = hashlib.sha256((title + "\n" + summary).encode("utf-8")).hexdigest()
                if digest != selection[article_id]["sheet_text_sha256"]:
                    changed.add(article_id)
                if label and article_id in labels and labels[article_id] != label:
                    conflicts.add(article_id)
                if label:
                    labels[article_id] = label
    return len(seen), len(selection) - len(seen), len(changed), len(conflicts)


def verify(
    collection: Collection[dict[str, Any]], selection: dict[str, dict[str, Any]]
) -> tuple[int, int, int]:
    documents: list[dict[str, Any]] = []
    ordered = sorted(selection)
    for start in range(0, len(ordered), 200):
        cursor = collection.find(
            {"_id": {"$in": ordered[start:start + 200]}},
            PROJECTION,
            batch_size=128,
            max_time_ms=30_000,
        )
        try:
            documents.extend(cursor)
        finally:
            cursor.close()
    return compare_documents(selection, documents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check V4 candidate text against local MongoDB")
    parser.add_argument("--run", required=True, type=Path, help="directory inside ml-v4/data/")
    args = parser.parse_args(argv)
    try:
        selection = load_selection(args.run, DATA_ROOT)
        sheet_checked, sheet_missing, sheet_changed, sheet_conflicts = compare_sheets(
            args.run, selection
        )
        uri = local_uri()
        with MongoClient(uri) as client:
            checked, missing, changed = verify(
                client.get_database("news").get_collection("articles"), selection
            )
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"V4 verification failed: {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        print(f"V4 local MongoDB read failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        f"V4 candidates: {checked} checked, {missing} missing, {changed} changed in DB; "
        f"sheets: {sheet_checked} checked, {sheet_missing} missing, "
        f"{sheet_changed} changed, {sheet_conflicts} label conflicts"
    )
    return 0 if not any(
        (missing, changed, sheet_missing, sheet_changed, sheet_conflicts)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
