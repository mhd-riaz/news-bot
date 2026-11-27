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
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import yaml
from pymongo import DESCENDING
from pymongo.collection import Collection
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from newsml import admit, annotate, clean, neardup
from newsml.labels import Taxonomy, from_categories, from_feed, from_publisher
from newsml.load import Article, _to_article

ML_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ML_ROOT.parent
DATA_ROOT = ML_ROOT / "artifacts" / "v4"
MODELS_ROOT = ML_ROOT / "models" / "classifier"
TAXONOMY_PATH = ML_ROOT / "taxonomy.yaml"
SOURCES_PATH = REPO_ROOT / "collector" / "configs" / "sources.yaml"
# The old label rounds left the working tree in R3 (roadmap D21). They stay in git history
# at tag `before-restructure`; old_gold_ids() refuses to export new candidates without them.
OLD_LABELS_ROOTS = (
    REPO_ROOT / "collector" / "ml" / "data" / "labels",
    REPO_ROOT / "collector" / "ml-v2" / "data" / "labels",
)
PROPOSALS_ROOT = DATA_ROOT / "proposals"
AGENT_METHOD = "ai-agent-mcp-v1"
# Agent confidence as a sampling score, so `_choose` still mixes sure and unsure picks.
CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}
WEAK_LABELS = "weak-labels.jsonl"

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
        raise FileNotFoundError(
            f"prior-gold exclusion file is missing: {first} "
            "(removed in R3; restore the old label rounds from git tag before-restructure)"
        )
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


def prior_documents(data_root: Path = DATA_ROOT) -> tuple[list[dict[str, Any]], frozenset[str]]:
    """Earlier V4 candidates rebuilt from their sheets, plus the IDs they have today.

    The sheets hold exactly the exported text, so a later round can exclude the same
    stories and content hashes even when the database the earlier round came from is
    gone. `current-ids.jsonl`, written by the export-verified import, adds the IDs those
    articles carry in today's database.
    """
    root = data_root.resolve()
    documents: list[dict[str, Any]] = []
    current: set[str] = set()
    for selection_path in sorted(data_root.glob("*/selection.jsonl")):
        run = selection_path.parent
        paths = [selection_path, *sorted(run.glob("*.csv")), run / "current-ids.jsonl"]
        if any(path.exists() and not path.resolve().is_relative_to(root) for path in paths):
            raise ValueError("a prior candidate file points outside the private data directory")
        hashes = {
            str(record.get("article_id")): str(record.get("content_hash") or "")
            for _, _, record in _records((selection_path,))
        }
        for article_id, (title, summary) in annotate.read_sheet_texts(sorted(run.glob("*.csv"))).items():
            documents.append({
                "_id": article_id,
                "title": unescape_cell(title),
                "summary": unescape_cell(summary),
                "content_hash": hashes.get(article_id, ""),
            })
        if (run / "current-ids.jsonl").is_file():
            for path, number, record in _records((run / "current-ids.jsonl",)):
                current_id = record.get("current_id")
                if not isinstance(current_id, str) or not current_id:
                    raise ValueError(f"{path}:{number}: invalid current_id")
                current.add(current_id)
    return documents, frozenset(current)


@dataclass(frozen=True)
class Proposal:
    """One AI-agent judgement: the class it gave an article, how sure, and what it sought."""

    topic: str
    confidence: str
    target: str


def load_proposals(directory: Path, taxonomy: Taxonomy) -> tuple[dict[str, Proposal], dict[str, Any]]:
    """AI-agent class judgements from `*.jsonl` files, plus provenance for the manifest.

    An article judged twice with different classes is dropped, because the agents
    disagree and neither class is a usable weak label. Repeats of the same class keep
    the most confident judgement.
    """
    root = PROPOSALS_ROOT.resolve()
    if not directory.resolve().is_relative_to(root) or not directory.is_dir():
        raise ValueError(f"proposals must be a directory inside {PROPOSALS_ROOT}")
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        raise ValueError(f"{directory}: no proposal files")
    if any(not path.resolve().is_relative_to(root) for path in paths):
        raise ValueError("a proposal file points outside the private proposals directory")
    allowed = taxonomy.ids | {taxonomy.unsorted}
    kept: dict[str, Proposal] = {}
    disputed: set[str] = set()
    judgements = 0
    for path, number, record in _records(paths):
        article_id = record.get("article_id")
        topic, confidence, target = (record.get(key) for key in ("topic", "confidence", "target"))
        if (
            not isinstance(article_id, str)
            or not article_id
            or topic not in allowed
            or confidence not in CONFIDENCE
            or target not in taxonomy.ids
        ):
            raise ValueError(
                f"{path}:{number}: expected article_id, a taxonomy topic, "
                "confidence high/medium/low and a target class"
            )
        judgements += 1
        previous = kept.get(article_id)
        if previous is not None and previous.topic != topic:
            disputed.add(article_id)
        elif previous is None or CONFIDENCE[confidence] > CONFIDENCE[previous.confidence]:
            kept[article_id] = Proposal(topic, confidence, target)
    for article_id in disputed:
        kept.pop(article_id, None)
    provenance = {
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "judgements": judgements,
        "articles": len(kept),
        "disputed_dropped": len(disputed),
        "topics": dict(sorted(Counter(p.topic for p in kept.values()).items())),
    }
    return kept, provenance


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
    topics: Mapping[str, tuple[str, float | None, str]] | None = None,
) -> Sample:
    """Choose candidates per class from `documents`.

    `topics` replaces the TF-IDF provisional topic with judgements made elsewhere, such
    as the AI agents of a later round; articles it does not cover are skipped. Every
    eligibility, exclusion and diversity rule applies either way.
    """
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
    if topics is None:
        inferred = provisional_topics(admitted, taxonomy)
    else:
        inferred = {
            row.article.id: topics[row.article.id]
            for row in admitted
            if row.article.id in topics and topics[row.article.id][0] in taxonomy.ids
        }
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
    prior_docs: Sequence[dict[str, Any]] = (),
) -> Sample:
    """Scan recent articles and sample them by TF-IDF provisional topic.

    `prior_docs` are earlier V4 rounds rebuilt from their sheets (`prior_documents`):
    their stories and content hashes are excluded like old gold, but only documents of
    the older gold actually found in the database count as `old_documents_found`.
    """
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
    old = _read_old(collection, old_ids)
    result = sample_documents(
        taxonomy,
        old_documents=[*old, *prior_docs],
        documents=documents,
        cut=cut,
        per_class=per_class,
        seed=seed,
        old_ids=old_ids,
        source_ids=source_ids,
        confirmed=confirmed,
        prior_candidates=prior_candidates,
    )
    return replace(result, old_documents_found=len(old))


