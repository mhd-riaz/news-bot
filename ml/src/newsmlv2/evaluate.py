"""Scoring, with the uncertainty attached.

The validation split holds ~1,120 labelled articles, so the standard error on macro-F1
is roughly +/-0.02-0.03. v1 repeatedly read per-class swings of +/-0.07 as signal and
chased them. Every number this module returns therefore carries an interval, and model
comparisons go through a paired test rather than a subtraction.

The bootstrap resamples **story groups**, not articles. Syndicated copies of one story
are not independent observations, and resampling articles would report an interval
narrower than the truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

BOOTSTRAP_ROUNDS = 1000


@dataclass(frozen=True, slots=True)
class ClassScore:
    topic: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class Score:
    macro_f1: float
    macro_f1_low: float
    macro_f1_high: float
    weighted_f1: float
    accuracy: float
    per_class: tuple[ClassScore, ...]
    n: int
    labels: tuple[str, ...] = ()
    matrix: tuple[tuple[int, ...], ...] = field(default=())

    @property
    def interval(self) -> str:
        return f"{self.macro_f1:.3f} [{self.macro_f1_low:.3f}, {self.macro_f1_high:.3f}]"

    def overlaps(self, other: "Score") -> bool:
        """Do the two intervals overlap? If so, prefer the simpler model."""
        return not (self.macro_f1_low > other.macro_f1_high or other.macro_f1_low > self.macro_f1_high)

    @property
    def weakest(self) -> tuple[ClassScore, ...]:
        return tuple(sorted(self.per_class, key=lambda c: c.f1)[:3])


def bootstrap_macro_f1(
    truth: np.ndarray,
    predicted: np.ndarray,
    groups: np.ndarray,
    *,
    rounds: int = BOOTSTRAP_ROUNDS,
    seed: int = 0,
) -> tuple[float, float]:
    """95% interval for macro-F1, resampling story groups rather than articles."""
    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    index_of = {g: np.flatnonzero(groups == g) for g in unique}

    scores = np.empty(rounds)
    for i in range(rounds):
        picked = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([index_of[g] for g in picked])
        scores[i] = f1_score(truth[idx], predicted[idx], average="macro", zero_division=0)
    return float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))


def score(
    truth: list[str] | np.ndarray,
    predicted: list[str] | np.ndarray,
    groups: list[str] | np.ndarray | None = None,
    *,
    seed: int = 0,
    with_matrix: bool = False,
) -> Score:
    truth = np.asarray(truth)
    predicted = np.asarray(predicted)
    labels = sorted(set(truth) | set(predicted))

    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=labels, zero_division=0
    )
    per_class = tuple(
        ClassScore(t, float(p), float(r), float(f), int(s))
        for t, p, r, f, s in zip(labels, precision, recall, f1, support)
    )

    macro = float(f1_score(truth, predicted, average="macro", zero_division=0))
    if groups is None:
        low = high = macro
    else:
        low, high = bootstrap_macro_f1(truth, predicted, np.asarray(groups), seed=seed)

    matrix: tuple[tuple[int, ...], ...] = ()
    if with_matrix:
        matrix = tuple(tuple(int(v) for v in row) for row in confusion_matrix(truth, predicted, labels=labels))

    return Score(
        macro_f1=macro,
        macro_f1_low=low,
        macro_f1_high=high,
        weighted_f1=float(f1_score(truth, predicted, average="weighted", zero_division=0)),
        accuracy=float(accuracy_score(truth, predicted)),
        per_class=per_class,
        n=len(truth),
        labels=tuple(labels),
        matrix=matrix,
    )


def bootstrap_class_f1(
    truth: np.ndarray,
    predicted: np.ndarray,
    groups: np.ndarray,
    labels: list[str],
    *,
    rounds: int = BOOTSTRAP_ROUNDS,
    seed: int = 0,
) -> dict[str, tuple[float, float]]:
    """95% interval per class, so a thin class cannot be read as if it were precise."""
    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    index_of = {g: np.flatnonzero(groups == g) for g in unique}

    draws = np.empty((rounds, len(labels)))
    for i in range(rounds):
        picked = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([index_of[g] for g in picked])
        draws[i] = f1_score(truth[idx], predicted[idx], labels=labels,
                            average=None, zero_division=0)
    low, high = np.percentile(draws, 2.5, axis=0), np.percentile(draws, 97.5, axis=0)
    return {t: (float(low[i]), float(high[i])) for i, t in enumerate(labels)}


def mcnemar(truth: list[str], a: list[str], b: list[str]) -> tuple[int, int, float]:
    """Paired test for two models on the same examples.

    Returns (a-only-right, b-only-right, p). Only the disagreements carry information,
    which is exactly why comparing two accuracy numbers is the wrong test.
    """
    from scipy.stats import binomtest

    truth, a, b = np.asarray(truth), np.asarray(a), np.asarray(b)
    a_right, b_right = a == truth, b == truth
    only_a = int(np.sum(a_right & ~b_right))
    only_b = int(np.sum(~a_right & b_right))
    if only_a + only_b == 0:
        return only_a, only_b, 1.0
    return only_a, only_b, float(binomtest(only_a, only_a + only_b, 0.5).pvalue)


def top_confusions(sc: Score, limit: int = 10) -> list[tuple[str, str, int]]:
    if not sc.matrix:
        return []
    out = [
        (sc.labels[i], sc.labels[j], count)
        for i, row in enumerate(sc.matrix)
        for j, count in enumerate(row)
        if i != j and count
    ]
    return sorted(out, key=lambda t: -t[2])[:limit]
