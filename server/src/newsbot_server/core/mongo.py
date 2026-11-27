"""MongoDB connections, shared by the web app, the MCP program and the owner CLI."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pymongo
from pymongo import MongoClient

from .settings import MongoSettings

# Actions a read-only login may hold. Anything else (insert, update, remove, DDL,
# user or role administration) means the login can change data.
READ_ONLY_ACTIONS = frozenset({
    "find", "listCollections", "listIndexes", "collStats", "dbStats", "dbHash",
    "listSearchIndexes", "planCacheRead", "killCursors", "changeStream",
})


def connect(settings: MongoSettings) -> MongoClient[dict[str, Any]]:
    """A client with the same timeouts as the Go services. Connects lazily, so it is fork-safe."""
    return MongoClient(
        settings.uri,
        appname=settings.app_name,
        connectTimeoutMS=int(settings.connect_timeout * 1000),
        serverSelectionTimeoutMS=int(settings.server_selection_timeout * 1000),
        timeoutMS=int(settings.operation_timeout * 1000),
        maxPoolSize=settings.max_pool_size,
        minPoolSize=settings.min_pool_size,
        maxIdleTimeMS=int(settings.max_idle_time * 1000),
        tz_aware=True,
        tzinfo=UTC,
        connect=False,
    )


def ping(client: MongoClient[dict[str, Any]], timeout: float = 2.0) -> None:
    with pymongo.timeout(timeout):
        client.admin.command("ping")


def write_privileges(client: MongoClient[dict[str, Any]], database: str) -> tuple[bool, list[str]]:
    """(authenticated, actions beyond read-only) for the connected login."""
    status = client[database].command("connectionStatus", showPrivileges=True)
    info = status.get("authInfo", {})
    authenticated = bool(info.get("authenticatedUsers"))
    extra: set[str] = set()
    for privilege in info.get("authenticatedUserPrivileges", []):
        extra.update(action for action in privilege.get("actions", []) if action not in READ_ONLY_ACTIONS)
    return authenticated, sorted(extra)
