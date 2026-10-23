"""Read the original corpus without writes and freeze a bounded recommendation cohort."""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from newsmlv2 import config
from newsmlv2.admit import Admitted, Policy, judge, non_latin_share
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean_article
from newsmlv2.load import _to_article

SEED = config.SEED
ROOT = config.ML_ROOT / "artifacts" / "recommender"
VERSION = "1.0.0"
SUPPORT_WORDS = 250


def settings() -> tuple[str, str]:
    values = config.env_values(Path(os.environ.get("NEWS_ENV_FILE", config.DOTENV_PATH)))
    uri = (
        os.environ.get("NEWS_MONGO_URI") or os.environ.get("NEWSMLV2_MONGO_URI")
        or values.get("NEWS_MONGO_URI") or config.DEFAULT_MONGO_URI
    )
    database = os.environ.get("NEWS_MONGO_DATABASE") or values.get("NEWS_MONGO_DATABASE") or "news"
    return uri, database


def inspect_database() -> dict[str, Any]:
    uri, database = settings()
    with MongoClient(uri, serverSelectionTimeoutMS=10_000) as client:
        collection = client[database].articles
        newest = collection.find_one({}, {"_id": 0, "collected_at": 1}, sort=[("collected_at", -1)])
        return {
            "database": database, "articles": collection.count_documents({}),
            "latest_collection": newest["collected_at"].isoformat() if newest else None,
        }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clip_words(text: str, count: int) -> str:
    words = text.split()
    return " ".join(words[:count]) + (" ..." if len(words) > count else "")


def english_text(text: str) -> bool:
    """A deterministic language gate; uncertain very short Latin headlines survive."""
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = SEED
    if non_latin_share(text) > 0.15:
        return False
    try:
        detected = detect_langs(text[:1500])
    except LangDetectException:
        return False
    best = detected[0]
    return best.lang == "en" or (len(text.split()) < 12 and best.prob < 0.95)


def input_text(title: str, summary: str, body: str) -> tuple[str, str]:
    """One field recipe for baseline, neural training and indexing, including short items."""
    support, kind = (body, "body") if body.strip() else (summary, "summary")
    if not support.strip() or support.casefold().strip() == title.casefold().strip():
        return title.strip(), "headline"
    if support.casefold().startswith(title.casefold()):
        support = support[len(title):].lstrip(" .:-\n")
    return f"{title}\n{' '.join(support.split()[:SUPPORT_WORDS])}".strip(), kind


