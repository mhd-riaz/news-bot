"""Helpers shared by the integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from pymongo import ASCENDING, DESCENDING, IndexModel


def create_index_plan(database) -> None:
    """The subset of collector/internal/mongodb's index plan these tests rely on."""
    cursor = [("published_at", DESCENDING), ("_id", DESCENDING)]
    database.articles.create_indexes([
        IndexModel(cursor, name="ix_published_cursor"),
        IndexModel([("collected_at", DESCENDING), ("_id", DESCENDING)], name="ix_collected_cursor"),
        IndexModel([("source_id", ASCENDING), *cursor], name="ix_source_published_cursor"),
        IndexModel([("language", ASCENDING), *cursor], name="ix_language_published_cursor"),
        IndexModel([("country", ASCENDING), ("state", ASCENDING), ("city", ASCENDING), *cursor], name="ix_region_published_cursor"),
        IndexModel([("topic", ASCENDING), *cursor], name="ix_topic_published_cursor"),
    ])
    database.readers.create_indexes([
        IndexModel([("email", ASCENDING)], name="uq_email", unique=True),
        IndexModel([("google_sub", ASCENDING)], name="uq_google_sub", unique=True,
                   partialFilterExpression={"google_sub": {"$gt": ""}}),
    ])
    database.reader_sessions.create_indexes([
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
        IndexModel([("reader_id", ASCENDING)], name="ix_reader"),
    ])


def article(index: int, base: datetime, **overrides):
    doc = {
        "_id": f"0198f3d2-3333-7000-8000-{index:012d}",
        "source_id": "0198f3d2-1111-7000-8000-00000000aaaa",
        "source_name": "Example Source",
        "url": f"https://example.com/story/{index}",
        "normalized_url": f"https://example.com/story/{index}",
        "dedup_id": f"dedup-{index}",
        "title": f"Story {index}",
        "summary": f"Summary {index}",
        "content": f"Full text {index}",
        "language": "en",
        "country": "IN",
        "state": "Karnataka",
        "city": "Bengaluru",
        "published_at": base + timedelta(minutes=index),
        "collected_at": base + timedelta(minutes=index),
    }
    doc.update(overrides)
    return doc
