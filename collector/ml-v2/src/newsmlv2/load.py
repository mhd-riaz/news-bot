"""Read the bronze corpus.

The one structural change from v1: `title`, `summary` and `body` stay **separate**
all the way through. v1 concatenated them into a single string at load time, which
made it impossible to weight fields differently later -- and with bodies now present
on 94.3% of gold articles, a 650-word body would silently drown a 10-word headline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from pymongo import MongoClient

from . import config

COLLECTION = "articles"

# `source_name` is "<publisher> — <section>", e.g. "The Indian Express — Technology".
# Splitting on the dash collapses ~8 Indian Express feeds into one publisher, which is
# the only unit a publisher holdout can use: a single section feed carries one or two
# classes, so most classes get zero support and macro-F1 becomes meaningless.
_SECTION = re.compile(r"\s*[\u2014\u2013]\s*|\s+-\s+")

# Cap the fallback lede at a word boundary. 25% of articles have no summary at all.
LEDE_CHARS = 400


def publisher_of(source_name: str) -> str:
    return _SECTION.split(source_name or "", 1)[0].strip() or "(unknown)"


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class Article:
    id: str
    source_id: str
    source_name: str
    url: str
    title: str
    summary: str
    body: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    content_hash: str
    language: str
    country: str
    published_at: datetime | None
    collected_at: datetime | None
    scrape_status: str

    @property
    def publisher(self) -> str:
        return publisher_of(self.source_name)

    @property
    def has_body(self) -> bool:
        return bool(self.body.strip())

    @property
    def lede(self) -> str:
        """The publisher's dek, or the opening of the body when there isn't one."""
        if self.summary.strip():
            return self.summary.strip()[:LEDE_CHARS]
        head = self.body.strip()[: LEDE_CHARS + 40]
        if len(head) <= LEDE_CHARS:
            return head
        return head[:LEDE_CHARS].rsplit(" ", 1)[0]


def _to_article(doc: dict[str, Any]) -> Article:
    return Article(
        id=str(doc["_id"]),
        source_id=str(doc.get("source_id", "")),
        source_name=doc.get("source_name") or "",
        url=doc.get("url") or "",
        title=(doc.get("title") or "").strip(),
        summary=(doc.get("summary") or "").strip(),
        body=(doc.get("content") or "").strip(),
        authors=tuple(doc.get("authors") or ()),
        categories=tuple(doc.get("categories") or ()),
        content_hash=doc.get("content_hash") or "",
        language=doc.get("language") or "",
        country=doc.get("country") or "",
        published_at=_as_datetime(doc.get("published_at")),
        collected_at=_as_datetime(doc.get("collected_at")),
        scrape_status=doc.get("scrape_status") or "",
    )


def load_articles(
    uri: str | None = None,
    *,
    limit: int | None = None,
    collected_before: datetime | None = None,
) -> list[Article]:
    """Every article collected before the cut, ordered by id so runs are reproducible.

    The cut is on `collected_at`, never `published_at`: a 2019 article can arrive in
    the feed tomorrow, so publication date says nothing about what the corpus knew.
    """
    client: MongoClient = MongoClient(uri or config.mongo_uri(), serverSelectionTimeoutMS=10_000)
    try:
        cursor = client.get_database()[COLLECTION].find().sort("_id", 1)
        if limit is not None:
            cursor = cursor.limit(limit)
        articles = [_to_article(doc) for doc in cursor]
    finally:
        client.close()

    if collected_before is not None:
        articles = [a for a in articles if a.collected_at and a.collected_at < collected_before]
    return articles


def by_publisher(articles: Iterable[Article]) -> dict[str, list[Article]]:
    out: dict[str, list[Article]] = {}
    for a in articles:
        out.setdefault(a.publisher, []).append(a)
    return out
