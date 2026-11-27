"""Ported from collector/cmd/reader/main_test.go and the handler tests for recommendations and articles."""

import json

import pytest
from pymongo.errors import ExecutionTimeout, ServerSelectionTimeoutError

from helpers import ONE_ID, FakeArticles, FakeRanker, recommendation_service, sample_article, web_settings
from newsbot_server.core.articles import ArticleCursor, ArticlePage
from newsbot_server.core.validation import ValidationFailed
from newsbot_server.web.app import Services, create_app


def client_for(ranker=None, articles=None, ping_error=None):
    articles = articles if articles is not None else FakeArticles(docs=[sample_article()])
    ranker = ranker or FakeRanker()

    def ping():
        if ping_error:
            raise ping_error

    services = Services(articles=articles, recommendations=recommendation_service(ranker, articles), ping_database=ping)
    return create_app(web_settings(), services).test_client()


def test_reader_exposes_reads_but_no_mutation_endpoints(same_origin):
    client = client_for()
    for path, status in {
        "/health/live": 200, "/health/ready": 200, "/api/v1/recommendations/meta": 200, "/stories": 200,
        "/api/v1/articles": 200, f"/api/v1/articles/{ONE_ID}": 200, "/": 200, "/api/v1/session": 200,
    }.items():
        assert client.get(path).status_code == status, path
    for method, path in [("DELETE", "/api/v1/articles"), ("POST", "/api/v1/sources"), ("PATCH", f"/api/v1/sources/{ONE_ID}"),
                         ("POST", "/read-events"), ("POST", "/api/v1/articles"), ("PATCH", "/api/v1/articles")]:
        response = client.open(path, method=method, data=b"{}", headers=same_origin)
        assert response.status_code in (404, 405), (method, path)
        assert "error" in response.get_json()


def test_old_go_pages_are_gone():
    client = client_for()
    assert client.get("/archive").status_code == 404
    assert client.get(f"/articles/{ONE_ID}").status_code == 404


@pytest.mark.parametrize(("ping_error", "ranker_status", "failed"), [
    (ServerSelectionTimeoutError("stub outage"), 200, "mongodb"),
    (None, 503, "ranker"),
])
def test_readiness_reports_dependency_outages(ping_error, ranker_status, failed):
    response = client_for(ranker=FakeRanker(status=ranker_status), ping_error=ping_error).get("/health/ready")
    body = response.get_json()
    assert response.status_code == 503 and body["status"] == "not_ready" and body["checks"][failed] == "unavailable"


def test_recommendations_serialize_original_metadata_and_clean_text(same_origin):
    when = "2026-08-01T00:00:00Z"
    from datetime import UTC, datetime

    moment = datetime(2026, 8, 1, tzinfo=UTC)
    articles = FakeArticles(docs=[sample_article(title="<script>not HTML</script>", source_name="Test source",
                                                 url="https://example.test/story", published_at=moment, collected_at=moment)])
    ranker = FakeRanker(body={"snapshot_id": "test", "method": "neural", "window": "yesterday", "edition_date": "2026-08-09",
                              "items": [{"id": ONE_ID, "text": "An excerpt.", "text_kind": "Excerpt", "input_kind": "body",
                                         "topic": "0", "score": 0.8, "reason": "Related to this article",
                                         "date_verified": True, "fresh": True, "published_at": "ignored"}]})
    response = client_for(ranker, articles).post("/api/v1/recommendations", json={"limit": 1, "window": "yesterday", "domains": ["ai"]}, headers=same_origin)
    body = response.get_json()
    item = body["items"][0]
    assert response.status_code == 200 and item["date_kind"] == "Collected" and item["title"] == "<script>not HTML</script>"
    assert item["text"] == "An excerpt." and item["group"] == "0" and item["published_at"] == when
    assert body["window"] == "yesterday" and body["edition_date"] == "2026-08-09" and item["date_verified"] and item["fresh"]
    assert body["unavailable_ids"] == [] and body["snapshot_id"] == "test" and "summary" not in item
    assert b"<script>" not in response.data and response.headers["Cache-Control"] == "no-store"
    assert ranker.requests[-1][3] == {"limit": 1, "window": "yesterday", "domains": ["ai"]}


def test_recommendation_metadata_and_downstream_failures():
    response = client_for().get("/api/v1/recommendations/meta")
    assert response.status_code == 200 and response.get_json()["snapshot_id"] == "test"
    assert response.headers["Cache-Control"] == "no-store"
    for status in (400, 404, 503):
        failed = client_for(ranker=FakeRanker(status=status)).get("/api/v1/recommendations/meta")
        assert failed.status_code == status and "error" in failed.get_json()


@pytest.mark.parametrize(("body", "content_type", "status"), [
    (b"{", "application/json", 400),
    (b'{"where":{}}', "application/json", 400),
    (b"{} {}", "application/json", 400),
    (b"{}", "text/plain", 415),
    (b"x" * (130 << 10), "application/json", 400),
    (b'{"seed_id":"$where"}', "application/json", 400),
    (b'{"method":"invalid"}', "application/json", 400),
])
def test_recommendation_payload_validation(same_origin, body, content_type, status):
    response = client_for().post("/api/v1/recommendations", data=body, headers={**same_origin, "Content-Type": content_type})
    assert response.status_code == status
    assert response.get_json()["error"]["code"] == "invalid_input"


