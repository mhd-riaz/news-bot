"""Build a private, reproducible classifier corpus without falsifying label origins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sklearn.model_selection import train_test_split

from newsml import admit, clean, neardup
from newsml.annotate import read_sheet_texts
from newsml.config import CLEANING_VERSION
from newsml.labels import Taxonomy, load_taxonomy
from newsml.load import LEDE_CHARS, Article, _clip

from .sampling import (
    DATA_ROOT, MODELS_ROOT, PROPOSALS_ROOT, REPO_ROOT, SOURCES_PATH, TAXONOMY_PATH, WEAK_LABELS,
    _records, approved_feed_urls, load_proposals, unescape_cell,
)
from .verify import compare_sheets, load_selection, sheet_digest

# The legacy snapshots, label rounds and pair key this pool was built from left the
# working tree in R3 (roadmap D21). They stay in git history at tag `before-restructure`,
# which is the only place this builder can run again.
LEGACY_ROOT = REPO_ROOT / "collector" / "ml" / "data"
SNAPSHOTS = ("20260826-120", "20260825-121", "20260825-120-v3", "20260825-120")
ROUND1 = "v4-20261110T120557Z"
ROUND2 = "v4-20261121T000000Z"
PROPOSALS = "r2-20261121"
DECISION = "D16"
PER_CLASS_TARGET = 200
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "unknown": 2, "low": 3}


@dataclass(frozen=True, slots=True)
class Row:
    article_id: str
    topic: str
    title: str
    summary: str
    origins: tuple[str, ...]
    confidence: str = "unknown"
    aliases: frozenset[str] = frozenset()
    source_id: str = ""
    source_name: str = ""
    url: str = ""
    content_hash: str = ""
    published_at: datetime | None = None
    collected_at: datetime | None = None
    language: str = ""
    verified_export: bool = False
    text_evidence: str = ""
    problem: str = ""
    group_id: str = ""

    @property
    def text(self) -> str:
        return f"{self.title.strip()}\n{self.summary.strip()}"

    @property
    def ids(self) -> frozenset[str]:
        return self.aliases | {self.article_id}

    def record(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id, "topic": self.topic,
            "title": self.title, "summary": self.summary,
            "label_source": "ai-agent", "provenance_decision": DECISION,
            "taxonomy_version": 4, "confidence": self.confidence,
            "origins": list(self.origins), "aliases": sorted(self.ids),
            "group_id": self.group_id, "text_evidence": self.text_evidence,
        }


@dataclass(frozen=True, slots=True)
class Pool:
    rows: tuple[Row, ...]
    excluded: tuple[dict[str, Any], ...]
    input_rows: int
    protected_ids: int
    protected_texts: int
    near_duplicate_pairs: int

    @property
    def reasons(self) -> dict[str, int]:
        return dict(sorted(Counter(row["reason"] for row in self.excluded).items()))


def _text_key(text: str) -> str:
    return hashlib.sha256(" ".join(clean.normalise(text).casefold().split()).encode()).hexdigest()


def _reject(row: Row, reason: str) -> dict[str, Any]:
    return {"article_id": row.article_id, "reason": reason, "origins": list(row.origins)}


def _eligible(row: Row, *, now: datetime) -> str:
    if row.problem:
        return row.problem
    if row.confidence == "low":
        return "low_confidence"
    if not row.title.strip() or not row.summary.strip():
        return "missing_title_or_summary"
    cleaned = clean.clean(row.text)
    if row.verified_export:
        rejection = admit.text_rejection(row.article_id, row.source_id, row.title, cleaned)
        if rejection:
            return str(rejection.reason)
        detected = admit._language_of(cleaned.text)
    else:
        if row.published_at is None or row.collected_at is None:
            return "missing_timestamp"
        article = Article(
            id=row.article_id, source_id=row.source_id, source_name=row.source_name, url=row.url,
            title=row.title, summary=row.summary, content="", authors=(), categories=(),
            content_hash=row.content_hash, language=row.language, country="",
            published_at=row.published_at, collected_at=row.collected_at,
            scrape_status="", processing_status="",
        )
        result = admit.judge(article, cleaned, now=now, check_language=True)
        if isinstance(result, admit.Rejection):
            return str(result.reason)
        detected = result.detected_language
    if detected != "en":
        return "non_english" if detected else "unverified_english"
    return ""


def pool_rows(
    rows: Sequence[Row],
    *,
    taxonomy: Taxonomy,
    protected_ids: frozenset[str] = frozenset(),
    protected_texts: Mapping[str, str] | None = None,
    rejected_ids: frozenset[str] = frozenset(),
    now: datetime,
) -> Pool:
    """Account for every input row; retain one label-consistent copy per independent story."""
    if now.tzinfo is None:
        raise ValueError("pool cutoff must include a timezone")
    protected_texts = protected_texts or {}
    union = neardup._Union()
    by_text: dict[str, str] = {}
    by_hash: dict[str, str] = {}
    for row in rows:
        if (
            not row.article_id.strip() or row.topic not in taxonomy.ids | {taxonomy.unsorted}
            or row.confidence not in CONFIDENCE_ORDER
        ):
            raise ValueError("invalid pooled annotation ID, topic or confidence")
        for alias in row.ids:
            union.union(row.article_id, alias)
        if row.title and row.summary:
            key = _text_key(clean.clean(row.text).text)
            if key in by_text:
                union.union(row.article_id, by_text[key])
            else:
                by_text[key] = row.article_id
        if row.content_hash:
            if row.content_hash in by_hash:
                union.union(row.article_id, by_hash[row.content_hash])
            else:
                by_hash[row.content_hash] = row.article_id

    exact: defaultdict[str, list[Row]] = defaultdict(list)
    for row in rows:
        exact[union.find(row.article_id)].append(row)
    excluded: list[dict[str, Any]] = []
    candidates: list[Row] = []
    protected_keys = {_text_key(clean.clean(text).text) for text in protected_texts.values()}
    for copies in exact.values():
        aliases = frozenset(alias for row in copies for alias in row.ids)
        reason = ""
        if aliases & protected_ids:
            reason = "protected_evaluation_id"
        elif aliases & rejected_ids:
            reason = "historical_admission_rejection"
        elif any(_text_key(clean.clean(row.text).text) in protected_keys for row in copies):
            reason = "protected_evaluation_text"
        elif len({row.topic for row in copies}) != 1:
            reason = "conflicting_labels"
        elif copies[0].topic == taxonomy.unsorted:
            reason = "unsorted"
        if reason:
            excluded.extend(_reject(row, reason) for row in copies)
            continue
        eligible: list[Row] = []
        for row in copies:
            reason = _eligible(row, now=now)
            if reason:
                excluded.append(_reject(row, reason))
            else:
                eligible.append(row)
        if not eligible:
            continue
        eligible.sort(key=lambda row: (CONFIDENCE_ORDER[row.confidence], not row.verified_export,
                                       row.article_id, row.origins))
        winner = eligible[0]
        candidates.append(replace(
            winner, aliases=aliases,
            origins=tuple(sorted({origin for row in eligible for origin in row.origins})),
        ))
        excluded.extend(_reject(row, "duplicate_annotation_or_text") for row in eligible[1:])

    documents = {row.article_id: clean.clean(row.text).text for row in candidates}
    reserved = {f"protected:{key}": clean.clean(text).text for key, text in protected_texts.items() if text}
    documents.update(reserved)
    grouping = neardup.group(documents)
    protected_groups = {grouping.group_of[key] for key in reserved}
    stories: defaultdict[str, list[Row]] = defaultdict(list)
    for row in candidates:
        stories[grouping.group_of[row.article_id]].append(row)
    selected: list[Row] = []
    for group, copies in sorted(stories.items()):
        if group in protected_groups:
            excluded.extend(_reject(row, "protected_near_duplicate") for row in copies)
        elif len({row.topic for row in copies}) != 1:
            excluded.extend(_reject(row, "near_duplicate_label_conflict") for row in copies)
        else:
            copies.sort(key=lambda row: (CONFIDENCE_ORDER[row.confidence], row.article_id))
            selected.append(replace(copies[0], group_id=group))
            excluded.extend(_reject(row, "near_duplicate") for row in copies[1:])
    if len(rows) != len(selected) + len(excluded):
        raise AssertionError("pool exclusion accounting is incomplete")
    if any(row.ids & protected_ids for row in selected):
        raise AssertionError("protected evaluation IDs entered the training corpus")
    return Pool(
        rows=tuple(sorted(selected, key=lambda row: row.article_id)),
        excluded=tuple(excluded), input_rows=len(rows),
        protected_ids=len(protected_ids), protected_texts=len(protected_texts),
        near_duplicate_pairs=len(grouping.pairs),
    )


class Inputs:
    def __init__(self) -> None:
        self.files: dict[Path, dict[str, Any]] = {}

    def remember(self, path: Path, role: str) -> str:
        path = path.resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.files[path] = {"path": str(path), "sha256": digest, "role": role}
        return digest

    def json(self, path: Path, role: str) -> dict[str, Any]:
        self.remember(path, role)
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError(f"{path}: expected a JSON object")
        return result

    def rows(self, path: Path, role: str) -> list[dict[str, Any]]:
        self.remember(path, role)
        return [record for _, _, record in _records((path,))]

    def array(self, path: Path, role: str) -> list[dict[str, Any]]:
        path = path.resolve()
        if path.suffix != ".json" or any(part.startswith(".env") for part in path.parts):
            raise ValueError("MCP inputs must be private JSON export files, not environment files")
        roots = (DATA_ROOT.resolve(), (Path.home() / ".mongodb" / "mongodb-mcp" / "exports").resolve())
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError("MCP input must be inside the private V4 data or MongoDB export directory")
        self.remember(path, role)
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ValueError(f"{path}: expected a MongoDB MCP JSON array")
        return result


def _date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, dict) and set(value) == {"$date"}:
        value = value["$date"]
    if not isinstance(value, str):
        raise ValueError("expected a timezone-aware ISO timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return result.astimezone(timezone.utc)


def _id(record: Mapping[str, Any], key: str = "article_id") -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid {key}")
    return value


def _labels(records: Sequence[dict[str, Any]], taxonomy: Taxonomy) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in records:
        article_id, topic = _id(record), record.get("topic")
        if topic not in taxonomy.ids | {taxonomy.unsorted} or record.get("taxonomy_version") != taxonomy.version:
            raise ValueError("annotation has an unknown topic or taxonomy version")
        if article_id in result and result[article_id] != topic:
            raise ValueError("canonical annotations have unresolved conflicting labels")
        result[article_id] = topic
    return result


def _legacy_summary(record: Mapping[str, Any]) -> tuple[str, str]:
    title, text = record.get("title"), record.get("text")
    if not isinstance(title, str) or not isinstance(text, str):
        raise ValueError("legacy snapshot has no title/summary text")
    headline = clean.clean(title).text
    head, separator, tail = text.partition("\n")
    if not headline:
        return text, "legacy_clean_title_summary_snapshot"
    if clean.collapse(head) == clean.collapse(headline) and separator:
        return tail, "legacy_clean_title_summary_snapshot"
    return "", "legacy_summary_not_recoverable"


def recover_test_ids(
    manifest: Mapping[str, Any],
    *,
    labels_by_run: Mapping[str, Mapping[str, str]],
    raw_by_run: Mapping[str, bytes],
    unsorted: str,
) -> frozenset[str]:
    """Reproduce the old trainer's split, and require its recorded source and test hashes."""
    digest = hashlib.sha256()
    ids: list[str] = []
    topics: list[str] = []
    entries = manifest.get("runs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("historical model has no recoverable annotation runs")
    for entry in sorted(entries, key=lambda entry: entry["run"]):
        name = entry["run"]
        if name not in labels_by_run or name not in raw_by_run:
            raise ValueError(f"cannot recover protected test IDs for run {name}")
        raw = raw_by_run[name]
        if hashlib.sha256(raw).hexdigest() != entry["gold_sha256"]:
            raise ValueError("historical model's annotation source changed")
        digest.update(name.encode() + b"\0" + raw + b"\0")
        for article_id, topic in sorted(labels_by_run[name].items()):
            if topic != unsorted:
                ids.append(article_id)
                topics.append(topic)
    if digest.hexdigest() != manifest.get("gold_digest"):
        raise ValueError("historical model's complete annotation digest differs")
    protocol = manifest["protocol"]
    _, test = train_test_split(
        list(range(len(ids))), test_size=protocol["test_share"],
        stratify=topics, random_state=protocol["seed"],
    )
    reserved = frozenset(ids[index] for index in test)
    fingerprint = hashlib.sha256("\n".join(sorted(reserved)).encode()).hexdigest()
    if (
        len(reserved) != manifest["split"]["test"]
        or fingerprint != manifest["split"]["test_ids_sha256"]
    ):
        raise ValueError("historical test split could not be reproduced exactly")
    return reserved


def _verified_run(
    name: str, inputs: Inputs, data_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, str]]]:
    run = data_root / name
    selection = load_selection(run, data_root)
    _, missing, changed, conflicts = compare_sheets(run, selection)
    if missing or changed or conflicts:
        raise ValueError(f"{name}: annotation sheets differ from their export")
    for path in (run / "manifest.json", run / "selection.jsonl", *sorted(run.glob("*.csv"))):
        inputs.remember(path, f"{name}:verified_export")
    texts = read_sheet_texts(sorted(run.glob("*.csv")))
    return selection, {
        article_id: (unescape_cell(title), unescape_cell(summary))
        for article_id, (title, summary) in texts.items()
    }


