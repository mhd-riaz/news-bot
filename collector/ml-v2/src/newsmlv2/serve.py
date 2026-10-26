"""The shipping model: fit it once, persist it, classify one article at a time.

Everything up to Phase H answered "is this model any good?". This module answers the
only question left over, which is "how does a person use it?" -- and it is deliberately
the *same* model, not a convenient approximation of it:

* fitted on **train only**, because every number in `docs/plan.md` was produced by a
  train-only fit. Refitting on train+val would ship a model that no reported figure
  actually describes, in exchange for accuracy nobody could quote.
* calibrated by the measured recipe -- five grouped folds of train, each with its own
  base estimator and isotonic calibrator, averaged. That is what `confidence.
  cross_validated_probabilities` does at evaluation time, so persisting the five folds
  reproduces the evaluated behaviour exactly rather than approximating it with
  `CalibratedClassifierCV(ensemble=False)`.
* one global confidence cut, read from the train out-of-fold probabilities, never from
  anything the model is scored on.

A `LinearSVC` margin is a signed distance from a hyperplane, so nothing here ever
returns one. Confidence is always a calibrated probability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import StratifiedGroupKFold

from . import clean, config, confidence, models

# The frozen recipe. These are not tuning knobs -- they are the outcome of Phases C-H,
# and changing one invalidates every number the model card quotes.
MODEL = "word_char_svc"
VARIANT = "title_body"
BODY_CHARS = 4000
CALIBRATION = "isotonic"
FOLDS = 5
AUTO_TARGET = 0.90

BUNDLE = "bundle.joblib"
CARD = "model-card.md"
METRICS = "metrics.json"

AUTO = confidence.AUTO
ABSTAIN = confidence.UNKNOWN


def text_for(title: str, summary: str, body: str, *, body_chars: int = BODY_CHARS) -> str:
    """Assemble model input the way the snapshot does, so training and serving agree.

    Mirrors `Snapshot.texts(..., "title_body")`, including its fallback: an article with
    no body falls back to its summary rather than training on a bare headline.
    """
    trimmed = (body or "")[:body_chars].strip()
    return f"{title or ''}\n{trimmed or (summary or '').strip()}"


def prepare(
    title: str, summary: str = "", body: str = "", *,
    boilerplate: frozenset[str] | None = None,
) -> tuple[str, str, str]:
    """Clean text with the corpus recipe and optional publisher-specific body rules.

    When no source is known, only source-independent rules apply.
    """
    cleaned_title, cleaned_summary, cleaned_body = clean.clean_article(
        title, summary, body, boilerplate=boilerplate
    )
    return cleaned_title.text, cleaned_summary.text, cleaned_body.text


@dataclass(frozen=True, slots=True)
class Prediction:
    topic: str
    confidence: float
    band: str
    probabilities: dict[str, float]
    evidence: tuple[tuple[str, float], ...] = ()

    @property
    def filed(self) -> bool:
        """Confident enough to file without a human reading it."""
        return self.band == AUTO

    @property
    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.probabilities.items(), key=lambda kv: -kv[1])


@dataclass(frozen=True, slots=True)
class Classifier:
    """Five calibrated folds, averaged, plus the cut that decides whether to file."""

    folds: tuple[CalibratedClassifierCV, ...]
    classes: np.ndarray
    cut: float
    metadata: dict

    def probabilities(self, texts: list[str]) -> np.ndarray:
        total = np.zeros((len(texts), len(self.classes)))
        for fold in self.folds:
            total += confidence.align_columns(
                fold.predict_proba(texts), fold.classes_, self.classes
            )
        return total / len(self.folds)

    def classify(self, title: str, summary: str = "", body: str = "",
                 *, explain: bool = True, top_terms: int = 12) -> Prediction:
        title, summary, body = prepare(title, summary, body)
        text = text_for(title, summary, body)
        if not text.strip():
            raise ValueError("nothing to classify: title, summary and body are all empty")

        probabilities = self.probabilities([text])[0]
        topic = str(self.classes[probabilities.argmax()])
        best = float(probabilities.max())
        return Prediction(
            topic=topic,
            confidence=best,
            band=AUTO if best >= self.cut else ABSTAIN,
            probabilities={str(c): float(p) for c, p in zip(self.classes, probabilities)},
            evidence=self.evidence(text, topic, limit=top_terms) if explain else (),
        )

    def route(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Batch form: (label-or-`unsorted`, confidence, filed?)."""
        probabilities = self.probabilities(texts)
        called = self.classes[probabilities.argmax(axis=1)]
        scores = probabilities.max(axis=1)
        filed = scores >= self.cut
        return np.where(filed, called, config.UNSORTED), scores, filed

    def evidence(self, text: str, topic: str, *, limit: int = 12) -> tuple[tuple[str, float], ...]:
        """Which words pushed this article toward the class it was given.

        A linear model over TF-IDF is one of the few that can answer this exactly rather
        than by approximation: the decision value is a plain sum of `weight x tf-idf`
        over the terms present, so the largest products *are* the reasons. Only the word
        branch is reported -- character 3-5 grams are real features but unreadable ones.

        Read from the first fold. All five are the same architecture fitted on 80%
        overlapping data; picking one keeps the explanation cheap and its ranking stable.
        """
        base = getattr(self.folds[0], "estimator", None)
        base = getattr(base, "estimator", base)  # unwrap FrozenEstimator
        if base is None or topic not in list(base.named_steps["clf"].classes_):
            return ()

        word = base.named_steps["features"].transformer_list[0][1]
        classifier = base.named_steps["clf"]
        row = word.transform([text]).tocoo()
        weights = classifier.coef_[list(classifier.classes_).index(topic)]

        names = word.get_feature_names_out()
        offset = 0  # the word branch is first in the union, so its indices are unshifted
        scored = [
            (str(names[j]), float(value * weights[offset + j]))
            for j, value in zip(row.col, row.data)
        ]
        scored = [item for item in scored if item[1] > 0]
        return tuple(sorted(scored, key=lambda kv: -kv[1])[:limit])


