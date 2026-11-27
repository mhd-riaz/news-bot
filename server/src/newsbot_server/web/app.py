"""The AFTERLINE web app: reader API, Google sign-in, sessions, CSRF checks and the React build.

Ported from the Go reader (collector/cmd/reader) route for route. MongoDB access
is read-only for articles; the only writes are to `readers` (sign-in binding and
last login) and `reader_sessions`.
"""

from __future__ import annotations

import base64
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from flask import Flask, Response, g, redirect, request
from pymongo.errors import PyMongoError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from ..core import jsonutil
from ..core.articles import (
    ArticleNotFound,
    ArticleReader,
    ArticleStore,
    article_response,
    date_kind,
    filter_from_query,
    get_article,
    list_articles,
)
from ..core.mongo import connect, ping
from ..core.ranker import (
    REQUEST_BODY_LIMIT,
    RankerClient,
    RankerError,
    RankerInvalid,
    RankerNotIndexed,
    RecommendationService,
    RecommendRequest,
    RequestDecodeError,
)
from ..core.readers import Reader, ReaderStore, SessionStore
from ..core.settings import WebSettings
from ..core.validation import ValidationFailed
from .auth import (
    CALLBACK_PATH,
    FLOW_COOKIE,
    FLOW_SECONDS,
    LOGIN_PATH,
    SESSION_COOKIE,
    FlowCookie,
    GoogleOIDC,
    LoginFlow,
    NotInvited,
    SignInFailed,
    admit,
    safe_next,
)
from .security import apply_headers, is_cross_site
from .static import Frontend

log = logging.getLogger("newsbot.web")

LOCAL_READER = {"email": "local@localhost", "name": "Local reader"}
HEALTH_VERSION = "stories"


@dataclass
class Services:
    """Everything the routes talk to; tests pass fakes."""

    articles: ArticleReader
    recommendations: RecommendationService
    ping_database: Callable[[], None]
    readers: ReaderStore | None = None
    sessions: SessionStore | None = None
    oidc: GoogleOIDC | None = None
    flow_cookie: FlowCookie | None = None


def build_services(settings: WebSettings) -> Services:
    client = connect(settings.mongo)
    database = client[settings.mongo.database]
    articles = ArticleStore(database["articles"])
    recommendations = RecommendationService(RankerClient(settings.ranker.endpoint, settings.ranker.api_key), articles)
    services = Services(articles=articles, recommendations=recommendations, ping_database=lambda: ping(client))
    if settings.auth_enabled:
        services.readers = ReaderStore(database)
        services.sessions = SessionStore(
            database,
            idle=timedelta(seconds=settings.session_idle_timeout),
            absolute=timedelta(seconds=settings.session_absolute_timeout),
        )
        services.oidc = GoogleOIDC(settings.google_client_id, settings.google_client_secret, settings.public_url + CALLBACK_PATH)
        services.flow_cookie = FlowCookie(settings.google_client_secret)
    return services


def json_response(status: int, payload: Any, *, no_store: bool = True) -> Response:
    response = Response(jsonutil.dumps(payload), status=status, mimetype="application/json")
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    if no_store:
        response.headers["Cache-Control"] = "no-store"
    return response


def error_response(status: int, code: str, message: str, fields: list[dict[str, str]] | None = None) -> Response:
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return json_response(status, {"error": detail})


def validation_error(error: ValidationFailed) -> Response:
    return error_response(400, "invalid_input", "the request payload is invalid", [item.as_dict() for item in error.fields])


