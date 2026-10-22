from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, abort, request
from werkzeug.exceptions import HTTPException

from newsmlv2 import serve

DEFAULT_MAX_BATCH = 100
DEFAULT_MAX_REQUEST_BYTES = 1 << 20


def create_app(
    *,
    classifier: serve.Classifier | None = None,
    model_version: str | None = None,
    topics: list[dict[str, str]] | None = None,
    api_key: str | None = None,
    max_batch: int | None = None,
    max_request_bytes: int | None = None,
) -> Flask:
    classifier = classifier or serve.load(_model_directory())
    model_version = model_version or _model_version(classifier)
    topics = topics if topics is not None else _topics(_taxonomy_path(), classifier.classes)
    api_key = api_key if api_key is not None else os.getenv("NEWSML_API_KEY")
    max_batch = max_batch or _positive_env("NEWSML_MAX_BATCH", DEFAULT_MAX_BATCH)
    max_request_bytes = max_request_bytes or _positive_env(
        "NEWSML_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = max_request_bytes

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException) -> tuple[dict[str, str], int]:
        return {"error": error.description}, error.code or 500

    @app.before_request
    def require_api_key() -> None:
        if request.path.startswith("/health/") or not api_key:
            return
        supplied = request.headers.get("X-Classifier-Key", "")
        if not hmac.compare_digest(supplied, api_key):
            abort(401, "missing or invalid classifier key")

    @app.get("/health/live")
    @app.get("/health/ready")
    def health() -> dict[str, str]:
        return {"status": "ok", "model_version": model_version}

    @app.get("/v1/meta")
    def metadata() -> dict[str, Any]:
        return {
            "model_version": model_version,
            "cut": classifier.cut,
            "topics": topics,
        }

    @app.post("/v1/classify")
    def classify() -> dict[str, Any]:
        payload = request.get_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            abort(400, "body must contain an items array")
        items = payload["items"]
        if not items:
            abort(400, "items must not be empty")
        if len(items) > max_batch:
            abort(400, f"items must contain at most {max_batch} entries")

        response_items: list[dict[str, Any] | None] = [None] * len(items)
        texts: list[str] = []
        valid_positions: list[int] = []
        for position, item in enumerate(items):
            article_id, title, summary, body = _article_fields(item)
            cleaned_title, cleaned_summary, cleaned_body = serve.prepare(title, summary, body)
            text = serve.text_for(cleaned_title, cleaned_summary, cleaned_body)
            if not text.strip():
                response_items[position] = {
                    "id": article_id,
                    "error": "title, summary and body are all empty",
                }
                continue
            texts.append(text)
            valid_positions.append(position)

        if texts:
            labels, scores, filed = classifier.route(texts)
            for position, topic, confidence, admitted in zip(
                valid_positions, labels, scores, filed, strict=True
            ):
                response_items[position] = {
                    "id": items[position]["id"],
                    "topic": str(topic),
                    "confidence": float(confidence),
                    "filed": bool(admitted),
                }

        return {"model_version": model_version, "items": response_items}

    return app


def _article_fields(item: object) -> tuple[str, str, str, str]:
    if not isinstance(item, dict):
        abort(400, "each item must be an object")
    article_id = item.get("id")
    if not isinstance(article_id, str) or not article_id.strip():
        abort(400, "each item must have a non-empty string id")
    fields = tuple(item.get(name, "") for name in ("title", "summary", "body"))
    if not all(isinstance(value, str) for value in fields):
        abort(400, "title, summary and body must be strings")
    return article_id, *fields


def _model_directory() -> Path:
    value = os.getenv("NEWSML_MODEL_DIR")
    if not value:
        raise RuntimeError("NEWSML_MODEL_DIR must point to a model directory")
    directory = Path(value)
    if not (directory / serve.BUNDLE).is_file():
        raise RuntimeError(f"model bundle is missing from {directory}")
    return directory


def _model_version(classifier: serve.Classifier) -> str:
    value = classifier.metadata.get("snapshot_id")
    if not isinstance(value, str) or not value:
        raise RuntimeError("model metadata is missing snapshot_id")
    return value


def _taxonomy_path() -> Path:
    return Path(os.getenv("NEWSML_TAXONOMY_PATH", Path(__file__).parents[1] / "taxonomy.yaml"))


def _topics(path: Path, classes: Any) -> list[dict[str, str]]:
    with path.open() as file:
        taxonomy = yaml.safe_load(file)
    topic_ids = [entry["id"] for entry in taxonomy["classes"]]
    if set(topic_ids) != {str(topic) for topic in classes}:
        raise RuntimeError("taxonomy classes do not match model classes")
    return [
        {"id": topic_id, "label": topic_id.replace("_", " ").title()}
        for topic_id in topic_ids
    ] + [{"id": taxonomy["unsorted"], "label": "Unsorted"}]


def _positive_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if parsed < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed