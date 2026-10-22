"""How many 'bodies' are actually scraped navigation rather than article text?

Found while measuring cleaning impact: some BBC bodies are video carousels. Per-source
boilerplate cannot catch these -- every carousel lists different video titles -- so if
this is widespread it belongs in admission, as its own rejection reason.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from newsmlv2 import config, load
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean

# Carousel tells: a duration stamp, a relative timestamp, or a bare section tag.
VIDEO_STAMP = re.compile(r"\bVideo,?\s*\d{2}:\d{2}(:\d{2})?", re.IGNORECASE)
RELATIVE_TIME = re.compile(r"^\d{1,2}\s+(second|minute|hour|day|week|month)s?\s+ago$", re.IGNORECASE)
UP_NEXT = re.compile(r"^up next\b", re.IGNORECASE)

SHORT_LINE_WORDS = 6


def looks_like_navigation(text: str) -> tuple[bool, str]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) < 5:
        return False, ""
    stamps = len(VIDEO_STAMP.findall(text))
    relative = sum(bool(RELATIVE_TIME.match(ln)) for ln in lines)
    short = sum(len(ln.split()) <= SHORT_LINE_WORDS for ln in lines)
    short_share = short / len(lines)

    if stamps >= 3:
        return True, "video carousel"
    if relative >= 3 and short_share > 0.5:
        return True, "timestamp list"
    if short_share > 0.8 and len(lines) >= 10:
        return True, "link list"
    return False, ""


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    lookup = as_lookup(discover([(a.source_name, a.body) for a in articles if a.has_body]))

    kinds: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    labelled_hits = 0
    examples: list[tuple[str, str, str]] = []

    from newsmlv2 import labels as labels_mod

    gold = labels_mod.read_gold()

    with_body = 0
    for a in articles:
        if not a.has_body:
            continue
        with_body += 1
        cleaned = clean(a.body, boilerplate=lookup.get(a.source_name), dateline=True)
        flagged, kind = looks_like_navigation(cleaned.text)
        if flagged:
            kinds[kind] += 1
            by_source[a.source_name] += 1
            labelled_hits += a.id in gold
            if len(examples) < 6:
                examples.append((a.source_name, a.title, cleaned.text[:160]))

    total = sum(kinds.values())
    print(f"bodies inspected      : {with_body}")
    print(f"look like navigation  : {total} ({total / with_body:.2%})")
    print(f"  of which gold-labelled: {labelled_hits}")
    print(f"\nby kind: {dict(kinds)}")
    print("\nby source:")
    for source, n in by_source.most_common(12):
        print(f"  {n:>4}  {source}")
    print("\nexamples:")
    for source, title, text in examples:
        print(f"\n  {source} | {title[:60]}")
        print(f"    {text}")

    print(f"\nUP_NEXT probe: {sum(bool(UP_NEXT.match(l)) for a in articles if a.has_body for l in a.body.split(chr(10))[:1])}")


if __name__ == "__main__":
    main()