def _request_id() -> str:
    return base64.b32encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def create_app(settings: WebSettings, services: Services | None = None) -> Flask:
    services = services or build_services(settings)
    if settings.auth_enabled and not (services.readers and services.sessions and services.oidc and services.flow_cookie):
        raise ValueError("sign-in is on but the reader, session or Google services are missing")
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = REQUEST_BODY_LIMIT
    frontend = Frontend(settings.static_dir)

    def current_reader() -> Reader | None:
        """The signed-in reader for this request, from the session cookie; cached per request."""
        if "reader" in g:
            return g.reader
        reader = None
        token = request.cookies.get(SESSION_COOKIE, "")
        if token and services.sessions and services.readers:
            session = services.sessions.lookup(token)
            if session is not None:
                reader = services.readers.get(session.reader_id)
                if reader is None or not reader.invited:
                    services.sessions.delete(token)
                    reader = None
        g.reader = reader
        return reader

    def ranker_failure(error: RankerError) -> Response:
        if isinstance(error, RankerInvalid):
            log.info("invalid recommendation request", extra={"fields": {"request_id": g.request_id}})
            return error_response(400, "invalid_input", "Choose valid interests, a known method and at most 30 results.")
        if isinstance(error, RankerNotIndexed):
            return error_response(404, "not_found", "An interest or article is outside this indexed archive. Reset your interests.")
        log.error("recommendations failed", extra={"fields": {"request_id": g.request_id, "error": str(error)}})
        return error_response(503, "unavailable", "Recommendations are unavailable. Check the model service and try again.")

    def store_failure(error: PyMongoError, operation: str) -> Response:
        log.error("article request failed", extra={"fields": {
            "request_id": g.request_id, "operation": operation,
            "error_type": type(error).__name__, "timeout": bool(getattr(error, "timeout", False)),
        }})
        if getattr(error, "timeout", False):
            return error_response(503, "unavailable", "the service is temporarily unavailable")
        return error_response(500, "internal_error", "internal server error")

    @app.before_request
    def start_request() -> Response | None:
        g.request_id = _request_id()
        g.started = time.perf_counter()
        if is_cross_site(request.method, request.headers, settings.public_origin):
            return error_response(403, "cross_site_request", "Cross-site requests are not allowed.")
        path = request.path
        gated = settings.auth_enabled and path.startswith("/api/v1/") and path != "/api/v1/session"
        if gated and current_reader() is None:
            return error_response(401, "sign_in_required", "Sign in to read your stories.")
        return None

    @app.after_request
    def finish_request(response: Response) -> Response:
        page = response.mimetype == "text/html"
        apply_headers(response.headers, page=page)
        response.headers["X-Request-Id"] = g.get("request_id", "")
        if request.path.startswith(("/api/", "/auth/")):
            response.headers["Cache-Control"] = "no-store"
        log.info("http request", extra={"fields": {
            "request_id": g.get("request_id", ""),
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "bytes": response.content_length or 0,
            "duration_ms": round((time.perf_counter() - g.get("started", time.perf_counter())) * 1000, 2),
        }})
        return response

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Response:
        if error.code == 404:
            response = error_response(404, "not_found", "route not found")
        elif error.code == 405:
            response = error_response(405, "method_not_allowed", "method not allowed")
            for key, value in error.get_headers():
                if key.lower() == "allow":
                    response.headers["Allow"] = value
        elif error.code == 413:
            response = error_response(413, "invalid_input", f"request body must not exceed {REQUEST_BODY_LIMIT} bytes")
        elif error.code and error.code < 500:
            response = error_response(error.code, "invalid_input", error.name.lower())
        else:
            response = error_response(500, "internal_error", "internal server error")
        return response

    @app.errorhandler(PyMongoError)
    def database_error(error: PyMongoError) -> Response:
        return store_failure(error, request.endpoint or "request")

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> Response:
        log.exception("unhandled error", extra={"fields": {"request_id": g.get("request_id", ""), "path": request.path}})
        return error_response(500, "internal_error", "internal server error")

    # --- Health -------------------------------------------------------------------------

    @app.get("/health/live")
    def live() -> Response:
        return json_response(200, {"status": "alive", "version": HEALTH_VERSION})

    @app.get("/health/ready")
    def ready() -> Response:
        checks = {"mongodb": "ok", "ranker": "ok"}
        try:
            services.ping_database()
        except Exception as error:  # any failure means not ready; the detail goes to the log only
            log.warning("readiness check failed", extra={"fields": {"dependency": "mongodb", "error_type": type(error).__name__}})
            checks["mongodb"] = "unavailable"
        try:
            services.recommendations.metadata(timeout=2.0)
        except RankerError as error:
            log.warning("recommender not ready", extra={"fields": {"dependency": "ranker", "error": str(error)}})
            checks["ranker"] = "unavailable"
        ok = all(value == "ok" for value in checks.values())
        return json_response(200 if ok else 503, {"status": "ready" if ok else "not_ready", "version": HEALTH_VERSION, "checks": checks})

    # --- Session and sign-in --------------------------------------------------------------

    @app.get("/api/v1/session")
    def session_info() -> Response:
        if not settings.auth_enabled:
            return json_response(200, {"auth_enabled": False, "signed_in": True, "reader": LOCAL_READER, "login_url": LOGIN_PATH})
        reader = current_reader()
        return json_response(200, {
            "auth_enabled": True,
            "signed_in": reader is not None,
            "reader": {"email": reader.email, "name": reader.name} if reader else None,
            "login_url": LOGIN_PATH,
        })

    def clear_flow(response: Response) -> Response:
        response.delete_cookie(FLOW_COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return response

    @app.get(LOGIN_PATH)
    def login() -> Response:
        next_path = safe_next(request.args.get("next"))
        if not settings.auth_enabled:
            return redirect(next_path, 302)
        assert services.oidc and services.flow_cookie
        flow = LoginFlow.start(next_path)
        response = redirect(services.oidc.authorization_url(flow), 302)
        response.set_cookie(FLOW_COOKIE, services.flow_cookie.encode(flow), max_age=FLOW_SECONDS,
                            path="/", secure=True, httponly=True, samesite="Lax")
        return response

    @app.get(CALLBACK_PATH)
    def callback() -> Response:
        if not settings.auth_enabled:
            return redirect("/", 302)
        assert services.oidc and services.flow_cookie and services.readers and services.sessions
        try:
            flow = services.flow_cookie.decode(request.cookies.get(FLOW_COOKIE))
            if request.args.get("error"):
                raise SignInFailed("Google returned an error")
            state = request.args.get("state", "")
            if not state or not secrets.compare_digest(state, flow.state):
                raise SignInFailed("state mismatch")
            claims = services.oidc.exchange(request.args.get("code", ""), flow)
            reader = admit(services.readers, claims)
        except NotInvited:
            log.info("sign-in refused", extra={"fields": {"request_id": g.request_id, "reason": "not_invited"}})
            return clear_flow(redirect("/?auth_error=not_invited", 302))
        except (SignInFailed, PyMongoError) as error:
            log.warning("sign-in failed", extra={"fields": {"request_id": g.request_id, "reason": str(error) if isinstance(error, SignInFailed) else type(error).__name__}})
            return clear_flow(redirect("/?auth_error=sign_in_failed", 302))
        old = request.cookies.get(SESSION_COOKIE, "")
        if old:
            services.sessions.delete(old)
        token, _session = services.sessions.create(reader.id)
        log.info("signed in", extra={"fields": {"request_id": g.request_id, "reader_id": reader.id}})
        response = redirect(safe_next(flow.next), 302)
        response.set_cookie(SESSION_COOKIE, token, max_age=int(settings.session_absolute_timeout),
                            path="/", secure=True, httponly=True, samesite="Lax")
        return clear_flow(response)

    @app.post("/auth/logout")
    def logout() -> Response:
        token = request.cookies.get(SESSION_COOKIE, "")
        if token and services.sessions:
            services.sessions.delete(token)
        response = Response(status=204)
        del response.headers["Content-Type"]
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return response

    # --- Reader API (unchanged from the Go reader) --------------------------------------

    @app.get("/api/v1/recommendations/meta")
    def recommendation_metadata() -> Response:
        try:
            return json_response(200, services.recommendations.metadata())
        except RankerError as error:
            return ranker_failure(error)

    @app.post("/api/v1/recommendations")
    def recommendations() -> Response:
        try:
            RecommendRequest.check_media_type(request.headers.get("Content-Type"))
            try:
                body = request.get_data(cache=False)
            except RequestEntityTooLarge:
                raise RequestDecodeError(f"request body must not exceed {REQUEST_BODY_LIMIT} bytes") from None
            wanted = RecommendRequest.from_body(body, None)
        except RequestDecodeError as error:
            return error_response(error.status, "invalid_input", str(error))
        try:
            result = services.recommendations.recommend(wanted)
        except RankerError as error:
            return ranker_failure(error)
        page = result.page
        payload: dict[str, Any] = {
            "items": [
                {
                    **article_response(doc),
                    "score": hit.score, "reason": hit.reason, "text": hit.text, "text_kind": hit.text_kind,
                    "input_kind": hit.input_kind, "group": hit.topic, "date_kind": date_kind(doc),
                    "date_verified": hit.date_verified, "fresh": hit.fresh,
                }
                for hit, doc in result.items
            ],
            "method": page.method,
            "snapshot_id": page.snapshot_id,
            "exhausted": page.exhausted,
            "unavailable_ids": result.unavailable_ids,
            "ignored_viewed_ids": page.ignored_viewed_ids,
            "window": page.window,
        }
        if page.edition_date:
            payload["edition_date"] = page.edition_date
        return json_response(200, payload)

    @app.get("/api/v1/articles")
    def articles() -> Response:
        try:
            page = list_articles(services.articles, filter_from_query(request.args))
        except ValidationFailed as error:
            return validation_error(error)
        except PyMongoError as error:
            return store_failure(error, "list articles")
        return json_response(200, page.response())

    @app.get("/api/v1/articles/<article_id>")
    def article(article_id: str) -> Response:
        try:
            doc = get_article(services.articles, article_id)
        except ValidationFailed as error:
            return validation_error(error)
        except ArticleNotFound:
            return error_response(404, "not_found", "the requested article does not exist")
        except PyMongoError as error:
            return store_failure(error, "get article")
        return json_response(200, article_response(doc))

    @app.post("/read-events")
    def read_events() -> Response:
        # The legacy telemetry route stays disabled, as in the Go reader.
        return error_response(405, "method_not_allowed", "telemetry is disabled in the read-only reader")

    # --- Pages ----------------------------------------------------------------------------

    def page() -> Response:
        if not frontend.built:
            return error_response(503, "unavailable", "The reader app is not built yet.")
        return frontend.index()

    app.add_url_rule("/", "index", page, methods=["GET"])
    app.add_url_rule("/stories", "stories", page, methods=["GET"])

    @app.get("/assets/<path:name>")
    def asset(name: str) -> Response:
        return frontend.asset(name)

    @app.get("/<name>")
    def root_file(name: str) -> Response:
        return frontend.root_file(name)

    return app