def _historical(
    inputs: Inputs, taxonomy: Taxonomy,
) -> tuple[dict[str, dict[str, Any]], set[str], set[str], dict[str, str]]:
    texts: dict[str, dict[str, Any]] = {}
    protected: set[str] = set()
    rejected: set[str] = set()
    for name in SNAPSHOTS:
        directory = LEGACY_ROOT / "snapshots" / name
        manifest = inputs.json(directory / "manifest.json", "historical_snapshot")
        records = inputs.rows(directory / "articles.jsonl", "historical_text_and_splits")
        if (
            manifest.get("text_variant") != "title_summary"
            or manifest.get("taxonomy_version") != taxonomy.version
            or manifest.get("cleaning_version") != CLEANING_VERSION
            or manifest["digests"]["articles.jsonl"] != inputs.files[(directory / "articles.jsonl").resolve()]["sha256"]
        ):
            raise ValueError(f"{name}: snapshot text variant, taxonomy or fingerprint differs")
        if any(record.get("split") not in {"train", "val", "test", "dropped_at_boundary"} for record in records):
            raise ValueError(f"{name}: unknown historical split")
        protected_groups = {record["story_group_id"] for record in records if record["split"] != "train"}
        for record in records:
            article_id = _id(record)
            texts.setdefault(article_id, record)
            if record["split"] != "train" or record["story_group_id"] in protected_groups:
                protected.add(article_id)
        rejections = inputs.rows(directory / "rejections.jsonl", "historical_admission_rejections")
        if manifest["digests"]["rejections.jsonl"] != inputs.files[(directory / "rejections.jsonl").resolve()]["sha256"]:
            raise ValueError(f"{name}: historical rejections changed")
        rejected.update(_id(record) for record in rejections)
        inputs.remember(directory / "labels.jsonl", "historical_label_alias")
    for path in (LEGACY_ROOT / "pairs" / "pairs-key.jsonl",
                 REPO_ROOT / "collector" / "ml-v2" / "data" / "pairs" / "pairs-key.jsonl"):
        for record in inputs.rows(path, "protected_pair_evaluation"):
            protected.update((_id(record, "article_a"), _id(record, "article_b")))
    reserved_texts = {article_id: texts[article_id]["text"] for article_id in protected if article_id in texts}
    return texts, protected, rejected, reserved_texts


