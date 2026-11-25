"""Recommendation contracts: real logic over isolated synthetic artifacts, never a live DB."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy import sparse
from sklearn.preprocessing import normalize

from newsrec import data, evaluate, model
from newsrec.api import create_app
from newsrec.index import Index, UnknownArticle


def save_documents(directory, rows):
    directory.mkdir()
    path = directory / "documents.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    data.write_json(directory / "manifest.json", {
        "snapshot_id": directory.name, "articles": len(rows),
        "documents_sha256": data.digest(path),
        "publication_range": ["2026-08-01", "2026-08-02"],
        "collected_before": "2026-08-03T00:00:00Z", "date_note": "Stored date, not verified.",
    })


@pytest.fixture
def index_dir(tmp_path):
    directory = tmp_path / "unit-index"
    rows = []
    for i, publisher in enumerate(("North", "Copy", "East", "South", "West", "North", "East", "West")):
        rows.append({
            "id": f"article-{i}", "title": f"Headline number {i}", "text": f"Article words {i}",
            "display_text": f"Stored text {i}", "display_kind": "Excerpt", "text_kind": "body",
            "publisher": publisher, "source_name": publisher, "url": f"https://example.test/{i}",
            "image_url": "", "published_at": "2026-08-01T00:00:00+00:00",
            "collected_at": "2026-08-02T00:00:00+00:00",
        })
    save_documents(directory, rows)
    vectors = normalize(np.array([
        [1, 0, 0], [1, 0, 0], [.99, .1, 0], [0, 1, 0],
        [.9, .1, .1], [-1, 0, 0], [0, 0, 1], [.8, .2, 0],
    ], dtype=np.float32))
    sparse.save_npz(directory / "tfidf.npz", sparse.csr_matrix(vectors))
    for name in ("svd", "neural"):
        np.save(directory / f"{name}.npy", vectors, allow_pickle=False)
    data.write_json(directory / "groups.json", ["a", "a", "b", "c", "d", "e", "f", "g"])
    np.save(directory / "assignments.npy", np.array([0, 0, 0, 1, 0, 1, 1, 0]))
    data.write_json(directory / "topics.json", [
        {"id": "0", "label": "research", "keywords": ["research"], "count": 5,
         "representatives": ["article-0", "article-2", "article-4", "article-7"]},
        {"id": "1", "label": "society", "keywords": ["society"], "count": 3,
         "representatives": ["article-3", "article-5", "article-6"]},
    ])
    names = ["documents.jsonl", "groups.json", "tfidf.npz", "neural.npy", "svd.npy",
             "assignments.npy", "topics.json"]
    data.write_json(directory / "training.json", {
        "artifacts": {name: data.digest(directory / name) for name in names},
    })
    return directory


@pytest.fixture
def index(index_dir):
    return Index(index_dir)


@pytest.mark.parametrize("method", ["tfidf", "svd", "neural"])
def test_related_excludes_self_copies_and_viewed(index, method):
    page = index.recommend({
        "seed_id": "article-0", "viewed": ["article-2"], "method": method, "limit": 5,
    })
    ids = [item["id"] for item in page["items"]]
    assert ids[0] == "article-4"
    assert not set(ids) & {"article-0", "article-1", "article-2"}
    assert len(ids) == len(set(ids))
    assert page["exhausted"]
    assert page["items"][0]["reason"] == "Related to this article"


def test_interests_and_explicit_negative_feedback_change_rankings(index):
    initial = index.recommend({"liked": ["article-0"], "limit": 2})
    changed = index.recommend({"liked": ["article-3"], "limit": 2})
    negative = index.recommend({"liked": ["article-0"], "disliked": ["article-2"], "limit": 2})
    assert initial["items"][0]["id"] != changed["items"][0]["id"]
    assert "article-2" not in [item["id"] for item in negative["items"]]
    assert negative["items"][0]["reason"] == "Based on your selections"


def test_related_seed_is_not_diluted_by_unrelated_saved_interests(index):
    page = index.recommend({"seed_id": "article-0", "liked": ["article-3"], "limit": 2})
    assert page["items"][0]["id"] == "article-2"
    assert "article-3" not in [item["id"] for item in page["items"]]


def test_cold_start_topic_and_exhaustion(index):
    page = index.recommend({"topic": "1", "limit": 30})
    assert {item["id"] for item in page["items"]} == {"article-3", "article-5", "article-6"}
    empty = index.recommend({"viewed": list(index.positions)})
    assert empty["items"] == [] and empty["exhausted"]
    assert index.metadata()["articles"] == 8


def test_history_is_bounded_and_stale_history_is_explicit(index):
    page = index.recommend({"viewed": ["no-longer-indexed"] * 1000})
    assert page["ignored_viewed_ids"] == 1
    with pytest.raises(ValueError, match="2000"):
        index.recommend({"viewed": ["article-0"] * 2001})


@pytest.mark.parametrize("payload", [
    None, [], {"unknown": 1}, {"method": "invented"}, {"method": []},
    {"limit": True}, {"limit": 0}, {"limit": 31}, {"topic": "99"}, {"topic": 1},
    {"seed_id": []}, {"liked": "article-0"}, {"liked": ["x"] * 51},
    {"liked": [None]}, {"disliked": ["x" * 65]},
    {"liked": ["article-0"], "disliked": ["article-0"]},
])
def test_malformed_and_oversized_input_is_rejected(index, payload):
    with pytest.raises(ValueError):
        index.recommend(payload)


def test_unknown_seed_is_not_a_success_shaped_cold_start(index):
    with pytest.raises(UnknownArticle):
        index.recommend({"seed_id": "outside-index"})


def dated_index(directory, now):
    """The unit index with C1 date provenance, domains and a fixed clock."""
    rows = data.documents(directory)
    dates = {  # (published_at, date_verified or None for an archive frozen before provenance)
        0: ("2026-08-09T10:00:00+05:30", True),  # yesterday in Asia/Kolkata
        1: ("2026-08-09T10:00:00+05:30", True),  # same story group as article-0
        2: ("2026-08-08T20:00:00+00:00", None),  # 01:30 on 9 Aug in Kolkata; legacy verified
        3: ("2026-08-09T19:00:00+00:00", True),  # 00:30 on 10 Aug in Kolkata: today, still fresh
        4: ("2026-08-09T09:00:00+00:00", False),  # unverified: never fresh
        5: ("2026-06-01T00:00:00+00:00", True),  # older than 30 days
        6: ("2026-08-11T00:00:00+00:00", True),  # future-dated
        7: (None, True),
    }
    for i, row in enumerate(rows):
        row["published_at"], verified = dates[i]
        if verified is None:
            row.pop("date_verified", None)
            row["date_kind"] = "Stored publication date"
        else:
            row["date_verified"] = verified
        row["domains"] = ["ai"] if i in (0, 2, 3) else ["software"] if i == 4 else []
    path = directory / "documents.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = data.read_json(directory / "manifest.json")
    manifest["documents_sha256"] = data.digest(path)
    data.write_json(directory / "manifest.json", manifest)
    training = data.read_json(directory / "training.json")
    training["artifacts"]["documents.jsonl"] = data.digest(path)
    data.write_json(directory / "training.json", training)
    return Index(directory, clock=lambda: now)


def test_news_windows_follow_c2_freshness_and_the_c9_edition_day(index_dir):
    index = dated_index(index_dir, datetime(2026, 8, 10, 4, tzinfo=UTC))  # 09:30 in Kolkata
    meta = index.metadata()
    assert meta["windows"] == {"fresh": 4, "yesterday": 3, "archive": 4}
    assert (meta["edition_date"], meta["edition_timezone"]) == ("2026-08-09", "Asia/Kolkata")
    assert meta["domains"] == {"ai": 3, "software": 1}

    edition = index.recommend({"window": "yesterday", "limit": 10})
    assert [item["id"] for item in edition["items"]] == ["article-0", "article-2"]
    assert edition["edition_date"] == "2026-08-09" and edition["window"] == "yesterday"
    assert edition["items"][0]["reason"] == "Published yesterday"
    fresh = index.recommend({"window": "fresh"})
    assert [item["id"] for item in fresh["items"]] == ["article-3", "article-0", "article-2"]
    assert all(item["fresh"] and item["date_verified"] for item in fresh["items"])
    archive = index.recommend({"window": "archive", "limit": 30})
    assert {item["id"] for item in archive["items"]} == {"article-4", "article-5", "article-6", "article-7"}
    assert not any(item["fresh"] for item in archive["items"])
    assert {item["id"] for item in index.recommend({"window": "fresh", "domains": ["ai"]})["items"]} == {
        "article-0", "article-2", "article-3",
    }
    assert index.recommend({"domains": ["software"]})["items"][0]["id"] == "article-4"

    # An edition ranks every eligible story by the profile, even unrelated ones.
    liked = index.recommend({"window": "yesterday", "liked": ["article-3"], "limit": 10})
    assert [item["id"] for item in liked["items"]] == ["article-2", "article-0"]

    early = dated_index(index_dir, datetime(2026, 8, 10, 0, tzinfo=UTC))  # 05:30 in Kolkata
    assert early.metadata()["edition_date"] == "2026-08-08"
    assert early.recommend({"window": "yesterday"})["items"] == []


@pytest.mark.parametrize("payload", [
    {"window": "tomorrow"}, {"window": 1}, {"domains": "ai"}, {"domains": [""]},
    {"domains": ["x" * 65]}, {"domains": [f"tag-{i}" for i in range(9)]},
])
def test_window_and_domain_input_is_rejected(index, payload):
    with pytest.raises(ValueError):
        index.recommend(payload)


def test_artifact_corruption_fails_startup(index_dir):
    (index_dir / "groups.json").write_text("[]")
    with pytest.raises(ValueError, match="digest"):
        Index(index_dir)


def test_flask_real_index_auth_validation_and_error_shapes(index):
    client = create_app(index, api_key="synthetic-unit-key").test_client()
    headers = {"X-Recommender-Key": "synthetic-unit-key"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/meta").status_code == 401
    assert client.get("/v1/meta", headers=headers).json["articles"] == 8
    result = client.post("/v1/recommend", headers=headers, json={"seed_id": "article-0"})
    assert result.status_code == 200 and result.json["items"]
    invalid = client.post("/v1/recommend", headers=headers, json={"limit": 31})
    assert invalid.status_code == 400 and invalid.json["error"]["message"]
    assert client.post("/v1/recommend", headers=headers, json={"seed_id": "unknown"}).status_code == 404
    assert client.post("/v1/recommend", headers=headers, data="x" * (129 << 10),
                       content_type="application/json").status_code == 413


def test_flask_loads_configured_artifacts_or_fails_explicitly(index_dir, monkeypatch):
    monkeypatch.delenv("NEWSREC_MODEL_DIR", raising=False)
    with pytest.raises(RuntimeError, match="NEWSREC_MODEL_DIR"):
        create_app()
    monkeypatch.setenv("NEWSREC_MODEL_DIR", str(index_dir))
    assert create_app(api_key="").test_client().get("/health/ready").status_code == 200


def test_index_checks_alignment_finite_values_and_featureless_inputs(index_dir, index):
    index.has_features[:] = False
    with pytest.raises(ValueError, match="no usable features"):
        index.recommend({"seed_id": "article-0"})
    index.has_features[:] = True
    index.matrices["neural"] = np.zeros((8, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="no usable features"):
        index.recommend({"seed_id": "article-0"})
    data.write_json(index_dir / "groups.json", ["wrong length"])
    training = data.read_json(index_dir / "training.json")
    training["artifacts"]["groups.json"] = data.digest(index_dir / "groups.json")
    data.write_json(index_dir / "training.json", training)
    with pytest.raises(ValueError, match="not aligned"):
        Index(index_dir)
    data.write_json(index_dir / "groups.json", list("abcdefgh"))
    vectors = np.ones((8, 3), dtype=np.float32)
    vectors[0, 0] = np.nan
    np.save(index_dir / "neural.npy", vectors)
    for name in ("groups.json", "neural.npy"):
        training["artifacts"][name] = data.digest(index_dir / name)
    data.write_json(index_dir / "training.json", training)
    with pytest.raises(ValueError, match="invalid values"):
        Index(index_dir)


@pytest.mark.parametrize("title,summary,body,kind", [
    ("A valid headline", "", "", "headline"),
    ("A valid headline", "A useful stored summary", "", "summary"),
    ("A valid headline", "Summary", "The real article body", "body"),
    ("A valid headline", "A valid headline", "", "headline"),
])
def test_input_recipe_fallbacks_and_length_cap(title, summary, body, kind):
    text, observed = data.input_text(title, summary, body)
    assert observed == kind and text.startswith(title)
    long_text, _ = data.input_text(title, "", "word " * 10000)
    assert len(long_text.split()) == len(title.split()) + data.SUPPORT_WORDS


def test_language_is_checked_not_inferred_from_source_metadata():
    accepted, confidence = data.english_text(
        "The research team published new findings about galaxies and distant stars."
    )
    assert accepted and 0 <= confidence <= 1
    accepted, confidence = data.english_text(
        "\u092f\u0939 \u0939\u093f\u0902\u0926\u0940 \u092e\u0947\u0902 \u090f\u0915 \u0938\u092e\u093e\u091a\u093e\u0930 \u0939\u0948"
    )
    assert not accepted and confidence == 0
    accepted, confidence = data.english_text("")
    assert not accepted and confidence == 0


def test_database_settings_honor_file_and_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("NEWS_MONGO_URI='mongodb://example.test:27017'\nNEWS_MONGO_DATABASE=news\n")
    monkeypatch.setenv("NEWS_ENV_FILE", str(env))
    monkeypatch.delenv("NEWS_MONGO_URI", raising=False)
    monkeypatch.delenv("NEWSMLV2_MONGO_URI", raising=False)
    monkeypatch.delenv("NEWS_MONGO_DATABASE", raising=False)
    assert data.settings() == ("mongodb://example.test:27017", "news")
    monkeypatch.setenv("NEWS_MONGO_URI", "mongodb://override.test")
    assert data.settings()[0] == "mongodb://override.test"


def test_export_is_bounded_deterministic_and_read_only(tmp_path, monkeypatch):
    records = [{
        "_id": f"article-{i:03}", "source_id": "source", "source_name": "Test publisher",
        "title": f"Research scientists examine distant galaxy number {i}",
        "content": "Researchers published a study of distant stars and planetary systems.",
        "language": "en", "url": f"https://example.test/{i}", "country": "GB",
        "content_hash": str(i), "collected_at": datetime(2026, 8, 1, tzinfo=UTC),
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
    } for i in range(140)]
    for i, record in enumerate(records):
        record["summary"] = "A useful stored summary of the research." if i % 3 == 0 else ""
        if i % 5 == 0:
            record["content"] = ""
    records[0]["title"] = "Daily horoscope today"

    class Cursor:
        def sort(self, *_):
            return self

        def batch_size(self, *_):
            return iter(records)

    class Collection:
        def find(self, query, projection):
            assert query["collected_at"]["$lt"].tzinfo
            assert "categories" not in projection
            return Cursor()

    class Sources:
        def find(self, query, projection):
            assert query == {} and projection == {"_id": 1, "domains": 1}
            return [{"_id": "source", "domains": ["software", "ai"]}]

    class Database:
        articles = Collection()
        sources = Sources()

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __getitem__(self, name):
            assert name == "news"
            return Database()

    monkeypatch.setattr(data, "MongoClient", Client)
    monkeypatch.setattr(data, "english_text", lambda _: (True, 1.0))
    monkeypatch.setattr(data, "settings", lambda: ("mongodb://unit.test", "news"))
    left, right = tmp_path / "left", tmp_path / "right"
    for directory in (left, right):
        result = data.freeze(directory, cut=datetime(2026, 8, 2, tzinfo=UTC), limit=100, candidates=120)
        assert result["articles"] == 100 and result["scanned"] == 140
        assert result["recent_articles"] == 0 and result["date_verified"] == 0
    assert (left / "documents.jsonl").read_bytes() == (right / "documents.jsonl").read_bytes()
    row = data.documents(left)[0]
    assert row["domains"] == ["ai", "software"] and row["source_id"] == "source"
    assert (row["date_source"], row["date_verified"]) == ("collected_fallback", False)
    with pytest.raises(FileExistsError):
        data.freeze(left, cut=datetime(2026, 8, 2, tzinfo=UTC))
    monkeypatch.setattr(data, "english_text", lambda _: (False, 0.0))
    with pytest.raises(ValueError, match="only 0"):
        data.freeze(tmp_path / "rejected", cut=datetime(2026, 8, 2, tzinfo=UTC), limit=100, candidates=120)
    records.clear()
    with pytest.raises(ValueError, match="no articles"):
        data.freeze(tmp_path / "empty", cut=datetime(2026, 8, 2, tzinfo=UTC), limit=100, candidates=120)
    with pytest.raises(ValueError, match="timezone-aware"):
        data.freeze(tmp_path / "naive", cut=datetime(2026, 8, 2))
    with pytest.raises(ValueError, match="require 100"):
        data.freeze(tmp_path / "bad-limit", cut=datetime(2026, 8, 2, tzinfo=UTC), limit=0)
    with pytest.raises(ValueError, match="recent_days"):
        data.freeze(tmp_path / "bad-recent", cut=datetime(2026, 8, 2, tzinfo=UTC), recent_days=-1)


def test_recent_window_is_kept_newest_first_and_dates_follow_c1_provenance(tmp_path, monkeypatch):
    def record(i, collected, published, **extra):
        return {
            "_id": f"article-{i:03}", "source_id": "tech" if i % 2 else "local",
            "source_name": "Test publisher", "title": f"Research scientists examine distant galaxy number {i}",
            "summary": "", "content": "Researchers published a study of distant stars and planets.",
            "language": "en", "url": f"https://example.test/{i}", "country": "GB",
            "content_hash": str(i), "collected_at": collected, "published_at": published, **extra,
        }

    older = datetime(2026, 8, 1, tzinfo=UTC)
    records = [record(i, older, older if i % 3 else datetime(2026, 7, 31, tzinfo=UTC)) for i in range(150)]
    # Stored provenance wins over the legacy rule: article-150 has differing dates but is unverified.
    recent = [
        record(150 + i, datetime(2026, 8, 9, tzinfo=UTC) + timedelta(minutes=i),
               datetime(2026, 8, 8, tzinfo=UTC), date_verified=i != 0,
               published_at_source="page" if i else "collected_fallback")
        for i in range(30)
    ]
    records += recent
    earliest = datetime.min.replace(tzinfo=UTC)

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def sort(self, field, direction):
            self.rows = sorted(self.rows, key=lambda row: row[field], reverse=direction < 0)
            return self

        def limit(self, count):
            self.rows = self.rows[:count]
            return self

        def batch_size(self, *_):
            return iter(self.rows)

    class Collection:
        def find(self, query, _projection):
            window = query["collected_at"]
            return Cursor([
                row for row in records
                if window.get("$gte", earliest) <= row["collected_at"] < window["$lt"]
            ])

    class Sources:
        def find(self, *_):
            return [{"_id": "tech", "domains": ["ai"]}, {"_id": "local"}]

    class Database:
        articles = Collection()
        sources = Sources()

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __getitem__(self, _):
            return Database()

    monkeypatch.setattr(data, "MongoClient", Client)
    monkeypatch.setattr(data, "english_text", lambda _: (True, 1.0))
    monkeypatch.setattr(data, "settings", lambda: ("mongodb://unit.test", "news"))
    cut = datetime(2026, 8, 10, tzinfo=UTC)
    result = data.freeze(tmp_path / "recent", cut=cut, limit=100, candidates=120, recent_days=3)
    rows = {row["id"]: row for row in data.documents(tmp_path / "recent")}
    assert result["scanned"] == 180 and result["articles"] == 100 and result["recent_articles"] == 30
    assert {row["_id"] for row in recent} <= set(rows)
    assert (rows["article-150"]["date_source"], rows["article-150"]["date_verified"]) == ("collected_fallback", False)
    assert (rows["article-151"]["date_source"], rows["article-151"]["date_verified"]) == ("page", True)
    older_rows = [row for row in rows.values() if row["collected_at"].startswith("2026-08-01")]
    assert {(row["date_source"], row["date_verified"]) for row in older_rows} == {
        ("feed", True), ("collected_fallback", False),
    }
    assert rows["article-151"]["domains"] == ["ai"] and rows["article-152"]["domains"] == []

    # A window busier than the candidate budget keeps its newest articles first.
    busy = data.freeze(tmp_path / "busy", cut=cut, limit=100, candidates=120, recent_days=9)
    kept = {row["id"] for row in data.documents(tmp_path / "busy")}
    assert busy["scanned"] == 120 and busy["recent_articles"] == 100
    assert {row["_id"] for row in recent} <= kept


def test_readonly_connection_inspection_has_no_write_methods(monkeypatch):
    class Collection:
        def count_documents(self, query):
            assert query == {}
            return 123

        def find_one(self, *_args, **_kwargs):
            return {"collected_at": datetime(2026, 8, 2, tzinfo=UTC)}

    class Database:
        articles = Collection()

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __getitem__(self, _):
            return Database()

    monkeypatch.setattr(data, "MongoClient", Client)
    monkeypatch.setattr(data, "settings", lambda: ("mongodb://unit.test", "news"))
    result = data.inspect_database()
    assert result["articles"] == 123 and "uri" not in result


def test_snapshot_digest_and_count_guards(index_dir):
    manifest = data.read_json(index_dir / "manifest.json")
    manifest["articles"] += 1
    data.write_json(index_dir / "manifest.json", manifest)
    with pytest.raises(ValueError, match="count"):
        data.documents(index_dir)
    manifest["documents_sha256"] = "changed"
    data.write_json(index_dir / "manifest.json", manifest)
    with pytest.raises(ValueError, match="digest"):
        data.documents(index_dir)


def test_benchmark_and_completed_blind_sheet_are_scored(index_dir, monkeypatch):
    monkeypatch.setattr(evaluate, "category_proxy", lambda _: {"status": "not human ground truth"})
    result = evaluate.benchmark(index_dir, queries=4)
    assert result["cases"] == 4 and result["human_relevance"].startswith("pending")
    sheet = index_dir / "judgements.jsonl"
    with pytest.raises(ValueError, match="independent grade"):
        evaluate.score(index_dir, sheet)
    rows = [json.loads(line) for line in sheet.read_text().splitlines()]
    for row in rows:
        row["grade"] = 2
    sheet.write_text("".join(json.dumps(row) + "\n" for row in rows))
    measured = evaluate.score(index_dir, sheet)
    assert set(measured) == {"tfidf", "svd", "neural"}
    assert all(0 <= method["precision_at_5"] <= 1 for method in measured.values())
    with pytest.raises(FileExistsError):
        evaluate.benchmark(index_dir, queries=4)
    with pytest.raises(ValueError, match="between 4"):
        evaluate.benchmark(index_dir, queries=0)
    cases = data.read_json(index_dir / "evaluation-cases.json")
    cases["training_sha256"] = "changed"
    data.write_json(index_dir / "evaluation-cases.json", cases)
    with pytest.raises(ValueError, match="model or retrieval changed"):
        evaluate.score(index_dir, sheet)


def test_selected_manual_cases_do_not_silently_claim_full_evaluation(index_dir, monkeypatch):
    monkeypatch.setattr(evaluate, "category_proxy", lambda _: {})
    evaluate.benchmark(index_dir, queries=4)
    sheet = index_dir / "judgements.jsonl"
    rows = [json.loads(line) for line in sheet.read_text().splitlines()]
    first_case = rows[0]["case_id"]
    for row in rows:
        if row["case_id"] == first_case:
            row["grade"] = 1
    sheet.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = evaluate.score(index_dir, sheet, case_ids=[first_case])
    assert result["neural"]["cases"] == 1 and result["neural"]["total_cases"] == 4
    assert result["neural"]["precision_at_5"] == 0
    assert (index_dir / "relevance-selected.json").is_file()
    with pytest.raises(ValueError, match="selected judgement cases"):
        evaluate.score(index_dir, sheet, case_ids=["unknown"])
    with pytest.raises(ValueError, match="independent grade"):
        evaluate.score(index_dir, sheet)


def test_acceptance_sample_is_reproducible_and_balanced(tmp_path):
    train_cut = datetime(2026, 9, 1, tzinfo=UTC)
    t_eval = datetime(2026, 10, 25, tzinfo=UTC)
    rows = []
    groups = []
    for number in range(55):
        rows.append({
            "id": f"article-{number:02}",
            "collected_at": "2026-08-31T00:00:00Z" if number < 2 else "2026-09-02T00:00:00Z",
            "published_at": "2026-10-20T00:00:00Z" if number < 50 else "2026-08-01T00:00:00Z",
            "detected_language": "en",
            "date_verified": number != 49,
        })
        groups.append(f"group-{number:02}")
    rows.append({
        "id": "article-prior-copy",
        "collected_at": "2026-08-31T00:00:00Z",
        "published_at": "2026-10-20T00:00:00Z",
        "detected_language": "en",
        "date_verified": True,
    })
    groups.append("group-02")
    profiles = {
        "grader-b": {"liked": ["article-01"], "viewed": ["article-00"]},
        "grader-a": {"liked": ["article-00"]},
    }

    sample = evaluate.sample_acceptance(
        rows, groups, train_cut=train_cut, t_eval=t_eval, grader_profiles=profiles,
    )
    repeated = evaluate.sample_acceptance(
        list(reversed(rows)), list(reversed(groups)), train_cut=train_cut, t_eval=t_eval,
        grader_profiles=dict(reversed(list(profiles.items()))),
    )
    assert sample == repeated
    assert sample["seed"] == 20260823
    assert sample["counts"] == {"total": 50, "feed": 2, "related_reading": 48}
    assert sample["grader_case_counts"] == {"grader-a": 25, "grader-b": 25}
    assert len(sample["cases"]) == 50
    feed = [case for case in sample["cases"] if case["type"] == "feed"]
    related = [case for case in sample["cases"] if case["type"] == "related_reading"]
    assert [case["request"]["liked"] for case in feed] == [["article-00"], ["article-01"]]
    assert all(case["request"]["limit"] == 5 for case in feed)
    assert len({case["request"]["seed_id"] for case in related}) == 48
    assert "article-02" not in sample["candidate_pools"]["post_train"]
    assert "article-prior-copy" not in sample["candidate_pools"]["post_train"]
    assert sample["candidate_pools"]["fresh_feed"] == [
        f"article-{number:02}" for number in range(3, 49)
    ]
    assert all(
        sample["candidate_pools"]["post_train"].count(case["request"]["seed_id"]) == 1
        for case in related
    )

    five_graders = {f"grader-{number}": {} for number in range(5)}
    five_grader_sample = evaluate.sample_acceptance(
        rows, groups, train_cut=train_cut, t_eval=t_eval, grader_profiles=five_graders,
    )
    assert five_grader_sample["counts"] == {"total": 50, "feed": 5, "related_reading": 45}
    assert set(five_grader_sample["grader_case_counts"].values()) == {10}

    output = tmp_path / "acceptance-sample.json"
    saved = evaluate.sample_acceptance(
        rows, groups, train_cut=train_cut, t_eval=t_eval, grader_profiles=profiles, output=output,
    )
    assert data.read_json(output) == saved
    with pytest.raises(FileExistsError, match="preserve the frozen"):
        evaluate.sample_acceptance(
            rows, groups, train_cut=train_cut, t_eval=t_eval, grader_profiles=profiles, output=output,
        )


def test_acceptance_sample_rejects_invalid_inputs():
    train_cut = datetime(2026, 9, 1, tzinfo=UTC)
    t_eval = datetime(2026, 10, 25, tzinfo=UTC)
    profiles = {"grader-a": {}, "grader-b": {}}
    rows = [{
        "id": f"article-{number}",
        "collected_at": "2026-09-02T00:00:00Z",
        "published_at": "2026-10-20T00:00:00Z",
        "detected_language": "en",
        "date_verified": True,
    } for number in range(50)]
    groups = [f"group-{number}" for number in range(50)]

    with pytest.raises(ValueError, match="later than train_cut"):
        evaluate.sample_acceptance(
            rows, groups, train_cut=t_eval, t_eval=train_cut, grader_profiles=profiles,
        )
    with pytest.raises(ValueError, match="outside the frozen index"):
        evaluate.sample_acceptance(
            rows, groups, train_cut=train_cut, t_eval=t_eval,
            grader_profiles={"grader-a": {"liked": ["missing"]}, "grader-b": {}},
        )
    with pytest.raises(ValueError, match="need 48 post-training"):
        evaluate.sample_acceptance(
            rows[:47], groups[:47], train_cut=train_cut, t_eval=t_eval, grader_profiles=profiles,
        )
    rows[0].pop("date_verified")
    with pytest.raises(ValueError, match="detected_language and boolean date_verified"):
        evaluate.sample_acceptance(
            rows, groups, train_cut=train_cut, t_eval=t_eval, grader_profiles=profiles,
        )


def test_category_proxy_uses_only_old_train_labels(index, monkeypatch):
    import pandas as pd

    frame = pd.DataFrame({
        "article_id": list(index.positions),
        "topic": ["science"] * len(index.positions),
    })

    class Table:
        def to_pandas(self):
            return frame

    def read_table(_path, **kwargs):
        assert kwargs["filters"] == [("split", "=", "train")]
        return Table()

    monkeypatch.setattr(evaluate.pq, "read_table", read_table)
    result = evaluate.category_proxy(index)
    assert result["articles"] == 8 and result["queries"] == 8
    assert all(value == 1 for value in result["same_category_at_5"].values())
    frame = frame.iloc[:2]
    assert evaluate.category_proxy(index)["status"].startswith("not enough")


@pytest.mark.parametrize("command,extra", [
    ("prepare", ["--cut", "2026-08-02T00:00:00+00:00"]),
    ("baseline", []), ("train", ["--epochs", "1"]), ("benchmark", []),
    ("measure", []),
    ("score", ["--judgements", "unit-sheet.jsonl"]),
])
def test_cli_routes_to_the_correct_pipeline_stage(command, extra, tmp_path, monkeypatch, capsys):
    from newsrec import cli

    def result(*_args, **_kwargs):
        return {"stage": command}

    monkeypatch.setattr(data, "freeze", result)
    monkeypatch.setattr(model, "baseline", result)
    monkeypatch.setattr(model, "train", result)
    monkeypatch.setattr(evaluate, "benchmark", result)
    monkeypatch.setattr(evaluate, "api_latency", result)
    monkeypatch.setattr(evaluate, "score", result)
    assert cli.main([command, "--id", "unit", "--root", str(tmp_path), *extra]) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == command


def test_cli_inspect_serve_and_invalid_arguments(index, monkeypatch, capsys):
    import newsrec.api
    import newsrec.index
    from newsrec import cli

    monkeypatch.setattr(data, "inspect_database", lambda: {"database": "news", "articles": 123})
    assert cli.main(["inspect"]) == 0
    assert json.loads(capsys.readouterr().out)["articles"] == 123
    calls = []

    class App:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(newsrec.index, "Index", lambda _: index)
    monkeypatch.setattr(newsrec.api, "create_app", lambda _: App())
    assert cli.main(["serve", "--id", "unit", "--port", "8001"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8001, "debug": False}]
    with pytest.raises(SystemExit):
        cli.main(["serve", "--id", "../bad"])
    with pytest.raises(SystemExit):
        cli.main(["serve", "--id", "unit", "--port", "0"])


def test_api_measurement_uses_frozen_cases_and_rejects_wrong_edition(index_dir, monkeypatch):
    from newsrec import cli

    data.write_json(index_dir / "evaluation-cases.json", {
        "cases": [{"id": "case-a", "request": {"seed_id": "article-0", "limit": 5}}],
        "rankings": {"case-a": {"tfidf": ["article-7", "article-6"]}},
    })

    class Response:
        def __init__(self, page):
            self.page = page

        def __enter__(self):
            import io
            return io.StringIO(json.dumps(self.page))

        def __exit__(self, *_):
            pass

    requests = []

    def open_response(request, **kwargs):
        assert kwargs["timeout"] == 10
        payload = json.loads(request.data)
        requests.append(payload)
        return Response({
            "snapshot_id": "unit-index", "method": payload["method"],
            "items": [{"id": "article-2"}], "unavailable_ids": [],
        })

    monkeypatch.setattr(evaluate, "urlopen", open_response)
    result = evaluate.api_latency(index_dir, api_url="http://unit.test")
    assert len(requests) == 309 and result["methods"]["neural"]["requests"] == 100
    assert requests[0]["viewed"] == ["article-7", "article-6"]
    assert (index_dir / "api-latency.json").is_file()
    monkeypatch.setattr(evaluate, "urlopen", lambda *_args, **_kwargs: Response({
        "snapshot_id": "wrong", "method": "neural", "items": [], "unavailable_ids": [],
    }))
    with pytest.raises(ValueError, match="different edition"):
        evaluate.api_latency(index_dir)


def test_baseline_and_one_epoch_keras_round_trip(tmp_path):
    directory = tmp_path / "tiny-training"
    rng = np.random.default_rng(5)
    vocabulary = [f"term{number}" for number in range(80)]
    rows = [{
        "id": f"article-{i:03}", "title": f"Research study number {i}",
        "text": " ".join(rng.choice(vocabulary, size=20, replace=False)),
        "publisher": f"Publisher {i % 4}", "source_name": "Test",
        "url": f"https://example.test/{i}", "normalized_url": f"https://example.test/{i}",
        "content_hash": str(i), "published_at": f"2026-08-{i % 28 + 1:02}T00:00:00+00:00",
        "collected_at": f"2026-08-{i % 28 + 1:02}T00:00:00+00:00",
        "display_text": "An explicitly synthetic training check.", "display_kind": "Excerpt",
        "text_kind": "body",
        "categories": ["THIS_LABEL_MUST_NOT_TRAIN"],
    } for i in range(120)]
    save_documents(directory, rows)
    base = model.baseline(directory, dimensions=12)
    assert base["svd_dimensions"] == 12
    trained = model.train(directory, epochs=1)
    assert trained["epochs"] == 1 and trained["parameters"] > 0
    index = Index(directory)
    assert index.recommend({"seed_id": rows[0]["id"]})["items"]
    import joblib
    import tensorflow as tf

    assert "this_label_must_not_train" not in joblib.load(directory / "preprocessing.joblib")["tfidf"].vocabulary_
    encoder = tf.keras.models.load_model(directory / "encoder.keras", compile=False)
    inputs = np.load(directory / "inputs.npy")
    center = np.load(directory / "latent_center.npy")
    reproduced = normalize(encoder(inputs[:3], training=False).numpy() - center)
    np.testing.assert_allclose(reproduced, index.matrices["neural"][:3], atol=1e-5)
    groups = data.read_json(directory / "groups.json")
    mask = np.load(directory / "train.npy")
    assert not set(np.array(groups)[mask]) & set(np.array(groups)[~mask])
