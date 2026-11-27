"""Ported from collector/internal/recommendation/recommendation_test.go, plus the real HTTP transport."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from helpers import ONE_ID, TWO_ID, FakeArticles, FakeRanker, recommendation_service, sample_article
from newsbot_server.core.ranker import (
    RankerClient,
    RankerInvalid,
    RankerNotIndexed,
    RankerUnavailable,
    RecommendationService,
    RecommendRequest,
    RequestDecodeError,
)


def test_hydrates_ranking_in_one_batch_and_preserves_order():
    articles = FakeArticles(docs=[sample_article(_id=TWO_ID), sample_article(_id=ONE_ID)])
    ranker = FakeRanker(body={"snapshot_id": "test", "method": "neural", "items": [{"id": ONE_ID, "score": 0.8}, {"id": TWO_ID, "score": 0.7}]})
    result = recommendation_service(ranker, articles).recommend(RecommendRequest(seed_id=TWO_ID, limit=2))
    assert articles.last_ids == [ONE_ID, TWO_ID] and articles.calls == 1
    assert [doc["_id"] for _, doc in result.items] == [ONE_ID, TWO_ID]
    assert "content" not in result.items[0][1] and "summary" not in result.items[0][1]


def test_unavailable_articles_are_explicit():
    articles = FakeArticles(docs=[sample_article(_id=ONE_ID)])
    service = recommendation_service(FakeRanker(body={"snapshot_id": "test", "items": [{"id": ONE_ID}, {"id": TWO_ID}]}), articles)
    assert service.recommend(RecommendRequest()).unavailable_ids == [TWO_ID]
    articles.docs = {}
    with pytest.raises(RankerUnavailable):
        service.recommend(RecommendRequest())


@pytest.mark.parametrize("request_", [
    RecommendRequest(limit=31), RecommendRequest(limit=-1), RecommendRequest(method="other"),
    RecommendRequest(topic="long"), RecommendRequest(seed_id="$where"), RecommendRequest(viewed=("invalid",)),
    RecommendRequest(liked=(ONE_ID,) * 51), RecommendRequest(disliked=(ONE_ID,) * 51),
    RecommendRequest(viewed=(ONE_ID,) * 2001), RecommendRequest(window="tomorrow"),
    RecommendRequest(domains=("AI",)), RecommendRequest(domains=tuple("abcdefghi")),
])
def test_request_validation(request_):
    with pytest.raises(RankerInvalid):
        request_.validate()


def test_valid_request_passes():
    RecommendRequest(liked=(ONE_ID,), viewed=(TWO_ID,), method="svd", limit=30).validate()


def test_window_and_domains_reach_the_ranker_and_date_flags_return():
    ranker = FakeRanker(body={"snapshot_id": "test", "window": "yesterday", "edition_date": "2026-08-09",
                              "items": [{"id": ONE_ID, "date_verified": True, "fresh": True}]})
    result = recommendation_service(ranker, FakeArticles(docs=[sample_article()])).recommend(
        RecommendRequest(window="yesterday", domains=("ai", "data-science")))
    sent = ranker.requests[-1][3]
    assert sent == {"window": "yesterday", "domains": ["ai", "data-science"]}
    hit = result.items[0][0]
    assert (result.page.window, result.page.edition_date, hit.date_verified, hit.fresh) == ("yesterday", "2026-08-09", True, True)


def test_empty_fields_are_omitted_like_go_omitempty_and_the_key_is_sent():
    ranker = FakeRanker()
    recommendation_service(ranker, FakeArticles(), key="unit-only-key").recommend(RecommendRequest())
    method, url, headers, payload = ranker.requests[-1]
    assert (method, url, payload) == ("POST", "http://ranker.test/v1/recommend", {})
    assert headers["X-Recommender-Key"] == "unit-only-key" and headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(("status", "body", "error"), [
    (400, {}, RankerInvalid),
    (404, {}, RankerNotIndexed),
    (503, {}, RankerUnavailable),
    (200, b"<html>", RankerUnavailable),
    (200, b"{} {}", RankerUnavailable),
    (200, {}, RankerUnavailable),
    (200, {"snapshot_id": "test", "items": [{"id": "bad"}]}, RankerUnavailable),
    (200, {"snapshot_id": "test", "items": [{"id": ONE_ID}, {"id": ONE_ID}]}, RankerUnavailable),
    (200, {"snapshot_id": "test", "items": [{"id": ONE_ID, "score": "high"}]}, RankerUnavailable),
    (200, b'{"snapshot_id": "test", "items": [{"id": "' + ONE_ID.encode() + b'", "score": 1e400}]}', RankerUnavailable),
    (200, {"snapshot_id": "test", "items": [{"id": ONE_ID, "text": "x" * 12001}]}, RankerUnavailable),
    (200, {"snapshot_id": "test", "items": [{"id": ONE_ID}] * 31}, RankerUnavailable),
])
def test_http_failures_and_malformed_rankings(status, body, error):
    with pytest.raises(error):
        recommendation_service(FakeRanker(status=status, body=body), FakeArticles()).recommend(RecommendRequest())


def test_database_failure_and_empty_feed():
    failing = recommendation_service(FakeRanker(body={"snapshot_id": "test", "items": [{"id": ONE_ID}]}), FakeArticles(error=RuntimeError("stub outage")))
    with pytest.raises(RankerUnavailable):
        failing.recommend(RecommendRequest())
    empty = recommendation_service(FakeRanker(body={"snapshot_id": "test", "items": [], "exhausted": True}), FakeArticles())
    result = empty.recommend(RecommendRequest())
    assert result.page.exhausted and result.items == []


def test_metadata_validation_and_transport_errors():
    service = recommendation_service(FakeRanker(), FakeArticles())
    assert service.metadata()["articles"] == 2
    with pytest.raises(RankerUnavailable):
        recommendation_service(FakeRanker(meta={}), FakeArticles()).metadata()

    def broken(*_args):
        raise TimeoutError("deadline")

    with pytest.raises(RankerUnavailable):
        RecommendationService(RankerClient("http://ranker.test", transport=broken), FakeArticles()).metadata()
    with pytest.raises(RankerInvalid):
        service.recommend(RecommendRequest(limit=100))


def test_metadata_is_reserialized_with_go_omitempty_rules():
    meta = recommendation_service(FakeRanker(meta={
        "snapshot_id": "s", "articles": 3, "topics": [{"id": "0", "label": "ai", "count": 2}],
        "windows": {"fresh": 1, "archive": 2}, "fresh_days": 0, "unknown": "dropped", "domains": {},
    }), FakeArticles()).metadata()
    assert list(meta) == ["snapshot_id", "articles", "publication_range", "collected_before", "methods", "topics",
                          "profile_note", "date_note", "windows"]
    assert meta["topics"] == [{"id": "0", "label": "ai", "keywords": None, "count": 2, "representatives": None}]
    assert list(meta["windows"]) == ["archive", "fresh"]


@pytest.mark.parametrize("endpoint", [
    "", "/relative", "file:///tmp/model", "http://u:p@ranker.test", "http://ranker.test?key=x",
    "http://ranker.test#fragment", "http://[",
])
def test_endpoint_validation(endpoint):
    with pytest.raises(ValueError):
        RankerClient(endpoint)


def test_missing_article_source_is_refused():
    with pytest.raises(ValueError):
        RecommendationService(RankerClient("http://ranker.test"), None)


@pytest.mark.parametrize(("body", "content_type", "status"), [
    (b"{", "application/json", 400),
    (b'{"where":{}}', "application/json", 400),
    (b"{} {}", "application/json", 400),
    (b"{}", "text/plain", 415),
    (b"x" * (130 << 10), "application/json", 400),
    (b"", "application/json", 400),
    (b"[]", None, 400),
    (b'{"limit": 1.5}', None, 400),
    (b'{"limit": true}', None, 400),
    (b'{"liked": "abc"}', None, 400),
])
def test_body_decoding_follows_go(body, content_type, status):
    with pytest.raises(RequestDecodeError) as error:
        RecommendRequest.from_body(body, content_type)
    assert error.value.status == status


def test_body_decoding_accepts_nulls_and_charset():
    request = RecommendRequest.from_body(b'{"liked": null, "seed_id": null, "limit": 3}', "application/json; charset=utf-8")
    assert request == RecommendRequest(limit=3)
    assert RecommendRequest.from_body(b"null", None) == RecommendRequest()


class _Ranker(BaseHTTPRequestHandler):
    """A tiny real HTTP ranker for the transport tests."""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/v1/meta":
            body = json.dumps({"snapshot_id": "http", "articles": 1, "topics": [{"id": "0"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect/v1/meta":
            self.send_response(302)
            self.send_header("Location", "/v1/meta")
            self.end_headers()
        elif self.path == "/huge/v1/meta":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"snapshot_id": "' + b"x" * (1 << 20) + b'"}')
        elif self.path == "/slow/v1/meta":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            time.sleep(1.5)
        else:
            self.send_response(503)
            self.end_headers()


@pytest.fixture(scope="module")
def ranker_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ranker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_real_transport_reads_metadata(ranker_url):
    assert RankerClient(ranker_url).metadata()["snapshot_id"] == "http"


@pytest.mark.parametrize("prefix", ["/redirect", "/huge", "/missing"])
def test_real_transport_refuses_redirects_oversized_bodies_and_errors(ranker_url, prefix):
    with pytest.raises(RankerUnavailable):
        RankerClient(ranker_url + prefix).metadata()


def test_real_transport_enforces_a_total_deadline(ranker_url):
    started = time.monotonic()
    with pytest.raises(RankerUnavailable):
        RankerClient(ranker_url + "/slow", timeout=0.5).metadata()
    assert time.monotonic() - started < 1.4


def test_unreachable_ranker_is_unavailable():
    with pytest.raises(RankerUnavailable):
        RankerClient("http://127.0.0.1:9", timeout=1).metadata()
