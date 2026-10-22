"""Phase G: make the 0.771 classifier know when it is unsure.

Nothing here raises macro-F1, and it is not supposed to. Three questions:

* **G1 calibration** -- `LinearSVC` has no `predict_proba` at all. Its margin is a signed
  distance from a hyperplane with no scale and no cross-class comparability, so it must
  never be shown as a confidence. Sigmoid against isotonic, and the cheap
  calibrate-on-validation recipe against the expensive cross-validated one.
* **G2 thresholds** -- per class, never one global cut, fitted on out-of-fold
  probabilities from train.
* **G3 imbalance** -- every Phase C-F number already used `class_weight="balanced"`, so
  this measures what that bought rather than whether to switch it on.

Note for anyone reading the plan: `cv="prefit"` was **removed** in scikit-learn 1.8.
`CalibratedClassifierCV(FrozenEstimator(fitted), ...)` is the replacement and does the
same job.
"""

from __future__ import annotations

import math
import time

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import StratifiedGroupKFold

from newsmlv2 import confidence, config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
MODEL = "word_char_svc"
OUTER_FOLDS = 5
INNER_FOLDS = 3
OOF_CACHE = config.CACHE_DIR / SNAPSHOT_ID / "phase_g_train_oof.npz"

# Precision targets, not score cuts. The plan's illustrative 0.90/0.60 were scores; a
# score means nothing across classes, whereas "file it only if 9 in 10 are right" is a
# statement about the outcome and lets the data pick the cut.
AUTO_TARGET = 0.90
REVIEW_TARGET = 0.70


def _aligned(probabilities: np.ndarray, fold_classes: np.ndarray,
             classes: np.ndarray) -> np.ndarray:
    return confidence.align_columns(probabilities, fold_classes, classes)


def _calibrate(fitted, method: str, x_cal, y_cal):
    return CalibratedClassifierCV(FrozenEstimator(fitted), method=method).fit(x_cal, y_cal)


def _train_cv_probabilities(x, y, groups, x_target, method: str,
                            classes: np.ndarray) -> np.ndarray:
    return confidence.cross_validated_probabilities(
        lambda: models.build(MODEL), x, y, groups, x_target, classes,
        method=method, folds=OUTER_FOLDS,
    )


def _prefit_on_val_probabilities(base, x_val, y_val, val_groups, method: str,
                                 classes: np.ndarray) -> np.ndarray:
    """The cheap recipe, scored honestly.

    Calibrating on validation and then reporting calibration on that same validation is
    in-sample and flatters itself. The calibrator is therefore cross-fitted within
    validation by story group, so every row is scored by a calibrator that never saw it.
    """
    folds = StratifiedGroupKFold(n_splits=2, shuffle=True, random_state=config.SEED)
    out = np.zeros((len(x_val), len(classes)))
    for cal_idx, score_idx in folds.split(x_val, y_val, val_groups):
        calibrated = _calibrate(base, method, x_val[cal_idx], y_val[cal_idx])
        out[score_idx] = _aligned(
            calibrated.predict_proba(x_val[score_idx]), calibrated.classes_, classes
        )
    return out


def _nested_oof(x, y, groups, method: str, classes: np.ndarray) -> np.ndarray:
    """Out-of-fold probabilities on train, for fitting the cuts.

    Genuinely nested: the outer fold is unseen by the base *and* by the calibrator. The
    cheaper single-loop version would fit the calibrator on the very rows it then scores,
    which is exactly the overfitting the cuts exist to avoid.
    """
    if OOF_CACHE.exists():
        cached = np.load(OOF_CACHE, allow_pickle=True)
        if list(cached["classes"]) == list(classes) and str(cached["method"]) == method:
            print(f"  loaded cached train OOF ({method})")
            return cached["probabilities"]

    outer = StratifiedGroupKFold(n_splits=OUTER_FOLDS, shuffle=True, random_state=config.SEED)
    oof = np.zeros((len(x), len(classes)))
    for n, (fit_idx, held_idx) in enumerate(outer.split(x, y, groups), start=1):
        started = time.perf_counter()
        inner = StratifiedGroupKFold(n_splits=INNER_FOLDS, shuffle=True, random_state=config.SEED)
        total = np.zeros((len(held_idx), len(classes)))
        for base_idx, cal_idx in inner.split(x[fit_idx], y[fit_idx], groups[fit_idx]):
            base = models.build(MODEL).fit(x[fit_idx][base_idx], y[fit_idx][base_idx])
            calibrated = _calibrate(base, method, x[fit_idx][cal_idx], y[fit_idx][cal_idx])
            total += _aligned(calibrated.predict_proba(x[held_idx]), calibrated.classes_, classes)
        oof[held_idx] = total / INNER_FOLDS
        print(f"  outer fold {n}/{OUTER_FOLDS}  {time.perf_counter() - started:>5.0f}s")

    OOF_CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(OOF_CACHE, probabilities=oof, classes=classes, method=method)
    return oof


