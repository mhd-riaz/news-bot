"""Corpus profile: what is actually in the bronze collection, before any modelling.

Phase 2's first deliverable, and the one every later decision cites. The point is
not the figures — it is that the taxonomy, the split strategy and the choice of
text field are all downstream of numbers that have to be looked at first.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .load import Article


@dataclass(frozen=True, slots=True)
class FieldStats:
    present: int
    absent: int
    p5: int
    p50: int
    p95: int


def _word_stats(values: list[int]) -> FieldStats:
    present = [v for v in values if v > 0]
    if not present:
        return FieldStats(0, len(values), 0, 0, 0)
    present.sort()

    def pct(p: float) -> int:
        return present[min(len(present) - 1, int(p * len(present)))]

    return FieldStats(len(present), len(values) - len(present), pct(0.05), pct(0.50), pct(0.95))


def build(articles: list[Article]) -> dict:
    """Every number the report needs, as plain JSON-serialisable data."""
    if not articles:
        return {"article_count": 0}

    by_source: defaultdict[str, list[Article]] = defaultdict(list)
    for article in articles:
        by_source[article.source_id].append(article)

    published = sorted(a.published_at for a in articles)
    lag = sorted((a.collected_at - a.published_at).total_seconds() / 3600 for a in articles)

    categories = Counter(c.casefold() for a in articles for c in a.categories)

    return {
        "article_count": len(articles),
        "source_count": len(by_source),
        "published_range": [published[0].isoformat(), published[-1].isoformat()],
        "collection_lag_hours": {
            "p5": round(lag[int(0.05 * len(lag))], 2),
            "p50": round(statistics.median(lag), 2),
            "p95": round(lag[min(len(lag) - 1, int(0.95 * len(lag)))], 2),
        },
        "scrape_status": dict(sorted(Counter(a.scrape_status for a in articles).items())),
        "processing_status": dict(sorted(Counter(a.processing_status for a in articles).items())),
        "language_declared": dict(sorted(Counter(a.language for a in articles).items())),
        "country": dict(sorted(Counter(a.country for a in articles).items())),
        "fields": {
            "title": asdict(_word_stats([len(a.title.split()) for a in articles])),
            "summary": asdict(_word_stats([len(a.summary.split()) for a in articles])),
            "content": asdict(_word_stats([len(a.content.split()) for a in articles])),
        },
        "categories": {
            "distinct": len(categories),
            "articles_without_any": sum(1 for a in articles if not a.categories),
            "top": dict(categories.most_common(40)),
        },
        "sources": {
            source_id: {
                "name": members[0].source_name,
                "articles": len(members),
                "with_content": sum(1 for a in members if a.content.strip()),
                "content_words": asdict(_word_stats([len(a.content.split()) for a in members])),
                "summary_words": asdict(_word_stats([len(a.summary.split()) for a in members])),
                "scrape_status": dict(sorted(Counter(a.scrape_status for a in members).items())),
            }
            for source_id, members in sorted(by_source.items())
        },
    }


def _figures(articles: list[Article], out_dir: Path) -> list[str]:
    """Render the profile figures. Import is local so the package stays usable
    (and testable) on a machine without matplotlib installed."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    by_source: defaultdict[str, list[Article]] = defaultdict(list)
    for article in articles:
        by_source[article.source_id].append(article)
    ordered = sorted(by_source.items(), key=lambda kv: -len(kv[1]))

    fig, ax = plt.subplots(figsize=(10, max(4, 0.32 * len(ordered))))
    names = [members[0].source_name[:28] for _, members in ordered]
    ax.barh(names, [sum(1 for a in m if a.content.strip()) for _, m in ordered], label="with content")
    ax.barh(names, [sum(1 for a in m if not a.content.strip()) for _, m in ordered],
            left=[sum(1 for a in m if a.content.strip()) for _, m in ordered], label="summary only")
    ax.invert_yaxis()
    ax.set_xlabel("articles")
    ax.set_title("Text availability by source")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "text-availability-by-source.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    written.append(path.name)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for label, values in (
        ("title", [len(a.title.split()) for a in articles]),
        ("summary", [len(a.summary.split()) for a in articles if a.summary.strip()]),
        ("content", [len(a.content.split()) for a in articles if a.content.strip()]),
    ):
        if values:
            ax.hist(values, bins=40, alpha=0.6, label=f"{label} (n={len(values)})")
    ax.set_xlabel("words")
    ax.set_ylabel("articles")
    ax.set_yscale("log")
    ax.set_title("Word-count distribution by field")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "word-count-distribution.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    written.append(path.name)

    counts = Counter(a.published_at.date() for a in articles)
    fig, ax = plt.subplots(figsize=(9, 4))
    days = sorted(counts)
    ax.bar([d.isoformat() for d in days], [counts[d] for d in days])
    ax.set_ylabel("articles")
    ax.set_title("Articles by publication date")
    ax.tick_params(axis="x", rotation=60, labelsize=7)
    fig.tight_layout()
    path = out_dir / "articles-by-publication-date.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    written.append(path.name)

    return written


def render_markdown(stats: dict, figures: list[str]) -> str:
    """The human-readable half of the deliverable."""
    if not stats.get("article_count"):
        return "# Corpus profile\n\nNo articles found.\n"

    lines = [
        "# Corpus profile",
        "",
        f"Generated {datetime.now().astimezone().isoformat(timespec='seconds')} — "
        "regenerate with `make ml-profile`. Do not edit by hand.",
        "",
        "## Shape",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Articles | {stats['article_count']:,} |",
        f"| Sources | {stats['source_count']} |",
        f"| Published range | {stats['published_range'][0]} → {stats['published_range'][1]} |",
        f"| Collection lag p50 | {stats['collection_lag_hours']['p50']} h |",
        f"| Distinct categories | {stats['categories']['distinct']} |",
        f"| Articles with no category | {stats['categories']['articles_without_any']:,} |",
        "",
        "## Field availability",
        "",
        "| Field | Present | Absent | p5 | p50 | p95 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, f in stats["fields"].items():
        lines.append(f"| {name} | {f['present']:,} | {f['absent']:,} | {f['p5']} | {f['p50']} | {f['p95']} |")

    lines += ["", "## Scrape status", "", "| Status | Articles |", "| --- | --- |"]
    lines += [f"| {k} | {v:,} |" for k, v in stats["scrape_status"].items()]

    lines += [
        "",
        "## Sources",
        "",
        "| Source | Articles | With content | Content p50 | Summary p50 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source_id, s in sorted(stats["sources"].items(), key=lambda kv: -kv[1]["articles"]):
        lines.append(
            f"| {s['name']} | {s['articles']:,} | {s['with_content']:,} "
            f"| {s['content_words']['p50']} | {s['summary_words']['p50']} |"
        )

    lines += ["", "## Top categories", "", "| Category | Articles |", "| --- | --- |"]
    lines += [f"| {k} | {v:,} |" for k, v in list(stats["categories"]["top"].items())[:25]]

    if figures:
        lines += ["", "## Figures", ""]
        lines += [f"![{name}](figures/{name})" for name in figures]

    return "\n".join(lines) + "\n"


def write(articles: list[Article], out_dir: Path) -> Path:
    """Write profile.json, the figures and the markdown report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = build(articles)
    (out_dir / "profile.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    figures = _figures(articles, out_dir / "figures")
    report = out_dir / "corpus-profile.md"
    report.write_text(render_markdown(stats, figures), encoding="utf-8")
    return report
