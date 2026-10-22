from __future__ import annotations

import numpy as np
import pytest

from app.api import create_app


class FakeClassifier:
    classes = np.array(["politics", "sport"])
    cut = 0.6
    metadata = {"snapshot_id": "test-v1"}

    def __init__(self) -> None:
        self.texts: list[str] = []

    def route(self, texts: list[str]):
        self.texts = texts
        return (
            np.array(["sport", "unsorted"][:len(texts)]),
            np.array([0.9, 0.4][:len(texts)]),
            np.array([True, False][:len(texts)]),
        )


@pytest.fixture
def classifier() -> FakeClassifier:
    return FakeClassifier()


@pytest.fixture
def client(classifier: FakeClassifier):
    app = create_app(
        classifier=classifier,
        topics=[
            {"id": "politics", "label": "Politics"},
            {"id": "sport", "label": "Sport"},
            {"id": "unsorted", "label": "Unsorted"},
        ],
        max_batch=2,
        max_request_bytes=1 << 10,
    )
    return app.test_client()


def test_classify_preserves_input_order_and_returns_unsorted(client, classifier):
    response = client.post(
        "/v1/classify",
        json={
            "items": [
                {"id": "one", "title": "Match result"},
                {"id": "two", "summary": "A story"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json == {
        "model_version": "test-v1",
        "items": [
            {"id": "one", "topic": "sport", "confidence": 0.9, "filed": True},
            {"id": "two", "topic": "unsorted", "confidence": 0.4, "filed": False},
        ],
    }
    assert classifier.texts == ["Match result\n", "\nA story"]


def test_classify_returns_per_item_error_without_skipping_other_articles(client, classifier):
    response = client.post(
        "/v1/classify",
        json={
            "items": [
                {"id": "empty", "title": " ", "summary": "", "body": ""},
                {"id": "one", "title": "Match result"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json["items"][0] == {
        "id": "empty",
        "error": "title, summary and body are all empty",
    }
    assert response.json["items"][1]["id"] == "one"
    assert classifier.texts == ["Match result\n"]


def test_classify_rejects_invalid_and_oversized_batches(client):
    assert client.post("/v1/classify", json={"items": []}).status_code == 400
    assert client.post("/v1/classify", json={"items": [{"id": "1"}] * 3}).status_code == 400
    assert client.post("/v1/classify", json={"items": [{"id": 1}]}).status_code == 400


def test_metadata_and_health_are_available(client):
    assert client.get("/health/live").json == {"status": "ok", "model_version": "test-v1"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/meta").json["topics"][-1] == {"id": "unsorted", "label": "Unsorted"}


def test_api_key_protects_model_endpoints(classifier):
    app = create_app(
        classifier=classifier,
        topics=[],
        api_key="secret",
        max_batch=2,
        max_request_bytes=1 << 10,
    )
    client = app.test_client()

    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/meta").status_code == 401
    assert client.get("/v1/meta", headers={"X-Classifier-Key": "secret"}).status_code == 200