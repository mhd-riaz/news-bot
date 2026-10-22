"""ROC comparison: the incumbent LinearSVC vs the logistic-regression candidate.

One-vs-rest ROC per class, macro-averaged, on the same v2-001 validation split used
throughout Phase E. `word_char_svc` has no native probability -- its margin
(`decision_function`) is used as the ROC score directly, which is valid for ROC/AUC
since both only need a ranking, not a calibrated probability.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import auc, roc_curve  # noqa: E402
from sklearn.preprocessing import label_binarize  # noqa: E402

from newsmlv2 import config, models  # noqa: E402
from newsmlv2 import snapshot as snapshot_mod  # noqa: E402

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
OUT = config.ML_ROOT / "reports" / "figures" / "roc-svm-vs-logreg.png"

CANDIDATES = [
    ("word_char_svc", "LinearSVC (incumbent)", "#c0392b"),
    ("tfidf_logreg", "LogisticRegression (C=10)", "#2c3e50"),
]


def macro_roc(y_true: np.ndarray, scores: np.ndarray, labels: list[str]) -> tuple[np.ndarray, np.ndarray, float]:
    """One-vs-rest ROC per class, averaged on a shared FPR grid, per scikit-learn's
    documented macro-average recipe."""
    y_bin = label_binarize(y_true, classes=labels)
    grid = np.linspace(0, 1, 200)
    curves = np.zeros_like(grid)
    aucs = []
    for i in range(len(labels)):
        fpr, tpr, _ = roc_curve(y_bin[:, i], scores[:, i])
        aucs.append(auc(fpr, tpr))
        curves += np.interp(grid, fpr, tpr)
    curves /= len(labels)
    return grid, curves, float(np.mean(aucs))


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)

    texts = np.array(snap.texts(frame, "title_body", body_chars=BODY_CHARS), dtype=object)
    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    labels = sorted(set(y))

    plt.rcParams.update({"font.size": 9, "figure.dpi": 150})
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], "--", color="0.6", lw=0.8, label="chance")

    for model_name, display, color in CANDIDATES:
        model = models.build(model_name)
        model.fit(texts[is_train], y[is_train])
        clf = model.named_steps["clf"]
        scores = (
            model.predict_proba(texts[~is_train]) if hasattr(clf, "predict_proba")
            else model.decision_function(texts[~is_train])
        )
        grid, tpr, macro_auc = macro_roc(y[~is_train], scores, labels)
        ax.plot(grid, tpr, color=color, lw=1.4, label=f"{display} (macro AUC {macro_auc:.3f})")
        print(f"{display}: macro AUC {macro_auc:.3f}")

    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title("One-vs-rest ROC, macro-averaged over 13 classes (val split)")
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
