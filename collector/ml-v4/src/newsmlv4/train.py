"""Choose, calibrate and save the V4 topic classifier with explicit label provenance.

The first run's 2,278 topical annotations motivated the stratified protocol below.
The later D16 pool has a separate AI-label input path. All existing classifier
labels, including round 1 formerly called human gold, are AI-generated (owner
correction, 22 Nov 2026). Scores and calibration on that pool measure AI-label
agreement only; human validation is not met and no local candidate is promoted.

* **Every split is stratified.** In the original round-1 export, IDs had timestamps
  within four hours on 10 Nov, not publication order; a temporal 70/15/15 split
  would have left about four disaster articles to validate on. A stratified test
  split is sealed first; the rung is chosen inside the rest with repeated stratified
  K-fold, so every fold scores every class.
* **Complexity has to earn its place.** Every rung is scored on the same folds, so
  the differences are paired. The best mean is saved only if a corrected resampled
  t-test separates it from every simpler rung; otherwise the simplest rung it cannot
  be separated from is saved instead.
* **The test split is opened once,** after the rung, the calibration and the cut are
  frozen. A model directory for the same primary label corpus is never overwritten.

The ladder reuses ml-v2's measured rungs and adds what its Phase E did not try on
short text: frozen sentence embeddings, which bring outside knowledge to classes with
a few dozen labels, a lexical-plus-semantic linear model, and a small neural network.
Trees are left out: Phase E measured them 0.04-0.09 macro-F1 behind the linear
models on this kind of text.

The local winner uses ml-v2's recipe: five cross-fitted base models, each
with its own calibrator, averaged, plus one global confidence cut read from
out-of-fold probabilities. Below the cut it answers `unsorted`.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Mapping, Sequence

import joblib
import numpy as np
import sklearn
from scipy import stats
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold, train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC
from sklearn.utils.class_weight import compute_class_weight

from newsml.annotate import read_gold, read_sheet_texts
from newsml.labels import Taxonomy, load_taxonomy
from newsml.snapshot import git_sha
from newsmlv2 import confidence, evaluate
from newsmlv2 import models as v2_models
from newsmlv2.config import UNSORTED

from .sampling import COLLECTOR_ROOT, DATA_ROOT, TAXONOMY_PATH, WEAK_LABELS, _records, unescape_cell
from .verify import compare_sheets, load_selection

SEED = 20261110  # the V4 export seed
FOLDS = 5
REPEATS = 3
TEST_SHARE = 0.20
TARGET_PRECISION = 0.80  # `newsml train`'s existing default
DIAL = (0.80, 0.85, 0.90)
ALPHA = 0.05
MIN_KEPT = 50  # ml-v2's floor for a global cut
CALIBRATION_METHODS = ("sigmoid", "isotonic")
VARIANT = "title_summary"
BUNDLE = "bundle.joblib"
MODELS_DIR = "models"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # ml-v2 Phase E4's encoder
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_BATCH = 32
MLP_FEATURES = 20_000
# Only the genuine-human --run path adds +weak rungs; the D16 pool is a separate input.
WEAK_SUFFIX = "+weak"
WEAK_CONFIDENCE = ("high", "medium")

V2_RUNGS = ("majority", "complement_nb", "tfidf_logreg", "tfidf_linear_svc", "word_char_svc")
EMBEDDING_RUNGS = ("minilm_logreg", "hybrid_svc")
# Simplest first: when rungs cannot be separated, the earlier one is saved.
LADDER = V2_RUNGS + EMBEDDING_RUNGS + ("keras_mlp",)

Encoder = Callable[[list[str]], np.ndarray]


def text_for(title: str, summary: str) -> str:
    """Local V4 input: the annotated title and summary, not the sidecar's body recipe."""
    return f"{title.strip()}\n{summary.strip()}"


# --- Data ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabelData:
    """Topical labels, their exact input text and their declared origin."""

    ids: np.ndarray
    texts: np.ndarray
    labels: np.ndarray
    unsorted_texts: tuple[str, ...]
    unsorted_ids: tuple[str, ...]
    runs: tuple[dict[str, Any], ...]
    per_class_target: int
    digest: str
    label_source: Literal["human", "ai-agent"] = "human"
    provenance_decision: str | None = None
    audit: Mapping[str, Any] | None = None


def load_gold(runs: Sequence[str], *, taxonomy: Taxonomy, data_root: Path = DATA_ROOT) -> LabelData:
    """Read the imported gold and reviewed sheets of every run, refusing anything unverified.

    The text comes from the sheets because that is what the reviewers judged; the
    export fingerprints prove it is also what the database held when it was drawn.
    """
    if not runs:
        raise ValueError("name at least one run")
    correction_path = data_root / "provenance-correction.json"
    if correction_path.is_file():
        correction = json.loads(correction_path.read_text(encoding="utf-8"))
        if (
            not isinstance(correction, dict) or correction.get("label_source") != "ai-agent"
            or not isinstance(correction.get("corrected_runs"), list)
            or not isinstance(correction.get("decision"), str)
        ):
            raise ValueError("invalid label provenance correction")
        if corrected := set(runs) & set(correction["corrected_runs"]):
            raise ValueError(
                f"{sorted(corrected)} are AI-generated ({correction['decision']}); "
                "use --dataset with the pooled AI-label corpus, not the human-gold path"
            )
    allowed = taxonomy.ids | {taxonomy.unsorted}
    ids: list[str] = []
    texts: list[str] = []
    labels: list[str] = []
    unsorted_texts: list[str] = []
    unsorted_ids: list[str] = []
    provenance: list[dict[str, Any]] = []
    targets: set[int] = set()
    seen: set[str] = set()
    digest = hashlib.sha256()

    for name in sorted(set(runs)):
        run = data_root / name
        selection = load_selection(run, data_root)
        _, missing, changed, conflicts = compare_sheets(run, selection)
        if missing or changed or conflicts:
            raise ValueError(
                f"{name}: sheets differ from the export ({missing} missing, {changed} changed, "
                f"{conflicts} conflicting); run make ml4-labels-verify RUN={name}"
            )
        gold_path = run / "gold.jsonl"
        if not gold_path.is_file():
            raise FileNotFoundError(
                f"{name}: no gold.jsonl; run make ml4-labels-import RUN={name} first"
            )
        gold = read_gold(gold_path)
        if outside := set(gold) - set(selection):
            raise ValueError(f"{name}: {len(outside)} gold labels are for articles outside the export")
        if unlabelled := set(selection) - set(gold):
            raise ValueError(f"{name}: {len(unlabelled)} exported candidates have no gold label")
        if invalid := {topic for topic in gold.values() if topic not in allowed}:
            raise ValueError(f"{name}: labels outside the taxonomy: {sorted(invalid)}")
        if repeated := seen & set(gold):
            raise ValueError(f"{name}: {len(repeated)} articles are also labelled in another run")
        seen |= set(gold)

        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        target = manifest.get("per_class")
        if not isinstance(target, int) or target < 1:
            raise ValueError(f"{name}: the export manifest has no per-class target")
        targets.add(target)

        sheet_texts = read_sheet_texts(sorted(run.glob("*.csv")))
        raw = gold_path.read_bytes()
        digest.update(name.encode("utf-8") + b"\0" + raw + b"\0")
        provenance.append(
            {"run": name, "gold_sha256": hashlib.sha256(raw).hexdigest(), "labels": len(gold)}
        )
        for article_id in sorted(gold):
            title, summary = sheet_texts[article_id]
            text = text_for(unescape_cell(title), unescape_cell(summary))
            if gold[article_id] == taxonomy.unsorted:
                unsorted_texts.append(text)
                unsorted_ids.append(article_id)
                continue
            ids.append(article_id)
            texts.append(text)
            labels.append(gold[article_id])

    if len(targets) != 1:
        raise ValueError(f"runs disagree on the per-class target: {sorted(targets)}")
    return LabelData(
        ids=np.array(ids, dtype=object),
        texts=np.array(texts, dtype=object),
        labels=np.array(labels, dtype=object),
        unsorted_texts=tuple(unsorted_texts),
        unsorted_ids=tuple(unsorted_ids),
        runs=tuple(provenance),
        per_class_target=targets.pop(),
        digest=digest.hexdigest(),
    )


