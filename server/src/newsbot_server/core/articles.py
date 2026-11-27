"""Read-only article access, ported from the Go handler, domain and repository.

Only the collector writes `articles` (rule 2). This module reads it with bounded,
indexed queries and maps documents to the same JSON the Go reader returned.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import pymongo

from .validation import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_REGION_LENGTH,
    FieldError,
    FieldErrors,
    ValidationFailed,
    parse_go_int,
    parse_rfc3339,
    too_long,
    two_letters,
    valid_id,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SORT_PUBLISHED = "published_at"
SORT_COLLECTED = "collected_at"
MAX_HYDRATE = 30
MAX_TEXT_QUERY = 200
_CURSOR_ALPHABET = re.compile(r"[A-Za-z0-9_-]*")
_CLASSIFIED = ("classified", "unsorted")

# The fields a response can show. dedup_id, normalized_url, content_hash, feed_guid and
# processing state are internal machinery and are never read for a response.
_RESPONSE_FIELDS = (
    "source_id", "source_name", "url", "canonical_url", "image_url", "title", "summary", "content",
    "authors", "categories", "language", "country", "state", "city", "published_at", "collected_at",
    "topic", "classification_status", "confidence",
)
FULL_PROJECTION = {name: 1 for name in _RESPONSE_FIELDS}
LIST_PROJECTION = {name: 1 for name in _RESPONSE_FIELDS if name != "content"}
HYDRATE_PROJECTION = {name: 1 for name in _RESPONSE_FIELDS if name not in ("content", "summary")}


class ArticleNotFound(LookupError):
    pass


def as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def format_time(value: Any) -> str:
    """Go's time.Time JSON form (RFC 3339 with trimmed nanoseconds). Missing is Go's zero time."""
    moment = as_utc(value)
    if moment is None:
        return "0001-01-01T00:00:00Z"
    text = f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
    if moment.microsecond:
        text += "." + f"{moment.microsecond:06d}".rstrip("0")
    return text + "Z"


def _text(doc: Mapping[str, Any], key: str) -> str:
    value = doc.get(key)
    return value if isinstance(value, str) else ""


def _texts(doc: Mapping[str, Any], key: str) -> list[str]:
    value = doc.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _number(doc: Mapping[str, Any], key: str) -> float:
    value = doc.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def article_response(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The Go reader's articleResponse, field for field, including its omitempty rules."""
    out: dict[str, Any] = {
        "id": doc.get("_id") if isinstance(doc.get("_id"), str) else "",
        "source_id": _text(doc, "source_id"),
        "source_name": _text(doc, "source_name"),
        "url": _text(doc, "url"),
    }
    for key in ("canonical_url", "image_url"):
        if _text(doc, key):
            out[key] = _text(doc, key)
    out["title"] = _text(doc, "title")
    for key in ("summary", "content"):
        if _text(doc, key):
            out[key] = _text(doc, key)
    for key in ("authors", "categories"):
        if _texts(doc, key):
            out[key] = _texts(doc, key)
    out["language"] = _text(doc, "language")
    out["country"] = _text(doc, "country")
    for key in ("state", "city"):
        if _text(doc, key):
            out[key] = _text(doc, key)
    out["published_at"] = format_time(doc.get("published_at"))
    out["collected_at"] = format_time(doc.get("collected_at"))
    status = _text(doc, "classification_status")
    if status in _CLASSIFIED:
        if _text(doc, "topic"):
            out["topic"] = _text(doc, "topic")
        out["classification_status"] = status
        out["confidence"] = _number(doc, "confidence")
    return out


def date_kind(doc: Mapping[str, Any]) -> str:
    """Go: "Collected" when the stored publication date is the collection time."""
    return "Collected" if as_utc(doc.get("published_at")) == as_utc(doc.get("collected_at")) else "Stored publication date"


def _millis(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True)
class ArticleCursor:
    """The last article of a page: its sort value and the _id tie-breaker."""

    value: datetime
    id: str

    def encode(self) -> str:
        raw = f"{_millis(self.value)}.{self.id}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def parse(raw: str) -> ArticleCursor:
        """Go: domain.ParseArticleCursor. A tampered cursor is rejected, never reset."""
        invalid = ValidationFailed([FieldError("cursor", "must be a cursor returned by a previous page")])
        token = raw.strip().replace("\r", "").replace("\n", "")
        if not _CURSOR_ALPHABET.fullmatch(token) or len(token) % 4 == 1:
            raise invalid
        try:
            decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise invalid from None
        value, found, article_id = decoded.partition(".")
        millis = parse_go_int(value)
        if not found or millis is None or not valid_id(article_id):
            raise invalid
        try:
            moment = EPOCH + timedelta(milliseconds=millis)
        except OverflowError:
            raise invalid from None
        return ArticleCursor(value=moment, id=article_id)


