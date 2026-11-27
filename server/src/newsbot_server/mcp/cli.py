"""`newsbot-mcp`: the read-only MCP program.

    newsbot-mcp                     streamable HTTP on NEWS_MCP_HOST:NEWS_MCP_PORT (default 127.0.0.1:8091), path /mcp
    newsbot-mcp --transport stdio   for a local agent that starts the program itself

It refuses to start if its MongoDB login (NEWS_MCP_MONGO_URI) can write. In
production it also refuses a login without authentication, because then MongoDB
cannot enforce read-only.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pymongo
from pymongo.errors import PyMongoError

from ..core import logs
from ..core.articles import ArticleStore
from ..core.mongo import connect, ping, write_privileges
from ..core.ranker import RankerClient, RecommendationService
from ..core.settings import McpSettings, SettingsError, environment, load_mcp_settings

log = logging.getLogger("newsbot.mcp")
MCP_OPERATION_TIMEOUT = 5.0


def check_read_only(client, settings: McpSettings) -> str | None:
    """A reason to refuse to start, or None."""
    with pymongo.timeout(10):
        authenticated, extra = write_privileges(client, settings.mongo.database)
    if extra:
        return f"the MCP database login can {', '.join(extra)}; give it a read-only user (deployment/mongo/mongo-users.js)"
    if not authenticated:
        if settings.environment == "production":
            return "the MCP database login is not authenticated, so MongoDB cannot enforce read-only"
        log.warning("mcp database login is not authenticated; read-only is not enforced by MongoDB here")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsbot-mcp", description="Read-only MCP server for the AFTERLINE archive.")
    parser.add_argument("--transport", choices=("http", "stdio"), default="http")
    args = parser.parse_args(argv)
    try:
        settings = load_mcp_settings(environment(), require_keys=args.transport == "http")
    except SettingsError as error:
        print(error, file=sys.stderr)
        return 2
    # On stdio, stdout carries the protocol, so logs go to stderr.
    logs.configure(settings.logging.level, settings.logging.format, stream=sys.stderr if args.transport == "stdio" else None)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    client = connect(settings.mongo)
    try:
        problem = check_read_only(client, settings)
    except PyMongoError as error:
        print(f"Cannot reach MongoDB with NEWS_MCP_MONGO_URI ({type(error).__name__}).", file=sys.stderr)
        return 1
    if problem:
        print(f"Refusing to start: {problem}.", file=sys.stderr)
        return 2

    from .auth import AgentKeys, RateLimiter
    from .server import build_server, http_app, readiness_checks
    from .tools import ReadOnlyTools

    articles = ArticleStore(client[settings.mongo.database]["articles"], timeout=MCP_OPERATION_TIMEOUT)
    recommendations = RecommendationService(RankerClient(settings.ranker.endpoint, settings.ranker.api_key), articles)
    server = build_server(
        ReadOnlyTools(articles, recommendations),
        ready=readiness_checks(lambda: ping(client), lambda: recommendations.metadata(timeout=2.0)),
    )
    if args.transport == "stdio":
        server.run("stdio")
        return 0

    import uvicorn

    app = http_app(server, AgentKeys(settings.agent_keys), RateLimiter(settings.rate_limit_per_minute), settings.allowed_hosts)
    log.info("mcp listening", extra={"fields": {"address": f"{settings.host}:{settings.port}", "path": "/mcp", "agents": len(settings.agent_keys)}})
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, access_log=False,
                server_header=False, timeout_graceful_shutdown=15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
