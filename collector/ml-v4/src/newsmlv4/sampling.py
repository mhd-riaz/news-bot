from __future__ import annotations

import hashlib
import json
import math
import random
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import yaml
from pymongo import DESCENDING
from pymongo.collection import Collection
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from newsml import admit, annotate, clean, neardup
from newsml.labels import Taxonomy, from_categories, from_feed, from_publisher
from newsml.load import Article, _to_article

COLLECTOR_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = COLLECTOR_ROOT / "ml-v4" / "data"
TAXONOMY_PATH = COLLECTOR_ROOT / "ml" / "taxonomy.yaml"
SOURCES_PATH = COLLECTOR_ROOT / "configs" / "sources.yaml"
OLD_LABELS_ROOTS = (
    COLLECTOR_ROOT / "ml" / "data" / "labels",
    COLLECTOR_ROOT / "ml-v2" / "data" / "labels",
)

PROJECTION = {
    key: 1
    for key in (
        "_id",
        "source_id",
        "source_name",
        "canonical_url",
        "url",
        "title",
        "summary",
        "categories",
        "clean_summary",
        "content_hash",
        "language",
        "detected_language",
        "country",
        "published_at",
        "collected_at",
        "processing_status",
        "scrape_status",
    )
}


@dataclass(frozen=True)
class Candidate:
    article: Article
    topic: str
    sampling_score: float | None
    sampling_method: str


@dataclass(frozen=True)
class Sample:
    selected: tuple[Candidate, ...]
    scanned: dict[str, int]
    eligible: dict[str, int]
    quotas: dict[str, int]
    old_ids: int
    old_documents_found: int
    rejected: int
    skipped: dict[str, int]
    sampling_methods: dict[str, int]
    queried: int = 0

    def counts(self) -> dict[str, dict[str, int]]:
        return {
            topic: {
                "scanned": self.scanned[topic],
                "eligible": self.eligible[topic],
                "selected": sum(c.topic == topic for c in self.selected),
                "shortfall": self.quotas[topic] - sum(c.topic == topic for c in self.selected),
            }
            for topic in self.quotas
        }


def approved_feed_urls(path: Path = SOURCES_PATH) -> frozenset[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"{path}: expected a sources list")
    urls: set[str] = set()
    for source in data["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("name"), str):
            raise ValueError(f"{path}: invalid source entry")
        feed_url = source.get("feed_url")
        if not isinstance(feed_url, str):
            raise ValueError(f"{path}: source has no feed URL")
        host = urlsplit(feed_url).hostname
        if host is None:
            raise ValueError(f"{path}: source has an invalid feed URL")
        if host == "medium.com" or host.endswith(".medium.com"):
            continue
        urls.add(feed_url)
    return frozenset(urls)


def approved_source_ids(
    collection: Collection[dict[str, Any]], feed_urls: frozenset[str]
) -> frozenset[str]:
    cursor = collection.find(
        {"feed_url": {"$in": sorted(feed_urls)}},
        {"_id": 1, "feed_url": 1, "added_by": 1},
        batch_size=128,
        max_time_ms=30_000,
    )
    try:
        return frozenset(
            str(doc["_id"])
            for doc in cursor
            if doc.get("feed_url") in feed_urls and not doc.get("added_by")
        )
    finally:
        cursor.close()


def _records(paths: Iterable[Path]) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number}: invalid JSON") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"{path}:{number}: expected an object")
                yield path, number, record


def old_gold_ids() -> frozenset[str]:
    first = OLD_LABELS_ROOTS[0] / "gold-combined.jsonl"
    if not first.is_file():
        raise FileNotFoundError(f"prior-gold exclusion file is missing: {first}")
    paths = {first}
    for root in OLD_LABELS_ROOTS:
        paths.update(root.rglob("gold.jsonl"))
    roots = tuple(root.resolve() for root in OLD_LABELS_ROOTS)
    if any(not any(path.resolve().is_relative_to(root) for root in roots) for path in paths):
        raise ValueError("a prior gold file points outside the known label directories")
    ids: set[str] = set()
    for path, number, record in _records(sorted(paths)):
        article_id = record.get("article_id")
        if not isinstance(article_id, str) or not article_id:
            raise ValueError(f"{path}:{number}: invalid article_id")
        ids.add(article_id)
    return frozenset(ids)


