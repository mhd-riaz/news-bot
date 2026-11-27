"""Serving the React build: index.html for app routes, hashed assets, strict CSP."""

from helpers import FIXTURES, FakeArticles, FakeRanker, recommendation_service, web_settings
from newsbot_server.web.app import Services, create_app
from newsbot_server.web.security import PAGE_POLICY


def client(static_dir=FIXTURES / "frontend"):
    articles = FakeArticles()
    services = Services(articles=articles, recommendations=recommendation_service(FakeRanker(), articles), ping_database=lambda: None)
    return create_app(web_settings(NEWS_STATIC_DIR=str(static_dir)), services).test_client()


def test_app_routes_serve_index_with_a_strict_policy():
    web = client()
    for path in ("/", "/stories"):
        response = web.get(path)
        assert response.status_code == 200 and b'<div id="root">' in response.data
        assert response.mimetype == "text/html" and response.headers["Cache-Control"] == "no-cache"
        assert response.headers["Content-Security-Policy"] == PAGE_POLICY
    assert "script-src 'self';" in PAGE_POLICY and "unsafe-inline" not in PAGE_POLICY and "img-src 'self' https: data:" in PAGE_POLICY


def test_hashed_assets_are_cached_for_a_year():
    web = client()
    script = web.get("/assets/app-abc123.js")
    assert script.status_code == 200 and script.mimetype == "text/javascript"
    assert script.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert web.get("/assets/app-abc123.css").mimetype == "text/css"
    assert web.get("/favicon.svg").status_code == 200


def test_paths_outside_the_build_are_not_served():
    web = client()
    for path in ("/assets/../index.html", "/assets/missing.js", "/assets/%2e%2e/%2e%2e/pyproject.toml", "/.hidden", "/index.html"):
        response = web.get(path)
        assert response.status_code == 404, path


def test_a_missing_build_is_reported_not_crashed():
    response = client(FIXTURES / "no-build-here").get("/")
    assert response.status_code == 503 and response.get_json()["error"]["code"] == "unavailable"
