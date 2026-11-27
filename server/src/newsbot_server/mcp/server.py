"""The MCP program: read-only tools over the article database and the ranker (C11, D21).

It uses its own MongoDB login (NEWS_MCP_MONGO_URI), meant for a user that can only
read `articles`, so MongoDB itself refuses any write. `get_story_group` and
`get_rules` are not offered: story groups and association rules do not exist yet
(roadmap M5).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.ranker import RankerError
from .auth import AGENT_STATE_KEY, AgentGate, AgentKeys, RateLimiter
from .tools import MAX_RESULT_BYTES, ReadOnlyTools, ToolInputError, result_size

log = logging.getLogger("newsbot.mcp")

REQUEST_BODY_LIMIT = 128 << 10
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
INSTRUCTIONS = (
    "Read-only access to the AFTERLINE news archive. Search articles, read one article, "
    "find related reading, get stateless recommendations from liked or disliked article IDs "
    "or a topic, and list the recommendation topics. Nothing can be changed through these tools."
)


def agent_of(ctx: Context | None) -> str:
    request = getattr(getattr(ctx, "request_context", None), "request", None) if ctx is not None else None
    if request is None:
        return "stdio"
    state = request.scope.get("state") or {}
    return str(state.get(AGENT_STATE_KEY, "unknown"))


def audited(tool: str, ctx: Context | None, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a tool and write one access-log line: agent, tool, time and result size, never article text."""
    started = time.perf_counter()
    outcome, size, items = "ok", 0, None
    try:
        result = call()
        size = result_size(result)
        if size > MAX_RESULT_BYTES:
            outcome = "too_large"
            raise ToolError("The result is too large. Ask for fewer items.")
        if isinstance(result.get("items"), list):
            items = len(result["items"])
        return result
    except ToolInputError as error:
        outcome = "refused"
        raise ToolError(str(error)) from None
    except ToolError:
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        log.info("mcp tool call", extra={"fields": {
            "agent": agent_of(ctx), "tool": tool, "outcome": outcome,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2), "result_bytes": size, "items": items,
        }})


def build_server(tools: ReadOnlyTools, ready: Callable[[], dict[str, str]] | None = None) -> MCPServer:
    server = MCPServer(name="newsbot", title="AFTERLINE news (read-only)", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool(annotations=READ_ONLY)
    def search_articles(
        ctx: Context,
        query: Annotated[str, Field(description="Words to find in the title or summary, case-insensitive. Empty lists the newest articles.", max_length=200)] = "",
        source_id: Annotated[str, Field(description="Only this source (UUID).")] = "",
        language: Annotated[str, Field(description="Two-letter language declared by the source. Default en; empty means any.")] = "en",
        country: Annotated[str, Field(description="Two-letter country code, for example IN.")] = "",
        topic: Annotated[str, Field(description="Classifier topic name, for example politics.")] = "",
        published_from: Annotated[str, Field(description="Earliest publication time, RFC 3339, for example 2026-11-01T00:00:00Z.")] = "",
        published_to: Annotated[str, Field(description="Latest publication time, RFC 3339.")] = "",
        sort: Annotated[str, Field(description="published_at or collected_at, newest first.")] = "published_at",
        limit: Annotated[int, Field(description="Articles per page, 1-100.", ge=1, le=100)] = 20,
        cursor: Annotated[str, Field(description="next_cursor from the previous page.")] = "",
    ) -> dict[str, Any]:
        """Search the article archive, newest first. Returns titles, sources, links, dates and summaries (no full text)."""
        return audited("search_articles", ctx, lambda: tools.search_articles(
            query=query, source_id=source_id, language=language, country=country, topic=topic,
            published_from=published_from, published_to=published_to, sort=sort, limit=limit, cursor=cursor,
        ))

    @server.tool(annotations=READ_ONLY)
    def get_article(
        ctx: Context,
        article_id: Annotated[str, Field(description="Article ID (UUID) from a search or recommendation.")],
    ) -> dict[str, Any]:
        """Read one article in full: title, source, link, dates, summary and the stored text."""
        return audited("get_article", ctx, lambda: tools.get_article(article_id))

    @server.tool(annotations=READ_ONLY)
    def get_related(
        ctx: Context,
        article_id: Annotated[str, Field(description="The article to find related reading for (UUID).")],
        limit: Annotated[int, Field(description="How many stories, 1-30.", ge=1, le=30)] = 10,
        method: Annotated[str, Field(description="tfidf, svd or neural; empty uses the ranker's default.")] = "",
        domains: Annotated[list[str], Field(description="Only sources tagged with these professional domains, for example ai.", max_length=8)] = [],  # noqa: B006
    ) -> dict[str, Any]:
        """Related reading for one article, from both fresh and archived stories, best match first."""
        return audited("get_related", ctx, lambda: tools.get_related(article_id, limit=limit, method=method, domains=domains))

    @server.tool(annotations=READ_ONLY)
    def get_recommendations(
        ctx: Context,
        liked: Annotated[list[str], Field(description="Article IDs the reader liked (at most 50).", max_length=50)] = [],  # noqa: B006
        disliked: Annotated[list[str], Field(description="Article IDs the reader disliked (at most 50).", max_length=50)] = [],  # noqa: B006
        topic: Annotated[str, Field(description="A topic ID from list_topics.")] = "",
        window: Annotated[str, Field(description="fresh (last 30 days, verified dates), yesterday, archive, or empty for all.")] = "",
        method: Annotated[str, Field(description="tfidf, svd or neural; empty uses the ranker's default.")] = "",
        domains: Annotated[list[str], Field(description="Only sources tagged with these professional domains.", max_length=8)] = [],  # noqa: B006
        limit: Annotated[int, Field(description="How many stories, 1-30.", ge=1, le=30)] = 10,
    ) -> dict[str, Any]:
        """Stateless recommendations from the liked and disliked article IDs and/or a topic sent in this call."""
        return audited("get_recommendations", ctx, lambda: tools.get_recommendations(
            liked=liked, disliked=disliked, topic=topic, window=window, method=method, domains=domains, limit=limit,
        ))

    @server.tool(annotations=READ_ONLY)
    def list_topics(ctx: Context) -> dict[str, Any]:
        """The recommendation topics (content groups) with labels, keywords and sizes, plus the index snapshot."""
        return audited("list_topics", ctx, tools.list_topics)

    @server.custom_route("/health/live", methods=["GET"])
    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "alive", "version": "mcp"})

    @server.custom_route("/health/ready", methods=["GET"])
    async def readiness(_: Request) -> JSONResponse:
        checks = await run_in_threadpool(ready) if ready else {}
        ok = all(value == "ok" for value in checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "version": "mcp", "checks": checks}, status_code=200 if ok else 503)

    return server


def http_app(server: MCPServer, keys: AgentKeys, limiter: RateLimiter, allowed_hosts: tuple[str, ...]) -> AgentGate:
    """Streamable HTTP at /mcp: stateless JSON responses, 128 KiB requests, Host allowlist, then per-agent keys."""
    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=REQUEST_BODY_LIMIT,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=list(allowed_hosts), allowed_origins=[],
        ),
    )
    return AgentGate(app, keys, limiter)


def readiness_checks(ping_database: Callable[[], None], ranker_ready: Callable[[], Any]) -> Callable[[], dict[str, str]]:
    def check() -> dict[str, str]:
        checks = {"mongodb": "ok", "ranker": "ok"}
        try:
            ping_database()
        except Exception:  # detail stays out of the response
            checks["mongodb"] = "unavailable"
        try:
            ranker_ready()
        except RankerError:
            checks["ranker"] = "unavailable"
        return checks

    return check
