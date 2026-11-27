"""Fakes shared by the tests. Unit tests never touch MongoDB, the ranker or Google."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from newsbot_server.core.articles import ArticleFilter, ArticlePage
from newsbot_server.core.ranker import RankerClient, RecommendationService
from newsbot_server.core.readers import Reader, Session, hash_token
from newsbot_server.core.settings import load_web_settings

ONE_ID = "0198f3d2-3333-7000-8000-000000000001"
TWO_ID = "0198f3d2-3333-7000-8000-000000000002"
SOURCE_ID = "0198f3d2-1111-7000-8000-000000000001"
FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_URL = "https://news.example.test"


def sample_article(**overrides: Any) -> dict[str, Any]:
    published = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    doc = {
        "_id": ONE_ID,
        "dedup_id": "8f14e45fceea167a5a36dedd4bea2543",
        "source_id": SOURCE_ID,
        "source_name": "The Hindu — Bengaluru",
        "url": "https://www.thehindu.com/news/cities/bangalore/a-story/article1.ece",
        "normalized_url": "https://thehindu.com/news/cities/bangalore/a-story/article1.ece",
        "content_hash": "9c1185a5c5e9fc54612808977ee8f548b2258d31",
        "feed_guid": "guid-1",
        "processing_status": "processed",
        "title": "A story about Bengaluru",
        "summary": "A summary.",
        "content": "The full text of the article.",
        "language": "en",
        "country": "IN",
        "state": "Karnataka",
        "city": "Bengaluru",
        "published_at": published,
        "collected_at": published + timedelta(hours=1),
    }
    doc.update(overrides)
    return doc


class FakeArticles:
    """Stands in for ArticleStore; records calls so tests can see what reached it."""

    def __init__(self, docs: Sequence[dict[str, Any]] = (), page: ArticlePage | None = None, error: Exception | None = None) -> None:
        self.docs = {doc["_id"]: doc for doc in docs}
        self.page = page
        self.error = error
        self.calls = 0
        self.last_filter: ArticleFilter | None = None
        self.last_ids: list[str] = []

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.docs.get(article_id)

    def get_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        self.calls += 1
        self.last_ids = list(ids)
        if self.error:
            raise self.error
        return [{k: v for k, v in self.docs[i].items() if k not in ("content", "summary")} for i in ids if i in self.docs]

    def list(self, flt: ArticleFilter) -> ArticlePage:
        self.calls += 1
        self.last_filter = flt
        if self.error:
            raise self.error
        return self.page or ArticlePage(items=[], limit=flt.limit, has_more=False, next_cursor="")


class FakeRanker:
    """A transport for RankerClient that answers like the Flask ranker."""

    def __init__(self, status: int = 200, body: Any = None, meta: Any = None) -> None:
        self.status = status
        self.body = body if body is not None else {"snapshot_id": "test", "items": [], "exhausted": True}
        self.meta = meta if meta is not None else {"snapshot_id": "test", "articles": 2, "topics": [{"id": "0", "label": "science"}]}
        self.requests: list[tuple[str, str, dict[str, str], Any]] = []

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
        self.requests.append((method, url, dict(headers), json.loads(body) if body else None))
        if self.status != 200:
            return self.status, b""
        payload = self.meta if url.endswith("/v1/meta") else self.body
        return 200, payload if isinstance(payload, bytes) else json.dumps(payload).encode()


def recommendation_service(ranker: FakeRanker, articles: FakeArticles, key: str = "") -> RecommendationService:
    return RecommendationService(RankerClient("http://ranker.test", key, transport=ranker), articles)


class FakeReaders:
    """In-memory ReaderStore."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.logins: list[str] = []

    def add(self, reader_id: str, email: str, invited: bool = True, sub: str | None = None, name: str = "") -> None:
        self.docs[reader_id] = {"_id": reader_id, "email": email, "invited": invited, "name": name, **({"google_sub": sub} if sub else {})}

    def get(self, reader_id: str) -> Reader | None:
        doc = self.docs.get(reader_id)
        return Reader.from_doc(doc) if doc else None

    def by_google_sub(self, sub: str) -> Reader | None:
        return next((Reader.from_doc(d) for d in self.docs.values() if d.get("google_sub") == sub), None)

    def by_email(self, email: str) -> Reader | None:
        return next((Reader.from_doc(d) for d in self.docs.values() if d["email"] == email), None)

    def bind_google_sub(self, reader_id: str, sub: str) -> bool:
        doc = self.docs[reader_id]
        if not doc["invited"] or "google_sub" in doc:
            return False
        doc["google_sub"] = sub
        return True

    def record_login(self, reader_id: str, now: datetime, name: str = "") -> None:
        self.logins.append(reader_id)
        if name and not self.docs[reader_id].get("name"):
            self.docs[reader_id]["name"] = name