@dataclass(frozen=True)
class ArticleFilter:
    source_id: str = ""
    language: str = ""
    country: str = ""
    state: str = ""
    city: str = ""
    topic: str = ""
    published_from: datetime | None = None
    published_to: datetime | None = None
    sort: str = ""
    cursor: ArticleCursor | None = None
    limit: int = 0
    # MCP search only: a case-insensitive phrase matched in the title or summary.
    text: str = ""

    def normalized(self) -> ArticleFilter:
        """Go: ArticleFilter.Normalize, including its order (default sort before trimming)."""
        sort = self.sort or SORT_PUBLISHED
        return replace(
            self,
            limit=self.limit or DEFAULT_LIST_LIMIT,
            sort=sort.strip().lower(),
            source_id=self.source_id.strip(),
            language=self.language.strip().lower(),
            country=self.country.strip().upper(),
            state=self.state.strip(),
            city=self.city.strip(),
            topic=self.topic.strip().lower(),
            text=self.text.strip(),
        )

    def validate(self) -> None:
        """Go: ArticleFilter.Validate. Every problem is reported at once."""
        errors = FieldErrors()
        if not 1 <= self.limit <= MAX_LIST_LIMIT:
            errors.add("limit", f"must be between 1 and {MAX_LIST_LIMIT}, got {self.limit}")
        if self.sort not in (SORT_PUBLISHED, SORT_COLLECTED):
            errors.add("sort", "must be one of published_at, collected_at")
        if self.source_id and not valid_id(self.source_id):
            errors.add("source_id", "must be a valid UUID")
        if self.language and not two_letters(self.language):
            errors.add("language", "must be a two-letter ISO 639-1 code")
        if self.country and not two_letters(self.country):
            errors.add("country", "must be a two-letter ISO 3166-1 alpha-2 code")
        for name in ("state", "city", "topic"):
            if too_long(getattr(self, name)):
                errors.add(name, f"must be at most {MAX_REGION_LENGTH} characters")
        if self.published_from and self.published_to and self.published_from > self.published_to:
            errors.add("published_from", "must not be later than published_to")
        if too_long(self.text, MAX_TEXT_QUERY):
            errors.add("query", f"must be at most {MAX_TEXT_QUERY} characters")
        errors.raise_if_any()

    def cursor_for(self, doc: Mapping[str, Any]) -> str:
        field = SORT_COLLECTED if self.sort == SORT_COLLECTED else SORT_PUBLISHED
        value = as_utc(doc.get(field)) or datetime(1, 1, 1, tzinfo=UTC)
        return ArticleCursor(value=value, id=str(doc.get("_id", ""))).encode()


def filter_from_query(args: Mapping[str, str]) -> ArticleFilter:
    """Go: parseArticleFilter. Handler-level problems are reported before the service runs."""
    errors = FieldErrors()

    def timestamp(name: str) -> datetime | None:
        raw = args.get(name, "")
        if not raw:
            return None
        parsed = parse_rfc3339(raw)
        if parsed is None:
            errors.add(name, "must be an RFC 3339 timestamp, for example 2026-08-22T10:30:00Z")
        return parsed

    published_from = timestamp("published_from")
    published_to = timestamp("published_to")
    limit = 0
    if args.get("limit", ""):
        parsed = parse_go_int(args["limit"])
        if parsed is None:
            errors.add("limit", "must be an integer")
        else:
            limit = parsed
    cursor = None
    if args.get("cursor", ""):
        try:
            cursor = ArticleCursor.parse(args["cursor"])
        except ValidationFailed:
            errors.add("cursor", "must be a cursor returned by a previous page")
    errors.raise_if_any()
    return ArticleFilter(
        source_id=args.get("source_id", ""),
        language=args.get("language", ""),
        country=args.get("country", ""),
        state=args.get("state", ""),
        city=args.get("city", ""),
        topic=args.get("topic", ""),
        published_from=published_from,
        published_to=published_to,
        sort=args.get("sort", ""),
        cursor=cursor,
        limit=limit,
    )


