"""Turning a score into something that can be trusted, or declined.

Two separate jobs, and conflating them is how v1 shipped a number nobody could read:

* **Calibration** -- a `LinearSVC` margin is a signed distance from a hyperplane. It has
  no scale, no comparability across classes, and it is not a probability. Showing it as
  a confidence is simply wrong, so the margin is mapped to a probability first.
* **Abstention** -- even a well-calibrated probability needs a cut, and one global cut
  is the wrong shape. `sport` reaches F1 0.95 and can be trusted low; `society_lifestyle`
  sits at 0.42 and cannot be trusted anywhere. Cuts are therefore per class, and a class
  that never reaches the target precision at any cut abstains outright rather than being
  handed a fake number.

The cuts are fitted on out-of-fold probabilities from **train**, never on validation.
v1 fitted them on a validation split where `education` had 29 articles, which fits the
sample rather than the class.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import StratifiedGroupKFold

from .config import SEED

AUTO = "auto"
REVIEW = "review"
UNKNOWN = "unknown"


def align_columns(probabilities: np.ndarray, fold_classes: np.ndarray,
                  classes: np.ndarray) -> np.ndarray:
    """Put a fold's columns in the canonical class order; absent classes stay zero."""
    out = np.zeros((len(probabilities), len(classes)))
    index = {c: i for i, c in enumerate(classes)}
    for j, c in enumerate(fold_classes):
        out[:, index[c]] = probabilities[:, j]
    return out


def cross_validated_probabilities(
    build: Callable[[], object],
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    x_target: np.ndarray,
    classes: np.ndarray,
    *,
    method: str = "isotonic",
    folds: int = 5,
    seed: int = SEED,
) -> np.ndarray:
    """Calibrate across folds of the fitting set, then average onto a target set.

    Each fold fits the base model on `folds-1`/`folds` of the data and the calibrator on
    the held-out remainder, so the calibrator never sees rows its own base model was
    fitted on. Written by hand rather than through `CalibratedClassifierCV(cv=...)`
    because the splitter needs `groups`, and sklearn only routes that with metadata
    routing switched on.

    Note `cv="prefit"` was removed in scikit-learn 1.8; `FrozenEstimator` replaces it.
    """
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    total = np.zeros((len(x_target), len(classes)))
    for fit_idx, cal_idx in splitter.split(x, y, groups):
        base = build().fit(x[fit_idx], y[fit_idx])
        calibrated = CalibratedClassifierCV(FrozenEstimator(base), method=method).fit(
            x[cal_idx], y[cal_idx]
        )
        total += align_columns(calibrated.predict_proba(x_target), calibrated.classes_, classes)
    return total / folds


def brier(probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray) -> float:
    """Multiclass Brier score: mean squared error against the one-hot truth. Lower is better."""
    index = {c: i for i, c in enumerate(classes)}
    onehot = np.zeros_like(probabilities)
    onehot[np.arange(len(truth)), [index[t] for t in truth]] = 1.0
    return float(np.mean(np.sum((probabilities - onehot) ** 2, axis=1)))


def log_loss(probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray,
             *, floor: float = 1e-15) -> float:
    index = {c: i for i, c in enumerate(classes)}
    picked = probabilities[np.arange(len(truth)), [index[t] for t in truth]]
    return float(-np.mean(np.log(np.clip(picked, floor, 1.0))))


@dataclass(frozen=True, slots=True)
class Bin:
    low: float
    high: float
    n: int
    confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        return self.accuracy - self.confidence


def reliability(probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray,
                *, bins: int = 10) -> tuple[Bin, ...]:
    """Top-label reliability: in each confidence band, is the model as right as it claims?"""
    confidence = probabilities.max(axis=1)
    predicted = classes[probabilities.argmax(axis=1)]
    correct = predicted == truth

    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for low, high in zip(edges[:-1], edges[1:]):
        inside = (confidence > low) & (confidence <= high) if low > 0 else confidence <= high
        if not inside.any():
            continue
        out.append(Bin(float(low), float(high), int(inside.sum()),
                       float(confidence[inside].mean()), float(correct[inside].mean())))
    return tuple(out)


def expected_calibration_error(probabilities: np.ndarray, truth: np.ndarray,
                               classes: np.ndarray, *, bins: int = 10) -> float:
    """Average gap between claimed confidence and observed accuracy, weighted by bin size."""
    buckets = reliability(probabilities, truth, classes, bins=bins)
    total = sum(b.n for b in buckets)
    if not total:
        return 0.0
    return float(sum(b.n * abs(b.gap) for b in buckets) / total)