def load_dataset(directory: Path, *, taxonomy: Taxonomy, data_root: Path = DATA_ROOT) -> LabelData:
    """Read an immutable pooled AI-label corpus without interpreting its labels as human gold."""
    if not directory.resolve().is_relative_to(data_root.resolve()) or not directory.is_dir():
        raise ValueError(f"dataset must be a directory inside {data_root}")
    manifest_path, labels_path = directory / "manifest.json", directory / "labels.jsonl"
    if any(not path.resolve().is_relative_to(directory.resolve()) for path in (manifest_path, labels_path)):
        raise ValueError("a dataset file points outside its directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "ai_generated_labels_not_gold"
        or manifest.get("label_source") != "ai-agent"
        or manifest.get("human_labels") != 0
        or manifest.get("provenance_decision") != "D16"
        or manifest.get("taxonomy_sha256") != hashlib.sha256(TAXONOMY_PATH.read_bytes()).hexdigest()
    ):
        raise ValueError("expected a current-taxonomy AI-label dataset, not human gold")
    raw = labels_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest.get("labels_sha256"):
        raise ValueError("dataset labels changed since the pool was built")
    target = manifest.get("per_class_target")
    if target != 200:
        raise ValueError("dataset has no valid per-class target")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources or any(
        not isinstance(source, dict) or not isinstance(source.get("run"), str)
        or source.get("label_source") != "ai-agent" for source in sources
    ):
        raise ValueError("dataset has no valid AI annotation provenance")
    ids: list[str] = []
    texts: list[str] = []
    labels: list[str] = []
    groups: set[str] = set()
    for path, number, record in _records((labels_path,)):
        article_id, topic, group = (record.get(key) for key in ("article_id", "topic", "group_id"))
        title, summary = record.get("title"), record.get("summary")
        if (
            not isinstance(article_id, str) or not article_id.strip() or article_id in ids
            or topic not in taxonomy.ids or record.get("taxonomy_version") != taxonomy.version
            or record.get("label_source") != "ai-agent"
            or record.get("provenance_decision") != "D16"
            or not isinstance(record.get("origins"), list) or not record["origins"]
            or not isinstance(group, str) or not group or group in groups
            or not isinstance(title, str) or not title.strip()
            or not isinstance(summary, str) or not summary.strip()
        ):
            raise ValueError(f"{path}:{number}: invalid, duplicate or non-AI dataset record")
        ids.append(article_id)
        texts.append(text_for(title, summary))
        labels.append(topic)
        groups.add(group)
    if dict(sorted(Counter(labels).items())) != manifest.get("counts"):
        raise ValueError("dataset class counts differ from its manifest")
    if not ids:
        raise ValueError("dataset has no usable labels")
    return LabelData(
        ids=np.array(ids, dtype=object),
        texts=np.array(texts, dtype=object),
        labels=np.array(labels, dtype=object),
        unsorted_texts=(),
        unsorted_ids=(),
        runs=tuple(manifest["sources"]),
        per_class_target=target,
        digest=digest,
        label_source="ai-agent",
        provenance_decision=manifest["provenance_decision"],
        audit=manifest,
    )


def check_balance(
    labels: np.ndarray,
    classes: Sequence[str],
    *,
    target: int,
    folds: int,
    accept_shortfall: bool,
) -> dict[str, int]:
    """Refuse to train on too few labels; return the shortfall the owner has accepted.

    Two bars. Below `2 x folds` a class cannot be stratified honestly, and nothing
    overrides that; a taxonomy class with no labels at all is the extreme case, since
    the model could never predict it. Below the per-class target, training waits for
    more labels unless the owner has recorded the shortfall as not met (roadmap ML4.2).
    """
    counts = Counter(labels.tolist())
    floor = 2 * folds
    every_class = sorted(set(classes) | set(counts))
    if thin := {topic: counts.get(topic, 0) for topic in every_class if counts.get(topic, 0) < floor}:
        raise ValueError(f"too few labels to stratify {folds} folds (need {floor} each): {thin}")
    short = {
        topic: target - counts.get(topic, 0)
        for topic in sorted(classes)
        if counts.get(topic, 0) < target
    }
    if short and not accept_shortfall:
        listing = ", ".join(f"{topic} {counts.get(topic, 0)}" for topic in short)
        raise ValueError(
            f"{len(short)} classes are below the {target}/class target ({listing}). Label more, "
            "or pass --accept-shortfall once the owner has recorded the shortfall as not met"
        )
    return short


@dataclass(frozen=True, slots=True)
class Weak:
    """AI-agent labels that may help fit a model but never score one."""

    ids: np.ndarray
    texts: np.ndarray
    labels: np.ndarray
    runs: tuple[dict[str, Any], ...]
    dropped: dict[str, int]


