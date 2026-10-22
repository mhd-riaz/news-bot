from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from newsml.config import TAXONOMY_PATH
from newsml.labels import load_taxonomy
from newsml.load import Article

BASE = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def taxonomy():
    """The real taxonomy.yaml, so tests fail when it stops parsing."""
    return load_taxonomy(TAXONOMY_PATH)


@pytest.fixture
def make_article():
    """Build an Article with sensible defaults so each test states only what it
    actually cares about."""

    def _make(
        article_id: str = "a1",
        *,
        title: str = "Supreme Court reserves verdict on the electoral bonds case",
        summary: str = "The bench heard arguments from both sides over three days before reserving its order.",
        content: str = "",
        source_id: str = "src-a",
        source_name: str = "Source A",
        categories: tuple[str, ...] = ("india",),
        language: str = "en",
        content_hash: str = "",
        published_at: datetime | None = None,
        minutes: int = 0,
        scrape_status: str = "success",
    ) -> Article:
        return Article(
            id=article_id,
            source_id=source_id,
            source_name=source_name,
            url=f"https://example.test/{article_id}",
            title=title,
            summary=summary,
            content=content,
            authors=(),
            categories=categories,
            content_hash=content_hash or f"hash-{article_id}",
            language=language,
            country="IN",
            published_at=published_at or (BASE + timedelta(minutes=minutes)),
            collected_at=(published_at or (BASE + timedelta(minutes=minutes))) + timedelta(minutes=30),
            scrape_status=scrape_status,
            processing_status="processed",
        )

    return _make
