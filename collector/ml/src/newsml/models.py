"""The baseline ladder, and the one function that scores a rung of it.

Every rung has to beat the one below it or explain why not. That is the whole
design: a single model reported alone says nothing, because there is no way to
tell a good score from an easy problem. `majority` exists to make the problem's
difficulty visible before any real model is credited with solving it.

Nothing here touches the test split. `evaluate` takes the split by name and the
notebook passes `"val"`; the test split is consulted once, at the end of the
phase, by a caller that says so explicitly.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer, TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from .config import SEED
from .dataset import Dataset

# In ladder order. Each name is both the identifier and the report label.
LADDER = ("majority", "complement_nb", "tfidf_linear_svc", "hashing_sgd")

# Rungs that can put a number on how sure they are, which is what an `unsorted`
# route needs. `tfidf_linear_svc` is deliberately absent: its margin has no scale
# that compares across classes, and thresholding it would be arithmetic on an
# uncalibrated quantity.
ABSTAINING = ("calibrated_linear_svc", "hashing_sgd", "complement_nb")

# Folds for the calibration wrapper. Five is the most the thinnest class in train
# can support; raising it fails outright rather than degrading.
CALIBRATION_FOLDS = 5

# Shared across the vectorised rungs so a difference between them is the
# classifier, not the features. HashingVectorizer keeps no vocabulary, so the
# document-frequency floor cannot apply to it.
_TEXT = {"lowercase": True, "ngram_range": (1, 2), "strip_accents": "unicode"}
_VOCAB = {**_TEXT, "min_df": 2}


def build(name: str, *, seed: int = SEED) -> Pipeline:
    """Construct one rung. Unfitted, so the caller controls what it sees."""
    if name == "majority":
        return Pipeline([("clf", DummyClassifier(strategy="most_frequent", random_state=seed))])

    if name == "complement_nb":
        return Pipeline(
            [
                ("vec", TfidfVectorizer(sublinear_tf=True, **_VOCAB)),
                ("clf", ComplementNB()),
            ]
        )

    if name == "tfidf_linear_svc":
        return Pipeline(
            [
                ("vec", TfidfVectorizer(sublinear_tf=True, **_VOCAB)),
                ("clf", LinearSVC(class_weight="balanced", random_state=seed)),
            ]
        )

    if name == "calibrated_linear_svc":
        # The winning rung, wrapped so it emits a probability instead of a
        # margin. Platt scaling fits a sigmoid per class on held-out folds, which
        # costs a refit per fold and can move macro-F1 in either direction — the
        # argmax of a calibrated score is not the argmax of the raw margin. That
        # movement is the measurement Phase 3 needs, so it is a separate rung
        # rather than a change to the one above.
        return Pipeline(
            [
                ("vec", TfidfVectorizer(sublinear_tf=True, **_VOCAB)),
                (
                    "clf",
                    CalibratedClassifierCV(
                        LinearSVC(class_weight="balanced", random_state=seed),
                        method="sigmoid",
                        cv=CALIBRATION_FOLDS,
                    ),
                ),
            ]
        )

    if name == "hashing_sgd":
        # No vocabulary to store, so the serving artifact stays small and a word
        # unseen in training still hashes to a feature. modified_huber is the
        # one SGD loss that yields calibrated-ish probabilities, which Phase 3
        # needs for the per-class "unsorted" thresholds.
        return Pipeline(
            [
                ("vec", HashingVectorizer(n_features=2**18, alternate_sign=False, **_TEXT)),
                ("tfidf", TfidfTransformer(sublinear_tf=True)),
                (
                    "clf",
                    SGDClassifier(
                        loss="modified_huber",
                        class_weight="balanced",
                        max_iter=50,
                        random_state=seed,
                    ),
                ),
            ]
        )

    raise ValueError(f"unknown model {name!r}; expected one of {LADDER}")


def probabilities(model: Pipeline, texts: list[str]) -> tuple[list[str], NDArray[np.float64]]:
    """Per-class scores that are comparable across classes, and the class order.

    A rung without `predict_proba` is refused rather than substituted with
    `decision_function`. A margin ranks correctly inside one class, which is all
    ROC needs, but a single cut applied across classes compares numbers that were
    never on the same scale — and that is exactly what abstention does.
    """
    classifier = model.named_steps["clf"]
    if not hasattr(classifier, "predict_proba"):
        raise TypeError(
            f"{type(classifier).__name__} emits no probability; "
            f"use one of {ABSTAINING} for anything that thresholds a confidence"
        )
    return [str(c) for c in classifier.classes_], np.asarray(model.predict_proba(texts), dtype=float)


@dataclass(frozen=True, slots=True)
class Result:
    """One rung's score, plus the numbers the 2 GB serving budget depends on."""

    name: str
    split: str
    macro_f1: float
    accuracy: float
    per_class_f1: dict[str, float] = field(default_factory=dict)
    fit_seconds: float = 0.0
    predict_ms_per_doc: float = 0.0
    n_train: int = 0
    n_eval: int = 0

    def row(self) -> dict[str, object]:
        return {
            "model": self.name,
            "macro_f1": round(self.macro_f1, 4),
            "accuracy": round(self.accuracy, 4),
            "fit_s": round(self.fit_seconds, 2),
            "ms/doc": round(self.predict_ms_per_doc, 3),
        }


