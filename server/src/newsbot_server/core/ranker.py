"""Ranker client and recommendation service, ported from Go's internal/recommendation.

The ranker (Flask `newsrec.api`) returns article IDs and display text only. This
module validates the request, calls the ranker, checks its answer and hydrates the
ranked IDs from MongoDB in one bounded query, keeping the ranker's order.
"""

from __future__ import annotations

import http.client
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import jsonutil
from .httpclient import MAX_RESPONSE_BYTES, Transport, http_transport
from .validation import METHODS, WINDOWS, valid_domain_tag, valid_id

MAX_RESULTS = 30
MAX_LIKED = 50
MAX_VIEWED = 2000
MAX_DOMAINS = 8
MAX_TEXT_BYTES = 12_000
REQUEST_BODY_LIMIT = 128 << 10


class RankerError(Exception):
    """Base class; the message is for logs only and never reaches a caller."""


class RankerInvalid(RankerError):
    """Go: recommendation.ErrInvalid."""


class RankerNotIndexed(RankerError):
    """Go: recommendation.ErrNotIndexed."""


class RankerUnavailable(RankerError):
    """Go: recommendation.ErrUnavailable."""


class RequestDecodeError(ValueError):
    """A recommendation body the Go handler would refuse before validation. Message is caller-safe."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --- Go-style typed decoding -------------------------------------------------------------

class _TypeMismatch(ValueError):
    pass


def _go_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise _TypeMismatch("expected a string")


def _go_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and -(2**63) <= value < 2**63:
        return value
    raise _TypeMismatch("expected an integer")


def _go_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            return number
    raise _TypeMismatch("expected a number")


def _go_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise _TypeMismatch("expected a boolean")


def _go_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [_go_str(item) for item in value]
    raise _TypeMismatch("expected an array of strings")


def _go_int_map(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _go_int(item) for key, item in sorted(value.items())}
    raise _TypeMismatch("expected an object of integers")


def _go_object(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise _TypeMismatch("expected an object")


# --- Request -------------------------------------------------------------------------------

_REQUEST_FIELDS = ("seed_id", "liked", "disliked", "viewed", "topic", "method", "limit", "window", "domains")


@dataclass(frozen=True)
class RecommendRequest:
    """Go: recommendation.Request."""

    seed_id: str = ""
    liked: tuple[str, ...] = ()
    disliked: tuple[str, ...] = ()
    viewed: tuple[str, ...] = ()
    topic: str = ""
    method: str = ""
    limit: int = 0
    window: str = ""
    domains: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, value: Any) -> RecommendRequest:
        """Decode like Go's json.Decoder with DisallowUnknownFields into the Request struct."""
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) - set(_REQUEST_FIELDS):
            raise RequestDecodeError("request body is not valid JSON, or contains unknown fields")
        try:
            lists = {name: tuple(_go_str_list(value.get(name)) or ()) for name in ("liked", "disliked", "viewed", "domains")}
            return cls(
                seed_id=_go_str(value.get("seed_id")),
                topic=_go_str(value.get("topic")),
                method=_go_str(value.get("method")),
                limit=_go_int(value.get("limit")),
                window=_go_str(value.get("window")),
                **lists,
            )
        except _TypeMismatch:
            raise RequestDecodeError("request body is not valid JSON, or contains unknown fields") from None

    @staticmethod
    def check_media_type(content_type: str | None) -> None:
        """Go: an absent Content-Type is accepted; any other media type is a 415."""
        if content_type and content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise RequestDecodeError("Content-Type must be application/json", status=415)

    @classmethod
    def from_body(cls, body: bytes, content_type: str | None, limit: int = REQUEST_BODY_LIMIT) -> RecommendRequest:
        """Go: decodeJSONLimit followed by the Request decode."""
        cls.check_media_type(content_type)
        if len(body) > limit:
            raise RequestDecodeError(f"request body must not exceed {limit} bytes")
        try:
            value = jsonutil.loads_one(body)
        except jsonutil.JSONBodyError as error:
            message = {
                "empty": "request body must not be empty",
                "trailing": "request body must contain exactly one JSON object",
            }.get(error.reason, "request body is not valid JSON, or contains unknown fields")
            raise RequestDecodeError(message) from None
        return cls.from_json(value)

    def validate(self) -> None:
        """Go: Request.Validate. Raises RankerInvalid."""
        if not 0 <= self.limit <= MAX_RESULTS or len(self.liked) > MAX_LIKED or len(self.disliked) > MAX_LIKED:
            raise RankerInvalid("limit or interests out of bounds")
        if len(self.viewed) > MAX_VIEWED:
            raise RankerInvalid("viewed history out of bounds")
        if self.method not in METHODS:
            raise RankerInvalid("unknown method")
        if jsonutil.utf8_len(self.topic) > 2:
            raise RankerInvalid("topic too long")
        if self.window not in WINDOWS or len(self.domains) > MAX_DOMAINS:
            raise RankerInvalid("window or domains out of bounds")
        if not all(valid_domain_tag(tag) for tag in self.domains):
            raise RankerInvalid("invalid domain tag")
        ids = [*self.liked, *self.disliked, *self.viewed, *([self.seed_id] if self.seed_id else [])]
        if not all(valid_id(article_id) for article_id in ids):
            raise RankerInvalid("invalid article ID")

    def ranker_payload(self) -> dict[str, Any]:
        """Go marshals the Request with omitempty on every field."""
        payload: dict[str, Any] = {}
        for name in _REQUEST_FIELDS:
            value = getattr(self, name)
            if value:
                payload[name] = list(value) if isinstance(value, tuple) else value
        return payload


