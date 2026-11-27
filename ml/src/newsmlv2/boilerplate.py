"""Discover the lines a publisher repeats across its own articles.

A line that appears in many of one source's articles and nowhere else carries no topic
information, only the identity of the masthead. That is exactly the signal we must not
let the classifier learn, so this finds those lines per source and `clean` removes them.

**The one real change from v1.** v1 skipped any line longer than 25 words, reasoning
that long lines are syndicated content rather than chrome. Measured on 400 bodies, that
rule silently keeps the worst offender: embedded **author biographies**. Phys.org opens
86% of its bodies with `Who's behind this story?` followed by multi-sentence bios, and
Livemint and the Indian Express do the same. Those bios are not merely noise -- they are
*topically misleading*, because a cricket correspondent's biography sitting inside a
business article pushes it toward `sport`.

The length cap therefore rises, and a repetition-based guard replaces it: a long line
that recurs verbatim across many articles cannot be that article's own reporting.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .clean import normalise

# A line must appear in this share of a source's articles to count as its furniture.
MIN_DOC_FRACTION = 0.05
MIN_DOC_COUNT = 5

# Long lines are allowed now, so bios are reachable. The protection against eating real
# prose is repetition, not brevity: a 60-word sentence repeated across 40 articles by
# one publisher is a template, whatever its length.
MAX_LINE_WORDS = 120
LONG_LINE_WORDS = 25
LONG_LINE_MIN_FRACTION = 0.15

# A source needs enough articles for a fraction to mean anything.
MIN_SOURCE_ARTICLES = 20

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def segments(text: str) -> list[str]:
    """Split into the units boilerplate actually arrives in.

    Lines are the obvious unit, but several scrapers emit an entire body as **one**
    line, and then a shared phrase inside it is invisible to line-level counting. The
    Economic Times prefixes 'Listen to this article in summarized format' and the BBC
    appends a 'Related topics ... My News' block that way. On a short body that shared
    phrase dominates the vector, and unrelated articles were merging at 0.99 because of
    it. So a long line is also split into sentences.
    """
    out: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line.split()) > LONG_LINE_WORDS:
            out.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
        else:
            out.append(line)
    return out


@dataclass(frozen=True, slots=True)
class Candidate:
    source_name: str
    line: str
    doc_count: int
    doc_fraction: float

    @property
    def word_count(self) -> int:
        return len(self.line.split())

    @property
    def is_long(self) -> bool:
        return self.word_count > LONG_LINE_WORDS


def discover(documents: Iterable[tuple[str, str]]) -> list[Candidate]:
    """`(source_name, text)` pairs in, per-source repeated lines out.

    Counts each line once per document, so an article that repeats its own footer four
    times cannot inflate the count on its own.
    """
    totals: Counter[str] = Counter()
    line_docs: dict[str, Counter[str]] = defaultdict(Counter)

    for source_name, text in documents:
        totals[source_name] += 1
        seen = {
            seg
            for seg in segments(normalise(text))
            if len(seg) >= 3 and len(seg.split()) <= MAX_LINE_WORDS
        }
        line_docs[source_name].update(seen)

    found: list[Candidate] = []
    for source_name, counts in line_docs.items():
        total = totals[source_name]
        if total < MIN_SOURCE_ARTICLES:
            continue
        for line, n in counts.items():
            fraction = n / total
            if n < MIN_DOC_COUNT or fraction < MIN_DOC_FRACTION:
                continue
            # A long line needs stronger evidence before we call it a template, so a
            # genuinely repeated sentence of reporting is not mistaken for chrome.
            if len(line.split()) > LONG_LINE_WORDS and fraction < LONG_LINE_MIN_FRACTION:
                continue
            found.append(Candidate(source_name, line, n, fraction))

    found.sort(key=lambda c: (c.source_name, -c.doc_fraction, c.line))
    return found


def as_lookup(candidates: Iterable[Candidate]) -> dict[str, frozenset[str]]:
    """source_name -> case-folded lines, in the shape `clean` expects."""
    out: dict[str, set[str]] = defaultdict(set)
    for c in candidates:
        out[c.source_name].add(c.line.casefold())
    return {k: frozenset(v) for k, v in out.items()}


# Chrome that is concatenated onto the body without sentence punctuation, so neither
# line nor sentence splitting can reach it. The BBC appends "Related topics
# MoneyUpdates from your News topics will appear in My News..." exactly this way, and it
# merged 21 unrelated articles into one story group at 0.99 similarity.
AFFIX_MIN_CHARS = 40
AFFIX_MAX_CHARS = 400
AFFIX_MIN_FRACTION = 0.30


@dataclass(frozen=True, slots=True)
class Affix:
    prefix: str = ""
    suffix: str = ""


def _common_edge(texts: list[str], *, suffix: bool, fraction: float) -> str:
    """Longest prefix or suffix shared by at least `fraction` of these texts."""
    needed = max(MIN_DOC_COUNT, int(len(texts) * fraction))
    if len(texts) < MIN_SOURCE_ARTICLES:
        return ""
    for length in range(min(AFFIX_MAX_CHARS, min(len(t) for t in texts)), AFFIX_MIN_CHARS, -1):
        edges = Counter(t[-length:] if suffix else t[:length] for t in texts)
        edge, count = edges.most_common(1)[0]
        if count >= needed:
            return edge
    return ""


def common_affixes(
    documents: Iterable[tuple[str, str]], *, fraction: float = AFFIX_MIN_FRACTION
) -> dict[str, Affix]:
    by_source: dict[str, list[str]] = defaultdict(list)
    for source_name, text in documents:
        cleaned = normalise(text)
        if cleaned:
            by_source[source_name].append(cleaned)

    found: dict[str, Affix] = {}
    for source_name, texts in by_source.items():
        affix = Affix(
            prefix=_common_edge(texts, suffix=False, fraction=fraction),
            suffix=_common_edge(texts, suffix=True, fraction=fraction),
        )
        if affix.prefix or affix.suffix:
            found[source_name] = affix
    return found
