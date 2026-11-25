from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from newsml.labels import Taxonomy, load_taxonomy

from .sampling import (
    AGENT_METHOD,
    DATA_ROOT,
    WEAK_LABELS,
    Proposal,
    Sample,
    TAXONOMY_PATH,
    approved_feed_urls,
    approved_source_ids,
    load_proposals,
    old_gold_ids,
    prior_candidate_ids,
    prior_documents,
    reviewed_labels,
    sample,
    sample_proposals,
    write_sample,
    write_weak_labels,
)


def local_uri() -> str:
    uri = os.environ.get("NEWS_ML_MONGO_URI")
    if not uri:
        raise ValueError("Set NEWS_ML_MONGO_URI to a local read-only MongoDB URI; .env is not read")
    try:
        parsed = urlsplit(uri)
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError("NEWS_ML_MONGO_URI is malformed") from exc
    if (
        parsed.scheme != "mongodb"
        or "," in parsed.netloc
        or host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/news"
    ):
        raise ValueError("NEWS_ML_MONGO_URI must target the local news database")
    return uri


def parse_cut(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(timezone.utc)
    try:
        cut = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("--cut must be an ISO-8601 datetime with a timezone") from exc
    if cut.tzinfo is None:
        raise ValueError("--cut must include a timezone")
    cut = cut.astimezone(timezone.utc)
    if cut > datetime.now(timezone.utc):
        raise ValueError("--cut cannot be in the future")
    return cut


def export(args: argparse.Namespace) -> int:
    cut = parse_cut(args.cut)
    out = args.out or DATA_ROOT / f"v4-{cut:%Y%m%dT%H%M%SZ}"
    if not out.resolve().is_relative_to(DATA_ROOT.resolve()):
        raise ValueError(f"output must be inside {DATA_ROOT}")
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    if args.per_class < 1 or args.scan_limit < args.per_class:
        raise ValueError("--per-class must be positive and --scan-limit >= --per-class")
    review_paths = args.reviewed_gold or []
    if any(
        path.name != "gold.jsonl"
        or not path.resolve().is_relative_to(DATA_ROOT.resolve())
        for path in review_paths
    ):
        raise ValueError("--reviewed-gold must be a gold.jsonl inside ml-v4/data/")
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    prior = prior_candidate_ids(DATA_ROOT)
    confirmed = reviewed_labels(review_paths, taxonomy)
    if prior and not confirmed:
        raise ValueError("existing V4 candidates need human review before another export")
    if confirmed.keys() - prior:
        raise ValueError("reviewed gold contains IDs not exported as V4 candidates")
    if prior - confirmed.keys():
        raise ValueError("some existing V4 candidates lack reviewed human labels")
    proposals_dir = getattr(args, "proposals", None)
    proposals: dict[str, Proposal] = {}
    # Every path excludes earlier V4 rounds by text and today's IDs, not only by export ID:
    # a rebuilt database re-keys the same articles.
    prior_docs, current_ids = prior_documents(DATA_ROOT)
    extra: dict[str, Any] = {
        "prior_round_documents": len(prior_docs),
        "prior_round_current_ids": len(current_ids),
    }
    if proposals_dir is not None:
        if not getattr(args, "start", None):
            raise ValueError("--start is required with --proposals")
        start = parse_cut(args.start)
        proposals, provenance = load_proposals(proposals_dir, taxonomy)
        extra.update({
            "sampling": AGENT_METHOD,
            "window_start": start.isoformat(),
            "proposals": provenance,
            "weak_labels": f"{WEAK_LABELS} (label_source ai-agent; never gold)",
        })
    uri = local_uri()
    os.umask(0o077)
    with MongoClient(uri) as client:
        db = client.get_database("news")
        source_ids = approved_source_ids(db.get_collection("sources"), approved_feed_urls())
        if proposals_dir is None:
            result = sample(
                db.get_collection("articles"),
                taxonomy,
                cut=cut,
                per_class=args.per_class,
                scan_limit=args.scan_limit,
                seed=args.seed,
                old_ids=old_gold_ids(),
                source_ids=source_ids,
                confirmed=confirmed,
                prior_candidates=prior | current_ids,
                prior_docs=prior_docs,
            )
        else:
            result = sample_proposals(
                db.get_collection("articles"),
                taxonomy,
                proposals=proposals,
                start=start,
                cut=cut,
                per_class=args.per_class,
                seed=args.seed,
                old_ids=old_gold_ids(),
                source_ids=source_ids,
                confirmed=confirmed,
                prior_candidates=prior | current_ids,
                prior_docs=prior_docs,
            )
    code = report_sample(result, args, out, cut, taxonomy, extra=extra)
    if proposals_dir is not None:
        print(f"AI-agent weak labels -> {write_weak_labels(out, result.selected, proposals, taxonomy)}")
    return code


def report_sample(
    result: Sample,
    args: argparse.Namespace,
    out: Path,
    cut: datetime,
    taxonomy: Taxonomy,
    *,
    extra: dict[str, Any] | None = None,
) -> int:
    counts_by_topic = result.counts()
    for topic, counts in counts_by_topic.items():
        print(
            f"{topic}: selected {counts['selected']}/{result.quotas[topic]}, "
            f"provisional pool {counts['scanned']}, "
            f"shortfall {counts['shortfall']}"
        )
    print(
        f"Recent articles scanned: {result.queried}/{args.scan_limit}; "
        f"prior gold found in local DB: {result.old_documents_found}/{result.old_ids}; "
        f"admission rejections: {result.rejected}; skipped: {result.skipped}",
        flush=True,
    )
    sheets = write_sample(
        result, out, cut=cut, seed=args.seed, per_class=args.per_class,
        scan_limit=args.scan_limit, taxonomy=taxonomy, shards=args.shards,
        overlap=args.overlap, extra=extra,
    )
    print(f"{len(result.selected)} distinct unlabeled candidates -> {out}")
    print(f"{len(sheets)} blind CSV sheets; predictions are in private selection.jsonl only")
    if any(counts["shortfall"] for counts in counts_by_topic.values()):
        print("Not balanced: see manifest.json for shortages and scan caps", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export fresh, model-assisted classifier label candidates")
    parser.add_argument("--cut", help="UTC-aware collection cutoff; defaults to the current UTC time")
    parser.add_argument("--out", type=Path, help="new directory inside ml-v4/data/")
    parser.add_argument("--per-class", type=int, default=200)
    parser.add_argument("--scan-limit", type=int, default=26000,
                        help="maximum recent articles read from MongoDB")
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--overlap", type=int, default=20)
    parser.add_argument("--reviewed-gold", action="append", type=Path,
                        help="reviewed reference labels from a previous V4 run; legacy human tags do not certify authorship; repeat for each run")
    parser.add_argument("--proposals", type=Path,
                        help="AI-agent judgements inside ml-v4/data/proposals/; replaces the TF-IDF strata")
    parser.add_argument("--start", help="with --proposals: UTC-aware start of the collection window")
    args = parser.parse_args(argv)
    try:
        return export(args)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"V4 export failed: {exc}", file=sys.stderr)
        return 1
    except PyMongoError as exc:
        print(f"V4 local MongoDB read failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
