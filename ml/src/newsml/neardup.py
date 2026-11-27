"""Near-duplicate detection (model #2) — MinHash over shingles, banded into LSH.

Wire syndication means the same PTI copy appears near-identically across a dozen
outlets. `content_hash` is an exact match and catches none of it.

Why this lives in Phase 2 rather than later: the train/test split must be grouped
by story, or the same story appears on both sides of the split and Phase 3's
metrics are inflated by memorisation. Grouping depends on this, so this comes
first.

Hand-rolled rather than pulled from a library, for three reasons: it is ~80 lines,
determinism is fully under our control (library defaults often seed from
`hash()`, which is randomised per process), and it is one of the models the
project is meant to showcase.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

# 128 permutations split into 32 bands of 4 rows. Two documents become candidates
# when any band matches, which puts the S-curve's steep region near
# (1/32)^(1/4) ~= 0.42.
#
# This was 16 bands of 8 rows, steep near 0.72, and that was wrong — measured, not
# guessed. An 8-row band has to match in full, which at 0.55 Jaccard happens about
# a tenth of the time, so most true duplicates were never even proposed for
# comparison. The proof is that lowering the threshold under the old banding
# changed almost nothing: 464 folds to 468. Under this one the same change folds
# 491. **The banding, not the threshold, was what suppressed folding.**
NUM_PERM = 128
BANDS = 32
ROWS = NUM_PERM // BANDS

# Calibrated 2026-08-25 against 43 hand-judged pairs — a census of every candidate
# pair in the region that was in doubt, not a sample. It was 0.72, derived from the
# old banding arithmetic and never checked, and at that value it recovered **7 of
# 31** true duplicates. At 0.44: recall 0.90, precision 0.80.
#
# 0.44 rather than the 0.42 that maximises F1, for two reasons. Recurring daily
# features — gold-rate tables, horoscopes — are genuinely near-identical text about
# different days and cluster at 0.406, so the cut needs clearance above them. And
# picking the argmax of F1 measured on 43 pairs is fitting the sample; 0.44 is
# inside the noise of that peak and further from the cliff.
DEFAULT_THRESHOLD = 0.44

SHINGLE_WORDS = 5

_MAX_HASH = (1 << 32) - 1
_TOKEN = re.compile(r"[a-z0-9]+")


def shingles(text: str, size: int = SHINGLE_WORDS) -> set[str]:
    """Overlapping word n-grams, lowercased and stripped of punctuation."""
    tokens = _TOKEN.findall(text.casefold())
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def _hash(value: str, seed: int) -> int:
    """A seeded 32-bit hash. blake2b keyed by the seed is stable across runs,
    processes and platforms, which Python's built-in hash() is not."""
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=4, key=seed.to_bytes(4, "big")).digest()
    return int.from_bytes(digest, "big")


def signature(text: str, num_perm: int = NUM_PERM) -> tuple[int, ...]:
    """The MinHash signature: the minimum hash under each of `num_perm` seeds."""
    grams = shingles(text)
    if not grams:
        return tuple([_MAX_HASH] * num_perm)
    return tuple(min(_hash(gram, seed) for gram in grams) for seed in range(num_perm))


def jaccard(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """Estimated Jaccard similarity: the fraction of signature positions agreeing."""
    if not a or not b:
        return 0.0
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)


class _Union:
    """Union-find, so transitive duplicates land in one group: if A~B and B~C,
    all three are one story even when A and C never matched directly."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Always attach the larger id to the smaller, so group roots are a
            # function of membership alone, never of insertion order.
            lo, hi = sorted((ra, rb))
            self._parent[hi] = lo


@dataclass(frozen=True, slots=True)
class Grouping:
    """Story groups plus the candidate pairs that produced them."""

    group_of: dict[str, str]
    pairs: tuple[tuple[str, str, float], ...]

    @property
    def group_count(self) -> int:
        return len(set(self.group_of.values()))


def candidate_pairs(
    documents: dict[str, str],
    num_perm: int = NUM_PERM,
    bands: int = BANDS,
) -> tuple[tuple[str, str, float], ...]:
    """Every pair the banding surfaced, with its score, threshold not applied.

    `group` keeps only the pairs above the cut, which is right for grouping and
    useless for calibrating the cut itself: the pairs that decide whether 0.72 is
    the correct number are the ones sitting just below it. This returns the whole
    candidate set so a threshold can be chosen from labelled evidence rather than
    derived from the banding arithmetic and assumed.
    """
    rows = num_perm // bands
    signatures = {doc_id: signature(text, num_perm) for doc_id, text in sorted(documents.items())}

    buckets: defaultdict[tuple[int, tuple[int, ...]], list[str]] = defaultdict(list)
    for doc_id in sorted(signatures):
        sig = signatures[doc_id]
        for band in range(bands):
            buckets[(band, sig[band * rows : (band + 1) * rows])].append(doc_id)

    verified: dict[tuple[str, str], float] = {}
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                if key not in verified:
                    verified[key] = jaccard(signatures[a], signatures[b])

    return tuple(sorted((a, b, score) for (a, b), score in verified.items()))


def group(
    documents: dict[str, str],
    threshold: float = DEFAULT_THRESHOLD,
    num_perm: int = NUM_PERM,
    bands: int = BANDS,
) -> Grouping:
    """Assign every document a story-group id.

    Documents are banded into buckets, pairs sharing a bucket are verified
    against the signature-estimated Jaccard, and survivors are unioned. The group
    id is the lexicographically smallest document id in the group, so grouping is
    reproducible regardless of iteration order.
    """
    candidates = candidate_pairs(documents, num_perm=num_perm, bands=bands)

    union = _Union()
    for doc_id in sorted(documents):
        union.find(doc_id)

    kept = tuple((a, b, score) for a, b, score in candidates if score >= threshold)
    for a, b, _ in kept:
        union.union(a, b)

    return Grouping(
        group_of={doc_id: union.find(doc_id) for doc_id in sorted(documents)},
        pairs=kept,
    )
