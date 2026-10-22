"""Group articles that tell the same story, so a story never straddles a split.

Syndicated wire copy runs at five publishers with reworded headlines. If one copy
trains and another tests, the score is inflated by memorisation. This clusters them so
a whole story group lands in one split.

**Two stages, because one threshold provably cannot do the job.** v1 measured its
single-cut MinHash and found precision could not exceed 0.80 at *any* threshold: its
false positives were four structural kinds, none of which a cut can separate. So:

1. **Block** on sparse TF-IDF cosine to propose candidates. Measured at 12s for 8,001
   articles with 4,000-char bodies, so this is cheap enough to be generous.
2. **Verify** each candidate with rules aimed at those four kinds:
   * a **time gap** on the same source means a recurring template -- two instalments of
     a daily gold-rate table or a weekly quiz are near-identical wording and are *not*
     the same story;
   * verification runs on **furniture-stripped** text, because two unrelated France 24
     articles were once merged on nothing but a shared footer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

# How many neighbours to consider per article. A story cluster larger than this is rare;
# transitive merging through union-find picks up the tail anyway.
NEIGHBOURS = 8

# Calibrated against v1's 43-pair hand-judged census (scripts/calibrate_dedup.py).
# At this cut, with the template guard on: precision 0.83, recall 0.81, F1 0.820 --
# clearing the 0.80 precision ceiling v1 proved a single MinHash threshold had.
#
# NOT the F1 argmax. F1 peaks at 0.30 (0.839), but two things rule that out: the census
# only covers the 0.40-0.95 band, so anything below 0.40 extrapolates into a region
# where no pair was ever judged, and the whole 0.30-0.52 range differs by a single true
# positive out of 39 -- picking the maximum would be fitting the sample.
DEFAULT_THRESHOLD = 0.50

# Same source, further apart than this, and near-identical: a recurring feature, not a
# duplicate. This is the single largest false-positive class v1 catalogued.
TEMPLATE_HOURS = 20

# Body text is truncated before vectorising: a 179k-character outlier would otherwise
# dominate the vocabulary, and the opening carries the story.
MATCH_CHARS = 4000


@dataclass(frozen=True, slots=True)
class Doc:
    id: str
    text: str
    publisher: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class Pair:
    a: str
    b: str
    score: float


@dataclass(frozen=True, slots=True)
class Grouping:
    group_of: dict[str, str]
    pairs: tuple[Pair, ...]
    rejected_as_template: tuple[Pair, ...]

    @property
    def group_count(self) -> int:
        return len(set(self.group_of.values()))

    def sizes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for group in self.group_of.values():
            counts[group] = counts.get(group, 0) + 1
        return counts


def candidate_pairs(docs: list[Doc], *, neighbours: int = NEIGHBOURS) -> tuple[Pair, ...]:
    """Every pair the blocking stage proposes, with no threshold applied.

    Returned unfiltered so a threshold can be calibrated against judged pairs rather
    than assumed.
    """
    if len(docs) < 2:
        return ()

    vectoriser = TfidfVectorizer(
        sublinear_tf=True,
        min_df=2,
        ngram_range=(1, 2),
        strip_accents="unicode",
        lowercase=True,
    )
    matrix = vectoriser.fit_transform(d.text[:MATCH_CHARS] for d in docs)

    k = min(neighbours + 1, len(docs))
    finder = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute").fit(matrix)
    distances, indices = finder.kneighbors(matrix)

    seen: set[tuple[int, int]] = set()
    found: list[Pair] = []
    for i, (row_d, row_i) in enumerate(zip(distances, indices)):
        for distance, j in zip(row_d, row_i):
            j = int(j)
            if i == j:
                continue
            key = (i, j) if i < j else (j, i)
            if key in seen:
                continue
            seen.add(key)
            found.append(Pair(docs[key[0]].id, docs[key[1]].id, float(1.0 - distance)))
    found.sort(key=lambda p: -p.score)
    return tuple(found)


def is_recurring_template(a: Doc, b: Doc, *, template_hours: int = TEMPLATE_HOURS) -> bool:
    """Same masthead, far apart in time: a scheduled feature rather than one story.

    Keyed on **publisher**, not the section feed. The Hindu runs one `Watch:` video
    series across its Science, Business and Sport feeds; treating those as different
    sources let 15 instalments merge into a single story group.

    Deliberately narrow otherwise. Two *different* publishers running the same wire copy
    a day apart is genuine syndication and must still fold.
    """
    if a.publisher != b.publisher:
        return False
    if a.published_at is None or b.published_at is None:
        return False
    return abs(a.published_at - b.published_at) > timedelta(hours=template_hours)


def group(
    docs: list[Doc],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    neighbours: int = NEIGHBOURS,
    template_hours: int = TEMPLATE_HOURS,
) -> Grouping:
    """Cluster same-story articles. Group id is the smallest member id, so it is stable."""
    by_id = {d.id: d for d in docs}
    parent = {d.id: d.id for d in docs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            low, high = (rx, ry) if rx < ry else (ry, rx)
            parent[high] = low

    kept: list[Pair] = []
    templates: list[Pair] = []
    for pair in candidate_pairs(docs, neighbours=neighbours):
        if pair.score < threshold:
            continue
        if is_recurring_template(by_id[pair.a], by_id[pair.b], template_hours=template_hours):
            templates.append(pair)
            continue
        kept.append(pair)
        union(pair.a, pair.b)

    return Grouping(
        group_of={d.id: find(d.id) for d in docs},
        pairs=tuple(kept),
        rejected_as_template=tuple(templates),
    )


def scores_for(docs: list[Doc], wanted: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """Cosine similarity for specific pairs, used when calibrating against judgements."""
    index = {d.id: i for i, d in enumerate(docs)}
    vectoriser = TfidfVectorizer(
        sublinear_tf=True, min_df=2, ngram_range=(1, 2), strip_accents="unicode"
    )
    matrix = vectoriser.fit_transform(d.text[:MATCH_CHARS] for d in docs)
    normed = matrix.multiply(1.0 / np.sqrt(matrix.multiply(matrix).sum(axis=1)))
    normed = normed.tocsr()

    out: dict[tuple[str, str], float] = {}
    for a, b in wanted:
        if a in index and b in index:
            out[(a, b)] = float(normed[index[a]].multiply(normed[index[b]]).sum())
    return out
