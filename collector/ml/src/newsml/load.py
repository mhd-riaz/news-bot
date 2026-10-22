"""Read-only access to the bronze corpus.

Ground rule 5: bronze is immutable. Nothing in this package writes to MongoDB.
Every function here opens a client, reads, and closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient

from .config import mongo_uri

# Every Indian Express feed ships an empty <description>, which is 2,000 articles
# — a quarter of the corpus — reduced to a bare headline. The lede falls back to
# the opening of the scraped body, and caps both fields at the same length so
# that how much text an article carries never encodes which source it came from.
LEDE_CHARS = 400

# The fields Phase 2 needs. Projecting explicitly keeps the working set small and
# makes it obvious when a new dependency on a field is introduced.
PROJECTION = {
    "_id": 1,
    "dedup_id": 1,
    "source_id": 1,
    "source_name": 1,
    "url": 1,
    "canonical_url": 1,
    "title": 1,
    "summary": 1,
    "content": 1,
    "authors": 1,
    "categories": 1,
    "content_hash": 1,
    "language": 1,
    "country": 1,
    "published_at": 1,
    "collected_at": 1,
    "processing_status": 1,
    "scrape_status": 1,
}


@dataclass(frozen=True, slots=True)
class Article:
    """One bronze record, normalised into plain Python types."""

    id: str
    source_id: str
    source_name: str
    url: str
    title: str
    summary: str
    content: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    content_hash: str
    language: str
    country: str
    published_at: datetime
    collected_at: datetime
    scrape_status: str
    processing_status: str

    @property
    def lede(self) -> str:
        """The publisher's dek, or the opening of the body when there is none."""
        return _clip(self.summary or self.content, LEDE_CHARS)

    def text(self, variant: str) -> str:
        """Concatenate the fields a given corpus variant is built from."""
        parts = {
            "title": (self.title,),
            "title_summary": (self.title, self.lede),
            "title_summary_content": (self.title, self.lede, self.content),
        }[variant]
        return "\n".join(p for p in parts if p)


def _clip(value: str, limit: int) -> str:
    """Cut at the last whole word inside `limit`, so no word is ever halved."""
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind(" ")
    return head[:cut] if cut > 0 else head


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _to_article(doc: dict[str, Any]) -> Article:
    return Article(
        id=str(doc.get("_id", "")),
        source_id=str(doc.get("source_id", "")),
        source_name=str(doc.get("source_name", "")),
        url=str(doc.get("canonical_url") or doc.get("url") or ""),
        title=str(doc.get("title") or ""),
        summary=str(doc.get("summary") or ""),
        content=str(doc.get("content") or ""),
        authors=tuple(str(a) for a in (doc.get("authors") or [])),
        categories=tuple(str(c) for c in (doc.get("categories") or [])),
        content_hash=str(doc.get("content_hash") or ""),
        language=str(doc.get("language") or ""),
        country=str(doc.get("country") or ""),
        published_at=_as_utc(doc.get("published_at")),
        collected_at=_as_utc(doc.get("collected_at")),
        scrape_status=str(doc.get("scrape_status") or "unset"),
        processing_status=str(doc.get("processing_status") or "unset"),
    )


def load_articles(
    uri: str | None = None,
    limit: int | None = None,
    collected_before: datetime | None = None,
) -> list[Article]:
    """Fetch the corpus, sorted by `_id` so two runs see the same order.

    Sort order matters: near-duplicate grouping and split assignment are both
    order-sensitive, and an unsorted cursor would make snapshots irreproducible.

    `collected_before` is the cut that makes a snapshot re-cuttable from a larger
    corpus later. It filters on `collected_at`, never `published_at`: an article
    published in 2019 can be collected tomorrow, so only the arrival time is
    stable enough to reproduce the same row set from a database that has grown.
    """
    query: dict[str, Any] = {}
    if collected_before is not None:
        query["collected_at"] = {"$lt": collected_before}

    client: MongoClient = MongoClient(uri or mongo_uri(), tz_aware=True)
    try:
        cursor = client.get_database().get_collection("articles").find(query, PROJECTION).sort("_id", 1)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [_to_article(doc) for doc in cursor]
    finally:
        client.close()
