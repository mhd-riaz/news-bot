"""The reading default is baseline TF-IDF; the trained neural method stays selectable."""

import json

import pytest

from newsrec.api import create_app
from test_recommendations import index, index_dir


def test_api_advertises_and_uses_the_evaluated_default(index):
    client = create_app(index, api_key="").test_client()
    metadata = client.get("/v1/meta").json
    assert metadata["default_method"] == "tfidf"
    assert set(metadata["methods"]) == {"tfidf", "svd", "neural"}
    result = client.post("/v1/recommend", json={"limit": 1})
    assert result.status_code == 200 and result.json["method"] == "tfidf"


@pytest.mark.parametrize("method", ["tfidf", "svd", "neural"])
def test_explicit_comparison_lens_is_never_overridden(index, method):
    result = create_app(index, api_key="").test_client().post(
        "/v1/recommend", json={"method": method, "limit": 1},
    )
    assert result.status_code == 200 and result.json["method"] == method


@pytest.mark.parametrize("payload", [None, [], "invalid", 1])
def test_non_object_payload_remains_an_explicit_bad_request(index, payload):
    result = create_app(index, api_key="").test_client().post(
        "/v1/recommend", data=json.dumps(payload), content_type="application/json",
    )
    assert result.status_code == 400 and result.json["error"]["message"]