def reviewed_labels(paths: Iterable[Path], taxonomy: Taxonomy) -> dict[str, str]:
    labels: dict[str, str] = {}
    for source, number, record in _records(paths):
        article_id, topic = record.get("article_id"), record.get("topic")
        if (
            not isinstance(article_id, str)
            or not article_id
            or not isinstance(topic, str)
            or topic not in taxonomy.ids | {taxonomy.unsorted}
            or record.get("label_source") != "human"
            or record.get("taxonomy_version") != taxonomy.version
        ):
            raise ValueError(f"{source}:{number}: expected a human label in the current taxonomy")
        if article_id in labels and labels[article_id] != topic:
            raise ValueError(f"{source}:{number}: conflicting labels for {article_id}")
        labels[article_id] = topic
    return labels


def prior_candidate_ids(data_root: Path = DATA_ROOT) -> frozenset[str]:
    ids: set[str] = set()
    paths = sorted(data_root.glob("*/selection.jsonl"))
    if any(not path.resolve().is_relative_to(data_root.resolve()) for path in paths):
        raise ValueError("a prior selection file points outside the private data directory")
    for path, number, record in _records(paths):
        article_id = record.get("article_id")
        if not isinstance(article_id, str) or not article_id:
            raise ValueError(f"{path}:{number}: invalid article_id")
        ids.add(article_id)
    return frozenset(ids)


def _article(doc: dict[str, Any]) -> Article:
    prepared = dict(doc)
    if not prepared.get("summary"):
        prepared["summary"] = prepared.get("clean_summary", "")
    return _to_article(prepared)