class FakeSessions:
    """In-memory SessionStore keyed by token hash, like the real one."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def create(self, reader_id: str) -> tuple[str, Session]:
        token = f"token-{len(self.docs) + 1}-" + "x" * 32
        now = datetime.now(UTC)
        session = Session(hash_token(token), reader_id, now, now + timedelta(days=7))
        self.docs[session.token_hash] = {"reader_id": reader_id}
        return token, session

    def lookup(self, token: str) -> Session | None:
        doc = self.docs.get(hash_token(token))
        if not doc:
            return None
        now = datetime.now(UTC)
        return Session(hash_token(token), doc["reader_id"], now, now + timedelta(days=7))

    def delete(self, token: str) -> None:
        self.docs.pop(hash_token(token), None)


def id_token(claims: Mapping[str, Any]) -> str:
    import base64

    def part(value: Any) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256', 'kid': 'test'})}.{part(dict(claims))}.c2lnbmF0dXJl"


class FakeGoogle:
    """Google's token endpoint: checks the PKCE verifier against the challenge it saw."""

    def __init__(self, client_id: str = "client-id.apps.googleusercontent.com") -> None:
        self.client_id = client_id
        self.challenge = ""
        self.nonce = ""
        self.status = 200
        self.claims: dict[str, Any] = {}
        self.posts: list[dict[str, list[str]]] = []

    def saw_authorization(self, location: str) -> dict[str, str]:
        query = {key: values[0] for key, values in parse_qs(location.split("?", 1)[1]).items()}
        self.challenge, self.nonce = query["code_challenge"], query["nonce"]
        return query

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
        import base64
        import hashlib

        form = parse_qs((body or b"").decode())
        self.posts.append(form)
        verifier = form["code_verifier"][0]
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if self.status != 200 or expected != self.challenge:
            return 400, b""
        now = int(datetime.now(UTC).timestamp())
        claims = {
            "iss": "https://accounts.google.com", "aud": self.client_id, "azp": self.client_id,
            "sub": "1076915035000615071511", "email": "reader@example.test", "email_verified": True,
            "iat": now, "exp": now + 3600, "nonce": self.nonce, "name": "Reader One",
        }
        claims.update(self.claims)
        claims = {key: value for key, value in claims.items() if value is not None}
        return 200, json.dumps({"access_token": "unused", "id_token": id_token(claims), "token_type": "Bearer"}).encode()


def web_settings(**overrides: str):
    values = {
        "NEWS_AUTH_ENABLED": "false",
        "NEWS_SERVER_HOST": "127.0.0.1",
        "NEWS_STATIC_DIR": str(FIXTURES / "frontend"),
    }
    values.update(overrides)
    return load_web_settings(values)


def auth_settings(**overrides: str):
    values = {
        "NEWS_AUTH_ENABLED": "true",
        "NEWS_GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
        "NEWS_GOOGLE_CLIENT_SECRET": "unit-test-client-secret",
        "NEWS_PUBLIC_URL": PUBLIC_URL,
        "NEWS_STATIC_DIR": str(FIXTURES / "frontend"),
    }
    values.update(overrides)
    return load_web_settings(values)
