"""Discover per-source boilerplate over real bodies and write it for review.

Run this before a snapshot: the output is an artifact a human should skim, because a
rule that eats real reporting is far more damaging than one that misses some chrome.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import yaml

from newsmlv2 import config, load
from newsmlv2.boilerplate import LONG_LINE_WORDS, discover

OUT = config.ARTIFACT_DIR / "boilerplate.yaml"


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    bodies = [(a.source_name, a.body) for a in articles if a.has_body]
    print(f"{len(articles)} articles, {len(bodies)} with a body")

    found = discover(bodies)
    per_source = Counter(c.source_name for c in found)
    longs = [c for c in found if c.is_long]

    print(f"\n{len(found)} boilerplate lines across {len(per_source)} sources")
    print(f"  {len(longs)} are over {LONG_LINE_WORDS} words -- these are what v1 could not see")

    print("\ntop sources by boilerplate lines found:")
    for source, n in per_source.most_common(12):
        print(f"  {n:>3}  {source}")

    print("\nhighest-coverage lines (the publisher fingerprints):")
    for c in sorted(found, key=lambda c: -c.doc_fraction)[:20]:
        flag = " [LONG]" if c.is_long else ""
        print(f"  {c.doc_fraction:>5.0%} {c.doc_count:>4}  {c.source_name[:26]:<26} {c.line[:60]}{flag}")

    if longs:
        print(f"\nlong lines caught (author bios and similar) -- {len(longs)} total:")
        for c in sorted(longs, key=lambda c: -c.doc_fraction)[:10]:
            print(f"\n  {c.doc_fraction:.0%} of {c.source_name} ({c.word_count} words)")
            print(f"    {c.line[:220]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "cleaning_version": config.CLEANING_VERSION,
        "collected_before": config.COLLECTED_BEFORE,
        "sources": {
            source: [
                {"line": c.line, "docs": c.doc_count, "fraction": round(c.doc_fraction, 3)}
                for c in found
                if c.source_name == source
            ]
            for source in sorted(per_source)
        },
    }
    OUT.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(config.ML_ROOT)}")


if __name__ == "__main__":
    main()