def _read_old(
    collection: Collection[dict[str, Any]], old_ids: frozenset[str]
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    ordered = sorted(old_ids)
    for offset in range(0, len(ordered), 200):
        cursor = collection.find(
            {"_id": {"$in": ordered[offset : offset + 200]}},
            PROJECTION,
            batch_size=128,
            max_time_ms=30_000,
        )
        try:
            documents.extend(cursor)
        finally:
            cursor.close()
    return documents


def provisional_topics(
    rows: Sequence[admit.Admitted], taxonomy: Taxonomy
) -> dict[str, tuple[str, float | None, str]]:
    if not rows:
        return {}
    classes = sorted(taxonomy.classes, key=lambda item: item.id)
    profiles = [
        clean.clean(
            f"{item.id.replace('_', ' ')} {item.description} {' '.join(map(str, item.iptc))}"
        ).text
        for item in classes
    ]
    vectorizer = TfidfVectorizer(
        stop_words="english", ngram_range=(1, 2), max_features=40_000
    )
    vectors = vectorizer.fit_transform(
        [row.cleaned.text for row in rows] + profiles
    )
    scores = cosine_similarity(vectors[:len(rows)], vectors[len(rows):])
    index = {item.id: number for number, item in enumerate(classes)}
    inferred: dict[str, tuple[str, float | None, str]] = {}
    for row, similarities in zip(rows, scores):
        article = row.article
        hints = (
            from_feed(article, taxonomy),
            from_categories(article, taxonomy),
            from_publisher(article, taxonomy),
        )
        hinted = next(
            (hint.topic for hint in hints
             if hint is not None
             and hint.topic in index
             and similarities[index[hint.topic]] > 0),
            None,
        )
        best = classes[int(similarities.argmax())].id if similarities.max() > 0 else None
        topic = hinted or best or next(
            (hint.topic for hint in hints if hint is not None and hint.topic in index),
            None,
        )
        if topic is not None:
            similarity = float(similarities[index[topic]])
            inferred[article.id] = (
                topic,
                similarity if similarity > 0 else None,
                "taxonomy-tfidf-v1" if similarity > 0 else "taxonomy-hint-only",
            )
    return inferred


def _choose(
    pools: dict[str, list[Candidate]],
    quotas: dict[str, int],
    group_of: dict[str, str],
    old_groups: set[str],
    old_hashes: set[str],
    seed: int,
) -> tuple[Candidate, ...]:
    selected: list[Candidate] = []
    used_groups = set(old_groups)
    used_hashes = set(old_hashes)
    for topic in sorted(quotas, key=lambda value: (len(pools[value]), value)):
        quota = quotas[topic]
        if not quota:
            continue
        rng = random.Random(f"{seed}:{topic}")
        pool = sorted(pools[topic], key=lambda c: c.article.id)
        rng.shuffle(pool)
        uncertain = sorted(
            pool, key=lambda c: (c.sampling_score is None, c.sampling_score or 0)
        )
        typical = sorted(
            pool, key=lambda c: (c.sampling_score is None, -(c.sampling_score or 0))
        )
        random_count = round(quota * 0.15)
        uncertain_count = (quota - random_count) // 2
        phases = (
            (pool, random_count),
            (uncertain, uncertain_count),
            (typical, quota - random_count - uncertain_count),
        )
        source_counts: Counter[str] = Counter()
        month_counts: Counter[str] = Counter()
        picked: set[str] = set()

        def take(items: list[Candidate], target: int, diverse: bool) -> None:
            taken = 0
            for candidate in items:
                if taken >= target or len(picked) >= quota:
                    break
                article = candidate.article
                root = group_of[article.id]
                if (
                    article.id in picked
                    or root in used_groups
                    or (article.content_hash and article.content_hash in used_hashes)
                ):
                    continue
                month = article.collected_at.strftime("%Y-%m")
                if diverse and (
                    source_counts[article.source_name] >= max(1, math.ceil(quota / 5))
                    or month_counts[month] >= max(1, math.ceil(quota / 2))
                ):
                    continue
                selected.append(candidate)
                picked.add(article.id)
                used_groups.add(root)
                if article.content_hash:
                    used_hashes.add(article.content_hash)
                source_counts[article.source_name] += 1
                month_counts[month] += 1
                taken += 1

        for ordering, target in phases:
            take(ordering, target, diverse=True)
        if len(picked) < quota:
            take(pool, quota - len(picked), diverse=False)
    return tuple(sorted(selected, key=lambda c: c.article.id))


def sample_documents(
    taxonomy: Taxonomy,
    *,
    old_documents: Sequence[dict[str, Any]],
    documents: Sequence[dict[str, Any]],
    cut: datetime,
    per_class: int,
    seed: int,
    old_ids: frozenset[str],
    source_ids: frozenset[str],
    confirmed: dict[str, str] | None = None,
    prior_candidates: frozenset[str] = frozenset(),
) -> Sample:
    if per_class < 1 or cut.tzinfo is None:
        raise ValueError("per_class must be positive and cut timezone-aware")
    if not source_ids:
        raise ValueError("no approved shipped source IDs in the local database")
    confirmed = confirmed or {}
    quotas = {
        topic: max(0, per_class - sum(label == topic for label in confirmed.values()))
        for topic in sorted(taxonomy.ids)
    }
    old_texts: dict[str, str] = {}
    old_hashes: set[str] = set()
    for doc in old_documents:
        article = _article(doc)
        if article.content_hash:
            old_hashes.add(article.content_hash)
        if article.title and article.summary:
            old_texts[article.id] = clean.clean(article.text("title_summary")).text
    excluded = set(old_ids) | set(prior_candidates) | set(confirmed)
    scanned: dict[str, int] = dict.fromkeys(quotas, 0)
    skipped: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    raw: dict[str, Article] = {}
    for doc in documents:
        article = _article(doc)
        if article.source_id not in source_ids:
            skipped["unapproved_source"] += 1
            continue
        if article.collected_at >= cut:
            skipped["after_cut"] += 1
            continue
        if article.id in excluded:
            skipped["prior_id"] += 1
            continue
        if article.content_hash and article.content_hash in old_hashes:
            skipped["prior_content_hash"] += 1
            continue
        if doc.get("detected_language") not in (None, "", "en"):
            skipped["non_english"] += 1
            continue
        if not article.title or not article.summary:
            skipped["no_title_or_lede"] += 1
            continue
        raw[article.id] = article
    pairs = [
        (article, clean.clean(article.text("title_summary")))
        for article in raw.values()
    ]
    admitted, rejected = admit.partition(pairs, now=cut, check_language=True)
    inferred = provisional_topics(admitted, taxonomy)
    texts = dict(old_texts)
    texts.update({row.article.id: row.cleaned.text for row in admitted})
    grouping = neardup.group(texts)
    old_groups = {grouping.group_of[article_id] for article_id in old_texts}
    pools: dict[str, list[Candidate]] = {topic: [] for topic in quotas}
    for row in admitted:
        article_id = row.article.id
        if article_id not in inferred:
            skipped["no_provisional_topic"] += 1
            continue
        topic, score, method = inferred[article_id]
        scanned[topic] += 1
        versions[method] += 1
        if grouping.group_of[article_id] in old_groups:
            skipped["prior_near_duplicate"] += 1
            continue
        pools[topic].append(Candidate(row.article, topic, score, method))
    selected = _choose(
        pools, quotas, grouping.group_of, old_groups, old_hashes, seed
    )
    return Sample(
        selected,
        scanned,
        {topic: len(pool) for topic, pool in pools.items()},
        quotas,
        len(old_ids),
        len(old_documents),
        len(rejected),
        dict(skipped),
        dict(versions),
        len(documents),
    )


def sample(
    collection: Collection[dict[str, Any]],
    taxonomy: Taxonomy,
    *,
    cut: datetime,
    per_class: int,
    scan_limit: int,
    seed: int,
    old_ids: frozenset[str],
    source_ids: frozenset[str],
    confirmed: dict[str, str] | None = None,
    prior_candidates: frozenset[str] = frozenset(),
) -> Sample:
    if scan_limit < per_class or per_class < 1 or cut.tzinfo is None:
        raise ValueError("scan_limit must be at least a positive per_class and cut timezone-aware")
    if not source_ids:
        raise ValueError("no approved shipped source IDs in the local database")
    cursor = collection.find(
        {
            "source_id": {"$in": sorted(source_ids)},
            "collected_at": {"$lt": cut},
        },
        PROJECTION,
        batch_size=128,
        max_time_ms=30_000,
    ).sort([("collected_at", DESCENDING), ("_id", DESCENDING)]).limit(scan_limit)
    try:
        documents = list(cursor)
    finally:
        cursor.close()
    return sample_documents(
        taxonomy,
        old_documents=_read_old(collection, old_ids),
        documents=documents,
        cut=cut,
        per_class=per_class,
        seed=seed,
        old_ids=old_ids,
        source_ids=source_ids,
        confirmed=confirmed,
        prior_candidates=prior_candidates,
    )


def safe_cell(value: str) -> str:
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def write_sample(
    sample_data: Sample,
    out: Path,
    *,
    cut: datetime,
    seed: int,
    per_class: int,
    scan_limit: int,
    taxonomy: Taxonomy,
    shards: int = 4,
    overlap: int = 20,
) -> list[Path]:
    if not sample_data.selected:
        raise ValueError("no eligible new candidates; inspect the reported class shortages")
    if shards < 1 or overlap < 0:
        raise ValueError("shards must be positive and overlap nonnegative")
    output = out.resolve()
    if not output.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError(f"output must be inside {DATA_ROOT}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".v4-", dir=output.parent) as temp:
        stage = Path(temp)
        articles = [
            replace(c.article, title=safe_cell(c.article.title),
                    summary=safe_cell(c.article.summary))
            for c in sample_data.selected
        ]
        sheets = annotate.write_sheets(articles, stage, shards=shards,
                                       overlap=overlap, seed=seed)
        with (stage / "selection.jsonl").open("w", encoding="utf-8") as handle:
            for candidate, article in zip(sample_data.selected, articles):
                handle.write(json.dumps({
                    "article_id": candidate.article.id,
                    "predicted_topic": candidate.topic,
                    "sampling_score": candidate.sampling_score,
                    "sampling_method": candidate.sampling_method,
                    "content_hash": candidate.article.content_hash,
                    "sheet_text_sha256": hashlib.sha256(
                        (article.title + "\n" + article.lede).encode("utf-8")
                    ).hexdigest(),
                }, sort_keys=True) + "\n")
        manifest = {
            "cut": cut.isoformat(),
            "taxonomy_version": taxonomy.version,
            "taxonomy_sha256": hashlib.sha256(TAXONOMY_PATH.read_bytes()).hexdigest(),
            "sources_sha256": hashlib.sha256(SOURCES_PATH.read_bytes()).hexdigest(),
            "seed": seed,
            "per_class": per_class,
            "scan_limit_total": scan_limit,
            "queried": sample_data.queried,
            "scan_cap_reached": sample_data.queried >= scan_limit,
            "prior_gold_ids": sample_data.old_ids,
            "prior_gold_documents_found": sample_data.old_documents_found,
            "admission_rejections": sample_data.rejected,
            "skipped": sample_data.skipped,
            "sampling_methods_in_pool": sample_data.sampling_methods,
            "counts": sample_data.counts(),
            "selected_digest": hashlib.sha256(
                "\n".join(c.article.id for c in sample_data.selected).encode("utf-8")
            ).hexdigest(),
            "status": "unlabeled_candidates_not_gold",
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return [output / sheet.name for sheet in sheets]