def evaluate(name: str, data: Dataset, *, split: str = "val", seed: int = SEED) -> tuple[Result, Pipeline]:
    """Fit on train, score on `split`. Returns the score and the fitted model."""
    if split == "test":
        raise ValueError("the test split is consulted once, by a caller that names it explicitly")
    return _fit_and_score(name, data, split=split, seed=seed)


def evaluate_on_test(name: str, data: Dataset, *, seed: int = SEED) -> tuple[Result, Pipeline]:
    """The one door to the test split. Separate so its use is greppable."""
    return _fit_and_score(name, data, split="test", seed=seed)


@dataclass(frozen=True, slots=True)
class GoldResult:
    """A rung scored against people rather than against the teacher that made it."""

    name: str
    macro_f1_in_scope: float
    accuracy_in_scope: float
    macro_f1_all: float
    n_gold: int
    n_in_scope: int
    n_unreachable: int
    per_class_f1: dict[str, float] = field(default_factory=dict)
    confusions: tuple[tuple[str, str, int], ...] = ()

    def row(self) -> dict[str, object]:
        return {
            "model": self.name,
            "macro_f1_in_scope": round(self.macro_f1_in_scope, 4),
            "macro_f1_all": round(self.macro_f1_all, 4),
            "accuracy_in_scope": round(self.accuracy_in_scope, 4),
            "n_gold": self.n_gold,
        }


def evaluate_on_gold(name: str, data: Dataset, *, seed: int = SEED) -> tuple[GoldResult, Pipeline]:
    """Fit on the weak labels, score against the human ones.

    Two numbers, because they answer two different questions and quoting either
    one alone is misleading. `macro_f1_in_scope` asks how well the model does on
    the classes it is capable of emitting at all. `macro_f1_all` asks how well it
    does on the news, scoring every class the weak labels never taught it as a
    zero — which is the question a reader of the report is actually asking.
    """
    x_train, y_train = data.xy("train")
    x_gold, y_gold = data.xy("gold")
    if not x_train or not x_gold:
        raise ValueError(f"empty split: train={len(x_train)} gold={len(x_gold)}")

    model = build(name, seed=seed)
    model.fit(x_train, y_train)
    predicted = [str(p) for p in model.predict(x_gold)]

    reachable = list(data.classes)
    everything = sorted(set(reachable) | set(y_gold))
    scored = [(truth, guess) for truth, guess in zip(y_gold, predicted, strict=True) if truth in set(reachable)]

    if scored:
        truths, guesses = (list(part) for part in zip(*scored, strict=True))
        per_class = dict(
            zip(reachable, f1_score(truths, guesses, labels=reachable, average=None, zero_division=0), strict=True)
        )
        macro_in_scope = float(f1_score(truths, guesses, labels=reachable, average="macro", zero_division=0))
        accuracy_in_scope = float(accuracy_score(truths, guesses))
    else:
        per_class, macro_in_scope, accuracy_in_scope = {}, 0.0, 0.0

    confusions = Counter(
        (truth, guess) for truth, guess in zip(y_gold, predicted, strict=True) if truth != guess
    )

    result = GoldResult(
        name=name,
        macro_f1_in_scope=macro_in_scope,
        accuracy_in_scope=accuracy_in_scope,
        macro_f1_all=float(f1_score(y_gold, predicted, labels=everything, average="macro", zero_division=0)),
        n_gold=len(y_gold),
        n_in_scope=len(scored),
        n_unreachable=len(y_gold) - len(scored),
        per_class_f1={k: float(v) for k, v in per_class.items()},
        confusions=tuple((t, g, n) for (t, g), n in confusions.most_common(10)),
    )
    return result, model


def _fit_and_score(name: str, data: Dataset, *, split: str, seed: int) -> tuple[Result, Pipeline]:
    x_train, y_train = data.xy("train")
    x_eval, y_eval = data.xy(split)
    if not x_train or not x_eval:
        raise ValueError(f"empty split: train={len(x_train)} {split}={len(x_eval)}")

    model = build(name, seed=seed)

    started = time.perf_counter()
    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started

    started = time.perf_counter()
    predicted = model.predict(x_eval)
    predict_ms = (time.perf_counter() - started) * 1000 / len(x_eval)

    labels = list(data.classes)
    per_class = dict(
        zip(labels, f1_score(y_eval, predicted, labels=labels, average=None, zero_division=0), strict=True)
    )

    result = Result(
        name=name,
        split=split,
        macro_f1=float(f1_score(y_eval, predicted, labels=labels, average="macro", zero_division=0)),
        accuracy=float(accuracy_score(y_eval, predicted)),
        per_class_f1={k: float(v) for k, v in per_class.items()},
        fit_seconds=fit_seconds,
        predict_ms_per_doc=predict_ms,
        n_train=len(x_train),
        n_eval=len(x_eval),
    )
    return result, model
