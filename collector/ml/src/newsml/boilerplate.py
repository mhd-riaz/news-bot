"""Learn each source's template furniture instead of guessing at it.

A hand-written regex list does not survive contact with twenty sources. This
finds the furniture by counting: hash every line of every article from a source,
count how many *distinct* articles contain each line, and treat the lines that
recur across many otherwise-unrelated articles as template rather than story.

The output is written for a human to read and approve before it is ever applied
(Phase 2 deliverable 3). A line that gets removed from every article of a source
is exactly the kind of change that is invisible once a model is trained on it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .clean import line_key, normalise
from .load import Article

# A line must appear in at least this fraction of a source's articles to count as
# furniture. Set from the shape of the distribution, not from taste: real
# sentences essentially never repeat across articles, so the histogram is
# strongly bimodal and anything above a few percent is template.
MIN_DOC_FRACTION = 0.05

# ...and in at least this many articles outright, so a source with 12 collected
# articles cannot promote a line to furniture on the strength of one repeat.
MIN_DOC_COUNT = 5

# Furniture is short. A long repeated line is more likely a syndicated paragraph
# appearing in several articles, which is a near-duplicate signal, not noise.
MAX_LINE_WORDS = 25


@dataclass(frozen=True, slots=True)
class Candidate:
    """One line proposed for removal, with the evidence for the proposal."""

    source_id: str
    key: str
    example: str
    doc_count: int
    doc_fraction: float


def discover(articles: list[Article], variant: str) -> list[Candidate]:
    """Rank every repeated line per source. Deterministic for a given input."""
    per_source_docs: Counter[str] = Counter()
    line_docs: defaultdict[tuple[str, str], int] = defaultdict(int)
    examples: dict[tuple[str, str], str] = {}

    for article in articles:
        per_source_docs[article.source_id] += 1
        seen: set[str] = set()
        for line in normalise(article.text(variant)).split("\n"):
            stripped = line.strip()
            if not stripped or len(stripped.split()) > MAX_LINE_WORDS:
                continue
            key = line_key(stripped)
            if not key or key in seen:
                continue
            seen.add(key)
            line_docs[(article.source_id, key)] += 1
            examples.setdefault((article.source_id, key), stripped)

    candidates = [
        Candidate(
            source_id=source_id,
            key=key,
            example=examples[(source_id, key)],
            doc_count=count,
            doc_fraction=count / per_source_docs[source_id],
        )
        for (source_id, key), count in line_docs.items()
        if count >= MIN_DOC_COUNT and count / per_source_docs[source_id] >= MIN_DOC_FRACTION
    ]
    # Sort is part of the contract: the YAML artifact must be diffable across runs.
    candidates.sort(key=lambda c: (c.source_id, -c.doc_count, c.key))
    return candidates


def as_lookup(candidates: list[Candidate]) -> dict[str, frozenset[str]]:
    """Collapse candidates into the per-source key sets that clean() consumes."""
    by_source: defaultdict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        by_source[candidate.source_id].add(candidate.key)
    return {source: frozenset(keys) for source, keys in by_source.items()}


def to_yaml_document(candidates: list[Candidate]) -> dict:
    """Shape the review artifact. Grouped by source, with the evidence kept."""
    by_source: defaultdict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_source[candidate.source_id].append(
            {
                "key": candidate.key,
                "example": candidate.example,
                "doc_count": candidate.doc_count,
                "doc_fraction": round(candidate.doc_fraction, 4),
            }
        )
    return {
        "thresholds": {
            "min_doc_fraction": MIN_DOC_FRACTION,
            "min_doc_count": MIN_DOC_COUNT,
            "max_line_words": MAX_LINE_WORDS,
        },
        "sources": {source: by_source[source] for source in sorted(by_source)},
    }