def _global_cut_at_coverage(probabilities: np.ndarray, target_coverage: float) -> float:
    """The single cut that files the same share of articles, for a like-for-like fight."""
    return float(np.quantile(probabilities.max(axis=1), 1.0 - target_coverage))


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)

    texts = np.array(snap.texts(frame, "title_body", body_chars=BODY_CHARS), dtype=object)
    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    groups = frame["story_group_id"].to_numpy()
    publishers = frame["publisher"].to_numpy()

    x_tr, y_tr, g_tr = texts[is_train], y[is_train], groups[is_train]
    x_val, y_val, g_val = texts[~is_train], y[~is_train], groups[~is_train]
    classes = np.array(sorted(set(y)))
    print(f"train {len(x_tr)} / val {len(x_val)} / {len(classes)} classes\n")

    base = models.build(MODEL)
    started = time.perf_counter()
    base.fit(x_tr, y_tr)
    raw = evaluate.score(y_val, base.predict(x_val), g_val)
    print(f"uncalibrated {MODEL}: {raw.interval}  ({time.perf_counter() - started:.0f}s)\n")

    print("=" * 84)
    print("G1  Calibration -- two recipes, two link functions, all scored out-of-sample")
    print("=" * 84)
    header = (f"{'recipe':<22} {'method':<9} {'macro-F1 [CI]':<26} {'Brier':>7} "
              f"{'log loss':>9} {'ECE':>7}")
    print(header)
    print("-" * len(header))

    calibrated_val: dict[tuple[str, str], np.ndarray] = {}
    for recipe in ("train 5-fold CV", "prefit on val"):
        for method in ("sigmoid", "isotonic"):
            started = time.perf_counter()
            if recipe == "train 5-fold CV":
                probabilities = _train_cv_probabilities(x_tr, y_tr, g_tr, x_val, method, classes)
            else:
                probabilities = _prefit_on_val_probabilities(
                    base, x_val, y_val, g_val, method, classes
                )
            calibrated_val[(recipe, method)] = probabilities
            predicted = classes[probabilities.argmax(axis=1)]
            sc = evaluate.score(y_val, predicted, g_val)
            print(f"{recipe:<22} {method:<9} {sc.interval:<26} "
                  f"{confidence.brier(probabilities, y_val, classes):>7.4f} "
                  f"{confidence.log_loss(probabilities, y_val, classes):>9.4f} "
                  f"{confidence.expected_calibration_error(probabilities, y_val, classes):>7.4f}"
                  f"   {time.perf_counter() - started:.0f}s")

    best_key = min(
        calibrated_val,
        key=lambda k: confidence.expected_calibration_error(calibrated_val[k], y_val, classes),
    )
    val_probabilities = calibrated_val[best_key]
    print(f"\nbest calibration: {best_key[0]} + {best_key[1]}")
    print("\nreliability of that recipe (does it deliver the accuracy it claims?)")
    print(f"{'confidence band':<18} {'n':>5} {'claimed':>9} {'actual':>8} {'gap':>7}")
    print("-" * 50)
    for b in confidence.reliability(val_probabilities, y_val, classes):
        print(f"{f'{b.low:.1f}-{b.high:.1f}':<18} {b.n:>5} {b.confidence:>9.3f} "
              f"{b.accuracy:>8.3f} {b.gap:>+7.3f}")

    print("\n" + "=" * 84)
    print("G2  Per-class thresholds, fitted on out-of-fold probabilities from TRAIN")
    print("=" * 84)
    oof = _nested_oof(x_tr, y_tr, g_tr, best_key[1], classes)
    cuts = confidence.fit_cuts(oof, y_tr, classes,
                              auto_precision=AUTO_TARGET, review_precision=REVIEW_TARGET)

    header = (f"{'class':<22} {'OOF n':>6} {'auto cut':>9} {'auto P':>7} "
              f"{'review cut':>11} {'review P':>9}")
    print(header)
    print("-" * len(header))
    for topic in classes:
        cut = cuts[topic]
        auto = "never" if math.isinf(cut.auto) else f"{cut.auto:.3f}"
        review = "never" if math.isinf(cut.review) else f"{cut.review:.3f}"
        auto_p = "  --" if math.isnan(cut.auto_precision) else f"{cut.auto_precision:.3f}"
        review_p = "  --" if math.isnan(cut.review_precision) else f"{cut.review_precision:.3f}"
        print(f"{topic:<22} {cut.support:>6} {auto:>9} {auto_p:>7} {review:>11} {review_p:>9}")

    forced = [t for t in classes if cuts[t].forced_abstain]
    print(f"\nforced abstainers (no cut reaches {REVIEW_TARGET:.0%} precision): "
          f"{', '.join(forced) if forced else 'none'}")

    routed = confidence.route(val_probabilities, classes, cuts, unsorted=config.UNSORTED)
    print("\napplied to validation:")
    print(f"{'band':<26} {'coverage':>9} {'accuracy on kept':>18}")
    print("-" * 55)
    print(f"{'auto only':<26} {routed.coverage():>9.3f} "
          f"{routed.accuracy_on_kept(y_val):>18.3f}")
    print(f"{'auto + review':<26} {routed.coverage(including_review=True):>9.3f} "
          f"{routed.accuracy_on_kept(y_val, including_review=True):>18.3f}")
    print(f"{'everything (no abstain)':<26} {1.0:>9.3f} "
          f"{float((classes[val_probabilities.argmax(axis=1)] == y_val).mean()):>18.3f}")

    print("\nper-class cuts vs ONE global cut at the same coverage:")
    coverage = routed.coverage()
    global_cut = _global_cut_at_coverage(val_probabilities, coverage)
    keep = val_probabilities.max(axis=1) >= global_cut
    global_accuracy = float(
        (classes[val_probabilities[keep].argmax(axis=1)] == y_val[keep]).mean()
    )
    print(f"  per-class  coverage {coverage:.3f}  accuracy {routed.accuracy_on_kept(y_val):.3f}")
    print(f"  global     coverage {float(keep.mean()):.3f}  accuracy {global_accuracy:.3f}"
          f"   (cut {global_cut:.3f})")

    print("\ncoverage/accuracy at three auto-precision targets:")
    print(f"{'target':<10} {'coverage':>9} {'accuracy':>9} {'forced abstainers':>19}")
    print("-" * 50)
    for target in (0.80, 0.85, 0.90):
        alt = confidence.fit_cuts(oof, y_tr, classes,
                                  auto_precision=target, review_precision=REVIEW_TARGET)
        alt_routed = confidence.route(val_probabilities, classes, alt, unsorted=config.UNSORTED)
        n_forced = sum(1 for t in classes if alt[t].forced_abstain)
        print(f"{target:<10.0%} {alt_routed.coverage():>9.3f} "
              f"{alt_routed.accuracy_on_kept(y_val):>9.3f} {n_forced:>19}")

    print("\n" + "=" * 84)
    print("G3  What did class_weight='balanced' actually buy? (imbalance 6.7:1)")
    print("=" * 84)
    header = f"{'weighting':<26} {'val macro-F1 [CI]':<26} {'Hindu':>7} {'Guardian':>9}"
    print(header)
    print("-" * len(header))

    def run(params, sample=None):
        x_fit, y_fit = (x_tr, y_tr) if sample is None else sample
        model = models.build(MODEL, **params).fit(x_fit, y_fit)
        val = evaluate.score(y_val, model.predict(x_val), g_val)
        holds = {}
        for publisher in config.PUBLISHER_HOLDOUTS:
            held = publishers == publisher
            other = models.build(MODEL, **params).fit(texts[~held], y[~held])
            holds[publisher] = evaluate.score(
                y[held], other.predict(texts[held]), groups[held]
            ).macro_f1
        return val, holds

    for label, params in (("none (plain)", {"class_weight": None}),
                          ("balanced (incumbent)", {})):
        val, holds = run(params)
        print(f"{label:<26} {val.interval:<26} {holds['The Hindu']:>7.3f} "
              f"{holds['The Guardian']:>9.3f}")

    # Oversample to the median class size only. Duplicating up to the largest class
    # would copy conflict_war 6.7x and teach the model its 234 articles by heart.
    counts = {t: int((y_tr == t).sum()) for t in classes}
    ceiling = int(np.median(list(counts.values())))
    rng = np.random.default_rng(config.SEED)
    picked = []
    for topic in classes:
        idx = np.flatnonzero(y_tr == topic)
        picked.append(idx)
        if len(idx) < ceiling:
            picked.append(rng.choice(idx, size=ceiling - len(idx), replace=True))
    idx = np.concatenate(picked)
    val, holds = run({"class_weight": None}, sample=(x_tr[idx], y_tr[idx]))
    print(f"{f'oversampled to {ceiling}':<26} {val.interval:<26} "
          f"{holds['The Hindu']:>7.3f} {holds['The Guardian']:>9.3f}")


if __name__ == "__main__":
    main()
