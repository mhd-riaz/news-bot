"""The dataset analysis report.

Reads a frozen snapshot and answers the fourteen data-quality questions in one file, so
the numbers a model is later judged against are written down before any model exists.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from . import config
from .snapshot import Snapshot

SHORT_WORDS = 60
LONG_CHARS = 20_000


def _table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def _percentiles(series: pd.Series, points=(0.10, 0.50, 0.90, 0.99)) -> str:
    return " / ".join(f"{series.quantile(p):,.0f}" for p in points)


def write(snap: Snapshot, rejections: pd.DataFrame) -> str:
    frame = snap.frame
    manifest = snap.manifest
    labelled = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    counts = manifest["counts"]
    n = len(frame)

    parts: list[str] = []
    add = parts.append

    add(f"# Data quality report — snapshot `{snap.snapshot_id}`\n")
    add(
        f"Frozen corpus cut `{manifest['collected_before']}`. "
        f"Cleaning version {manifest['cleaning_version']}, taxonomy v{manifest['taxonomy_version']}, "
        f"seed {manifest['seed']}.\n"
    )
    add(
        "> Generated from the snapshot, not from a live query, so every number here is "
        "reproducible from the manifest digests.\n"
    )

    add("## 1. Shape\n")
    add(_table(
        [
            ("Articles read", f"{counts['admitted'] + counts['rejected']:,}"),
            ("Admitted", f"{counts['admitted']:,}"),
            ("Rejected", f"{counts['rejected']:,} ({counts['rejected'] / (n + counts['rejected']):.1%})"),
            ("Labelled", f"{counts['labelled']:,} of {counts['labels_offered']:,} offered"),
            ("`unsorted` (abstention set)", counts["unsorted"]),
            ("Story groups", f"{counts['story_groups']:,}"),
            ("Publishers", frame["publisher"].nunique()),
            ("Section feeds", frame["source_name"].nunique()),
        ],
        ("Measure", "Value"),
    ))

    add("\n## 2. Fields available\n")
    coverage = [
        ("title", (frame["title"].str.strip() != "").mean()),
        ("summary", (frame["summary"].str.strip() != "").mean()),
        ("body", frame["has_body"].mean()),
        ("published_at", frame["published_at"].notna().mean()),
        ("collected_at", frame["collected_at"].notna().mean()),
        ("categories", (frame["categories"].str.len() > 0).mean()),
        ("dateline_city", (frame["dateline_city"] != "").mean()),
        ("wire_agency", (frame["wire_agency"] != "").mean()),
    ]
    add(_table([(k, f"{v:.1%}") for k, v in coverage], ("Field", "Non-empty")))
    add(
        f"\n**Body is present for {frame['has_body'].mean():.1%} of admitted articles.** "
        "That is the whole premise of v2: v1 classified on title+summary alone.\n"
    )

    add("## 3-4. Classes and distribution\n")
    dist = labelled["topic"].value_counts()
    add(_table(
        [(t, f"{c:,}", f"{c / len(labelled):.1%}") for t, c in dist.items()],
        ("Class", "Labelled", "Share"),
    ))
    add(
        f"\nImbalance **{dist.max() / dist.min():.1f}:1** "
        f"({dist.idxmax()} {dist.max():,} vs {dist.idxmin()} {dist.min():,}). "
        "Handled by class weighting, not resampling.\n"
    )

    add("## 5. Missing values\n")
    add(_table(
        [
            ("No body", f"{(~frame['has_body']).sum():,}"),
            ("No summary", f"{(frame['summary'].str.strip() == '').sum():,}"),
            ("Neither body nor summary (title only)",
             f"{((~frame['has_body']) & (frame['summary'].str.strip() == '')).sum():,}"),
            ("No published_at", f"{frame['published_at'].isna().sum():,}"),
        ],
        ("Gap", "Articles"),
    ))

    add("\n## 6, 11. Exact duplicates\n")
    reasons = Counter(rejections["reason"]) if len(rejections) else Counter()
    add(
        f"{reasons.get('exact_duplicate', 0)} articles rejected on a repeated content hash. "
        f"Distinct URLs among admitted: {frame['url'].nunique():,} of {n:,}.\n"
    )

    add("## 7, 12, 14. Near-duplicates and syndication\n")
    sizes = Counter(Counter(frame["story_group_id"]).values())
    add(_table(
        [(f"{size} article{'s' if size > 1 else ''}", f"{count:,}") for size, count in sorted(sizes.items())],
        ("Group size", "Groups"),
    ))
    folded = counts["folded"]
    add(
        f"\n**{folded:,} articles ({folded / n:.1%}) fold into a larger story group** — "
        f"{counts['merged_pairs']:,} pairs merged, {counts['blocked_as_template']:,} rejected as "
        "recurring templates by the time-gap guard.\n"
    )
    multi = [g for g, c in Counter(frame["story_group_id"]).items() if c > 1]
    cross = frame[frame["story_group_id"].isin(multi)].groupby("story_group_id")["publisher"].nunique()
    add(
        f"Story groups spanning more than one publisher: **{(cross > 1).sum():,}** — "
        "these are the syndicated copies that would leak across a split if left ungrouped.\n"
    )

    add("## 8-9. Article length\n")
    words = frame["word_count"]
    add(_table(
        [
            ("Words (p10/p50/p90/p99)", _percentiles(words)),
            ("Body chars (p10/p50/p90/p99)", _percentiles(frame.loc[frame["has_body"], "body_chars"])),
            (f"Shorter than {SHORT_WORDS} words", f"{(words < SHORT_WORDS).sum():,}"),
            (f"Body longer than {LONG_CHARS:,} chars", f"{(frame['body_chars'] > LONG_CHARS).sum():,}"),
            ("Longest body", f"{frame['body_chars'].max():,} chars"),
        ],
        ("Measure", "Value"),
    ))
    add(
        f"\nThe longest body is {frame['body_chars'].max() / max(frame.loc[frame['has_body'], 'body_chars'].median(), 1):.0f}x "
        "the median. Body reduction is a Phase D decision, not a detail.\n"
    )

    add("## 10. Publishers\n")
    top = frame["publisher"].value_counts().head(12)
    lab_by_pub = labelled["publisher"].value_counts()
    add(_table(
        [
            (p, f"{c:,}", f"{lab_by_pub.get(p, 0):,}",
             labelled[labelled["publisher"] == p]["topic"].nunique())
            for p, c in top.items()
        ],
        ("Publisher", "Articles", "Labelled", "Classes covered"),
    ))
    add(
        f"\nHoldouts: {', '.join(manifest['publisher_holdouts'])} — chosen because they cover "
        "all 13 classes. A section feed cannot be held out: it carries one or two classes, so "
        "macro-F1 over it is arithmetic noise.\n"
    )

    add("## 13. Timestamps and the split\n")
    add(_table(
        [
            ("collected_at range", f"{frame['collected_at'].min():%Y-%m-%d %H:%M} → {frame['collected_at'].max():%Y-%m-%d %H:%M}"),
            ("published_at range", f"{frame['published_at'].min():%Y-%m-%d} → {frame['published_at'].max():%Y-%m-%d}"),
            ("train until", manifest["split_boundaries"]["train_until"]),
            ("val until", manifest["split_boundaries"]["val_until"]),
            ("Labelled by split", str(manifest["labelled_by_split"])),
        ],
        ("Measure", "Value"),
    ))
    span = (frame["collected_at"].max() - frame["collected_at"].min()).days
    add(
        f"\nThe split is on `collected_at`, never `published_at` — a 2019 article can arrive in "
        f"the feed tomorrow. **The window is only {span} days**, so this is a weak drift test; the "
        "publisher holdouts carry the generalization argument.\n"
    )

    add("## Rejections\n")
    if len(rejections):
        add(_table(
            [(r, f"{c:,}") for r, c in Counter(rejections["reason"]).most_common()],
            ("Reason", "Articles"),
        ))
    add("\nEvery gate is a switch on `admit.Policy`, so Phase C can price each one by "
        "disabling it and re-scoring.\n")

    return "\n".join(parts)
