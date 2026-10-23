"""Same-case comparisons, bounded latency checks and blind relevance-judgement sheets."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pyarrow.parquet as pq

from .data import SEED, digest, read_json, write_json
from .index import METHODS, Index


def api_latency(directory: Path, *, api_url: str = "http://127.0.0.1:8090") -> dict:
    """Measure the real Go/Mongo path on the frozen cases and assert retrieval exclusions."""
    from newsmlv2 import config

    index = Index(directory)
    evaluation = read_json(directory / "evaluation-cases.json")
    cases = evaluation["cases"]
    values = config.env_values(Path(os.environ.get("NEWS_ENV_FILE", config.DOTENV_PATH)))
    keys = os.environ.get("NEWS_AUTH_API_KEYS", values.get("NEWS_AUTH_API_KEYS", ""))
    header_name = os.environ.get("NEWS_AUTH_API_KEY_HEADER", "X-API-Key")
    headers = {"Content-Type": "application/json"}
    if keys:
        headers[header_name] = keys.split(",")[0].strip()
    results = {}
    for method in METHODS:
        samples = []
        for number in range(103):
            case = cases[number % len(cases)]
            payload = {**case["request"], "method": method}
            payload["viewed"] = evaluation["rankings"][case["id"]]["tfidf"][:2]
            body = json.dumps(payload).encode()
            request = Request(api_url.rstrip("/") + "/api/v1/recommendations", data=body, headers=headers)
            started = time.perf_counter()
            with urlopen(request, timeout=10) as response:
                page = json.load(response)
            elapsed = (time.perf_counter() - started) * 1000
            if page["snapshot_id"] != index.manifest["snapshot_id"] or page["method"] != method:
                raise ValueError("the live API is serving a different edition or method")
            blocked = set(payload.get("liked", []) + payload.get("disliked", []) + payload.get("viewed", []))
            if payload.get("seed_id"):
                blocked.add(payload["seed_id"])
            blocked_groups = {index.groups[index.positions[value]] for value in blocked if value in index.positions}
            groups = [index.groups[index.positions[item["id"]]] for item in page["items"]]
            if len(groups) != len(set(groups)) or set(groups) & blocked_groups:
                raise ValueError("live API returned self, duplicate, selected or viewed articles")
            if page["unavailable_ids"]:
                raise ValueError("some indexed Mongo records are missing; rebuild before measuring")
            if number >= 3:
                samples.append(elapsed)
        results[method] = {
            "requests": len(samples),
            "p50_ms": round(float(np.percentile(samples, 50)), 2),
            "p95_ms": round(float(np.percentile(samples, 95)), 2),
            "p95_under_500_ms": float(np.percentile(samples, 95)) < 500,
        }
    result = {
        "snapshot_id": index.manifest["snapshot_id"],
        "scope": "warm loopback Go API + Python retrieval + original MongoDB batch hydration",
        "methods": results, "exclusion_checks": "passed on all 309 requests",
    }
    write_json(directory / "api-latency.json", result)
    return result


def benchmark(directory: Path, *, queries: int = 40) -> dict:
    if not 4 <= queries <= 200:
        raise ValueError("queries must be between 4 and 200")
    sheet = directory / "judgements.jsonl"
    if sheet.exists():
        raise FileExistsError("judgements.jsonl already exists; preserve completed judgements")
    index = Index(directory)
    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(index.rows))
    short = [i for i in order if index.rows[int(i)]["text_kind"] == "headline"][:5]
    seeds = list(dict.fromkeys(short + [int(i) for i in order]))[:queries * 3 // 4]
    cases = [
        {"id": f"article-{number:02}", "request": {"seed_id": index.rows[i]["id"], "limit": 5}}
        for number, i in enumerate(seeds)
    ]
    for number in range(queries - len(cases)):
        positions = rng.choice(len(index.rows), size=3, replace=False)
        cases.append({
            "id": f"interests-{number:02}",
            "request": {"liked": [index.rows[int(i)]["id"] for i in positions], "limit": 5},
        })
    rankings = {}
    samples = {method: [] for method in METHODS}
    diversity = {method: [] for method in METHODS}
    judgements = []
    for case in cases:
        ranked = {}
        for method in METHODS:
            started = time.perf_counter()
            page = index.recommend({**case["request"], "method": method})
            samples[method].append((time.perf_counter() - started) * 1000)
            ranked[method] = [item["id"] for item in page["items"]]
            diversity[method].append(len({
                index.rows[index.positions[article_id]]["publisher"] for article_id in ranked[method]
            }))
        rankings[case["id"]] = ranked
        pool = sorted(set(article_id for values in ranked.values() for article_id in values))
        rng.shuffle(pool)
        interests = case["request"].get("liked", [case["request"].get("seed_id")])
        for article_id in pool:
            row = index.rows[index.positions[article_id]]
            judgements.append({
                "case_id": case["id"], "article_id": article_id, "grade": None,
                "interest_titles": [index.rows[index.positions[value]]["title"] for value in interests],
                "candidate_title": row["title"], "candidate_text": row["display_text"],
                "source": row["source_name"], "url": row["url"],
            })
    # One request at a time; only O(N) query scores, never O(N^2) cached similarities.
    for number in range(100):
        for method in METHODS:
            started = time.perf_counter()
            index.recommend({**cases[number % len(cases)]["request"], "method": method})
            samples[method].append((time.perf_counter() - started) * 1000)
    write_json(directory / "evaluation-cases.json", {
        "documents_sha256": index.manifest["documents_sha256"],
        "training_sha256": digest(directory / "training.json"),
        "retrieval_sha256": digest(Path(__file__).with_name("index.py")),
        "cases": cases, "rankings": rankings,
    })
    with sheet.open("w", encoding="utf-8") as stream:
        for row in judgements:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
    result = {
        "snapshot_id": index.manifest["snapshot_id"], "cases": len(cases),
        "judgement_pairs": len(judgements), "human_relevance": "pending independent judgement",
        "latency_scope": "warm Python retrieval only, not Go/Mongo/network",
        "methods": {
            method: {
                "requests": len(samples[method]),
                "p50_ms": round(float(np.percentile(samples[method], 50)), 2),
                "p95_ms": round(float(np.percentile(samples[method], 95)), 2),
                "mean_publishers_at_5": round(float(np.mean(diversity[method])), 2),
            } for method in METHODS
        },
    }
    result["category_proxy"] = category_proxy(index)
    write_json(directory / "benchmark.json", result)
    return result


def category_proxy(index: Index) -> dict:
    """Old training labels only; same-category agreement is NOT recommendation ground truth."""
    from newsmlv2.config import SNAPSHOT_DIR

    frame = pq.read_table(
        SNAPSHOT_DIR / "v2-001" / "articles.parquet",
        columns=["article_id", "topic"], filters=[("split", "=", "train")],
    ).to_pandas()
    labels = {
        row.article_id: row.topic for row in frame.itertuples()
        if isinstance(row.topic, str) and row.topic != "unsorted" and row.article_id in index.positions
    }
    ids = sorted(labels)
    if len(ids) < 6:
        return {"status": "not enough overlapping old training labels", "articles": len(ids)}
    positions = [index.positions[article_id] for article_id in ids]
    rng = np.random.default_rng(SEED)
    queries = rng.choice(len(ids), min(100, len(ids)), replace=False)
    results = {}
    for method in METHODS:
        matrix = index.matrices[method][positions]
        scores = []
        for i in queries:
            query = matrix[int(i)]
            values = (
                (matrix @ query.T).toarray().ravel() if hasattr(matrix, "tocsr")
                else matrix @ query
            )
            group = index.groups[positions[int(i)]]
            values[[j for j, position in enumerate(positions) if index.groups[position] == group]] = -np.inf
            top = np.argsort(-values)[:5]
            scores.append(sum(labels[ids[int(j)]] == labels[ids[int(i)]] for j in top) / 5)
        results[method] = round(float(np.mean(scores)), 4)
    return {
        "scope": "restricted to overlapping labelled articles from OLD TRAIN split; no old test labels",
        "warning": "Category agreement is a coarse proxy, not human relevance or preference prediction.",
        "articles": len(ids), "queries": len(queries), "same_category_at_5": results,
    }


def score(directory: Path, sheet: Path, *, case_ids: list[str] | None = None) -> dict:
    cases = read_json(directory / "evaluation-cases.json")
    if cases["documents_sha256"] != digest(directory / "documents.jsonl"):
        raise ValueError("evaluation cases belong to a different snapshot")
    if cases["training_sha256"] != digest(directory / "training.json") or cases["retrieval_sha256"] != digest(
        Path(__file__).with_name("index.py")
    ):
        raise ValueError("model or retrieval changed since the blind judgement pool was frozen")
    rows = [json.loads(line) for line in sheet.read_text(encoding="utf-8").splitlines()]
    selected = set(case_ids) if case_ids else set(cases["rankings"])
    if not selected or not selected <= set(cases["rankings"]):
        raise ValueError("selected judgement cases do not exist in the frozen evaluation")
    grades: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["case_id"] not in cases["rankings"]:
            raise ValueError("unknown judgement case")
        if row["case_id"] not in selected:
            continue
        if type(row["grade"]) is not int or row["grade"] not in (0, 1, 2):
            raise ValueError("every candidate needs an independent grade: 0, 1 or 2")
        case = grades.setdefault(row["case_id"], {})
        if row["article_id"] in case:
            raise ValueError("duplicate judgement pair")
        case[row["article_id"]] = row["grade"]
    results = {}
    for method in METHODS:
        precision, ndcg = [], []
        for case_id, ranking in cases["rankings"].items():
            if case_id not in selected:
                continue
            pool = grades.get(case_id, {})
            required = {value for values in ranking.values() for value in values}
            if set(pool) != required:
                raise ValueError(f"judgement pool is incomplete or changed for {case_id}")
            top = [pool[value] for value in ranking[method]]
            precision.append(sum(grade == 2 for grade in top) / 5)
            discounts = np.log2(np.arange(2, 7))
            gains = np.array([2 ** grade - 1 for grade in top])
            ideal = np.array(sorted((2 ** grade - 1 for grade in pool.values()), reverse=True)[:5])
            denominator = float(np.sum(ideal / discounts[:len(ideal)]))
            ndcg.append(float(np.sum(gains / discounts[:len(gains)])) / denominator if denominator else 0.0)
        results[method] = {
            "precision_at_5": round(float(np.mean(precision)), 4),
            "pooled_ndcg_at_5": round(float(np.mean(ndcg)), 4),
            "cases": len(precision),
            "total_cases": len(cases["rankings"]),
            "case_ids": sorted(selected),
        }
    write_json(directory / ("relevance-selected.json" if case_ids else "relevance.json"), results)
    return results
