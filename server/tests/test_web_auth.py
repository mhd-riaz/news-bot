"""Google sign-in, sessions, the API gate and CSRF checks (C10), with Google faked."""

from urllib.parse import parse_qs, urlsplit

import pytest

from helpers import PUBLIC_URL, FakeArticles, FakeGoogle, FakeRanker, FakeReaders, FakeSessions, auth_settings, recommendation_service, sample_article
from newsbot_server.core.readers import hash_token
from newsbot_server.web.app import Services, create_app
from newsbot_server.web.auth import (
    AUTHORIZATION_ENDPOINT,
    FLOW_COOKIE,
    SESSION_COOKIE,
    TOKEN_ENDPOINT,
    FlowCookie,
    GoogleOIDC,
    LoginFlow,
    SignInFailed,
    safe_next,
)

CLIENT_ID = "client-id.apps.googleusercontent.com"
READER_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def world():
    google = FakeGoogle(CLIENT_ID)
    readers, sessions = FakeReaders(), FakeSessions()
    readers.add(READER_ID, "reader@example.test")
    articles = FakeArticles(docs=[sample_article()])
    services = Services(
        articles=articles,
        recommendations=recommendation_service(FakeRanker(), articles),
        ping_database=lambda: None,
        readers=readers,
        sessions=sessions,
        oidc=GoogleOIDC(CLIENT_ID, "unit-test-client-secret", PUBLIC_URL + "/auth/callback", transport=google),
        flow_cookie=FlowCookie("unit-test-client-secret"),
    )
    app = create_app(auth_settings(), services)
    return app.test_client(), google, readers, sessions


def set_cookie_header(response, name):
    return next(value for value in response.headers.getlist("Set-Cookie") if value.startswith(name + "="))


def sign_in(client, google, next_path="/stories", **callback_args):
    login = client.get(f"/auth/login?next={next_path}")
    query = google.saw_authorization(login.headers["Location"])
    args = {"state": query["state"], "code": "4/test-code", **callback_args}
    return login, client.get("/auth/callback", query_string=args)


def test_login_redirects_to_google_with_pkce_state_and_nonce(world):
    client, google, *_ = world
    login = client.get("/auth/login?next=/stories")
    location = login.headers["Location"]
    query = google.saw_authorization(location)
    assert login.status_code == 302 and location.startswith(AUTHORIZATION_ENDPOINT + "?")
    assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID and query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == PUBLIC_URL + "/auth/callback" and query["scope"] == "openid email profile"
    assert len(query["state"]) >= 30 and len(query["nonce"]) >= 30 and len(query["code_challenge"]) == 43
    cookie = set_cookie_header(login, FLOW_COOKIE)
    for attribute in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=600"):
        assert attribute in cookie


def test_callback_signs_an_invited_reader_in_and_binds_their_google_account(world):
    client, google, readers, sessions = world
    _, done = sign_in(client, google)
    assert done.status_code == 302 and done.headers["Location"] == "/stories"
    cookie = set_cookie_header(done, SESSION_COOKIE)
    for attribute in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
        assert attribute in cookie
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert list(sessions.docs) == [hash_token(token)] and token not in str(sessions.docs)
    assert readers.docs[READER_ID]["google_sub"] == "1076915035000615071511" and readers.logins == [READER_ID]
    assert google.posts[0]["grant_type"] == ["authorization_code"] and google.posts[0]["redirect_uri"] == [PUBLIC_URL + "/auth/callback"]
    session = client.get("/api/v1/session").get_json()
    assert session == {"auth_enabled": True, "signed_in": True, "reader": {"email": "reader@example.test", "name": "Reader One"},
                       "login_url": "/auth/login"}
    assert client.get("/api/v1/articles").status_code == 200


def test_uninvited_email_is_refused(world):
    client, google, readers, sessions = world
    google.claims = {"email": "stranger@example.test", "sub": "999"}
    _, done = sign_in(client, google)
    assert done.headers["Location"] == "/?auth_error=not_invited" and not sessions.docs
    readers.docs[READER_ID]["invited"] = False
    google.claims = {}
    _, again = sign_in(client, google)
    assert again.headers["Location"] == "/?auth_error=not_invited"


@pytest.mark.parametrize("break_it", [
    "state", "nonce", "audience", "issuer", "unverified", "expired", "token_error", "google_error", "no_cookie",
    "forged_cookie", "other_account",
])
def test_any_other_failure_is_sign_in_failed(world, break_it):
    client, google, readers, sessions = world
    extra = {}
    if break_it == "state":
        extra = {"state": "guessed"}
    elif break_it == "nonce":
        google.claims = {"nonce": "replayed"}
    elif break_it == "audience":
        google.claims = {"aud": "someone-else.apps.googleusercontent.com", "azp": None}
    elif break_it == "issuer":
        google.claims = {"iss": "https://evil.example"}
    elif break_it == "unverified":
        google.claims = {"email_verified": False}
    elif break_it == "expired":
        google.claims = {"exp": 1_000_000}
    elif break_it == "token_error":
        google.status = 400
    elif break_it == "google_error":
        extra = {"error": "access_denied"}
    elif break_it == "other_account":
        readers.docs[READER_ID]["google_sub"] = "a-different-google-account"
    login = client.get("/auth/login?next=/stories")
    query = google.saw_authorization(login.headers["Location"])
    if break_it == "no_cookie":
        client.delete_cookie(FLOW_COOKIE)
    if break_it == "forged_cookie":
        forged = FlowCookie("not-the-secret").encode(LoginFlow.start("/stories"))
        client.set_cookie(FLOW_COOKIE, forged)
    done = client.get("/auth/callback", query_string={"state": query["state"], "code": "4/x", **extra})
    assert done.status_code == 302 and done.headers["Location"] == "/?auth_error=sign_in_failed"
    assert not sessions.docs and SESSION_COOKIE + "=" not in " ".join(done.headers.getlist("Set-Cookie"))