def test_large_valid_history_is_accepted(same_origin):
    payload = json.dumps({"viewed": [ONE_ID] * 2000}).encode()
    response = client_for().post("/api/v1/recommendations", data=payload, headers={**same_origin, "Content-Type": "application/json"})
    assert len(payload) > 64 << 10 and response.status_code == 200


def test_recommendation_failure_does_not_leak_internal_details(same_origin):
    articles = FakeArticles(error=RuntimeError("private database detail"))
    ranker = FakeRanker(body={"snapshot_id": "test", "items": [{"id": ONE_ID}]})
    response = client_for(ranker, articles).post("/api/v1/recommendations", json={}, headers=same_origin)
    assert response.status_code == 503 and b"private database" not in response.data
    assert response.get_json()["error"]["code"] == "unavailable"


def test_list_articles_returns_the_page_without_content():
    listed = sample_article()
    del listed["content"]
    articles = FakeArticles(page=ArticlePage(items=[listed], limit=50, has_more=True, next_cursor="MTc2Njk5MDgwMDAwMC4wMTk4ZjNkMi0zMzMzLTcwMDAtODAwMC0wMDAwMDAwMDAwMDE"))
    response = client_for(articles=articles).get("/api/v1/articles")
    body = response.get_json()
    assert response.status_code == 200 and len(body["items"]) == 1 and body["has_more"] and body["next_cursor"]
    assert body["items"][0]["title"] == "A story about Bengaluru" and body["items"][0]["city"] == "Bengaluru"
    assert b'"content"' not in response.data


def test_article_response_hides_internal_keys_and_includes_content():
    response = client_for().get(f"/api/v1/articles/{ONE_ID}")
    for leaked in (b"dedup_id", b"normalized_url", b"content_hash", b"processing_status", b"feed_guid"):
        assert leaked not in response.data
    assert response.get_json()["content"] == "The full text of the article."


def test_list_articles_passes_the_filter_through():
    articles = FakeArticles()
    response = client_for(articles=articles).get(
        "/api/v1/articles?source_id=0198f3d2-1111-7000-8000-000000000001&language=en&country=IN&state=Karnataka"
        "&city=Bengaluru&topic=Politics&published_from=2026-08-01T00:00:00Z&published_to=2026-08-22T00:00:00Z"
        "&sort=collected_at&limit=25")
    got = articles.last_filter
    assert response.status_code == 200
    assert (got.language, got.country, got.state, got.city, got.topic) == ("en", "IN", "Karnataka", "Bengaluru", "politics")
    assert (got.sort, got.limit) == ("collected_at", 25) and got.published_from and got.published_to


def test_list_articles_forwards_a_cursor_and_rejects_tampered_ones():
    from datetime import UTC, datetime

    articles = FakeArticles()
    cursor = ArticleCursor(datetime(2026, 8, 22, 9, tzinfo=UTC), ONE_ID)
    assert client_for(articles=articles).get(f"/api/v1/articles?cursor={cursor.encode()}").status_code == 200
    assert articles.last_filter.cursor == cursor
    for token in ("not-base64!!", "YWJjZGVm", "MTIzNDU2Nzg5MC57JG5lOjF9"):
        untouched = FakeArticles()
        response = client_for(articles=untouched).get(f"/api/v1/articles?cursor={token}")
        assert response.status_code == 400 and untouched.calls == 0


def test_list_articles_reports_every_bad_parameter_at_once():
    articles = FakeArticles()
    response = client_for(articles=articles).get("/api/v1/articles?limit=lots&published_from=yesterday&published_to=tomorrow")
    body = response.get_json()
    assert response.status_code == 400 and len(body["error"]["fields"]) == 3 and articles.calls == 0
    assert body["error"] == {"code": "invalid_input", "message": "the request payload is invalid", "fields": body["error"]["fields"]}


@pytest.mark.parametrize(("error", "status"), [
    (None, 404),
    (ValidationFailed([]), 400),
    (ExecutionTimeout("deadline"), 503),
    (ServerSelectionTimeoutError("no reachable servers at cluster0.internal:27017"), 503),
    (RuntimeError("server selection error: no reachable servers at cluster0.internal:27017"), 500),
])
def test_get_article_maps_failures(error, status):
    articles = FakeArticles(error=error)
    target = "0198f3d2-3333-7000-8000-000000000009" if error is None else ONE_ID
    if isinstance(error, ValidationFailed):
        articles.error, target = None, "not-a-uuid"
    response = client_for(articles=articles).get(f"/api/v1/articles/{target}")
    assert response.status_code == status and b"cluster0.internal" not in response.data
    assert "error" in response.get_json()


def test_read_events_stays_disabled(same_origin):
    response = client_for().post("/read-events", json={"events": []}, headers=same_origin)
    assert response.status_code == 405 and response.get_json()["error"]["message"] == "telemetry is disabled in the read-only reader"


def test_session_with_sign_in_off_is_the_local_reader():
    body = client_for().get("/api/v1/session").get_json()
    assert body == {"auth_enabled": False, "signed_in": True, "reader": {"email": "local@localhost", "name": "Local reader"},
                    "login_url": "/auth/google/login"}


def test_every_response_carries_request_id_and_security_headers():
    response = client_for().get("/api/v1/articles")
    assert len(response.headers["X-Request-Id"]) == 26
    assert response.headers["X-Content-Type-Options"] == "nosniff" and response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"] and response.headers["X-Frame-Options"] == "DENY"
