"""Freeze a dataset so a number can be reproduced months later.

The corpus grows by roughly 1,500 articles every 12 hours, so nothing is reproducible
until a cut is frozen. A snapshot is that freeze: the admitted rows, the labels joined
onto them, the split assignment, and a manifest recording every input that shaped it.

Two changes from v1 that matter:

* **Parquet, not JSONL.** Bodies are ~100x longer than v1's text, so a JSONL snapshot
  runs to tens of megabytes and every experiment re-reads it. Parquet with zstd is
  several times smaller and much faster to load, and keeps column types.
* **Title, summary and body are stored separately.** v1 froze one concatenated string,
  which structurally prevents weighting fields differently later.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .admit import Policy
from .dedup import DEFAULT_THRESHOLD, NEIGHBOURS, TEMPLATE_HOURS
from .labels import Taxonomy
from .pipeline import Prepared
from .splits import SplitRow, groups_spanning_splits, make_splits

ARTICLES = "articles.parquet"
REJECTIONS = "rejections.parquet"
MANIFEST = "manifest.json"

# Default body truncation for model input. Phase D sweeps this; the cap exists because
# the longest body is 175k characters against a 3.3k median.
BODY_CHARS = 4000

_COMPRESSION = "zstd"


def _git_sha(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return out.stdout.strip()
    except Exception:  # a snapshot outside a checkout is still worth having
        return "unknown"


@dataclass(frozen=True, slots=True)
class Snapshot:
    directory: Path
    manifest: dict
    frame: pd.DataFrame

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshot_id"])

    @property
    def labelled(self) -> pd.DataFrame:
        return self.frame[self.frame["topic"].notna()]

    def split(self, name: str, *, labelled_only: bool = True) -> pd.DataFrame:
        frame = self.labelled if labelled_only else self.frame
        return frame[frame["split"] == name]

    def texts(self, frame: pd.DataFrame, variant: str, *, body_chars: int | None = None) -> list[str]:
        """Assemble model input from the separately stored fields.

        `body_chars` truncates the body. Phase D sweeps it properly; the default here is
        generous but finite, because the longest body is 175k characters -- 53x the
        median -- and a handful of outliers would otherwise dominate both the vocabulary
        and the fitting time.
        """
        limit = BODY_CHARS if body_chars is None else body_chars
        title = frame["title"].fillna("")
        summary = frame["summary"].fillna("")
        body = frame["body"].fillna("").str.slice(0, limit)

        if variant == "title":
            return title.tolist()
        if variant == "title_summary":
            return (title + "\n" + summary).tolist()
        if variant == "title_body":
            fallback = body.where(body.str.strip() != "", summary)
            return (title + "\n" + fallback).tolist()
        if variant == "full":
            return (title + "\n" + summary + "\n" + body).tolist()
        raise ValueError(f"unknown text variant: {variant}")


def build(
    prepared: Prepared,
    labels: dict[str, str],
    taxonomy: Taxonomy,
    *,
    snapshot_id: str,
    out_root: Path | None = None,
    repo: Path | None = None,
    policy: Policy | None = None,
    train_fraction: float = 0.70,
    val_fraction: float = 0.15,
) -> Snapshot:
    """Write a frozen dataset. `snapshot_id` is required and must not already exist."""
    out_root = out_root or config.SNAPSHOT_DIR
    directory = out_root / snapshot_id
    if directory.exists():
        # v1's ids were derived from the date, collided on a same-day rerun, and
        # overwrote the earlier snapshot in place with no diff to recover it from.
        raise FileExistsError(f"snapshot {snapshot_id} already exists at {directory}")

    rows = []
    for item in prepared.admitted:
        article = item.article
        rows.append(
            {
                "article_id": article.id,
                "source_name": article.source_name,
                "publisher": article.publisher,
                "url": article.url,
                "title": item.title.text,
                "summary": item.summary.text,
                "body": item.body.text,
                "body_chars": len(item.body.text),
                "has_body": bool(item.body.text),
                "word_count": item.word_count,
                "dateline_city": item.body.dateline_city,
                "wire_agency": item.body.wire_agency,
                "categories": list(article.categories),
                "published_at": article.published_at,
                "collected_at": article.collected_at,
                "story_group_id": prepared.grouping.group_of[article.id],
                "topic": labels.get(article.id),
            }
        )
    frame = pd.DataFrame(rows).sort_values("article_id").reset_index(drop=True)

    split_rows = [
        SplitRow(
            article_id=r.article_id,
            group_id=r.story_group_id,
            collected_at=r.collected_at,
            publisher=r.publisher,
            # `isinstance`, not truthiness: an unlabelled row's topic is NaN here, and
            # bool(nan) is True -- which silently made every row count as labelled and
            # put the cuts back on corpus-wide quantiles, the exact bug this avoids.
            labelled=isinstance(r.topic, str) and r.topic != config.UNSORTED,
        )
        for r in frame.itertuples()
    ]
    # Cuts are placed on the labelled rows only; see splits.make_splits.
    reference = [r for r in split_rows if r.labelled]
    splits = make_splits(
        split_rows,
        train_fraction=train_fraction,
        val_fraction=val_fraction,
        reference=reference or None,
    )
    spanning = groups_spanning_splits(split_rows, splits)
    if spanning:
        raise AssertionError(f"{len(spanning)} story groups span splits")

    frame["split"] = frame["article_id"].map(splits.assignment())

    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / ARTICLES, compression=_COMPRESSION, index=False)
    pd.DataFrame(
        [
            {"article_id": r.article_id, "source_name": r.source_name,
             "reason": str(r.reason), "detail": r.detail}
            for r in prepared.rejected
        ]
    ).to_parquet(directory / REJECTIONS, compression=_COMPRESSION, index=False)

    labelled = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    manifest = {
        "snapshot_id": snapshot_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_sha": _git_sha(repo or config.ML_ROOT.parent),
        "seed": config.SEED,
        "cleaning_version": config.CLEANING_VERSION,
        "taxonomy_version": taxonomy.version,
        "collected_before": config.COLLECTED_BEFORE,
        "label_file": str(config.LABEL_PATH.name),
        "label_digest": config.digest(config.LABEL_PATH),
        "counts": {
            **prepared.counts,
            "labels_offered": len(labels),
            "labelled": int(len(labelled)),
            "unsorted": int((frame["topic"] == config.UNSORTED).sum()),
            **splits.counts(),
        },
        "labelled_by_split": {
            name: int((labelled["split"] == name).sum())
            for name in ("train", "val", "test", "dropped")
        },
        "class_distribution": labelled["topic"].value_counts().to_dict(),
        "split_boundaries": {
            "placed_by": "labelled articles",
            "train_until": splits.train_until.isoformat() if splits.train_until else None,
            "val_until": splits.val_until.isoformat() if splits.val_until else None,
        },
        "near_duplicates": {
            "threshold": DEFAULT_THRESHOLD,
            "neighbours": NEIGHBOURS,
            "template_hours": TEMPLATE_HOURS,
        },
        "admission_policy": (policy or Policy()).as_dict(),
        "publisher_holdouts": list(config.PUBLISHER_HOLDOUTS),
        "digests": {
            ARTICLES: config.digest(directory / ARTICLES),
            REJECTIONS: config.digest(directory / REJECTIONS),
        },
    }
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return Snapshot(directory, manifest, frame)


def read(directory: Path) -> Snapshot:
    """The only door training goes through."""
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    return Snapshot(directory, manifest, pd.read_parquet(directory / ARTICLES))


def verify(directory: Path) -> dict[str, bool]:
    """Do the files on disk still match the digests the manifest recorded?"""
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    return {
        name: config.digest(directory / name) == expected
        for name, expected in manifest["digests"].items()
    }