def build(
    *,
    articles_path: Path,
    sources_path: Path,
    out: Path,
    data_root: Path = DATA_ROOT,
    models_root: Path = MODELS_ROOT,
) -> Path:
    if not out.resolve().is_relative_to(data_root.resolve()):
        raise ValueError(f"output must be inside {data_root}")
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    inputs = Inputs()
    inputs.remember(TAXONOMY_PATH, "taxonomy")
    inputs.remember(SOURCES_PATH, "source_policy")
    sources = inputs.array(sources_path, "private_mcp_source_snapshot")
    allowed_urls = approved_feed_urls()
    approved = {
        _id(source, "_id") for source in sources
        if source.get("feed_url") in allowed_urls and not source.get("added_by")
    }
    if not approved:
        raise ValueError("MCP source snapshot has no approved shipped feed IDs")
    documents = inputs.array(articles_path, "private_mcp_article_snapshot")
    current: dict[str, dict[str, Any]] = {}
    for document in documents:
        article_id = _id(document, "_id")
        if article_id in current:
            raise ValueError("MCP article snapshot repeats an ID")
        current[article_id] = document
    legacy_texts, protected, rejected, reserved_texts = _historical(inputs, taxonomy)
    r1_selection, r1_texts = _verified_run(ROUND1, inputs, data_root)
    r2_selection, r2_texts = _verified_run(ROUND2, inputs, data_root)
    aliases = {
        _id(record): _id(record, "current_id")
        for record in inputs.rows(data_root / ROUND1 / "current-ids.jsonl", "verified_current_id_aliases")
    }
    gold_path = data_root / ROUND1 / "gold.jsonl"
    r1_records = inputs.rows(gold_path, "round1_ai_annotations")
    r1_labels = _labels(r1_records, taxonomy)
    if set(r1_labels) != set(r1_selection):
        raise ValueError("round-1 annotations do not cover their verified export")
    r1_raw = gold_path.read_bytes()
    recovered: dict[str, dict[str, Any]] = {}
    for directory in sorted(models_root.glob("*")):
        if not directory.is_dir():
            continue
        manifest_path, split_path = directory / "manifest.json", directory / "split.jsonl"
        if split_path.is_file():
            split_records = inputs.rows(split_path, "protected_model_split")
            if any(record.get("split") not in {"development", "test"} for record in split_records):
                raise ValueError("historical model has an invalid explicit split")
            if manifest_path.is_file():
                model = inputs.json(manifest_path, "historical_model")
                if model["split"]["sha256"] != inputs.files[split_path.resolve()]["sha256"]:
                    raise ValueError("historical model's explicit split changed")
                dataset = model.get("dataset")
                if dataset is not None:
                    dataset_path = Path(dataset)
                    if not dataset_path.resolve().is_relative_to(data_root.resolve()):
                        raise ValueError("historical model dataset points outside private V4 data")
                    dataset_manifest = inputs.json(dataset_path / "manifest.json", "protected_model_corpus")
                    if model.get("dataset_manifest_sha256") != inputs.files[(dataset_path / "manifest.json").resolve()]["sha256"]:
                        raise ValueError("historical model's dataset audit changed")
                    dataset_records = inputs.rows(dataset_path / "labels.jsonl", "protected_model_input_text")
                    if dataset_manifest["labels_sha256"] != inputs.files[(dataset_path / "labels.jsonl").resolve()]["sha256"]:
                        raise ValueError("historical model's dataset labels changed")
                    for record in dataset_records:
                        if record["article_id"] in {
                            value["article_id"] for value in split_records if value["split"] == "test"
                        }:
                            reserved_texts[f"{directory.name}:{record['article_id']}"] = (
                                f"{record['title']}\n{record['summary']}"
                            )
                            protected.update(record["aliases"])
            test_ids = frozenset(_id(record) for record in split_records if record["split"] == "test")
        elif manifest_path.is_file():
            model = inputs.json(manifest_path, "historical_model")
            test_ids = recover_test_ids(
                model, labels_by_run={ROUND1: r1_labels}, raw_by_run={ROUND1: r1_raw},
                unsorted=taxonomy.unsorted,
            )
            recovered[directory.name] = {
                "test_ids": sorted(test_ids),
                "test_ids_sha256": model["split"]["test_ids_sha256"],
            }
        else:
            raise ValueError(f"{directory.name}: model directory has no recoverable protected split")
        protected.update(test_ids)
        for article_id in test_ids:
            if article_id in r1_texts:
                reserved_texts[f"{directory.name}:{article_id}"] = "\n".join(r1_texts[article_id])
            elif article_id in legacy_texts:
                reserved_texts[f"{directory.name}:{article_id}"] = legacy_texts[article_id]["text"]

    rows: list[Row] = []
    source_groups: list[dict[str, Any]] = []
    for name, path in (("legacy_combined", LEGACY_ROOT / "labels" / "gold-combined.jsonl"),
                       ("legacy_pilot", LEGACY_ROOT / "labels" / "gold.jsonl")):
        records = inputs.rows(path, f"{name}:ai_annotations")
        _labels(records, taxonomy)
        source_groups.append({"run": name, "label_source": "ai-agent", "rows": len(records)})
        for number, record in enumerate(records, start=1):
            article_id = _id(record)
            text = legacy_texts.get(article_id)
            title, summary, evidence, source_id = "", "", "", ""
            if text is not None:
                title = text["title"]
                summary, evidence = _legacy_summary(text)
                source_id = text["source_id"]
            rows.append(Row(
                article_id, record["topic"], title, summary, (f"{name}:{number}",),
                source_id=source_id, verified_export=True, text_evidence=evidence,
                problem="missing_legacy_text" if text is None else (
                    "unapproved_source" if source_id not in approved else ""
                ),
            ))
    source_groups.append({"run": ROUND1, "label_source": "ai-agent", "rows": len(r1_records)})
    for number, record in enumerate(r1_records, start=1):
        article_id = _id(record)
        title, summary = r1_texts[article_id]
        rows.append(Row(
            article_id, record["topic"], title, summary, (f"{ROUND1}:{number}",),
            aliases=frozenset({aliases[article_id]}) if article_id in aliases else frozenset(),
            content_hash=r1_selection[article_id]["content_hash"], verified_export=True,
            text_evidence="fingerprint_verified_annotation_export",
        ))
    proposal_directory = PROPOSALS_ROOT / PROPOSALS
    proposals, proposal_evidence = load_proposals(proposal_directory, taxonomy)
    proposal_origins: defaultdict[str, list[str]] = defaultdict(list)
    all_proposal_ids: set[str] = set()
    for path in sorted(proposal_directory.glob("*.jsonl")):
        inputs.remember(path, "complete_original_ai_proposals")
        for _, number, record in _records((path,)):
            article_id = _id(record)
            all_proposal_ids.add(article_id)
            proposal_origins[article_id].append(f"{PROPOSALS}/{path.name}:{number}")
    weak_records = inputs.rows(data_root / ROUND2 / WEAK_LABELS, "selected_round2_ai_label_alias")
    for record in weak_records:
        article_id = _id(record)
        if (
            record.get("label_source") != "ai-agent"
            or record.get("taxonomy_version") != taxonomy.version
            or article_id not in all_proposal_ids
            or (article_id in proposals and record["topic"] != proposals[article_id].topic)
        ):
            raise ValueError("selected weak labels disagree with their original proposal source")
    source_groups.append({
        "run": PROPOSALS, "label_source": "ai-agent",
        "rows": proposal_evidence["judgements"], "canonical_articles": len(proposals),
    })
    r2_manifest = inputs.json(data_root / ROUND2 / "manifest.json", "round2_window")
    start, cut = _date(r2_manifest["window_start"]), _date(r2_manifest["cut"])
    if start is None or cut is None:
        raise ValueError("round-2 export has no frozen window")
    for article_id, proposal in sorted(proposals.items()):
        document = current.get(article_id)
        title, summary, problem, evidence = "", "", "", ""
        published, collected, source_id, content_hash, language = None, None, "", "", ""
        if document is None:
            problem = "missing_proposal_text"
        else:
            source_id = _id(document, "source_id")
            title, summary = document.get("title"), document.get("summary") or document.get("clean_summary", "")
            if not isinstance(title, str) or not isinstance(summary, str):
                raise ValueError("MCP article snapshot has invalid title or summary fields")
            published, collected = _date(document.get("published_at")), _date(document.get("collected_at"))
            language = str(document.get("language") or "")
            content_hash = str(document.get("content_hash") or "")
            summary = _clip(summary, LEDE_CHARS)
            evidence = "current_snapshot_original_ai_judgement_text_not_fingerprinted"
            if source_id not in approved:
                problem = "unapproved_source"
            elif collected is None or not start <= collected < cut:
                problem = "outside_proposal_window"
            elif document.get("detected_language") not in (None, "", "en"):
                problem = "non_english"
            if article_id in r2_selection:
                if (
                    sheet_digest({**document, "published_at": published, "collected_at": collected})
                    != r2_selection[article_id]["sheet_text_sha256"]
                    or content_hash != r2_selection[article_id]["content_hash"]
                ):
                    problem = "changed_export_text"
                title, summary = r2_texts[article_id]
                evidence = "fingerprint_verified_annotation_export"
        rows.append(Row(
            article_id, proposal.topic, title, summary, tuple(proposal_origins[article_id]),
            confidence=proposal.confidence, source_id=source_id, content_hash=content_hash,
            published_at=published, collected_at=collected, language=language,
            text_evidence=evidence, problem=problem,
        ))
    result = pool_rows(
        rows, taxonomy=taxonomy, protected_ids=frozenset(protected),
        protected_texts=reserved_texts, rejected_ids=frozenset(rejected), now=cut,
    )
    if not result.rows:
        raise ValueError("no eligible AI-labelled articles remain")
    for metadata in inputs.files.values():
        if hashlib.sha256(Path(metadata["path"]).read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("a pool input changed during the build")
    correction = {
        "decision": DECISION, "label_source": "ai-agent",
        "authority": "owner confirmation on 2026-11-22: all old and new classifier labels are AI-generated",
        "corrected_runs": [ROUND1, ROUND2], "human_validation": "not_met",
        "original_artifacts_preserved": True,
        "supersedes_stored_human_claims": True,
        "affected_sources": source_groups,
    }
    correction_path = data_root / "provenance-correction.json"
    if correction_path.is_file():
        if json.loads(correction_path.read_text(encoding="utf-8")) != correction:
            raise ValueError("existing provenance correction differs; owner review required")
    os.umask(0o077)
    out.mkdir(parents=True)
    snapshot_directory = out / "inputs"
    snapshot_directory.mkdir()
    for name, path in (("articles.json", articles_path), ("sources.json", sources_path)):
        shutil.copyfile(path, snapshot_directory / name)
    labels_path = out / "labels.jsonl"
    labels_path.write_text("".join(json.dumps(row.record(), sort_keys=True) + "\n" for row in result.rows),
                           encoding="utf-8")
    conflicts = all_proposal_ids - set(proposals)
    (out / "excluded.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in result.excluded)
        + "".join(json.dumps({
            "article_id": article_id, "reason": "conflicting_original_proposals",
            "origins": proposal_origins[article_id],
        }, sort_keys=True) + "\n" for article_id in sorted(conflicts)), encoding="utf-8",
    )
    (out / "protected-tests.json").write_text(
        json.dumps({"ids": sorted(protected), "recovered_models": recovered}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "status": "ai_generated_labels_not_gold", "label_source": "ai-agent",
        "provenance_decision": DECISION, "human_labels": 0, "human_validation": "not_met",
        "production_approved": False, "per_class_target": PER_CLASS_TARGET,
        "taxonomy_sha256": hashlib.sha256(TAXONOMY_PATH.read_bytes()).hexdigest(),
        "labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cleaning_version": CLEANING_VERSION,
        "dedup": {
            "threshold": neardup.DEFAULT_THRESHOLD, "num_perm": neardup.NUM_PERM,
            "bands": neardup.BANDS, "rows": neardup.ROWS, "one_row_per_story_group": True,
        },
        "sources": source_groups, "inputs": list(inputs.files.values()),
        "counts": dict(sorted(Counter(row.topic for row in result.rows).items())),
        "input_rows": result.input_rows, "selected": len(result.rows),
        "excluded_rows": len(result.excluded), "rejection_reasons": result.reasons,
        "original_proposals": proposal_evidence,
        "proposal_conflicting_ids": len(conflicts),
        "protected_ids": result.protected_ids, "protected_texts": result.protected_texts,
        "recovered_test_counts": {name: len(value["test_ids"]) for name, value in recovered.items()},
        "near_duplicate_pairs": result.near_duplicate_pairs,
        "text_evidence": dict(sorted(Counter(row.text_evidence for row in result.rows).items())),
        "confidence": dict(sorted(Counter(row.confidence for row in result.rows).items())),
        "round2_selected_ids": len(r2_selection),
        "additional_proposal_articles_used": sum(
            row.article_id in proposals and row.article_id not in r2_selection for row in result.rows
        ),
        "frozen_window": {"start": start.isoformat(), "cut": cut.isoformat()},
        "source_policy": "approved shipped feed IDs; R1 retains its fingerprint-verified export policy",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not correction_path.exists():
        correction_path.write_text(json.dumps(correction, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pool usable old and new AI labels into a private V4 candidate corpus")
    parser.add_argument("--articles", type=Path, required=True, help="private read-only MCP title/summary export")
    parser.add_argument("--sources", type=Path, required=True, help="private read-only MCP source metadata export")
    parser.add_argument("--out", type=Path, default=DATA_ROOT / f"v4-ai-pooled-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    args = parser.parse_args(argv)
    try:
        directory = build(articles_path=args.articles, sources_path=args.sources, out=args.out)
    except (ValueError, KeyError, FileNotFoundError, FileExistsError, json.JSONDecodeError) as exc:
        print(f"V4 pooling refused: {exc}", file=sys.stderr)
        return 1
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    print(f"Wrote {manifest['selected']} AI-labelled articles -> {directory}")
    print(f"Additional AI-sampled articles used: {manifest['additional_proposal_articles_used']}")
    print(f"Exclusions: {manifest['rejection_reasons']}")
    print(f"Protected historical tests recovered: {manifest['recovered_test_counts']}")
    print("Human validation: not met. Local candidate only; no production promotion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