def load_weak(
    runs: Sequence[str],
    *,
    taxonomy: Taxonomy,
    exclude: set[str],
    classes: Sequence[str],
    human_runs: Sequence[str] = (),
    data_root: Path = DATA_ROOT,
) -> Weak:
    """Read AI-agent labels with the exact text of their blind sheets.

    Human labels always win: an article in `exclude` (every human-labelled ID,
    `unsorted` included) is dropped, as are low-confidence judgements and classes that
    no human label can score. A weak run that already has human gold must also be
    trained as a human run, so its human labels are never silently replaced.
    """
    ids: list[str] = []
    texts: list[str] = []
    labels: list[str] = []
    provenance: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for name in sorted(set(runs)):
        run = data_root / name
        if (run / "gold.jsonl").is_file() and name not in human_runs:
            raise ValueError(f"{name} has human gold; pass it with --run so its human labels win")
        selection = load_selection(run, data_root)
        _, missing, changed, _ = compare_sheets(run, selection)
        if missing or changed:
            raise ValueError(f"{name}: sheets differ from the export ({missing} missing, {changed} changed)")
        path = run / WEAK_LABELS
        if not path.is_file():
            raise FileNotFoundError(f"{name}: no {WEAK_LABELS}")
        sheet_texts = read_sheet_texts(sorted(run.glob("*.csv")))
        used = 0
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            article_id, topic = record.get("article_id"), record.get("topic")
            if (
                article_id not in selection
                or article_id in ids
                or record.get("label_source") != "ai-agent"
                or record.get("taxonomy_version") != taxonomy.version
                or topic not in taxonomy.ids
            ):
                raise ValueError(f"{path}:{number}: expected one ai-agent label per exported candidate")
            if article_id in exclude:
                dropped["human_label"] += 1
            elif record.get("confidence") not in WEAK_CONFIDENCE:
                dropped["low_confidence"] += 1
            elif topic not in classes:
                dropped["class_without_human_labels"] += 1
            else:
                title, summary = sheet_texts[article_id]
                ids.append(article_id)
                texts.append(text_for(unescape_cell(title), unescape_cell(summary)))
                labels.append(topic)
                used += 1
        provenance.append(
            {"run": name, "weak_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "used": used}
        )
    return Weak(
        ids=np.array(ids, dtype=object),
        texts=np.array(texts, dtype=object),
        labels=np.array(labels, dtype=object),
        runs=tuple(provenance),
        dropped=dict(dropped),
    )


def _rung(name: str) -> tuple[str, bool]:
    """A ladder entry's base rung, and whether it also fits on weak labels."""
    if name.endswith(WEAK_SUFFIX):
        return name[: -len(WEAK_SUFFIX)], True
    return name, False


def _with_weak(x: np.ndarray, y: np.ndarray, weak: Weak | None, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Primary fold rows, plus training-only weak rows when the entry asks for them."""
    if weak is None or not _rung(name)[1] or not len(weak.labels):
        return x, y
    return np.concatenate([x, weak.texts]), np.concatenate([y, weak.labels])


# --- Rungs --------------------------------------------------------------------

# Real-encoder vectors keyed by (model, revision, text digest), kept only while a
# training run is active. Without this, cross-validation re-encodes the same few
# thousand texts in every fold; outside a run it would grow with every article served.
_EMBEDDINGS: dict[tuple[str, str, str], np.ndarray] | None = None


@contextlib.contextmanager
def embedding_memo() -> Iterator[None]:
    """Remember sentence vectors for the length of a training run, and only then."""
    global _EMBEDDINGS
    previous, _EMBEDDINGS = _EMBEDDINGS, {}
    try:
        yield
    finally:
        _EMBEDDINGS = previous


@functools.lru_cache(maxsize=2)
def _sentence_model(name: str, revision: str) -> Any:
    from sentence_transformers import SentenceTransformer

    # CPU only: GPU and MPS kernels are not bit-reproducible (ml-v2 Phase E4).
    return SentenceTransformer(name, revision=revision, device="cpu")


class SentenceEmbedder(TransformerMixin, BaseEstimator):
    """Frozen, unit-length sentence vectors. Nothing here is fitted.

    The loaded encoder lives in a module cache rather than on the estimator, so a
    pickled model carries only the model name and revision. `encoder` stands in for
    the real model in tests.
    """

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        revision: str = EMBEDDING_REVISION,
        encoder: Encoder | None = None,
    ):
        self.model_name = model_name
        self.revision = revision
        self.encoder = encoder

    def fit(self, X, y=None):
        return self

    def transform(self, X) -> np.ndarray:
        texts = [str(text) for text in X]
        if self.encoder is not None:
            return np.asarray(self.encoder(texts), dtype=np.float32)
        keys = [
            (self.model_name, self.revision, hashlib.sha256(text.encode("utf-8")).hexdigest())
            for text in texts
        ]
        memo = _EMBEDDINGS if _EMBEDDINGS is not None else {}
        todo = {key: text for key, text in zip(keys, texts) if key not in memo}
        if todo:
            vectors = _sentence_model(self.model_name, self.revision).encode(
                list(todo.values()),
                batch_size=EMBEDDING_BATCH,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            memo.update(zip(todo, np.asarray(vectors, dtype=np.float32)))
        return np.vstack([memo[key] for key in keys])


def _keras() -> Any:
    """Import Keras on TensorFlow with deterministic ops. Only the neural rung pays for this."""
    os.environ.setdefault("KERAS_BACKEND", "tensorflow")
    # Under op determinism TensorFlow rewrites Keras's input pipeline and logs a benign
    # "NodeDef mentions attribute ... will be ignored" line at error level on every fit.
    # Level 3 hides it; real failures still raise Python exceptions.
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import keras

    if keras.backend.backend() == "tensorflow":
        import tensorflow as tf

        tf.config.experimental.enable_op_determinism()
    return keras


def _dense(X) -> np.ndarray:
    return np.asarray(X.toarray() if hasattr(X, "toarray") else X, dtype=np.float32)


class KerasMLP(ClassifierMixin, BaseEstimator):
    """One hidden layer over TF-IDF, with dropout, balanced class weights and early stopping.

    Early stopping watches a stratified slice of the training rows, never the rows
    being scored. When pickled, the fitted network travels as a `.keras` archive.
    """

    def __init__(
        self,
        hidden: int = 256,
        dropout: float = 0.5,
        epochs: int = 60,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
        patience: int = 5,
        validation_share: float = 0.1,
        seed: int = SEED,
    ):
        self.hidden = hidden
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.patience = patience
        self.validation_share = validation_share
        self.seed = seed

    def fit(self, X, y):
        keras = _keras()
        keras.utils.set_random_seed(self.seed)
        self.classes_, encoded = np.unique(np.asarray(y), return_inverse=True)
        features = _dense(X)
        weights = compute_class_weight(
            "balanced", classes=np.arange(len(self.classes_)), y=encoded
        )
        rows = np.arange(len(encoded))
        try:
            fit_rows, stop_rows = train_test_split(
                rows, test_size=self.validation_share, stratify=encoded, random_state=self.seed
            )
        except ValueError:  # a class too small to appear on both sides
            fit_rows, stop_rows = train_test_split(
                rows, test_size=self.validation_share, random_state=self.seed
            )

        model = keras.Sequential([
            keras.Input(shape=(features.shape[1],)),
            keras.layers.Dense(self.hidden, activation="relu"),
            keras.layers.Dropout(self.dropout, seed=self.seed),
            keras.layers.Dense(len(self.classes_), activation="softmax"),
        ])
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.learning_rate),
            loss="sparse_categorical_crossentropy",
        )
        model.fit(
            features[fit_rows],
            encoded[fit_rows],
            validation_data=(features[stop_rows], encoded[stop_rows]),
            epochs=self.epochs,
            batch_size=self.batch_size,
            class_weight=dict(enumerate(weights.tolist())),
            callbacks=[
                keras.callbacks.EarlyStopping(
                    monitor="val_loss", patience=self.patience, restore_best_weights=True
                )
            ],
            verbose=0,
        )
        self.model_ = model
        self.n_features_in_ = features.shape[1]
        return self

    def predict_proba(self, X) -> np.ndarray:
        # Called directly: `predict` traces a new function for every fold's network
        # and warns about retracing each time.
        features = _dense(X)
        return np.vstack([
            np.asarray(self.model_(features[start:start + 512], training=False), dtype=float)
            for start in range(0, len(features), 512)
        ])

    def predict(self, X) -> np.ndarray:
        return self.classes_[self.predict_proba(X).argmax(axis=1)]

    def __getstate__(self):
        # Copy: for classes outside sklearn, BaseEstimator hands back the live __dict__.
        state = dict(super().__getstate__())
        model = state.pop("model_", None)
        if model is not None:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "model.keras"
                model.save(path)
                state["model_archive_"] = path.read_bytes()
        return state

    def __setstate__(self, state):
        state = dict(state)
        archive = state.pop("model_archive_", None)
        super().__setstate__(state)
        if archive is not None:
            keras = _keras()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "model.keras"
                path.write_bytes(archive)
                self.model_ = keras.models.load_model(path)


def build(name: str, *, seed: int = SEED, encoder: Encoder | None = None) -> Pipeline:
    """One unfitted rung. ml-v2's rungs keep ml-v2's own fixed seed."""
    name, _ = _rung(name)
    if name in V2_RUNGS:
        return v2_models.build(name)
    if name == "minilm_logreg":
        return Pipeline([
            ("embed", SentenceEmbedder(encoder=encoder)),
            # ml-v2 Phase E4's head, unchanged.
            ("clf", LogisticRegression(
                C=10.0, max_iter=3000, class_weight="balanced", random_state=seed
            )),
        ])
    if name == "hybrid_svc":
        lexical = v2_models.build("word_char_svc").named_steps["features"]
        return Pipeline([
            ("features", FeatureUnion([
                ("lexical", lexical),
                ("semantic", SentenceEmbedder(encoder=encoder)),
            ])),
            ("clf", LinearSVC(class_weight="balanced", random_state=seed)),
        ])
    if name == "keras_mlp":
        vectoriser = v2_models.build("tfidf_linear_svc").named_steps["tfidf"]
        return Pipeline([
            ("tfidf", vectoriser.set_params(max_features=MLP_FEATURES)),
            ("clf", KerasMLP(seed=seed)),
        ])
    raise KeyError(f"unknown rung {name!r}; have {', '.join(LADDER)}")


# --- Choosing a rung ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RungResult:
    """One rung across every fold, plus its first-repeat out-of-fold score."""

    name: str
    fold_scores: tuple[float, ...]
    oof: evaluate.Score
    fit_seconds: float
    predict_ms_per_doc: float

    @property
    def mean(self) -> float:
        return float(np.mean(self.fold_scores))

    @property
    def std(self) -> float:
        return float(np.std(self.fold_scores, ddof=1)) if len(self.fold_scores) > 1 else 0.0

    def row(self) -> dict[str, Any]:
        return {
            "mean_macro_f1": round(self.mean, 4),
            "std_macro_f1": round(self.std, 4),
            "oof_macro_f1": round(self.oof.macro_f1, 4),
            "oof_macro_f1_low": round(self.oof.macro_f1_low, 4),
            "oof_macro_f1_high": round(self.oof.macro_f1_high, 4),
            "oof_accuracy": round(self.oof.accuracy, 4),
            "per_class_f1": {c.topic: round(c.f1, 4) for c in self.oof.per_class},
            "fold_scores": [round(score, 4) for score in self.fold_scores],
            "fit_seconds_per_fold": round(self.fit_seconds, 3),
            "predict_ms_per_doc": round(self.predict_ms_per_doc, 4),
        }


def cross_validate(
    names: Sequence[str],
    x: np.ndarray,
    y: np.ndarray,
    classes: np.ndarray,
    *,
    folds: int,
    repeats: int,
    seed: int,
    encoder: Encoder | None = None,
    weak: Weak | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, RungResult]:
    """Score every rung on the same repeated stratified folds, so comparisons are paired.

    On the genuine-human path, a `+weak` entry fits on the fold's human rows plus
    every weak row; weak rows never score it. The separate D16 pooled path fits
    and scores its declared AI-label corpus, without `+weak` entries.
    """
    splits = list(
        RepeatedStratifiedKFold(n_splits=folds, n_repeats=repeats, random_state=seed).split(x, y)
    )
    # Each article is its own story group: the export already dropped near-duplicates.
    articles = np.arange(len(y))
    results: dict[str, RungResult] = {}
    for name in names:
        scores: list[float] = []
        fit_seconds: list[float] = []
        predict_ms: list[float] = []
        first = np.empty(len(y), dtype=object)
        for index, (fit_idx, eval_idx) in enumerate(splits):
            model = build(name, seed=seed, encoder=encoder)
            started = time.perf_counter()
            model.fit(*_with_weak(x[fit_idx], y[fit_idx], weak, name))
            fit_seconds.append(time.perf_counter() - started)
            started = time.perf_counter()
            predicted = model.predict(x[eval_idx])
            predict_ms.append((time.perf_counter() - started) * 1000 / len(eval_idx))
            scores.append(float(
                f1_score(y[eval_idx], predicted, labels=classes, average="macro", zero_division=0)
            ))
            if index < folds:
                first[eval_idx] = predicted
        result = RungResult(
            name=name,
            fold_scores=tuple(scores),
            oof=evaluate.score(y, first.astype(str), groups=articles, seed=seed),
            fit_seconds=float(np.mean(fit_seconds)),
            predict_ms_per_doc=float(np.mean(predict_ms)),
        )
        results[name] = result
        log(f"  {name:<18} {result.mean:.3f} ± {result.std:.3f}   out-of-fold {result.oof.interval}")
    return results


@dataclass(frozen=True, slots=True)
class Comparison:
    """The best rung against one other rung, on paired fold scores."""

    rung: str
    mean_difference: float
    p_value: float
    tied: bool


def corrected_t_test(best: Sequence[float], other: Sequence[float], *, folds: int) -> tuple[float, float]:
    """Nadeau and Bengio's corrected resampled t-test on paired fold scores.

    Repeated K-fold reuses every article in several training sets, so the fold scores
    are correlated and a plain paired t-test calls far too many differences real. The
    correction inflates the variance by the test/train size ratio, 1/(K-1). Returns
    the mean difference and the one-sided p-value that `best` is better.
    """
    differences = np.asarray(best, dtype=float) - np.asarray(other, dtype=float)
    k = len(differences)
    mean = float(differences.mean())
    variance = float(differences.var(ddof=1)) if k > 1 else 0.0
    if variance == 0.0:
        return mean, 0.0 if mean > 0 else 1.0
    t = mean / math.sqrt((1 / k + 1 / (folds - 1)) * variance)
    return mean, float(stats.t.sf(t, df=k - 1))


def select(
    fold_scores: Mapping[str, Sequence[float]], *, folds: int, alpha: float = ALPHA
) -> tuple[str, str, dict[str, Comparison]]:
    """The best mean, then the simplest rung the best cannot be separated from.

    Every primary-corpus-only rung counts as simpler than every `+weak` entry,
    so optional weak labels are kept only when they measurably improve the result.
    Returns (best by mean, chosen, comparisons against the best).
    """
    ladder = (*LADDER, *(rung + WEAK_SUFFIX for rung in LADDER))
    order = [name for name in ladder if name in fold_scores]
    if not order:
        raise ValueError("no rung was scored")
    best = max(order, key=lambda name: float(np.mean(fold_scores[name])))
    comparisons: dict[str, Comparison] = {}
    for name in order:
        if name == best:
            continue
        difference, p_value = corrected_t_test(fold_scores[best], fold_scores[name], folds=folds)
        comparisons[name] = Comparison(name, difference, p_value, p_value >= alpha)
    chosen = next(name for name in order if name == best or comparisons[name].tied)
    return best, chosen, comparisons


# --- Calibration, cut and the saved local classifier ---------------------------


@dataclass(frozen=True, slots=True)
class Calibration:
    method: str
    probabilities: np.ndarray
    log_loss: float
    ece: float
    brier: float
    macro_f1: float

    def row(self) -> dict[str, float]:
        return {
            "log_loss": round(self.log_loss, 4),
            "ece": round(self.ece, 4),
            "brier": round(self.brier, 4),
            "macro_f1": round(self.macro_f1, 4),
        }


def calibrate(base: Pipeline, x: np.ndarray, y: np.ndarray, method: str) -> CalibratedClassifierCV:
    """Calibrate an already fitted model on every row given.

    One explicit all-rows split is scikit-learn's documented meaning for a frozen
    estimator. Its default 5-fold split adds only a check that fails whenever a class
    has fewer than five calibration rows, as happened in early thin-class experiments.
    """
    rows = np.arange(len(y))
    return CalibratedClassifierCV(FrozenEstimator(base), method=method, cv=[(rows, rows)]).fit(x, y)


def cross_fit(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    *,
    method: str,
    folds: int,
    seed: int,
    encoder: Encoder | None = None,
    weak: Weak | None = None,
) -> tuple[CalibratedClassifierCV, ...]:
    """ml-v2's shipping recipe: each fold fits a base model and calibrates it on the rows it held out.

    Plain stratified folds rather than ml-v2's grouped ones: every V4 article is its own
    story group, and this splitter puts every class into every calibration fold. Weak
    rows, when the entry uses them, join the base model's fit only. Calibrators see
    the primary corpus's labels: AI labels for D16, human labels for genuine human runs.
    """
    fitted = []
    for fit_idx, cal_idx in StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed).split(x, y):
        if missing := set(y.tolist()) - set(y[cal_idx].tolist()):
            raise ValueError(
                f"too few development labels to calibrate {sorted(missing)} across {folds} folds"
            )
        base = build(name, seed=seed, encoder=encoder).fit(*_with_weak(x[fit_idx], y[fit_idx], weak, name))
        fitted.append(calibrate(base, x[cal_idx], y[cal_idx], method))
    return tuple(fitted)


def average_probabilities(
    fitted: Sequence[CalibratedClassifierCV], texts: Sequence[str], classes: np.ndarray
) -> np.ndarray:
    total = np.zeros((len(texts), len(classes)))
    for fold in fitted:
        total += confidence.align_columns(fold.predict_proba(texts), fold.classes_, classes)
    return total / len(fitted)


def calibrated_oof(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    classes: np.ndarray,
    *,
    method: str,
    folds: int,
    seed: int,
    encoder: Encoder | None = None,
    weak: Weak | None = None,
) -> np.ndarray:
    """Out-of-fold probabilities from the shipping recipe, cross-fitted inside each outer fold."""
    out = np.zeros((len(y), len(classes)))
    outer = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for fit_idx, eval_idx in outer.split(x, y):
        fitted = cross_fit(
            name, x[fit_idx], y[fit_idx], method=method, folds=folds, seed=seed, encoder=encoder,
            weak=weak,
        )
        out[eval_idx] = average_probabilities(fitted, list(x[eval_idx]), classes)
    return out


def compare_calibration(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    classes: np.ndarray,
    *,
    folds: int,
    seed: int,
    encoder: Encoder | None = None,
    weak: Weak | None = None,
) -> tuple[Calibration, ...]:
    """Both calibrators, measured out of fold. Isotonic can overfit a class with a few dozen rows."""
    measured = []
    for method in CALIBRATION_METHODS:
        probabilities = calibrated_oof(
            name, x, y, classes, method=method, folds=folds, seed=seed, encoder=encoder, weak=weak
        )
        predicted = classes[probabilities.argmax(axis=1)]
        measured.append(Calibration(
            method=method,
            probabilities=probabilities,
            log_loss=confidence.log_loss(probabilities, y, classes),
            ece=confidence.expected_calibration_error(probabilities, y, classes),
            brier=confidence.brier(probabilities, y, classes),
            macro_f1=float(f1_score(y, predicted, labels=classes, average="macro", zero_division=0)),
        ))
    return tuple(measured)


def coverage_at(
    probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray, cut: float
) -> tuple[float, float]:
    """(share filed, accuracy on the filed) at one confidence cut."""
    kept = probabilities.max(axis=1) >= cut
    if not kept.any():
        return 0.0, math.nan
    predicted = classes[probabilities.argmax(axis=1)]
    return float(kept.mean()), float((predicted[kept] == truth[kept]).mean())


def per_class_at_cut(
    probabilities: np.ndarray, truth: np.ndarray, classes: np.ndarray, cut: float
) -> dict[str, dict[str, Any]]:
    """What each class files at the global cut, and how often it is right. A diagnostic."""
    predicted = classes[probabilities.argmax(axis=1)]
    kept = probabilities.max(axis=1) >= cut
    out: dict[str, dict[str, Any]] = {}
    for topic in classes:
        filed = kept & (predicted == topic)
        n = int(filed.sum())
        out[str(topic)] = {
            "filed": n,
            "precision": _finite(float((truth[filed] == topic).mean())) if n else None,
        }
    return out


@dataclass(frozen=True, slots=True)
class V4Classifier:
    """Cross-fitted calibrated folds, averaged, plus the cut below which it answers `unsorted`.

    It reads `text_for(title, lede)`; `serving.SidecarModel` rebuilds that input from
    a sidecar request, so this model can serve there (roadmap D19).
    """

    folds: tuple[CalibratedClassifierCV, ...]
    classes: np.ndarray
    cut: float
    metadata: dict[str, Any]

    def probabilities(self, texts: Sequence[str]) -> np.ndarray:
        return average_probabilities(self.folds, list(texts), self.classes)

    def route(self, texts: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        """(topic or `unsorted`, calibrated confidence) for each text."""
        probabilities = self.probabilities(texts)
        scores = probabilities.max(axis=1)
        called = self.classes[probabilities.argmax(axis=1)]
        return np.where(scores >= self.cut, called, UNSORTED), scores

    def classify(self, title: str, summary: str) -> tuple[str, float]:
        labels, scores = self.route([text_for(title, summary)])
        return str(labels[0]), float(scores[0])


# --- The run ---------------------------------------------------------------------


@embedding_memo()
def run(
    runs: Sequence[str],
    *,
    dataset: Path | None = None,
    data_root: Path = DATA_ROOT,
    out: Path | None = None,
    models: Sequence[str] = LADDER,
    folds: int = FOLDS,
    repeats: int = REPEATS,
    test_share: float = TEST_SHARE,
    target_precision: float = TARGET_PRECISION,
    seed: int = SEED,
    accept_shortfall: bool = False,
    min_kept: int = MIN_KEPT,
    weak_runs: Sequence[str] = (),
    encoder: Encoder | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    """Choose, calibrate, test once and save. Returns the model directory."""
    if unknown := [name for name in models if name not in LADDER]:
        raise KeyError(f"unknown rungs {unknown}; have {', '.join(LADDER)}")
    if not 0.0 < test_share < 1.0 or folds < 2 or repeats < 1:
        raise ValueError("need 0 < test share < 1, at least 2 folds and at least 1 repeat")
    if dataset is not None and (runs or weak_runs):
        raise ValueError("--dataset cannot be mixed with human --run or --weak-run")

    taxonomy = load_taxonomy(TAXONOMY_PATH)
    gold = (
        load_dataset(dataset, taxonomy=taxonomy, data_root=data_root)
        if dataset is not None else load_gold(runs, taxonomy=taxonomy, data_root=data_root)
    )
    ai_labels = gold.label_source == "ai-agent"
    shortfall = check_balance(
        gold.labels,
        sorted(taxonomy.ids),
        target=gold.per_class_target,
        folds=folds,
        accept_shortfall=accept_shortfall,
    )
    # Keyed by the primary label corpus: the test split depends on nothing else, so adding
    # weak labels later must not become a second opening of the same test split.
    prefix = "v4-ai" if ai_labels else "v4"
    directory = out or data_root / MODELS_DIR / f"{prefix}-{gold.digest[:12]}"
    if directory.exists():
        raise FileExistsError(
            f"{directory} exists: the test split of this gold has been opened (an empty or "
            "partial directory means a run stopped after opening it). Move it aside "
            "deliberately before retraining"
        )

    classes = np.array(sorted(set(gold.labels.tolist())), dtype=object)
    weak = (
        load_weak(weak_runs, taxonomy=taxonomy,
                  exclude=set(gold.ids.tolist()) | set(gold.unsorted_ids),
                  classes=classes.tolist(), human_runs=runs, data_root=data_root)
        if weak_runs else None
    )
    names = list(models)
    if weak is not None and len(weak.labels):
        names += [name + WEAK_SUFFIX for name in models if name != "majority"]
    dev, test = train_test_split(
        np.arange(len(gold.labels)), test_size=test_share, stratify=gold.labels, random_state=seed
    )
    dev, test = np.sort(dev), np.sort(test)
    x, y = gold.texts[dev], gold.labels[dev]
    log(f"{len(gold.labels)} labelled articles: {len(dev)} development, {len(test)} sealed test")
    if ai_labels:
        log("All labels are AI-generated. Scores and calibration measure AI-label agreement only; "
            "human validation is not met and production promotion is not approved.")
    if weak is not None:
        log(f"{len(weak.labels)} AI-agent weak labels for training only; dropped {weak.dropped}")

    log(f"Ladder: {folds}-fold stratified cross-validation, {repeats} repeats")
    results = cross_validate(
        names, x, y, classes, folds=folds, repeats=repeats, seed=seed, encoder=encoder, weak=weak,
        log=log,
    )
    best, chosen, comparisons = select(
        {name: result.fold_scores for name, result in results.items()}, folds=folds
    )
    log(f"Best mean: {best}. Chosen: {chosen}.")

    calibrations = compare_calibration(
        chosen, x, y, classes, folds=folds, seed=seed, encoder=encoder, weak=weak
    )
    calibration = min(calibrations, key=lambda c: c.log_loss)
    oof = calibration.probabilities
    cut, achieved = confidence.fit_global_cut(
        oof, y, classes, target=target_precision, min_kept=min_kept
    )
    dial = []
    for target in sorted(set(DIAL) | {target_precision}):
        dial_cut, _ = confidence.fit_global_cut(oof, y, classes, target=target, min_kept=min_kept)
        covered, accurate = coverage_at(oof, y, classes, dial_cut)
        dial.append({
            "target_precision": target,
            "cut": _finite(dial_cut),
            "coverage": round(covered, 4),
            "accuracy_on_kept": _finite(accurate),
        })
    oof_coverage, _ = coverage_at(oof, y, classes, cut)
    log(f"Calibration: {calibration.method}. Cut {cut:.3f} files {oof_coverage:.1%} at "
        f"{achieved:.3f} out-of-fold precision.")

    version = f"{prefix}-{gold.digest[:12]}-{chosen}"
    classifier = V4Classifier(
        folds=cross_fit(
            chosen, x, y, method=calibration.method, folds=folds, seed=seed, encoder=encoder, weak=weak
        ),
        classes=classes,
        cut=cut,
        metadata={
            "model_version": version,
            "model": chosen,
            "variant": VARIANT,
            "calibration": calibration.method,
            "cut": cut,
            "target_precision": target_precision,
            "gold_digest": gold.digest,
            "seed": seed,
            "label_source": gold.label_source,
            "evaluation_basis": "ai_label_agreement" if ai_labels else "human_label_agreement",
            "production_approved": False,
        },
    )

    # The one opening of the sealed test split. Everything it could influence is frozen above,
    # and the directory marks the opening first so a run stopped part-way cannot repeat it.
    directory.mkdir(parents=True)
    split_path = directory / "split.jsonl"
    split_path.write_text(
        "".join(json.dumps({"article_id": str(gold.ids[index]), "split": split}) + "\n"
                for split, indices in (("development", dev), ("test", test)) for index in indices),
        encoding="utf-8",
    )
    x_test, y_test = gold.texts[test], gold.labels[test]
    test_probabilities = classifier.probabilities(x_test)
    predicted = classes[test_probabilities.argmax(axis=1)]
    test_score = evaluate.score(y_test, predicted, groups=np.arange(len(test)), seed=seed, with_matrix=True)
    class_intervals = evaluate.bootstrap_class_f1(
        y_test, predicted, np.arange(len(test)), list(classes), seed=seed
    )
    test_coverage, test_kept_accuracy = coverage_at(test_probabilities, y_test, classes, cut)
    unsorted_labels = (
        classifier.route(list(gold.unsorted_texts))[0] if gold.unsorted_texts else np.array([])
    )
    log(f"Test (opened once): macro-F1 {test_score.interval}, accuracy {test_score.accuracy:.3f}, "
        f"{test_coverage:.1%} filed at {_finite(test_kept_accuracy)} accuracy")

    uses_embeddings = _rung(chosen)[0] in EMBEDDING_RUNGS
    manifest = {
        "model_version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(COLLECTOR_ROOT),
        "trainer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset": str(dataset.resolve()) if dataset is not None else None,
        "dataset_manifest_sha256": (
            hashlib.sha256((dataset / "manifest.json").read_bytes()).hexdigest()
            if dataset is not None else None
        ),
        "dataset_manifest_link": (
            Path(os.path.relpath(dataset / "manifest.json", directory)).as_posix()
            if dataset is not None else None
        ),
        "dataset_audit": gold.audit,
        "label_source": gold.label_source,
        "provenance_decision": gold.provenance_decision,
        "evaluation_basis": "ai_label_agreement" if ai_labels else "human_label_agreement",
        "human_validation": "not_met" if ai_labels else "not_assessed_here",
        "human_labels": 0 if ai_labels else len(gold.labels),
        "human_per_class_target": gold.per_class_target,
        "production_approved": False,
        "runs": list(gold.runs),
        "gold_digest": gold.digest,
        "text_variant": VARIANT,
        "classes": [str(c) for c in classes],
        "counts": dict(sorted(Counter(gold.labels.tolist()).items())),
        "per_class_target": gold.per_class_target,
        "shortfall": shortfall,
        "shortfall_accepted": bool(shortfall),
        "unsorted_set_aside": len(gold.unsorted_texts),
        "weak": None if weak is None else {
            "label_source": "ai-agent",
            "runs": list(weak.runs),
            "used": len(weak.labels),
            "per_class": dict(sorted(Counter(weak.labels.tolist()).items())),
            "dropped": weak.dropped,
            "confidence_used": list(WEAK_CONFIDENCE),
            "chosen_trains_on_weak": _rung(chosen)[1],
        },
        "protocol": {
            "seed": seed,
            "test_share": test_share,
            "folds": folds,
            "repeats": repeats,
            "alpha": ALPHA,
            "selection": (
                "best mean fold macro-F1, then the simplest rung a one-sided corrected "
                "resampled t-test (Nadeau and Bengio 2003) cannot separate from it"
            ),
            "calibration": (
                f"{folds} cross-fitted folds with their own calibrators, averaged; the method "
                "with the lower out-of-fold log loss"
            ),
            "cut": f"one global cut at {target_precision} precision on out-of-fold probabilities",
            "min_kept": min_kept,
        },
        "split": {
            "development": len(dev),
            "test": len(test),
            "file": split_path.name,
            "sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
            "test_ids_sha256": hashlib.sha256(
                "\n".join(sorted(gold.ids[test].tolist())).encode("utf-8")
            ).hexdigest(),
        },
        "ladder": {name: result.row() for name, result in results.items()},
        "best_by_mean": best,
        "chosen": chosen,
        "comparisons": {
            name: {
                "mean_difference": round(c.mean_difference, 4),
                "p_value": round(c.p_value, 4),
                "tied": c.tied,
            }
            for name, c in comparisons.items()
        },
        "calibration": {
            "chosen": calibration.method,
            **{c.method: c.row() for c in calibrations},
        },
        "cut": {
            "value": _finite(cut),
            "target_precision": target_precision,
            "precision_out_of_fold": _finite(achieved),
            "coverage_out_of_fold": round(oof_coverage, 4),
            "per_class_out_of_fold": per_class_at_cut(oof, y, classes, cut),
        },
        "dial": dial,
        "test": {
            "n": len(test),
            "macro_f1": round(test_score.macro_f1, 4),
            "macro_f1_low": round(test_score.macro_f1_low, 4),
            "macro_f1_high": round(test_score.macro_f1_high, 4),
            "accuracy": round(test_score.accuracy, 4),
            "weighted_f1": round(test_score.weighted_f1, 4),
            "coverage": round(test_coverage, 4),
            "accuracy_on_kept": _finite(test_kept_accuracy),
            "ece": round(confidence.expected_calibration_error(test_probabilities, y_test, classes), 4),
            "log_loss": round(confidence.log_loss(test_probabilities, y_test, classes), 4),
            "per_class": {
                c.topic: {
                    "f1": round(c.f1, 4),
                    "f1_low": round(class_intervals[c.topic][0], 4),
                    "f1_high": round(class_intervals[c.topic][1], 4),
                    "precision": round(c.precision, 4),
                    "recall": round(c.recall, 4),
                    "support": c.support,
                }
                for c in test_score.per_class
                if c.topic in class_intervals
            },
            "top_confusions": [list(item) for item in evaluate.top_confusions(test_score)],
        },
        "unsorted_check": {
            "n": len(gold.unsorted_texts),
            "abstained": int((unsorted_labels == UNSORTED).sum()),
        },
        "embedding": (
            {"model": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION} if uses_embeddings else None
        ),
        "runtime": _runtime(chosen),
    }

    joblib.dump(classifier, directory / BUNDLE, compress=3)
    manifest["bundle_bytes"] = (directory / BUNDLE).stat().st_size
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "model-card.md").write_text(_model_card(manifest), encoding="utf-8")
    return directory


def _finite(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), 4)


def _runtime(chosen: str) -> dict[str, str]:
    chosen, _ = _rung(chosen)
    runtime = {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "numpy": np.__version__,
        "joblib": joblib.__version__,
    }
    if chosen in EMBEDDING_RUNGS:
        import sentence_transformers

        runtime["sentence_transformers"] = sentence_transformers.__version__
    if chosen == "keras_mlp":
        runtime["keras"] = _keras().__version__
    return runtime


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "—" if value is None else format(value, spec)


def _weak_sentence(weak: dict[str, Any] | None) -> str:
    if not weak:
        return "No AI-agent labels were offered."
    return (
        f"{weak['used']:,} AI-agent labels from {', '.join(r['run'] for r in weak['runs'])} were "
        "offered for training only (`+weak` rungs); they never score a model. The shipped model "
        f"{'trains on them' if weak['chosen_trains_on_weak'] else 'does not use them'}."
    )


def _model_card(m: dict[str, Any]) -> str:
    test, cut, protocol = m["test"], m["cut"], m["protocol"]
    ai_labels = m["label_source"] == "ai-agent"
    label_description = "AI-generated" if ai_labels else "human"
    total = sum(m["counts"].values())
    shortfall = m["shortfall"]
    if shortfall:
        balance = (
            f"The {m['per_class_target']}/class target is **not met** for {len(shortfall)} of "
            f"{len(m['classes'])} classes ({', '.join(shortfall)}); the owner accepted the shortfall."
        )
    else:
        balance = f"Every class meets the {m['per_class_target']}/class target."
    if ai_labels:
        balance += " This counts AI labels only; the human-label target and human validation are **not met**."
    if m["chosen"] == m["best_by_mean"]:
        reason = "it had the best mean, and the test separated it from every simpler rung"
    else:
        reason = (
            f"`{m['best_by_mean']}` had the best mean, but the test could not separate it from "
            f"this simpler rung"
        )

    lines = [
        f"# Model card — `{m['model_version']}`",
        "",
        "Written by `newsmlv4.train`. Do not edit by hand; retrain instead.",
        *([
            "",
            "**Local candidate only. All training and evaluation labels are AI-generated "
            f"(owner correction {m['provenance_decision']}). Every score below measures "
            "agreement with AI labels, not human-validated accuracy. Calibration and "
            "confidence cuts are provisional on AI labels. Production promotion is not approved.",
        ] if ai_labels else []),
        "",
        "## What it does",
        "",
        f"Reads an article's title and summary and files it under one of {len(m['classes'])} "
        f"topics, or answers `unsorted` when its calibrated confidence is below "
        f"{_fmt(cut['value'])}. It was trained on the title and summary the reviewers labelled, "
        "not on the body. The sidecar serves it through `newsmlv4.serving`, which rebuilds "
        "that input from each article.",
        "",
        "## Data",
        "",
        f"{total:,} topical articles with {label_description} labels ({m['label_source']}) from "
        f"{', '.join(r['run'] for r in m['runs'])}; {m['unsorted_set_aside']} labelled "
        f"`unsorted` were set aside. Sealed stratified test split: {m['split']['test']:,} "
        f"articles; development: {m['split']['development']:,}. {balance}",
        "",
        "The pooled corpus uses the existing AI annotation effort; no labels are called human gold."
        if ai_labels else _weak_sentence(m.get("weak")),
        *([
            "",
            f"The [dataset audit]({m['dataset_manifest_link']}) preserves source hashes, "
            "exclusion reasons, confidence levels and the historical test exclusions. "
            f"It includes {m['dataset_audit'].get('additional_proposal_articles_used', 0):,} "
            "additional articles from the original AI proposal effort. Some additional "
            "proposals have current snapshot text but no fingerprint of the original AI "
            "judgement's text; older summaries come from cleaned title-summary snapshots, "
            "not recovered raw review sheets. These limitations are not human validation.",
        ] if ai_labels else []),
        "",
        "## How the rung was chosen",
        "",
        f"{protocol['folds']}-fold stratified cross-validation, repeated {protocol['repeats']} "
        "times on the development split; every rung saw the same folds.",
        "",
        "| Rung | Macro-F1, mean ± sd over folds | Out-of-fold macro-F1 [95% CI] "
        "| Best minus rung | p | Fit s/fold |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in m["ladder"].items():
        comparison = m["comparisons"].get(name)
        lines.append(
            f"| `{name}`{' **(chosen)**' if name == m['chosen'] else ''} "
            f"| {row['mean_macro_f1']:.3f} ± {row['std_macro_f1']:.3f} "
            f"| {row['oof_macro_f1']:.3f} [{row['oof_macro_f1_low']:.3f}, {row['oof_macro_f1_high']:.3f}] "
            f"| {_fmt(comparison['mean_difference'] if comparison else None)} "
            f"| {_fmt(comparison['p_value'] if comparison else None)} "
            f"| {row['fit_seconds_per_fold']:.2f} |"
        )
    lines += [
        "",
        f"Selected `{m['chosen']}`: {reason} (one-sided corrected resampled t-test, "
        f"α = {protocol['alpha']}).",
        "",
        "## Calibration and abstention",
        "",
        "| Method | Log loss | ECE | Brier | Macro-F1 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for method in CALIBRATION_METHODS:
        row = m["calibration"][method]
        lines.append(
            f"| {method}{' **(chosen)**' if method == m['calibration']['chosen'] else ''} "
            f"| {row['log_loss']:.3f} | {row['ece']:.3f} | {row['brier']:.3f} | {row['macro_f1']:.3f} |"
        )
    lines += [
        "",
        f"The cut {_fmt(cut['value'])} reaches {_fmt(cut['precision_out_of_fold'])} precision on "
        f"out-of-fold development predictions and files {cut['coverage_out_of_fold']:.1%} of them.",
        "",
        "| Target precision | Cut | Coverage | Accuracy on filed |",
        "| --- | --- | --- | --- |",
    ]
    for row in m["dial"]:
        lines.append(
            f"| {row['target_precision']:.2f} | {_fmt(row['cut'])} | {row['coverage']:.1%} "
            f"| {_fmt(row['accuracy_on_kept'])} |"
        )
    lines += [
        "",
        "## Sealed test split (opened once)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Macro-F1 [95% CI] | {test['macro_f1']:.3f} [{test['macro_f1_low']:.3f}, {test['macro_f1_high']:.3f}] |",
        f"| Accuracy | {test['accuracy']:.3f} |",
        f"| Filed at the cut | {test['coverage']:.1%} |",
        f"| Accuracy on filed | {_fmt(test['accuracy_on_kept'])} |",
        f"| ECE | {test['ece']:.3f} |",
        f"| Articles | {test['n']:,} |",
        "",
        "| Class | Support | F1 [95% CI] | Precision | Recall |",
        "| --- | --- | --- | --- | --- |",
    ]
    for topic, row in sorted(test["per_class"].items(), key=lambda item: -item[1]["f1"]):
        lines.append(
            f"| `{topic}` | {row['support']} | {row['f1']:.2f} [{row['f1_low']:.2f}, {row['f1_high']:.2f}] "
            f"| {row['precision']:.2f} | {row['recall']:.2f} |"
        )
    confusions = ", ".join(f"{t} → {p} ({n})" for t, p, n in test["top_confusions"][:5]) or "none"
    lines += [
        "",
        f"Most frequent confusions: {confusions}. Of the {m['unsorted_check']['n']} articles "
        f"reference labels marked `unsorted`, the model declined {m['unsorted_check']['abstained']}.",
        "",
        "## Known weaknesses",
        "",
        "- **Thin classes are measured noisily.** Read the support column and the interval "
        "before trusting a per-class number.",
        "- **Drift is unmeasured.** The split is stratified, not temporal, because the article "
        "IDs carry no publication order.",
        "- **Title and summary only.** Some articles are ambiguous at that length, and no cut "
        "fixes that.",
        "",
        "## What it must not be used for",
        "",
        "- Deciding anything about a person. It classifies subject matter, nothing else.",
        "- Claims about how much coverage a topic receives: the class mix reflects how the "
        "candidates were sampled.",
        "- Redistributing the training text, which is third-party copyrighted material.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Choose, calibrate and save a local V4 classifier with explicit label provenance"
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--run", action="append",
        help="run directory inside ml-v4/data/ with an imported gold.jsonl; repeat for several rounds",
    )
    inputs.add_argument("--dataset", type=Path, help="verified pooled AI-label dataset directory")
    parser.add_argument("--models", help=f"comma-separated subset of: {', '.join(LADDER)}")
    parser.add_argument("--folds", type=int, default=FOLDS)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--test-share", type=float, default=TEST_SHARE)
    parser.add_argument("--target-precision", type=float, default=TARGET_PRECISION)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--accept-shortfall", action="store_true",
        help="train although classes are below the per-class target; only after the owner "
        "records the shortfall as not met (roadmap ML4.2)",
    )
    parser.add_argument(
        "--weak-run", action="append", default=[],
        help="run directory with AI-agent weak-labels.jsonl, used for training only; repeatable",
    )
    args = parser.parse_args(argv)
    models = tuple(name.strip() for name in args.models.split(",")) if args.models else LADDER
    try:
        directory = run(
            args.run or (),
            dataset=args.dataset,
            models=models,
            folds=args.folds,
            repeats=args.repeats,
            test_share=args.test_share,
            target_precision=args.target_precision,
            seed=args.seed,
            accept_shortfall=args.accept_shortfall,
            weak_runs=args.weak_run,
            log=lambda line: print(line, flush=True),
        )
    except (ValueError, KeyError, FileNotFoundError, FileExistsError) as exc:
        print(f"V4 training refused: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {directory}")
    return 0


if __name__ == "__main__":
    # Persist estimator classes under the importable package, never under __main__.
    from newsmlv4 import train

    raise SystemExit(train.main())
