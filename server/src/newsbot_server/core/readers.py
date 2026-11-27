"""Invited readers and their server-side sessions (C8, C10).

`readers`: _id (the reader ID), email (lower case, unique), name, invited,
created_at, google_sub (bound on first sign-in), last_login_at.
`reader_sessions`: _id (SHA-256 of the session token; the token itself is never
stored), reader_id, created_at, last_seen_at, expires_at (TTL index).
Both collections and their indexes are declared in collector/internal/mongodb.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

READERS = "readers"
READER_SESSIONS = "reader_sessions"
TOUCH_INTERVAL = timedelta(seconds=60)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def utcnow() -> datetime:
    # BSON dates carry milliseconds; truncating keeps stored and in-memory values equal.
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        raise ValueError("not an email address")
    return value


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Reader:
    id: str
    email: str
    name: str
    invited: bool
    google_bound: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> Reader:
        return cls(
            id=str(doc["_id"]),
            email=str(doc.get("email", "")),
            name=doc.get("name") if isinstance(doc.get("name"), str) else "",
            invited=doc.get("invited") is True,
            google_bound=isinstance(doc.get("google_sub"), str) and bool(doc.get("google_sub")),
            created_at=doc.get("created_at"),
            last_login_at=doc.get("last_login_at"),
        )


class ReaderStore:
    def __init__(self, database: Any) -> None:
        self._readers = database[READERS]

    def get(self, reader_id: str) -> Reader | None:
        doc = self._readers.find_one({"_id": reader_id})
        return Reader.from_doc(doc) if doc else None

    def by_google_sub(self, sub: str) -> Reader | None:
        doc = self._readers.find_one({"google_sub": sub})
        return Reader.from_doc(doc) if doc else None

    def by_email(self, email: str) -> Reader | None:
        doc = self._readers.find_one({"email": email})
        return Reader.from_doc(doc) if doc else None

    def google_sub_of(self, reader_id: str) -> str | None:
        doc = self._readers.find_one({"_id": reader_id}, {"google_sub": 1})
        sub = doc.get("google_sub") if doc else None
        return sub if isinstance(sub, str) and sub else None

    def bind_google_sub(self, reader_id: str, sub: str) -> bool:
        """First sign-in binds the Google account. Never rebinds an account already bound."""
        result = self._readers.update_one(
            {"_id": reader_id, "invited": True, "google_sub": {"$exists": False}},
            {"$set": {"google_sub": sub}},
        )
        return result.modified_count == 1

    def record_login(self, reader_id: str, now: datetime, name: str = "") -> None:
        self._readers.update_one({"_id": reader_id}, {"$set": {"last_login_at": now}})
        if name:
            self._readers.update_one({"_id": reader_id, "name": {"$in": ["", None]}}, {"$set": {"name": name[:200]}})

    def invite(self, email: str, name: str = "", now: datetime | None = None) -> tuple[Reader, bool]:
        """Insert or re-enable an invited email. Returns (reader, created)."""
        now = now or utcnow()
        update: dict[str, Any] = {
            "$set": {"invited": True},
            "$setOnInsert": {"_id": str(uuid.uuid4()), "email": email, "created_at": now},
        }
        if name:
            update["$set"]["name"] = name[:200]
        else:
            update["$setOnInsert"]["name"] = ""
        result = self._readers.update_one({"email": email}, update, upsert=True)
        reader = self.by_email(email)
        assert reader is not None
        return reader, result.upserted_id is not None

    def revoke(self, email: str) -> Reader | None:
        result = self._readers.update_one({"email": email}, {"$set": {"invited": False}})
        return self.by_email(email) if result.matched_count else None

    def all(self) -> list[Reader]:
        return [Reader.from_doc(doc) for doc in self._readers.find({}, {"google_sub": 1, "email": 1, "name": 1, "invited": 1, "created_at": 1, "last_login_at": 1}).sort("email", 1)]


@dataclass(frozen=True)
class Session:
    token_hash: str
    reader_id: str
    created_at: datetime
    expires_at: datetime


class SessionStore:
    """Server-side sessions with idle and absolute timeouts; only token hashes are stored."""

    def __init__(self, database: Any, idle: timedelta, absolute: timedelta, clock: Callable[[], datetime] = utcnow) -> None:
        self._sessions = database[READER_SESSIONS]
        self.idle = idle
        self.absolute = absolute
        self._clock = clock

    def create(self, reader_id: str) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        session = Session(hash_token(token), reader_id, now, min(now + self.idle, now + self.absolute))
        self._sessions.insert_one({
            "_id": session.token_hash, "reader_id": reader_id,
            "created_at": now, "last_seen_at": now, "expires_at": session.expires_at,
        })
        return token, session

    def lookup(self, token: str) -> Session | None:
        """A live session for the token, sliding its idle expiry at most once a minute."""
        if not token or len(token) > 256:
            return None
        now = self._clock()
        token_hash = hash_token(token)
        doc = self._sessions.find_one({"_id": token_hash, "expires_at": {"$gt": now}})
        if not doc or not isinstance(doc.get("reader_id"), str):
            return None
        created = doc["created_at"]
        expires = min(now + self.idle, created + self.absolute)
        if now - doc.get("last_seen_at", created) >= TOUCH_INTERVAL:
            self._sessions.update_one(
                {"_id": token_hash, "expires_at": {"$gt": now}},
                {"$set": {"last_seen_at": now, "expires_at": expires}},
            )
        else:
            expires = doc["expires_at"]
        return Session(token_hash, doc["reader_id"], created, expires)

    def delete(self, token: str) -> None:
        if token and len(token) <= 256:
            self._sessions.delete_one({"_id": hash_token(token)})

    def delete_for_reader(self, reader_id: str) -> int:
        return self._sessions.delete_many({"reader_id": reader_id}).deleted_count

    def count_for_reader(self, reader_id: str) -> int:
        return self._sessions.count_documents({"reader_id": reader_id, "expires_at": {"$gt": self._clock()}})
