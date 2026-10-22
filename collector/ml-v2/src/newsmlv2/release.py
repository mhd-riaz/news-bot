"""Package the chosen model for a demo: bundle, metrics, model card.

Everything here is derived from the **validation** split or from train out-of-fold
probabilities. The test split was opened once on 2026-08-26 and is closed for good, so
its numbers are recorded as constants rather than recomputed -- re-running it would turn
a held-out measurement into a training signal, which is the one thing this project has
been careful not to do all the way through.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from . import config, confidence, evaluate, serve
from . import snapshot as snapshot_mod

# Recorded from `scripts/phase_h4_open_test.py`, run once with --yes on 2026-08-26.
# Do not recompute. See docs/plan.md, section H4.
TEST_RESULTS = {
    "opened_on": "2026-08-26",
    "macro_f1": 0.751,
    "macro_f1_low": 0.719,
    "macro_f1_high": 0.780,
    "accuracy": 0.778,
    "n": 1159,
    "cut": 0.584,
    "coverage": 0.807,
    "accuracy_filed": 0.834,
    "accuracy_without_abstention": 0.777,
    "ece": 0.0211,
    "predict_ms_per_article": 0.784,
    "per_class_f1": {
        "sport": 0.95, "disaster_accident": 0.87, "entertainment_arts": 0.85,
        "crime_justice": 0.82, "technology": 0.81, "science_space": 0.81,
        "business_economy": 0.78, "politics": 0.76, "environment_climate": 0.71,
        "health": 0.69, "education": 0.65, "conflict_war": 0.60,
        "society_lifestyle": 0.44,
    },
    "support": {
        "politics": 238, "business_economy": 152, "crime_justice": 113,
        "technology": 106, "sport": 86, "entertainment_arts": 82, "science_space": 81,
        "disaster_accident": 62, "environment_climate": 62, "society_lifestyle": 58,
        "health": 53, "conflict_war": 51, "education": 15,
    },
}

# The headline comparison the whole project was built to answer, from Phase C.
BODY_AB = {
    "title_summary": 0.712,
    "title_body": 0.771,
    "delta": 0.059,
    "mcnemar_p": 7.5e-06,
    "v1_parity_rung": 0.696,
    "v1_shipped": 0.720,
}


def build(snapshot_id: str, out_dir: Path) -> dict:
    """Fit, score on validation, and write bundle + metrics + card."""
    classifier = serve.fit(snapshot_id)
    metrics = _validation_report(classifier, snapshot_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    serve.save(classifier, out_dir)
    metrics["metadata"] = classifier.metadata
    (out_dir / serve.METRICS).write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (out_dir / serve.CARD).write_text(_card(metrics), encoding="utf-8")
    return metrics


def _validation_report(classifier: serve.Classifier, snapshot_id: str) -> dict:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / snapshot_id)
    frame = snap.frame
    labelled = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    val = labelled[labelled["split"] == "val"].reset_index(drop=True)

    texts = snap.texts(val, serve.VARIANT, body_chars=serve.BODY_CHARS)
    truth = val["topic"].to_numpy()
    groups = val["story_group_id"].to_numpy()

    started = time.perf_counter()
    probabilities = classifier.probabilities(texts)
    per_doc_ms = (time.perf_counter() - started) * 1000 / len(texts)

    predicted = classifier.classes[probabilities.argmax(axis=1)]
    scored = evaluate.score(truth, predicted, groups, with_matrix=True)
    intervals = evaluate.bootstrap_class_f1(truth, predicted, groups, list(scored.labels))

    counts = labelled["split"].value_counts().to_dict()
    return {
        "snapshot_id": snapshot_id,
        "splits": {k: int(v) for k, v in counts.items()},
        "classes": [str(c) for c in classifier.classes],
        "cut": classifier.cut,
        "validation": {
            "n": scored.n,
            "macro_f1": scored.macro_f1,
            "macro_f1_low": scored.macro_f1_low,
            "macro_f1_high": scored.macro_f1_high,
            "weighted_f1": scored.weighted_f1,
            "accuracy": scored.accuracy,
            "ece": confidence.expected_calibration_error(probabilities, truth, classifier.classes),
            "brier": confidence.brier(probabilities, truth, classifier.classes),
            "log_loss": confidence.log_loss(probabilities, truth, classifier.classes),
            "predict_ms_per_article": per_doc_ms,
            "per_class": [
                {
                    "topic": c.topic, "precision": c.precision, "recall": c.recall,
                    "f1": c.f1, "support": c.support,
                    "low": intervals[c.topic][0], "high": intervals[c.topic][1],
                }
                for c in sorted(scored.per_class, key=lambda c: -c.f1)
            ],
            "labels": list(scored.labels),
            "matrix": [list(row) for row in scored.matrix],
            "confusions": [
                {"actual": a, "called": b, "n": n}
                for a, b, n in evaluate.top_confusions(scored, limit=10)
            ],
        },
        "reliability": [
            {"low": b.low, "high": b.high, "n": b.n,
             "claimed": b.confidence, "actual": b.accuracy}
            for b in confidence.reliability(probabilities, truth, classifier.classes)
        ],
        "coverage_curve": _coverage_curve(probabilities, truth, classifier.classes),
        "body_ab": BODY_AB,
        "test": TEST_RESULTS,
    }


def _coverage_curve(probabilities: np.ndarray, truth: np.ndarray,
                    classes: np.ndarray) -> list[dict]:
    """The abstention dial: at each cut, how much is filed and how right is it?"""
    called = classes[probabilities.argmax(axis=1)]
    scores = probabilities.max(axis=1)
    correct = called == truth

    out = []
    for cut in np.round(np.arange(0.0, 0.96, 0.05), 2):
        kept = scores >= cut
        if not kept.any():
            continue
        out.append({
            "cut": float(cut),
            "coverage": float(kept.mean()),
            "accuracy_on_kept": float(correct[kept].mean()),
        })
    return out


def _card(metrics: dict) -> str:
    val = metrics["validation"]
    test = metrics["test"]
    meta = metrics["metadata"]
    ab = metrics["body_ab"]

    rows = "\n".join(
        f"| {c['topic']} | {c['f1']:.2f} | [{c['low']:.2f}, {c['high']:.2f}] | "
        f"{c['support']} | {test['per_class_f1'].get(c['topic'], float('nan')):.2f} |"
        for c in val["per_class"]
    )
    return f"""# Model card — news topic classifier

