"""Private representation service. MongoDB hydration stays in the Go application."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from flask import Flask, abort, request
from werkzeug.exceptions import HTTPException

from newsmlv2 import config

from .index import Index, UnknownArticle

DEFAULT_METHOD = "tfidf"


def create_app(index: Index | None = None, *, api_key: str | None = None) -> Flask:
    if index is None:
        directory = os.environ.get("NEWSREC_MODEL_DIR")
        if not directory:
            raise RuntimeError("NEWSREC_MODEL_DIR must point to a trained recommendation snapshot")
        index = Index(Path(directory))
    values = config.env_values(Path(os.environ.get("NEWS_ENV_FILE", config.DOTENV_PATH)))
    key = os.environ.get(
        "NEWS_RECOMMENDER_API_KEY", values.get("NEWS_RECOMMENDER_API_KEY", "")
    ) if api_key is None else api_key
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 << 10

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        return {"error": {"message": error.description}}, error.code

    @app.before_request
    def authenticate() -> None:
        if key and not request.path.startswith("/health/"):
            if not hmac.compare_digest(request.headers.get("X-Recommender-Key", ""), key):
                abort(401, "missing or invalid recommender key")

    @app.get("/health/live")
    @app.get("/health/ready")
    def health():
        return {"status": "ready", "snapshot_id": index.manifest["snapshot_id"]}

    @app.get("/v1/meta")
    def metadata():
        return {**index.metadata(), "default_method": DEFAULT_METHOD}

    @app.post("/v1/recommend")
    def recommend():
        try:
            payload = request.get_json()
            if isinstance(payload, dict):
                payload.setdefault("method", DEFAULT_METHOD)
            return index.recommend(payload)
        except UnknownArticle as error:
            app.logger.info("recommendation seed rejected: %s", error)
            abort(404, str(error))
        except ValueError as error:
            app.logger.info("recommendation input rejected: %s", error)
            abort(400, str(error))

    return app