# --- Responses -----------------------------------------------------------------------------

def _decode_topic(value: Any) -> dict[str, Any]:
    raw = _go_object(value)
    return {
        "id": _go_str(raw.get("id")),
        "label": _go_str(raw.get("label")),
        "keywords": _go_str_list(raw.get("keywords")),
        "count": _go_int(raw.get("count")),
        "representatives": _go_str_list(raw.get("representatives")),
    }


def decode_metadata(value: Any) -> dict[str, Any]:
    """Go: recommendation.Metadata, re-serialized with its omitempty rules."""
    raw = _go_object(value)
    topics = raw.get("topics")
    if topics is not None and not isinstance(topics, list):
        raise _TypeMismatch("topics must be an array")
    out: dict[str, Any] = {
        "snapshot_id": _go_str(raw.get("snapshot_id")),
        "articles": _go_int(raw.get("articles")),
        "publication_range": _go_str_list(raw.get("publication_range")),
        "collected_before": _go_str(raw.get("collected_before")),
        "methods": _go_str_list(raw.get("methods")),
    }
    default_method = _go_str(raw.get("default_method"))
    if default_method:
        out["default_method"] = default_method
    out["topics"] = None if topics is None else [_decode_topic(topic) for topic in topics]
    out["profile_note"] = _go_str(raw.get("profile_note"))
    out["date_note"] = _go_str(raw.get("date_note"))
    windows = _go_int_map(raw.get("windows"))
    if windows:
        out["windows"] = windows
    fresh_days = _go_int(raw.get("fresh_days"))
    if fresh_days:
        out["fresh_days"] = fresh_days
    for key in ("edition_date", "edition_timezone"):
        text = _go_str(raw.get(key))
        if text:
            out[key] = text
    domains = _go_int_map(raw.get("domains"))
    if domains:
        out["domains"] = domains
    return out


@dataclass(frozen=True)
class Hit:
    id: str
    score: float
    reason: str
    text: str
    text_kind: str
    input_kind: str
    topic: str
    date_verified: bool
    fresh: bool

    @classmethod
    def decode(cls, value: Any) -> Hit:
        raw = _go_object(value)
        return cls(
            id=_go_str(raw.get("id")),
            score=_go_float(raw.get("score")),
            reason=_go_str(raw.get("reason")),
            text=_go_str(raw.get("text")),
            text_kind=_go_str(raw.get("text_kind")),
            input_kind=_go_str(raw.get("input_kind")),
            topic=_go_str(raw.get("topic")),
            date_verified=_go_bool(raw.get("date_verified")),
            fresh=_go_bool(raw.get("fresh")),
        )


@dataclass(frozen=True)
class RankedPage:
    """Go: recommendation.Page."""

    items: tuple[Hit, ...]
    method: str
    snapshot_id: str
    exhausted: bool
    ignored_viewed_ids: int
    window: str
    edition_date: str

    @classmethod
    def decode(cls, value: Any) -> RankedPage:
        raw = _go_object(value)
        items = raw.get("items")
        if items is not None and not isinstance(items, list):
            raise _TypeMismatch("items must be an array")
        return cls(
            items=tuple(Hit.decode(item) for item in items or ()),
            method=_go_str(raw.get("method")),
            snapshot_id=_go_str(raw.get("snapshot_id")),
            exhausted=_go_bool(raw.get("exhausted")),
            ignored_viewed_ids=_go_int(raw.get("ignored_viewed_ids")),
            window=_go_str(raw.get("window")),
            edition_date=_go_str(raw.get("edition_date")),
        )