def fit(snapshot_id: str, *, target: float = AUTO_TARGET) -> Classifier:
    """Fit the shipping model on the train split of a frozen snapshot."""
    from . import snapshot as snapshot_mod

    snap = snapshot_mod.read(config.SNAPSHOT_DIR / snapshot_id)
    frame = snap.frame
    labelled = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    train = labelled[labelled["split"] == "train"].reset_index(drop=True)

    x = np.array(snap.texts(train, VARIANT, body_chars=BODY_CHARS), dtype=object)
    y = train["topic"].to_numpy()
    groups = train["story_group_id"].to_numpy()
    classes = np.array(sorted(set(y)))

    splitter = StratifiedGroupKFold(n_splits=FOLDS, shuffle=True, random_state=config.SEED)
    folds = []
    for fit_idx, cal_idx in splitter.split(x, y, groups):
        base = models.build(MODEL).fit(x[fit_idx], y[fit_idx])
        folds.append(
            CalibratedClassifierCV(FrozenEstimator(base), method=CALIBRATION).fit(
                x[cal_idx], y[cal_idx]
            )
        )

    cut, achieved = _global_cut(snapshot_id, y, classes, target=target)
    return Classifier(
        folds=tuple(folds),
        classes=classes,
        cut=cut,
        metadata={
            "snapshot_id": snapshot_id,
            "fitted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model": MODEL,
            "variant": VARIANT,
            "body_chars": BODY_CHARS,
            "calibration": CALIBRATION,
            "folds": FOLDS,
            "train_articles": int(len(train)),
            "classes": [str(c) for c in classes],
            "cut": cut,
            "cut_target_precision": target,
            "cut_precision_on_train_oof": achieved,
            "cleaning_version": config.CLEANING_VERSION,
            "label_digest": snap.manifest.get("label_digest", ""),
            "git_sha": snap.manifest.get("git_sha", ""),
        },
    )


def _global_cut(snapshot_id: str, y: np.ndarray, classes: np.ndarray,
                *, target: float) -> tuple[float, float]:
    """The cut, from Phase G's nested out-of-fold probabilities on train.

    Deliberately not recomputed here. Those probabilities cost five outer by three inner
    fits, and re-deriving them would be a second implementation of the same thing that
    could silently drift from the one every reported number used.
    """
    cache = config.CACHE_DIR / snapshot_id / "phase_g_train_oof.npz"
    if not cache.is_file():
        raise SystemExit(
            f"missing train out-of-fold probabilities at {cache}\n"
            "run: uv run python scripts/phase_g_confidence.py"
        )
    oof = np.load(cache, allow_pickle=True)["probabilities"]
    if len(oof) != len(y):
        raise SystemExit(
            f"the cached out-of-fold probabilities describe {len(oof)} articles but this "
            f"train split has {len(y)}; re-run scripts/phase_g_confidence.py"
        )
    return confidence.fit_global_cut(oof, y, classes, target=target)


def save(classifier: Classifier, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / BUNDLE
    joblib.dump(classifier, path, compress=3)
    classifier.metadata["bundle_mb"] = round(path.stat().st_size / 1e6, 1)
    (directory / "metadata.json").write_text(
        json.dumps(classifier.metadata, indent=2) + "\n", encoding="utf-8"
    )
    return path


def load(directory: Path) -> Classifier:
    return joblib.load(directory / BUNDLE)
