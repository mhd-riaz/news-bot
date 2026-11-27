"""The MCP program: tools in memory, then the real HTTP transport with keys, limits and logging."""

import hashlib
import http.client
import json
import logging
import threading
import time

import anyio
import pytest
import uvicorn
from mcp import Client

from helpers import ONE_ID, TWO_ID, FakeArticles, FakeRanker, recommendation_service, sample_article
from newsbot_server.core.settings import AgentKey
from newsbot_server.mcp.auth import AgentKeys, RateLimiter
from newsbot_server.mcp.server import build_server, http_app
from newsbot_server.mcp.tools import MAX_RESULT_BYTES, ReadOnlyTools, ToolInputError

BODY = "SECRET-ARTICLE-BODY-TEXT that must never reach a log line"
KEY = "agent-key-" + "k" * 40


def make_tools(ranker=None, docs=None):
    articles = FakeArticles(docs=docs if docs is not None else [sample_article(content=BODY)])
    ranker = ranker or FakeRanker(body={"snapshot_id": "test", "items": [{"id": ONE_ID, "text": "Excerpt", "score": 0.5}]})
    return ReadOnlyTools(articles, recommendation_service(ranker, articles)), articles, ranker


def call(server, name, arguments=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(run)


def test_only_the_five_read_only_tools_are_offered():
    async def run():
        async with Client(build_server(make_tools()[0])) as client:
            return (await client.list_tools()).tools

    tools = anyio.run(run)
    assert sorted(tool.name for tool in tools) == ["get_article", "get_recommendations", "get_related", "list_topics", "search_articles"]
    for tool in tools:
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False


def test_get_article_returns_the_full_article():
    result = call(build_server(make_tools()[0]), "get_article", {"article_id": ONE_ID})
    assert not result.is_error and result.structured_content["content"] == BODY
    missing = call(build_server(make_tools()[0]), "get_article", {"article_id": TWO_ID})
    assert missing.is_error and "No article has this ID" in missing.content[0].text
    invalid = call(build_server(make_tools()[0]), "get_article", {"article_id": "$where"})
    assert invalid.is_error and "article_id must be a valid UUID" in invalid.content[0].text


def test_search_defaults_to_english_and_matches_a_phrase():
    tools, articles, _ = make_tools()
    result = call(build_server(tools), "search_articles", {"query": "  Bengaluru rain ", "limit": 5})
    flt = articles.last_filter
    assert not result.is_error and (flt.language, flt.text, flt.limit, flt.sort) == ("en", "Bengaluru rain", 5, "published_at")
    bad = call(build_server(tools), "search_articles", {"published_from": "yesterday", "cursor": "nope!"})
    assert bad.is_error and "published_from" in bad.content[0].text and "cursor" in bad.content[0].text
    too_many = call(build_server(tools), "search_articles", {"limit": 101})
    assert too_many.is_error


def test_related_and_recommendations_go_through_the_ranker():
    tools, articles, ranker = make_tools()
    related = call(build_server(tools), "get_related", {"article_id": TWO_ID, "limit": 3, "domains": ["ai"]})
    assert not related.is_error and related.structured_content["items"][0]["id"] == ONE_ID
    assert ranker.requests[-1][3] == {"seed_id": TWO_ID, "limit": 3, "domains": ["ai"]}
    recommended = call(build_server(tools), "get_recommendations", {"liked": [ONE_ID], "topic": "3", "window": "fresh"})
    assert not recommended.is_error and recommended.structured_content["snapshot_id"] == "test"
    assert ranker.requests[-1][3] == {"liked": [ONE_ID], "topic": "3", "limit": 10, "window": "fresh"}
    assert "content" not in recommended.structured_content["items"][0]


@pytest.mark.parametrize(("status", "message"), [(400, "Choose valid article IDs"), (404, "outside the current recommendation index"), (503, "unavailable")])
def test_ranker_failures_become_tool_errors(status, message):
    result = call(build_server(make_tools(ranker=FakeRanker(status=status))[0]), "get_related", {"article_id": ONE_ID})
    assert result.is_error and message in result.content[0].text


def test_list_topics_reads_ranker_metadata():
    result = call(build_server(make_tools()[0]), "list_topics")
    assert result.structured_content["topics"][0]["label"] == "science"


def test_huge_articles_are_truncated_to_the_result_limit():
    tools, *_ = make_tools(docs=[sample_article(content="word " * (MAX_RESULT_BYTES // 4))])
    article = tools.get_article(ONE_ID)
    assert article["content_truncated"] is True and len(json.dumps(article)) <= MAX_RESULT_BYTES
    with pytest.raises(ToolInputError):
        tools.get_related(ONE_ID, limit=0)


def test_access_log_names_agent_tool_time_and_size_but_never_article_text(caplog):
    caplog.set_level(logging.INFO, logger="newsbot.mcp")
    call(build_server(make_tools()[0]), "get_article", {"article_id": ONE_ID})
    records = [r for r in caplog.records if r.getMessage() == "mcp tool call"]
    assert len(records) == 1
    fields = records[0].fields
    assert fields["agent"] == "stdio" and fields["tool"] == "get_article" and fields["outcome"] == "ok" and fields["result_bytes"] > len(BODY)
    assert all(BODY not in (r.getMessage() + json.dumps(getattr(r, "fields", {}), default=str)) for r in caplog.records)


def test_keys_are_checked_by_hash_and_limits_refill():
    keys = AgentKeys([AgentKey("one", hashlib.sha256(b"first-key").hexdigest()), AgentKey("two", hashlib.sha256(b"second-key").hexdigest())])
    assert keys.verify("first-key") == "one" and keys.verify("second-key") == "two"
    assert keys.verify("") is None and keys.verify("first-key ") is None and keys.verify("x" * 600) is None
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.allow("a") == (True, 0) and limiter.allow("a") == (True, 0)
    allowed, retry = limiter.allow("a")
    assert not allowed and retry == 30 and limiter.allow("b")[0]
    now[0] = 30.0
    assert limiter.allow("a")[0]


@pytest.fixture(scope="module")
def mcp_http():
    tools, *_ = make_tools()
    digest = hashlib.sha256(KEY.encode()).hexdigest()
    app = http_app(build_server(tools), AgentKeys([AgentKey("tester", digest)]), RateLimiter(5), ("127.0.0.1:*",))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield server.servers[0].sockets[0].getsockname()[1]
    server.should_exit = True
    thread.join(5)


def post(port, body, key=KEY, **headers):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
    if key:
        sent["Authorization"] = f"Bearer {key}"
    sent.update(headers)
    connection.request("POST", "/mcp", body=body if isinstance(body, bytes) else json.dumps(body), headers=sent)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), data


def rpc(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def test_http_needs_a_valid_agent_key(mcp_http, caplog):
    caplog.set_level(logging.INFO, logger="newsbot.mcp")
    for key in (None, "wrong-key", KEY.upper()):
        status, headers, data = post(mcp_http, rpc("tools/list"), key=key)
        assert status == 401 and headers["www-authenticate"].startswith("Bearer") and b"unauthorized" in data
    status, _, data = post(mcp_http, rpc("tools/call", {"name": "get_article", "arguments": {"article_id": ONE_ID}}))
    result = json.loads(data)["result"]
    assert status == 200 and not result.get("isError") and result["structuredContent"]["title"] == "A story about Bengaluru"
    calls = [r.fields for r in caplog.records if r.getMessage() == "mcp tool call"]
    assert calls and calls[-1]["agent"] == "tester" and calls[-1]["tool"] == "get_article"


def test_http_refuses_other_hosts_browsers_and_big_bodies(mcp_http):
    assert post(mcp_http, rpc("tools/list"), Host="evil.example")[0] == 421
    assert post(mcp_http, rpc("tools/list"), Origin="https://evil.example")[0] == 403
    assert post(mcp_http, b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"pad":"' + b"x" * (130 << 10) + b'"}}')[0] == 413
    connection = http.client.HTTPConnection("127.0.0.1", mcp_http, timeout=10)
    connection.request("GET", "/health/live")
    assert connection.getresponse().status == 200


def test_http_rate_limit_is_per_key(mcp_http, caplog):
    caplog.set_level(logging.INFO, logger="newsbot.mcp")
    time.sleep(1.5)  # earlier tests in this module used part of the 5-per-minute budget
    statuses = [post(mcp_http, rpc("tools/list"))[0] for _ in range(8)]
    assert statuses.count(429) >= 3 and statuses[0] == 200
    status, headers, _ = post(mcp_http, rpc("tools/list"))
    assert status == 429 and int(headers["retry-after"]) >= 1
    assert any(getattr(r, "fields", {}).get("reason") == "rate_limited" and r.fields["agent"] == "tester" for r in caplog.records)