@dataclass(frozen=True, slots=True)
class Cut:
    topic: str
    auto: float
    review: float
    auto_precision: float
    review_precision: float
    support: int

    @property
    def forced_abstain(self) -> bool:
        """No score reaches even the review bar, so this class never files on its own."""
        return math.isinf(self.review)


def _lowest_cut(scores: np.ndarray, correct: np.ndarray, target: float,
                *, min_kept: int) -> tuple[float, float]:
    """Lowest score whose kept set still reaches `target` precision.

    Lowest, not highest: a higher cut always looks better on precision and files almost
    nothing. Returns (inf, nan) when no cut reaches the target at all -- which is a real
    answer about the class, not a failure to search.
    """
    order = np.argsort(-scores)
    scores, correct = scores[order], correct[order]
    running = np.cumsum(correct)
    kept = np.arange(1, len(scores) + 1)
    precision = running / kept

    viable = np.flatnonzero((precision >= target) & (kept >= min_kept))
    if viable.size == 0:
        return math.inf, math.nan
    last = viable[-1]
    return float(scores[last]), float(precision[last])


def fit_cuts(
    probabilities: np.ndarray,
    truth: np.ndarray,
    classes: np.ndarray,
    *,
    auto_precision: float = 0.90,
    review_precision: float = 0.70,
    min_kept: int = 10,
) -> dict[str, Cut]:
    """Per-class score bands, fitted on out-of-fold probabilities.

    A class is judged only on the rows it actually claims -- where it is the argmax --
    because that is the decision the cut governs at inference.
    """
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)

    cuts: dict[str, Cut] = {}
    for topic in classes:
        claimed = predicted == topic
        if not claimed.any():
            cuts[topic] = Cut(topic, math.inf, math.inf, math.nan, math.nan, 0)
            continue
        scores = confidence[claimed]
        correct = (truth[claimed] == topic).astype(float)
        auto, auto_p = _lowest_cut(scores, correct, auto_precision, min_kept=min_kept)
        review, review_p = _lowest_cut(scores, correct, review_precision, min_kept=min_kept)
        # A review bar above the auto bar is nonsense; collapse it.
        review = min(review, auto)
        cuts[topic] = Cut(topic, auto, review, auto_p, review_p, int(claimed.sum()))
    return cuts


def fit_global_cut(probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray,
                   *, target: float = 0.90, min_kept: int = 50) -> tuple[float, float]:
    """One cut for every class, which is enough once the probabilities are calibrated.

    Per-class cuts exist because raw scores are not comparable between classes.
    Calibration removes that problem, and measured on this corpus the per-class version
    then buys nothing -- so the shipping policy is this single number.
    """
    correct = (classes[probabilities.argmax(axis=1)] == truth).astype(float)
    return _lowest_cut(probabilities.max(axis=1), correct, target, min_kept=min_kept)


@dataclass(frozen=True, slots=True)
class Routed:
    labels: np.ndarray
    bands: np.ndarray
    unsorted: str

    def coverage(self, *, including_review: bool = False) -> float:
        keep = self.bands == AUTO
        if including_review:
            keep = keep | (self.bands == REVIEW)
        return float(keep.mean())

    def accuracy_on_kept(self, truth: np.ndarray, *, including_review: bool = False) -> float:
        keep = self.bands == AUTO
        if including_review:
            keep = keep | (self.bands == REVIEW)
        if not keep.any():
            return math.nan
        return float((self.labels[keep] == truth[keep]).mean())


def route(probabilities: np.ndarray, classes: np.ndarray, cuts: dict[str, Cut],
          *, unsorted: str = "unsorted") -> Routed:
    """File, flag for review, or decline -- per the class's own cuts."""
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)

    labels = np.full(len(predicted), unsorted, dtype=object)
    bands = np.full(len(predicted), UNKNOWN, dtype=object)
    for i, (topic, score) in enumerate(zip(predicted, confidence)):
        cut = cuts.get(topic)
        if cut is None:
            continue
        if score >= cut.auto:
            labels[i], bands[i] = topic, AUTO
        elif score >= cut.review:
            labels[i], bands[i] = topic, REVIEW
    return Routed(labels, bands, unsorted)
