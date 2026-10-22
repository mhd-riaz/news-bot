"""H4 -- the one-time test-split read. THE SINGLE DOOR.

Grep for `open_the_test_split_once` to find every place the test split is touched. There
is one, and it is here.

Why this file exists at all: a held-out split stops being held out the moment it informs
a decision. Score on it, tweak, score again, and the number quietly becomes a training
signal. So the model is frozen before this runs -- `word_char_svc` on `title_body` at
4,000 characters, `class_weight="balanced"`, isotonic calibration cross-validated on
train, one global confidence cut derived from train out-of-fold probabilities.

**Nothing may be changed in response to what this prints.** If test and validation
disagree by more than ~0.05 the answer is to investigate why, not to adjust the model
until they agree.

Requires `--yes` so it cannot run by accident, including from a stray `python scripts/*`.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from newsmlv2 import confidence, config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
MODEL = "word_char_svc"
PARAMS: dict = {}
CALIBRATION = "isotonic"
AUTO_TARGET = 0.90
DIVERGENCE_GUARD = 0.05
OOF_CACHE = config.CACHE_DIR / SNAPSHOT_ID / "phase_g_train_oof.npz"


def open_the_test_split_once() -> None:
    """The only read of the test split in this project."""
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    everything = snap.frame
    labelled = everything[everything["topic"].notna() & (everything["topic"] != config.UNSORTED)]

    pool = labelled[labelled["split"].isin(["train", "val"])].reset_index(drop=True)
    test = labelled[labelled["split"] == "test"].reset_index(drop=True)

    texts = np.array(snap.texts(pool, "title_body", body_chars=BODY_CHARS), dtype=object)
    is_train = (pool["split"] == "train").to_numpy()
    y = pool["topic"].to_numpy()
    groups = pool["story_group_id"].to_numpy()
    classes = np.array(sorted(set(y)))

    x_test = np.array(snap.texts(test, "title_body", body_chars=BODY_CHARS), dtype=object)
    y_test = test["topic"].to_numpy()
    test_groups = test["story_group_id"].to_numpy()

    print(f"train {int(is_train.sum())} / val {int((~is_train).sum())} / "
          f"test {len(test)}   snapshot {SNAPSHOT_ID}\n")

    # Fit on train only, exactly as every validation number was produced. Refitting on
    # train+val would score a different model than the one every earlier decision used.
    model = models.build(MODEL, **PARAMS)
    model.fit(texts[is_train], y[is_train])

    val = evaluate.score(y[~is_train], model.predict(texts[~is_train]), groups[~is_train])

    started = time.perf_counter()
    predicted = model.predict(x_test)
    per_doc_ms = (time.perf_counter() - started) * 1000 / len(x_test)
    result = evaluate.score(y_test, predicted, test_groups, with_matrix=True)

    print("=" * 78)
    print("H4  TEST SPLIT -- opened once")
    print("=" * 78)
    print(f"{'validation':<14} {val.interval}   accuracy {val.accuracy:.3f}")
    print(f"{'test':<14} {result.interval}   accuracy {result.accuracy:.3f}")
    delta = result.macro_f1 - val.macro_f1
    print(f"\ndelta {delta:+.3f}   guard +/-{DIVERGENCE_GUARD}   "
          f"intervals overlap: {val.overlaps(result)}")
    if abs(delta) > DIVERGENCE_GUARD:
        print("*** OVER THE GUARD -- investigate, do not adjust the model to fit it. ***")
    else:
        print("within the guard: the validation number held up on unseen data.")

    print("\nper class on test:")
    print(f"{'class':<22} {'test F1':>8} {'support':>8} {'val F1':>8} {'delta':>7}")
    print("-" * 57)
    val_f1 = {c.topic: c.f1 for c in val.per_class}
    for c in sorted(result.per_class, key=lambda c: -c.f1):
        seen = val_f1.get(c.topic)
        gap = f"{c.f1 - seen:+.2f}" if seen is not None else "  --"
        print(f"{c.topic:<22} {c.f1:>8.2f} {c.support:>8} "
              f"{seen if seen is None else f'{seen:>8.2f}'} {gap:>7}")

    print("\ntop confusions on test:")
    for actual, called, count in evaluate.top_confusions(result, limit=6):
        print(f"  {actual:>20} called {called:<20} {count:>4}")

    # The shipping policy, applied to test. The cut comes from train out-of-fold
    # probabilities, so it was never fitted on anything scored here.
    cached = np.load(OOF_CACHE, allow_pickle=True)
    oof = cached["probabilities"]
    if len(oof) != int(is_train.sum()):
        raise SystemExit("train OOF cache does not match this frame; re-run phase_g")
    global_cut, achieved = confidence.fit_global_cut(
        oof, y[is_train], classes, target=AUTO_TARGET
    )

    probabilities = confidence.cross_validated_probabilities(
        lambda: models.build(MODEL, **PARAMS),
        texts[is_train], y[is_train], groups[is_train], x_test, classes,
        method=CALIBRATION,
    )
    called = classes[probabilities.argmax(axis=1)]
    kept = probabilities.max(axis=1) >= global_cut

    print("\n" + "=" * 78)
    print("The shipping policy on test: calibrate, then abstain below one global cut")
    print("=" * 78)
    print(f"cut {global_cut:.3f}, fitted on train OOF for {AUTO_TARGET:.0%} precision "
          f"(achieved {achieved:.3f} there)")
    print(f"{'coverage':<26} {float(kept.mean()):.3f}")
    print(f"{'accuracy on filed':<26} {float((called[kept] == y_test[kept]).mean()):.3f}")
    print(f"{'accuracy if it never abstained':<26} {float((called == y_test).mean()):.3f}")
    print(f"{'ECE on test':<26} "
          f"{confidence.expected_calibration_error(probabilities, y_test, classes):.4f}")

    with tempfile.NamedTemporaryFile(suffix=".joblib") as fh:
        import joblib

        joblib.dump(model, fh.name)
        size_mb = Path(fh.name).stat().st_size / 1e6
    print(f"\n{'predict':<26} {per_doc_ms:.3f} ms/article")
    print(f"{'bundle':<26} {size_mb:.1f} MB (uncalibrated estimator, joblib)")
    print("\nThe test split is now closed for good. Do not run this again.")


if __name__ == "__main__":
    if "--yes" not in sys.argv:
        raise SystemExit(
            "Refusing to open the test split without --yes.\n"
            "This is a one-way door: once these numbers are seen, no further tuning\n"
            "decision can honestly be made against them."
        )
    open_the_test_split_once()
