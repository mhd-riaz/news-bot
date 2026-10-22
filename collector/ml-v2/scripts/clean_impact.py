"""How much text does cleaning actually remove, and from whom?

Discovery is only half the job. A rule that eats real reporting is far worse than one
that misses chrome, so this measures the damage per source before any snapshot is cut.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

import yaml

from newsmlv2 import config, load
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean

# A source losing more than this share of its body text is suspicious, not successful.
ALARM_FRACTION = 0.35


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    bodies = [(a.source_name, a.body) for a in articles if a.has_body]
    lookup = as_lookup(discover(bodies))
    print(f"{len(articles)} articles | boilerplate for {len(lookup)} sources\n")

    lost: dict[str, list[float]] = defaultdict(list)
    before_total = after_total = 0
    emptied: list[load.Article] = []
    shrunk: list[tuple[float, load.Article, str]] = []

    for a in articles:
        if not a.has_body:
            continue
        out = clean(a.body, boilerplate=lookup.get(a.source_name), dateline=True)
        before, after = len(a.body), len(out.text)
        before_total += before
        after_total += after
        fraction = 1.0 - (after / before) if before else 0.0
        lost[a.source_name].append(fraction)
        if not out.text:
            emptied.append(a)
        elif fraction > 0.5:
            shrunk.append((fraction, a, out.text))

    print(f"corpus-wide body text removed: {1 - after_total / before_total:.1%}")
    print(f"bodies cleaned away entirely : {len(emptied)}")

    print(f"\nsources losing more than {ALARM_FRACTION:.0%} of their body text:")
    ranked = sorted(
        ((statistics.median(v), k, len(v)) for k, v in lost.items() if len(v) >= 20),
        reverse=True,
    )
    for median, source, n in ranked[:12]:
        flag = "  <== CHECK" if median > ALARM_FRACTION else ""
        print(f"  {median:>6.1%}  n={n:<5} {source}{flag}")

    print("\nleast affected (sanity: real reporting should barely move):")
    for median, source, n in ranked[-5:]:
        print(f"  {median:>6.1%}  n={n:<5} {source}")

    print(f"\nbodies cleaned to nothing ({len(emptied)}) -- these belong to admission:")
    for a in emptied[:10]:
        print(f"  {a.source_name[:30]:<30} {a.title[:60]}")

    print("\nworst shrinkage still leaving text (eyeball for eaten prose):")
    for fraction, a, text in sorted(shrunk, key=lambda t: -t[0])[:5]:
        print(f"\n  -{fraction:.0%}  {a.source_name} | {a.title[:60]}")
        print(f"    kept: {text[:200]}")

    out_path = config.REPORT_DIR / "clean-impact.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(
            {
                "corpus_removed_fraction": round(1 - after_total / before_total, 4),
                "bodies_emptied": len(emptied),
                "median_removed_by_source": {
                    source: round(median, 4) for median, source, _ in ranked
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path.relative_to(config.ML_ROOT)}")


if __name__ == "__main__":
    main()