# --- Client -------------------------------------------------------------------------------

def check_endpoint(endpoint: str) -> str:
    """Go: recommendation.New's endpoint rule."""
    try:
        parts = urlsplit(endpoint)
        parts.port  # noqa: B018 - raises for an invalid port
    except ValueError:
        raise ValueError("recommender endpoint must be an http(s) URL without credentials or query") from None
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or not parts.hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
        or "?" in endpoint
        or "#" in endpoint
    ):
        raise ValueError("recommender endpoint must be an http(s) URL without credentials or query")
    return endpoint.rstrip("/")


class RankerClient:
    def __init__(self, endpoint: str, key: str = "", *, timeout: float = 5.0, transport: Transport | None = None) -> None:
        self.endpoint = check_endpoint(endpoint)
        self._key = key
        self._timeout = timeout
        self._transport = transport or http_transport

    def _call(self, path: str, payload: Mapping[str, Any] | None, timeout: float | None = None) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._key:
            headers["X-Recommender-Key"] = self._key
        body = None if payload is None else jsonutil.dumps(dict(payload))
        method = "GET" if payload is None else "POST"
        try:
            status, data = self._transport(method, self.endpoint + path, headers, body, timeout or self._timeout)
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise RankerUnavailable(f"request failed: {type(error).__name__}") from None
        if status == 400:
            raise RankerInvalid("ranker rejected the request")
        if status == 404:
            raise RankerNotIndexed("ranker does not know an article")
        if status != 200:
            raise RankerUnavailable(f"downstream status {status}")
        if len(data) > MAX_RESPONSE_BYTES:
            raise RankerUnavailable("ranker response too large")
        try:
            return jsonutil.loads_one(data)
        except jsonutil.JSONBodyError as error:
            raise RankerUnavailable(f"invalid response: {error.reason}") from None

    def metadata(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            metadata = decode_metadata(self._call("/v1/meta", None, timeout))
        except _TypeMismatch:
            raise RankerUnavailable("invalid metadata") from None
        if not metadata["snapshot_id"] or metadata["articles"] < 1 or not metadata["topics"]:
            raise RankerUnavailable("incomplete metadata")
        return metadata

    def rank(self, request: RecommendRequest) -> RankedPage:
        try:
            return RankedPage.decode(self._call("/v1/recommend", request.ranker_payload()))
        except _TypeMismatch:
            raise RankerUnavailable("invalid ranking response") from None


# --- Service -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Recommendation:
    """Go: recommendation.Result: the page plus hydrated articles and unavailable IDs."""

    page: RankedPage
    items: list[tuple[Hit, dict[str, Any]]] = field(default_factory=list)
    unavailable_ids: list[str] = field(default_factory=list)


class ArticleSource(Protocol):
    """What hydration needs: Go's recommendation.Articles."""

    def get_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]: ...


class RecommendationService:
    def __init__(self, ranker: RankerClient, articles: ArticleSource | None) -> None:
        if articles is None:
            raise ValueError("recommendation articles must not be nil")
        self.ranker = ranker
        self._articles = articles

    def metadata(self, timeout: float | None = None) -> dict[str, Any]:
        return self.ranker.metadata(timeout)

    def recommend(self, request: RecommendRequest) -> Recommendation:
        request.validate()
        page = self.ranker.rank(request)
        if len(page.items) > MAX_RESULTS or not page.snapshot_id:
            raise RankerUnavailable("invalid ranking response")
        seen: set[str] = set()
        for hit in page.items:
            if not valid_id(hit.id) or hit.id in seen or jsonutil.utf8_len(hit.text) > MAX_TEXT_BYTES:
                raise RankerUnavailable("invalid ranking item")
            seen.add(hit.id)
        ids = [hit.id for hit in page.items]
        if not ids:
            return Recommendation(page=page)
        try:
            docs = self._articles.get_by_ids(ids)
        except Exception as error:  # the store's failure must surface as unavailable, never as detail
            raise RankerUnavailable(f"hydrate articles: {type(error).__name__}") from None
        by_id = {doc.get("_id"): doc for doc in docs}
        result = Recommendation(page=page)
        for hit in page.items:
            doc = by_id.get(hit.id)
            if doc is None:
                result.unavailable_ids.append(hit.id)
            else:
                result.items.append((hit, doc))
        if not result.items:
            raise RankerUnavailable("no indexed articles remain in the selected database")
        return result
