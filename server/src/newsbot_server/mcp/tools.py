"""The read-only MCP tools, independent of the MCP SDK so they can be tested directly.

Every tool reads `articles` (through the MCP program's read-only database login) or
asks the ranker. None writes anything. Limits match the reader API: at most 100
listed articles, 30 recommendations, 50 liked or disliked IDs, and the ranker's
12,000-byte text cap; any tool result is capped at 1 MiB.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pymongo.errors import PyMongoError

from ..core import jsonutil
from ..core.articles import (
    ArticleCursor,
    ArticleFilter,
    ArticleNotFound,
    ArticleReader,
    article_response,
    date_kind,
    get_article,
    list_articles,
)
from ..core.ranker import (
    MAX_RESULTS,
    RankerError,
    RankerInvalid,
    RankerNotIndexed,
    RecommendationService,
    Recommendation,
    RecommendRequest,
)
from ..core.validation import FieldErrors, ValidationFailed, parse_rfc3339

MAX_RESULT_BYTES = 1 << 20
DEFAULT_SEARCH_LIMIT = 20
DEFAULT_RECOMMENDATION_LIMIT = 10


class ToolInputError(ValueError):
    """A problem the calling agent can fix; the message is shown to it."""


def _validation_message(error: ValidationFailed) -> str:
    return "Invalid input: " + "; ".join(f"{item.field} {item.message}" for item in error.fields)


def _database_message(error: PyMongoError) -> str:
    if getattr(error, "timeout", False):
        return "The database took too long. Narrow the search (dates, source or a longer phrase) and try again."
    return "The article database is unavailable right now. Try again later."


def _ranker_message(error: RankerError) -> str:
    if isinstance(error, RankerInvalid):
        return "Choose valid article IDs, a known method (tfidf, svd or neural), a known window and at most 30 results."
    if isinstance(error, RankerNotIndexed):
        return "An article or topic is outside the current recommendation index. Use IDs from this index."
    return "Recommendations are unavailable right now. Try again later."


def _story(hit: Any, doc: dict[str, Any]) -> dict[str, Any]:
    return {
        **article_response(doc),
        "score": hit.score, "reason": hit.reason, "text": hit.text, "text_kind": hit.text_kind,
        "input_kind": hit.input_kind, "group": hit.topic, "date_kind": date_kind(doc),
        "date_verified": hit.date_verified, "fresh": hit.fresh,
    }


def _recommendations(result: Recommendation) -> dict[str, Any]:
    page = result.page
    out: dict[str, Any] = {
        "items": [_story(hit, doc) for hit, doc in result.items],
        "method": page.method,
        "snapshot_id": page.snapshot_id,
        "window": page.window,
        "exhausted": page.exhausted,
        "unavailable_ids": list(result.unavailable_ids),
        "ignored_viewed_ids": page.ignored_viewed_ids,
    }
    if page.edition_date:
        out["edition_date"] = page.edition_date
    return out


def result_size(value: Any) -> int:
    return len(jsonutil.dumps(value))


class ReadOnlyTools:
    def __init__(self, articles: ArticleReader, recommendations: RecommendationService) -> None:
        self._articles = articles
        self._recommendations = recommendations

    def search_articles(
        self,
        query: str = "",
        source_id: str = "",
        language: str = "en",
        country: str = "",
        topic: str = "",
        published_from: str = "",
        published_to: str = "",
        sort: str = "published_at",
        limit: int = DEFAULT_SEARCH_LIMIT,
        cursor: str = "",
    ) -> dict[str, Any]:
        errors = FieldErrors()
        bounds = {}
        for name, raw in (("published_from", published_from), ("published_to", published_to)):
            bounds[name] = parse_rfc3339(raw) if raw else None
            if raw and bounds[name] is None:
                errors.add(name, "must be an RFC 3339 timestamp, for example 2026-08-22T10:30:00Z")
        parsed_cursor = None
        if cursor:
            try:
                parsed_cursor = ArticleCursor.parse(cursor)
            except ValidationFailed:
                errors.add("cursor", "must be a next_cursor returned by an earlier search")
        try:
            errors.raise_if_any()
            page = list_articles(self._articles, ArticleFilter(
                source_id=source_id, language=language, country=country, topic=topic,
                published_from=bounds["published_from"], published_to=bounds["published_to"],
                sort=sort, cursor=parsed_cursor, limit=limit, text=query,
            ))
        except ValidationFailed as error:
            raise ToolInputError(_validation_message(error)) from None
        except PyMongoError as error:
            raise ToolInputError(_database_message(error)) from None
        return page.response()

    def get_article(self, article_id: str) -> dict[str, Any]:
        try:
            doc = get_article(self._articles, article_id.strip())
        except ValidationFailed:
            raise ToolInputError("Invalid input: article_id must be a valid UUID") from None
        except ArticleNotFound:
            raise ToolInputError("No article has this ID.") from None
        except PyMongoError as error:
            raise ToolInputError(_database_message(error)) from None
        article = article_response(doc)
        if result_size(article) > MAX_RESULT_BYTES:
            content = article.get("content", "")
            overflow = result_size(article) - MAX_RESULT_BYTES + 1024
            article["content"] = content.encode("utf-8")[: max(0, len(content.encode("utf-8")) - overflow)].decode("utf-8", "ignore")
            article["content_truncated"] = True
        return article

    def _recommend(self, request: RecommendRequest) -> dict[str, Any]:
        try:
            return _recommendations(self._recommendations.recommend(request))
        except RankerError as error:
            raise ToolInputError(_ranker_message(error)) from None

    def get_related(
        self, article_id: str, limit: int = DEFAULT_RECOMMENDATION_LIMIT, method: str = "", domains: Sequence[str] = (),
    ) -> dict[str, Any]:
        return self._recommend(RecommendRequest(
            seed_id=article_id.strip(), limit=_bounded(limit), method=method, domains=tuple(domains),
        ))

    def get_recommendations(
        self,
        liked: Sequence[str] = (),
        disliked: Sequence[str] = (),
        topic: str = "",
        window: str = "",
        method: str = "",
        domains: Sequence[str] = (),
        limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    ) -> dict[str, Any]:
        return self._recommend(RecommendRequest(
            liked=tuple(liked), disliked=tuple(disliked), topic=topic, window=window,
            method=method, domains=tuple(domains), limit=_bounded(limit),
        ))

    def list_topics(self) -> dict[str, Any]:
        try:
            metadata = self._recommendations.metadata()
        except RankerError as error:
            raise ToolInputError(_ranker_message(error)) from None
        keep = ("snapshot_id", "articles", "methods", "default_method", "topics", "windows",
                "fresh_days", "edition_date", "edition_timezone", "domains", "date_note")
        return {key: metadata[key] for key in keep if key in metadata}


def _bounded(limit: int) -> int:
    """0 would mean the ranker's default; MCP asks for an explicit 1-30 instead."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise ToolInputError(f"Invalid input: limit must be between 1 and {MAX_RESULTS}")
    return limit
