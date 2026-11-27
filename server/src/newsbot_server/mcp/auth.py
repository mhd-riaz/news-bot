"""Per-agent API keys and rate limits for the MCP HTTP transport (C11).

Keys are configured as `name:sha256(key)` pairs (NEWS_MCP_API_KEYS); the keys themselves
are never stored. A presented key is hashed and compared with every configured
digest in constant time. Revoke a key by removing its entry and restarting.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..core.settings import AgentKey

log = logging.getLogger("newsbot.mcp")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

AGENT_STATE_KEY = "mcp_agent"


class AgentKeys:
    def __init__(self, keys: Iterable[AgentKey]) -> None:
        self._keys = tuple(keys)

    def __len__(self) -> int:
        return len(self._keys)

    def verify(self, presented: str) -> str | None:
        """The agent name for a presented key, or None."""
        if not presented or len(presented) > 512:
            return None
        digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        match = None
        for key in self._keys:
            if hmac.compare_digest(digest, key.digest):
                match = key.name
        return match


class RateLimiter:
    """A token bucket per agent: `per_minute` requests, refilled continuously."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, agent: str) -> tuple[bool, int]:
        """(allowed, seconds until the next request would be allowed)."""
        now = self._clock()
        with self._lock:
            tokens, updated = self._buckets.get(agent, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - updated) * self.rate)
            if tokens >= 1.0:
                self._buckets[agent] = (tokens - 1.0, now)
                return True, 0
            self._buckets[agent] = (tokens, now)
            return False, max(1, math.ceil((1.0 - tokens) / self.rate))


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


async def _refuse(send: Send, status: int, code: str, message: str, headers: list[tuple[bytes, bytes]]) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store"), *headers],
    })
    await send({"type": "http.response.body", "body": body})


class AgentGate:
    """ASGI middleware: a valid Bearer key and a free rate-limit slot, or the request stops here."""

    def __init__(self, app: ASGIApp, keys: AgentKeys, limiter: RateLimiter, open_paths: Iterable[str] = ("/health/live", "/health/ready")) -> None:
        self.app = app
        self.keys = keys
        self.limiter = limiter
        self.open_paths = frozenset(open_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") in self.open_paths:
            await self.app(scope, receive, send)
            return
        authorization = _header(scope, b"authorization")
        scheme, _, presented = authorization.partition(" ")
        agent = self.keys.verify(presented.strip()) if scheme.lower() == "bearer" else None
        if agent is None:
            log.info("mcp request refused", extra={"fields": {"reason": "unauthorized", "path": scope.get("path", "")}})
            await _refuse(send, 401, "unauthorized", "A valid agent key is required: Authorization: Bearer <key>.",
                          [(b"www-authenticate", b'Bearer realm="newsbot-mcp"')])
            return
        allowed, retry_after = self.limiter.allow(agent)
        if not allowed:
            log.info("mcp request refused", extra={"fields": {"reason": "rate_limited", "agent": agent}})
            await _refuse(send, 429, "rate_limited", "Too many requests for this agent key. Slow down and retry.",
                          [(b"retry-after", str(retry_after).encode())])
            return
        scope.setdefault("state", {})[AGENT_STATE_KEY] = agent
        await self.app(scope, receive, send)
