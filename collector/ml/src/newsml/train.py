"""Fit the shipping classifier, choose its abstention cuts, and write the bundle.

This is the one place a model is produced. It reads a frozen snapshot, so the
answer to "what data made this?" is a directory name rather than a memory of
which day the database was read.

Three decisions are made here and each is a measurement rather than a preference:

* **Which rung ships.** `tfidf_linear_svc` wins on macro-F1 but emits a margin
  with no scale that compares across classes, and a confidence threshold needs
  one. So the candidates are narrowed to rungs that can say how sure they are,
  and the best of those ships — after the cost of calibration is measured, not
  assumed.
* **Where each class's cut sits.** Chosen on validation, per class, against a
  precision target. See `thresholds`.
* **What the artifact has to carry.** Enough that a prediction in production can
  be traced to the exact corpus, labels and code that produced it. A bundle that
  cannot be traced is not a released model, it is a pickle.

The model is fitted on train only, never on train+val. Refitting on validation
would make the thresholds — which were chosen on validation — a measurement of
the model's own training data.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn

from . import models as models_mod
from . import thresholds as thresholds_mod
from .config import SEED
from .dataset import Dataset
from .labels import Taxonomy
from .snapshot import Snapshot, git_sha


@dataclass(frozen=True, slots=True)
class Report:
    """Everything one training run learned, in the order a reader needs it."""

    provenance: dict[str, object]
    ladder: tuple[models_mod.Result, ...]
    abstention: dict[str, dict[str, float]]
    chosen: str
    thresholds: thresholds_mod.Thresholds
    directory: Path
    bundle_bytes: int


def run(
    snap: Snapshot,
    taxonomy: Taxonomy,
    data: Dataset,
    *,
    out_root: Path,
    repo: Path,
    target_precision: float = 0.80,
    seed: int = SEED,
) -> Report:
    """Run the ladder, pick the rung that can abstain, and write the artifact."""
    x_val, y_val = data.xy("val")
    classes = list(data.classes)

    # Two rungs appear on both lists; fit each exactly once.
    results: dict[str, models_mod.Result] = {}
    fitted: dict[str, object] = {}
    for name in dict.fromkeys(models_mod.LADDER + models_mod.ABSTAINING):
        result, model = models_mod.evaluate(name, data, split="val", seed=seed)
        results[name], fitted[name] = result, model

    ladder = tuple(results[name] for name in models_mod.LADDER)

    abstention: dict[str, dict[str, float]] = {}
    for name in models_mod.ABSTAINING:
        cut_names, proba = models_mod.probabilities(fitted[name], x_val)  # type: ignore[arg-type]
        cuts = thresholds_mod.choose(cut_names, proba, y_val, target_precision=target_precision)
        abstention[name] = {
            "macro_f1": results[name].macro_f1,
            "accuracy": results[name].accuracy,
            "coverage": cuts.coverage,
            "accuracy_on_kept": cuts.accuracy_on_kept,
            "macro_f1_on_kept": cuts.macro_f1_on_kept,
            "unreached": len(cuts.unreached),
            "ms_per_doc": results[name].predict_ms_per_doc,
        }

    # Among rungs that can abstain, ship the one that classifies best. Coverage
    # is a threshold decision and can be retuned; macro-F1 cannot.
    chosen = max(abstention, key=lambda name: abstention[name]["macro_f1"])
    model = fitted[chosen]
    names, proba = models_mod.probabilities(model, x_val)  # type: ignore[arg-type]
    cuts = thresholds_mod.choose(names, proba, y_val, target_precision=target_precision)

    version = f"{chosen}-{snap.snapshot_id}"
    directory = out_root / version
    directory.mkdir(parents=True, exist_ok=True)

    bundle = directory / "model.joblib"
    joblib.dump(model, bundle, compress=3)

    manifest = {
        "model_version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(repo),
        "model": chosen,
        "serving": "python-sidecar",
        "dataset_snapshot_id": snap.snapshot_id,
        "cleaning_version": snap.provenance.get("cleaning_version"),
        "taxonomy_version": snap.provenance.get("taxonomy_version"),
        "collected_before": snap.provenance.get("collected_before"),
        "text_variant": data.variant,
        "seed": seed,
        "runtime": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "vectorizer": _vectorizer_config(model),
        "classes": classes,
        "label_map": {str(i): topic for i, topic in enumerate(names)},
        "thresholds": {
            "target_precision": target_precision,
            "chosen_on": "val",
            "per_class": cuts.per_class,
            "unreached": list(cuts.unreached),
        },
        "metrics": {
            "split": "val",
            "n_train": len(data.train),
            "n_val": len(data.val),
            "macro_f1": abstention[chosen]["macro_f1"],
            "accuracy": abstention[chosen]["accuracy"],
            "coverage": cuts.coverage,
            "accuracy_on_kept": cuts.accuracy_on_kept,
            "macro_f1_on_kept": cuts.macro_f1_on_kept,
            "ms_per_doc": abstention[chosen]["ms_per_doc"],
            "per_class_f1": results[chosen].per_class_f1,
            "ladder": {r.name: r.row() for r in ladder},
            "abstention_candidates": abstention,
        },
        "bundle_bytes": bundle.stat().st_size,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (directory / "model-card.md").write_text(_model_card(manifest, cuts, data), encoding="utf-8")

    return Report(
        provenance=dict(snap.provenance),
        ladder=ladder,
        abstention=abstention,
        chosen=chosen,
        thresholds=cuts,
        directory=directory,
        bundle_bytes=bundle.stat().st_size,
    )


def _vectorizer_config(model: object) -> dict[str, object]:
    """The feature settings, recorded so a serving mismatch is detectable."""
    steps = getattr(model, "named_steps", {})
    vectoriser = steps.get("vec")
    if vectoriser is None:
        return {}
    keep = ("lowercase", "ngram_range", "min_df", "max_df", "strip_accents", "sublinear_tf", "n_features")
    config = {k: v for k, v in vectoriser.get_params().items() if k in keep}
    config["type"] = type(vectoriser).__name__
    vocabulary = getattr(vectoriser, "vocabulary_", None)
    if vocabulary is not None:
        config["vocabulary_size"] = len(vocabulary)
    return config


def _model_card(manifest: dict, cuts: thresholds_mod.Thresholds, data: Dataset) -> str:
    metrics = manifest["metrics"]
    per_class = metrics.get("per_class_f1", {})
    train_counts = data.distribution("train")
    val_counts = data.distribution("val")

    lines = [
        f"# Model card — `{manifest['model_version']}`",
        "",
        "Written by `newsml train`. Do not edit by hand; retrain instead.",
        "",
        "## What it does",
        "",
        f"Reads a news headline and its opening sentence (`{manifest['text_variant']}`) and files",
        f"it under one of {len(manifest['classes'])} topics, or declines and returns `unsorted`.",
        "It is a linear model over word n-grams. It does not read the article body:",
        "body availability tracks the publisher rather than the topic, so training on",
        "it would teach the model to recognise the newspaper.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Model | `{manifest['model']}` |",
        f"| Trained at | {manifest['trained_at']} |",
        f"| Git SHA | `{manifest['git_sha']}` |",
        f"| Dataset snapshot | `{manifest['dataset_snapshot_id']}` |",
        f"| Corpus cut | {manifest['collected_before']} |",
        f"| Cleaning version | `{manifest['cleaning_version']}` |",
        f"| Taxonomy version | `{manifest['taxonomy_version']}` |",
        f"| Seed | `{manifest['seed']}` |",
        f"| scikit-learn | {manifest['runtime']['scikit_learn']} |",
        f"| Serving | {manifest['serving']} |",
        "",
        "Every label it was trained on is human. Weak labels derived from RSS section",
        "names agree with a person only about 74% of the time and cannot express",
        "`crime_justice`, `conflict_war` or `disaster_accident` at all, because no",
        "publisher runs those sections.",
        "",
        "## How it scored",
        "",
        "On the validation split. **The test split has not been opened.**",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Macro-F1 | {metrics['macro_f1']:.3f} |",
        f"| Accuracy | {metrics['accuracy']:.3f} |",
        f"| Coverage after abstention | {metrics['coverage']:.1%} |",
        f"| Accuracy on the articles it files | {metrics['accuracy_on_kept']:.3f} |",
        f"| Inference | {metrics['ms_per_doc']:.3f} ms/article |",
        f"| Bundle size | {manifest['bundle_bytes'] / 1e6:.1f} MB |",
        f"| Training articles | {metrics['n_train']:,} |",
        "",
        "Macro-F1 is the headline, not accuracy: with this many classes a model that",
        "ignores every small class still posts a respectable accuracy.",
        "",
        "## Per class",
        "",
        "| Class | Train | Val | F1 | Cut | Precision at the cut | Reached target |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for choice in sorted(cuts.choices, key=lambda c: -per_class.get(c.topic, 0.0)):
        cut_display = "—" if choice.forced else f"{choice.cut:.2f}"
        precision_display = "—" if choice.forced else f"{choice.precision:.2f}"
        reached_display = "**forced abstain**" if choice.forced else ("yes" if choice.reached_target else "**no**")
        lines.append(
            f"| `{choice.topic}` | {train_counts.get(choice.topic, 0)} | {val_counts.get(choice.topic, 0)} "
            f"| {per_class.get(choice.topic, 0.0):.2f} | {cut_display} | {precision_display} "
            f"| {reached_display} |"
        )

    unreached = ", ".join(f"`{t}`" for t in cuts.unreached if t not in cuts.forced_abstain) or "none"
    forced = ", ".join(f"`{t}`" for t in cuts.forced_abstain) or "none"
    lines += [
        "",
        f"Target precision was {cuts.target_precision:.0%}. Classes that never reach it at",
        f"any cut: {unreached}. Those are not thresholds that need tuning — they are",
        "classes the model cannot yet separate, and the cut simply cannot rescue them.",
        f"Classes barred from ever being emitted, by decision rather than measurement: {forced}.",
        "",
        "## Known weaknesses",
        "",
        "- **Short text.** A headline and one sentence is 20-60 words. Some articles are",
        "  genuinely ambiguous at that length, and no threshold fixes that.",
        "- **Small classes are measured noisily.** The split is temporal, which",
        "  concentrates rare classes into very few validation articles. A per-class score",
        "  with single-digit support is not a result; the Val column above is there so",
        "  that is visible rather than implied.",
        "- **Drift is unmeasured.** The corpus spans days, not months, so nothing here",
        "  says how the model ages. Decide a retraining trigger before relying on it.",
        "- **One annotator.** The labels come from a single person, so annotator bias and",
        "  the model's bias are not independent.",
        "- **English only.** Every configured source is an English feed; language is",
        "  assumed from configuration rather than detected.",
        "",
        "## What it must not be used for",
        "",
        "- Deciding anything about a person. It classifies subject matter, nothing else.",
        "- Any claim about how much coverage a topic receives: the class mix reflects",
        "  which feeds were configured, not what was published in the world.",
        "- Redistribution of the training corpus, which is third-party copyrighted text",
        "  collected for study.",
    ]
    return "\n".join(lines) + "\n"
