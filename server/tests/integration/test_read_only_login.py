"""The MCP program's database login is read-only, enforced by MongoDB itself (D21).

The first test runs against the local, unauthenticated test server. The others need
a MongoDB with users made by deployment/mongo/mongo-users.js:
    NEWS_TEST_MCP_MONGO_URI     the `mcp` login (must only read `articles`)
    NEWS_TEST_WRITER_MONGO_URI  any login that can write (for example `reader`)
They are skipped when those variables are not set.
"""

from __future__ import annotations

import os
from datetime import UTC

import pytest
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from newsbot_server.core.settings import load_mcp_settings
from newsbot_server.mcp.cli import check_read_only

pytestmark = pytest.mark.integration
UNAUTHORIZED = 13


def mcp_settings(uri: str, environment: str):
    return load_mcp_settings({"NEWS_MCP_MONGO_URI": uri, "NEWS_APP_ENVIRONMENT": environment,
                              "NEWS_MONGO_DATABASE": os.environ.get("NEWS_TEST_MONGO_DATABASE", "news")}, require_keys=False)


def test_an_unauthenticated_login_is_refused_in_production_only(database):
    client = database.client
    uri = os.environ.get("NEWS_TEST_MONGO_URI", "mongodb://localhost:27017")
    authenticated = bool(client.admin.command("connectionStatus")["authInfo"]["authenticatedUsers"])
    if authenticated:
        pytest.skip("the test server uses authentication")
    assert check_read_only(client, mcp_settings(uri, "development")) is None
    assert "not authenticated" in check_read_only(client, mcp_settings(uri, "production"))


@pytest.fixture
def mcp_login():
    uri = os.environ.get("NEWS_TEST_MCP_MONGO_URI")
    if not uri:
        pytest.skip("NEWS_TEST_MCP_MONGO_URI is not set")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True, tzinfo=UTC)
    yield client, uri
    client.close()


def test_the_mcp_login_reads_only_articles_and_every_write_is_refused(mcp_login):
    client, uri = mcp_login
    articles = client[os.environ.get("NEWS_TEST_MONGO_DATABASE", "news")]["articles"]
    assert articles.find_one({}, {"title": 1}) is not None
    writes = [
        lambda: articles.insert_one({"_id": "mcp-write-probe", "title": "should never exist"}),
        lambda: articles.update_one({}, {"$set": {"title": "changed by mcp"}}),
        lambda: articles.delete_one({}),
        lambda: articles.database["readers"].find_one(),
        lambda: articles.database["reader_sessions"].insert_one({"_id": "probe"}),
        lambda: articles.create_index("title"),
    ]
    for write in writes:
        with pytest.raises(OperationFailure) as refused:
            write()
        assert refused.value.code == UNAUTHORIZED
    assert check_read_only(client, mcp_settings(uri, "production")) is None


def test_a_login_that_can_write_is_refused_at_startup():
    uri = os.environ.get("NEWS_TEST_WRITER_MONGO_URI")
    if not uri:
        pytest.skip("NEWS_TEST_WRITER_MONGO_URI is not set")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        reason = check_read_only(client, mcp_settings(uri, "development"))
    finally:
        client.close()
    assert reason and "insert" in reason and "read-only user" in reason