**Snapshot** `{metrics['snapshot_id']}` · fitted {meta['fitted_at']} · cleaning
v{meta['cleaning_version']} · label digest `{meta['label_digest'][:12]}…`

## What it does

Files an English-language news article into one of {len(metrics['classes'])} topics, and
**declines to answer when it is not confident enough**. Confidence is a calibrated
probability, never a raw SVM margin.

## Recipe

| | |
| --- | --- |
| Estimator | `{meta['model']}` — word 1–2 grams + char\\_wb 3–5 grams on the first 600 chars → LinearSVC (C=1, `class_weight="balanced"`) |
| Input | `{meta['variant']}`, body capped at {meta['body_chars']} characters |
| Calibration | {meta['calibration']}, {meta['folds']} grouped folds of train, averaged |
| Abstention | one global cut at **{metrics['cut']:.3f}**, fitted on train out-of-fold probabilities for {meta['cut_target_precision']:.0%} precision |
| Trained on | {meta['train_articles']:,} articles (train split only) |
| Bundle | {meta.get('bundle_mb', '—')} MB · {val['predict_ms_per_article']:.2f} ms/article |

## How good it is

| | macro-F1 | accuracy |
| --- | --- | --- |
| validation | {val['macro_f1']:.3f} [{val['macro_f1_low']:.3f}, {val['macro_f1_high']:.3f}] | {val['accuracy']:.3f} |
| **test** (opened once, {test['opened_on']}) | **{test['macro_f1']:.3f} [{test['macro_f1_low']:.3f}, {test['macro_f1_high']:.3f}]** | {test['accuracy']:.3f} |

With abstention on test: **{test['coverage']:.1%} of articles filed at
{test['accuracy_filed']:.1%} accuracy**, against {test['accuracy_without_abstention']:.1%}
if it is forced to answer everything.

Calibration error (ECE): validation {val['ece']:.3f}, test {test['ece']:.3f}.

**The central result:** reading the article body instead of the headline and summary is
worth **+{ab['delta']:.3f} macro-F1** ({ab['title_summary']:.3f} → {ab['title_body']:.3f},
McNemar p={ab['mcnemar_p']:.1e}).

## Per class

| Class | val F1 | 95% interval | val support | test F1 |
| --- | ---: | --- | ---: | ---: |
{rows}

## Known limits

- `society_lifestyle` is a definitional grab-bag (community + labour + lifestyle) and
  scores F1 ~0.42. It still calibrates honestly, so abstention protects it.
- `education` has {next((c['support'] for c in val['per_class'] if c['topic'] == 'education'), 0)}
  validation articles; read its F1 as noise, not as a measurement.
- ~18.6% of errors sit on class pairs where human annotators themselves disagreed, so
  macro-F1 has a real ceiling well below 1.0.
- Trained on a 4-day collection window, so nothing here measures drift over weeks.
- English only, and India-heavy: 40 publishers, mostly Indian mastheads plus The
  Guardian, BBC and France 24.
"""