def freeze(
    directory: Path, *, cut: datetime, limit: int = 20_000, candidates: int = 30_000
) -> dict[str, Any]:
    """Reservoir-sample a stable Mongo cursor, clean it, and persist IDs/text plus provenance."""
    if directory.exists():
        raise FileExistsError(f"{directory} already exists; use a new snapshot id")
    if cut.tzinfo is None or cut > datetime.now(UTC):
        raise ValueError("cut must be a timezone-aware instant in the past")
    if not 100 <= limit <= candidates <= 200_000:
        raise ValueError("require 100 <= limit <= candidates <= 200000")

    rng = random.Random(SEED)
    selected: list[dict[str, Any]] = []
    uri, database_name = settings()
    projection: dict[str, Any] = {
        name: 1 for name in (
            "_id", "source_id", "source_name", "url", "normalized_url", "canonical_url",
            "title", "image_url", "content_hash", "language", "country",
            "published_at", "collected_at", "scrape_status",
        )
    }
    projection.update({
        "summary": {"$substrCP": [{"$ifNull": ["$summary", ""]}, 0, 3000]},
        "content": {"$substrCP": [{"$ifNull": ["$content", ""]}, 0, 12_000]},
    })
    scanned = 0
    with MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=10_000) as client:
        database = client[database_name]
        cursor = database.articles.find(
            {"collected_at": {"$lt": cut}}, projection
        ).sort("_id", 1).batch_size(512)
        for scanned, document in enumerate(cursor, 1):
            if len(selected) < candidates:
                selected.append(document)
            else:
                position = rng.randrange(scanned)
                if position < candidates:
                    selected[position] = document
    if not scanned:
        raise ValueError("the selected Mongo database contains no articles before the cut")
    print(f"Read {scanned} records; preparing {len(selected)} candidates.", flush=True)

    selected.sort(key=lambda document: document["_id"])
    articles = [_to_article(document) for document in selected]
    boilerplate = as_lookup(discover((article.publisher, article.body) for article in articles))
    policy = Policy(
        min_words=0, min_title_words=3, max_age_days=365 * 30,
        reject_exact_duplicates=False, reject_non_latin=True,
    )
    rejected: Counter[str] = Counter()
    rows = []
    for document, article in zip(selected, articles, strict=True):
        title, summary, body = clean_article(
            article.title, article.summary, article.body,
            boilerplate=boilerplate.get(article.publisher),
        )
        reason = judge(Admitted(article, title, summary, body), policy=policy, now=cut)
        if reason:
            rejected[str(reason.reason)] += 1
            continue
        text, kind = input_text(title.text, summary.text, body.text)
        if not english_text(text):
            rejected["not_english_or_uncertain"] += 1
            continue
        if summary.text and summary.text.casefold() != title.text.casefold():
            display, display_kind = clip_words(summary.text, 75), "Stored summary"
        elif body.text:
            display, display_kind = clip_words(body.text, 75), "Excerpt"
        else:
            display, display_kind = "", "Headline only"
        published = article.published_at
        collected = article.collected_at
        rows.append({
            "id": article.id, "title": title.text, "text": text, "text_kind": kind,
            "display_text": display, "display_kind": display_kind,
            "publisher": article.publisher, "source_name": article.source_name,
            "url": document.get("canonical_url") or article.url,
            "image_url": document.get("image_url", ""),
            "published_at": published.isoformat() if published else None,
            "collected_at": collected.isoformat() if collected else None,
            "date_kind": "Collected" if published == collected else "Stored publication date",
            "content_hash": article.content_hash,
            "normalized_url": document.get("normalized_url") or article.url,
        })
    rng.shuffle(rows)
    rows = sorted(rows[:limit], key=lambda row: row["id"])
    if len(rows) < 100:
        raise ValueError(f"only {len(rows)} articles passed preparation; at least 100 are needed")

    directory.mkdir(parents=True)
    output = directory / "documents.jsonl"
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
    write_json(directory / "boilerplate.json", {
        publisher: sorted(lines) for publisher, lines in sorted(boilerplate.items())
    })
    manifest = {
        "version": VERSION, "snapshot_id": directory.name, "seed": SEED,
        "collected_before": cut.isoformat(), "cleaning_version": config.CLEANING_VERSION,
        "support_words": SUPPORT_WORDS, "database": database_name,
        "scanned": scanned, "candidates": len(selected),
        "articles": len(rows), "rejections": dict(rejected),
        "input_kinds": dict(Counter(row["text_kind"] for row in rows)),
        "images": sum(bool(row["image_url"]) for row in rows),
        "publishers": len({row["publisher"] for row in rows}),
        "publication_range": [
            min(row["published_at"] for row in rows if row["published_at"]),
            max(row["published_at"] for row in rows if row["published_at"]),
        ],
        "documents_sha256": digest(output),
        "language_note": "Seeded langdetect and script guard; not verified human language labels.",
        "date_note": "Original collector may have substituted collection time for a missing date.",
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def documents(directory: Path) -> list[dict[str, Any]]:
    manifest = read_json(directory / "manifest.json")
    path = directory / "documents.jsonl"
    if digest(path) != manifest["documents_sha256"]:
        raise ValueError("article snapshot digest mismatch; do not mix or edit artifacts")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != manifest["articles"] or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("article snapshot count or ID uniqueness mismatch")
    return rows