def article_query(flt: ArticleFilter) -> dict[str, Any]:
    """Go: articleQuery. Built field by field from validated values; nothing is spliced in."""
    field = SORT_COLLECTED if flt.sort == SORT_COLLECTED else SORT_PUBLISHED
    query: dict[str, Any] = {}
    for name in ("source_id", "language", "country", "state", "city", "topic"):
        if getattr(flt, name):
            query[name] = getattr(flt, name)
    bounds: dict[str, Any] = {}
    if flt.published_from is not None:
        bounds["$gte"] = flt.published_from
    if flt.published_to is not None:
        bounds["$lte"] = flt.published_to
    if bounds:
        query["published_at"] = bounds
    alternatives: list[list[dict[str, Any]]] = []
    if flt.cursor is not None:
        # Resume strictly after the previous page; both arms use the (field, _id) index.
        alternatives.append([
            {field: {"$lt": flt.cursor.value}},
            {field: flt.cursor.value, "_id": {"$lt": flt.cursor.id}},
        ])
    if flt.text:
        pattern = re.escape(flt.text)
        alternatives.append([
            {"title": {"$regex": pattern, "$options": "i"}},
            {"summary": {"$regex": pattern, "$options": "i"}},
        ])
    if len(alternatives) == 1:
        query["$or"] = alternatives[0]
    elif alternatives:
        query["$and"] = [{"$or": arms} for arms in alternatives]
    return query


@dataclass(frozen=True)
class ArticlePage:
    items: list[dict[str, Any]]
    limit: int
    has_more: bool
    next_cursor: str

    def response(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "items": [article_response(doc) for doc in self.items],
            "limit": self.limit,
            "has_more": self.has_more,
        }
        if self.next_cursor:
            out["next_cursor"] = self.next_cursor
        return out


class ArticleReader(Protocol):
    def get_by_id(self, article_id: str) -> dict[str, Any] | None: ...

    def get_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]: ...

    def list(self, flt: ArticleFilter) -> ArticlePage: ...


class ArticleStore:
    """pymongo reads over `articles`. Never inserts, updates or deletes."""

    def __init__(self, collection: Any, timeout: float | None = None) -> None:
        self._coll = collection
        # A tighter per-operation deadline than the client's timeoutMS (pymongo.timeout nests).
        self._timeout = timeout

    def _find(self, query: dict[str, Any], projection: dict[str, int], **options: Any) -> list[dict[str, Any]]:
        if self._timeout is None:
            return list(self._coll.find(query, projection, **options))
        with pymongo.timeout(self._timeout):
            return list(self._coll.find(query, projection, **options))

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        found = self._find({"_id": article_id}, FULL_PROJECTION, limit=1)
        return found[0] if found else None

    def get_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        """One bounded $in query for a ranked page; the caller keeps the ranker's order."""
        if len(ids) > MAX_HYDRATE:
            raise ValueError(f"article batch must contain at most {MAX_HYDRATE} IDs")
        if not all(valid_id(article_id) for article_id in ids):
            raise ValueError("article batch contains an invalid ID")
        if not ids:
            return []
        return self._find({"_id": {"$in": list(ids)}}, HYDRATE_PROJECTION)

    def list(self, flt: ArticleFilter) -> ArticlePage:
        field = SORT_COLLECTED if flt.sort == SORT_COLLECTED else SORT_PUBLISHED
        items = self._find(article_query(flt), LIST_PROJECTION, sort=[(field, -1), ("_id", -1)], limit=flt.limit + 1)
        if len(items) > flt.limit:
            items = items[: flt.limit]
            return ArticlePage(items=items, limit=flt.limit, has_more=True, next_cursor=flt.cursor_for(items[-1]))
        return ArticlePage(items=items, limit=flt.limit, has_more=False, next_cursor="")


def list_articles(reader: ArticleReader, flt: ArticleFilter) -> ArticlePage:
    """Go: ArticleService.List."""
    flt = flt.normalized()
    flt.validate()
    return reader.list(flt)


def get_article(reader: ArticleReader, article_id: str) -> dict[str, Any]:
    """Go: ArticleService.Get."""
    if not valid_id(article_id):
        raise ValidationFailed([FieldError("id", "must be a valid UUID")])
    doc = reader.get_by_id(article_id)
    if doc is None:
        raise ArticleNotFound(article_id)
    return doc