@pytest.mark.parametrize(("raw", "expected"), [
    ("/stories", "/stories"), ("/?view=fresh", "/?view=fresh"), (None, "/"), ("", "/"), ("//evil.example", "/"),
    ("https://evil.example/", "/"), ("/\\evil.example", "/"), ("javascript:alert(1)", "/"), ("/auth/login", "/"),
    ("/%0d%0aSet-Cookie:x", "/%0d%0aSet-Cookie:x"), ("/a\r\nb", "/"), ("stories", "/"),
])
def test_next_is_a_same_site_path_only(raw, expected):
    assert safe_next(raw) == expected


def test_open_redirect_through_login_is_impossible(world):
    client, google, *_ = world
    _, done = sign_in(client, google, next_path="//evil.example/steal")
    assert done.headers["Location"] == "/"


def test_api_needs_a_session_except_the_session_route(world, same_origin):
    client, *_ = world
    assert client.get("/api/v1/session").get_json()["signed_in"] is False
    for method, path in [("GET", "/api/v1/articles"), ("GET", "/api/v1/recommendations/meta"),
                         ("POST", "/api/v1/recommendations"), ("GET", "/api/v1/nothing-here")]:
        response = client.open(path, method=method, json={}, headers=same_origin)
        assert response.status_code == 401 and response.get_json()["error"]["code"] == "sign_in_required"
    assert client.get("/stories").status_code == 200 and client.get("/health/live").status_code == 200


def test_revoked_reader_loses_access_at_once(world):
    client, google, readers, sessions = world
    sign_in(client, google)
    readers.docs[READER_ID]["invited"] = False
    assert client.get("/api/v1/articles").status_code == 401
    assert not sessions.docs


def test_logout_deletes_the_server_session(world, same_origin):
    client, google, _, sessions = world
    sign_in(client, google)
    assert sessions.docs
    response = client.post("/auth/logout", headers=same_origin)
    assert response.status_code == 204 and not sessions.docs
    assert "Max-Age=0" in set_cookie_header(response, SESSION_COOKIE) or "expires=Thu, 01 Jan 1970" in set_cookie_header(response, SESSION_COOKIE)
    assert client.get("/api/v1/articles").status_code == 401


@pytest.mark.parametrize(("headers", "allowed"), [
    ({}, False),
    ({"Sec-Fetch-Site": "cross-site"}, False),
    ({"Sec-Fetch-Site": "same-site"}, False),
    ({"Sec-Fetch-Site": "same-origin"}, True),
    ({"Sec-Fetch-Site": "none"}, True),
    ({"Sec-Fetch-Site": "cross-site", "Origin": PUBLIC_URL}, False),
    ({"Origin": PUBLIC_URL}, True),
    ({"Origin": PUBLIC_URL.upper() + ":443"}, True),
    ({"Origin": "https://evil.example"}, False),
    ({"Origin": "null"}, False),
])
def test_state_changing_requests_must_be_same_origin(world, headers, allowed):
    client, *_ = world
    response = client.post("/auth/logout", headers=headers)
    if allowed:
        assert response.status_code == 204
    else:
        assert response.status_code == 403 and response.get_json()["error"]["code"] == "cross_site_request"


def test_reads_are_not_blocked_by_the_csrf_check(world):
    client, *_ = world
    assert client.get("/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_flow_cookie_expires_and_resists_tampering():
    cookie = FlowCookie("secret")
    flow = LoginFlow.start("/stories", now=1000)
    assert cookie.decode(cookie.encode(flow), now=1000) == flow
    with pytest.raises(SignInFailed):
        cookie.decode(cookie.encode(flow), now=1000 + 601)
    payload, signature = cookie.encode(flow).split(".")
    with pytest.raises(SignInFailed):
        cookie.decode(payload[:-2] + "AA." + signature, now=1000)


def test_token_exchange_sends_the_verifier_to_googles_token_endpoint():
    seen = {}

    def transport(method, url, headers, body, timeout):
        seen.update(method=method, url=url, form=parse_qs(body.decode()), timeout=timeout)
        return 400, b""

    oidc = GoogleOIDC(CLIENT_ID, "s", PUBLIC_URL + "/auth/callback", transport=transport)
    flow = LoginFlow.start("/")
    with pytest.raises(SignInFailed):
        oidc.exchange("code", flow)
    assert seen["method"] == "POST" and seen["url"] == TOKEN_ENDPOINT and seen["form"]["code_verifier"] == [flow.verifier]
    assert urlsplit(TOKEN_ENDPOINT).scheme == "https"