def sample_proposals(
    collection: Collection[dict[str, Any]],
    taxonomy: Taxonomy,
    *,
    proposals: Mapping[str, Proposal],
    start: datetime,
    cut: datetime,
    per_class: int,
    seed: int,
    old_ids: frozenset[str],
    source_ids: frozenset[str],
    confirmed: dict[str, str],
    prior_candidates: frozenset[str],
    prior_docs: Sequence[dict[str, Any]],
) -> Sample:
    """Like `sample`, but each article's class comes from an AI-agent judgement.

    Only proposed articles collected in [start, cut) are read. Earlier rounds are
    excluded by ID, by content hash and by near-duplicate story through `prior_docs`.
    """
    if start.tzinfo is None or cut.tzinfo is None or start >= cut:
        raise ValueError("start must be timezone-aware and before the cut")
    topics = {
        article_id: (proposal.topic, CONFIDENCE[proposal.confidence], AGENT_METHOD)
        for article_id, proposal in proposals.items()
        if proposal.topic in taxonomy.ids
    }
    ids = sorted(topics)
    documents: list[dict[str, Any]] = []
    for offset in range(0, len(ids), 200):
        cursor = collection.find(
            {"_id": {"$in": ids[offset:offset + 200]}, "collected_at": {"$gte": start, "$lt": cut}},
            PROJECTION,
            batch_size=128,
            max_time_ms=30_000,
        )
        try:
            documents.extend(cursor)
        finally:
            cursor.close()
    old = _read_old(collection, old_ids)
    result = sample_documents(
        taxonomy,
        old_documents=[*old, *prior_docs],
        documents=documents,
        cut=cut,
        per_class=per_class,
        seed=seed,
        old_ids=old_ids,
        source_ids=source_ids,
        confirmed=confirmed,
        prior_candidates=prior_candidates,
        topics=topics,
    )
    skipped = dict(result.skipped)
    skipped["proposal_unsorted"] = len(proposals) - len(ids)
    skipped["proposal_outside_window_or_missing"] = len(ids) - len(documents)
    return replace(result, skipped=skipped, old_documents_found=len(old))


def write_weak_labels(
    run: Path, selected: Sequence[Candidate], proposals: Mapping[str, Proposal], taxonomy: Taxonomy
) -> Path:
    """AI-agent labels for selected candidates, separate from imported reference sheets."""
    path = run / WEAK_LABELS
    with path.open("x", encoding="utf-8") as handle:
        for candidate in sorted(selected, key=lambda c: c.article.id):
            proposal = proposals[candidate.article.id]
            handle.write(json.dumps({
                "article_id": candidate.article.id,
                "topic": candidate.topic,
                "confidence": proposal.confidence,
                "target": proposal.target,
                "label_source": "ai-agent",
                "method": AGENT_METHOD,
                "taxonomy_version": taxonomy.version,
            }, sort_keys=True) + "\n")
    return path


FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_cell(value: str) -> str:
    return "'" + value if value.lstrip().startswith(FORMULA_PREFIXES) else value


def unescape_cell(value: str) -> str:
    """Undo `safe_cell`, and only where it added the apostrophe."""
    if value.startswith("'") and value[1:].lstrip().startswith(FORMULA_PREFIXES):
        return value[1:]
    return value


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
    extra: Mapping[str, Any] | None = None,
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
        if clash := set(extra or {}) & set(manifest):
            raise ValueError(f"extra manifest fields would overwrite {sorted(clash)}")
        manifest.update(extra or {})
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return [output / sheet.name for sheet in sheets]
