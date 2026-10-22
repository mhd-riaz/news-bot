"""Figures for the IEEE report and the slide deck.

Reads the metrics written by `newsmlv2 train`, so a figure can never quote a number the
shipped model does not produce.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from newsmlv2 import config, serve  # noqa: E402

SNAPSHOT_ID = "v2-001"
OUT = config.ML_ROOT.parent / "submission" / "report" / "figures"

plt.rcParams.update({
    "font.size": 8,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 300,
})


def reliability_and_coverage(metrics: dict, *, size: tuple[float, float],
                             name: str, font: float) -> None:
    """The two charts that carry the calibration + abstention argument.

    Rendered twice: wide for the slides, and again at IEEE column width, where a
    downscaled copy of the wide version would be unreadable.
    """
    with plt.rc_context({"font.size": font}):
        fig, (left, right) = plt.subplots(1, 2, figsize=size)

        bins = metrics["reliability"]
        claimed = [b["claimed"] for b in bins]
        actual = [b["actual"] for b in bins]
        left.plot([0, 1], [0, 1], "--", color="0.5", lw=0.8, label="perfect")
        left.plot(claimed, actual, "o-", color="#c0392b", ms=3.0, lw=1.1,
                  label="measured")
        left.set_xlabel("claimed confidence")
        left.set_ylabel("observed accuracy")
        left.set_title(f"(a) reliability, ECE {metrics['validation']['ece']:.3f}")
        left.set_xlim(0, 1)
        left.set_ylim(0, 1)
        left.legend(frameon=False, loc="upper left", handlelength=1.4)

        curve = metrics["coverage_curve"]
        cuts = [p["cut"] for p in curve]
        right.plot(cuts, [p["coverage"] for p in curve], color="#2c3e50", lw=1.1,
                   label="filed")
        right.plot(cuts, [p["accuracy_on_kept"] for p in curve], color="#c0392b",
                   lw=1.1, label="accuracy on filed")
        right.axvline(metrics["cut"], color="0.4", ls=":", lw=1.0)
        right.annotate(f"cut {metrics['cut']:.2f}", xy=(metrics["cut"], 0.99),
                       xytext=(metrics["cut"] + 0.02, 0.99), fontsize=font - 1,
                       color="0.3", va="top")
        right.set_xlabel("confidence cut")
        right.set_ylabel("proportion")
        right.set_title("(b) the abstention trade-off")
        right.set_xlim(0, 0.95)
        right.set_ylim(0.25, 1.02)
        right.legend(frameon=False, loc="lower left", handlelength=1.4)

        fig.tight_layout(pad=0.3)
        fig.savefig(OUT / name, bbox_inches="tight")
        plt.close(fig)


def per_class(metrics: dict) -> None:
    """Per-class F1 with bootstrap intervals, so a thin class cannot be misread."""
    rows = sorted(metrics["validation"]["per_class"], key=lambda c: c["f1"])
    names = [r["topic"].replace("_", " ") for r in rows]
    f1 = [r["f1"] for r in rows]
    low = [r["f1"] - r["low"] for r in rows]
    high = [r["high"] - r["f1"] for r in rows]

    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    ax.barh(names, f1, color="#4a6fa5", height=0.62)
    ax.errorbar(f1, names, xerr=[low, high], fmt="none", ecolor="0.25",
                elinewidth=0.8, capsize=2)
    for y, row in enumerate(rows):
        ax.text(0.02, y, f"n={row['support']}", va="center", fontsize=6, color="white")
    ax.set_xlabel("validation macro-F1 (95% CI)")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(OUT / "per-class.png", bbox_inches="tight")
    plt.close(fig)


def confusion(metrics: dict) -> None:
    """13x13 confusion matrix, rows normalised so each row reads as recall."""
    val = metrics["validation"]
    labels = [t.replace("_", " ") for t in val["labels"]]
    matrix = val["matrix"]
    shares = [[cell / max(sum(row), 1) for cell in row] for row in matrix]

    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    image = ax.imshow(shares, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_xlabel("predicted")
    ax.set_ylabel("actual")
    ax.grid(visible=False)
    for r, row in enumerate(matrix):
        for c, count in enumerate(row):
            if count:
                ax.text(c, r, count, ha="center", va="center", fontsize=6,
                        color="white" if shares[r][c] > 0.5 else "0.2")
    fig.colorbar(image, ax=ax, shrink=0.7, label="share of the actual class")
    fig.tight_layout()
    fig.savefig(OUT / "confusion.png", bbox_inches="tight")
    plt.close(fig)


# The ladder rungs are closed experiments recorded in docs/plan.md, not in metrics.json.
LADDER = [
    ("always guess\nthe biggest class", 0.025, 0.025),
    ("Naive Bayes", 0.635, 0.594),
    ("logistic\nregression", 0.698, 0.752),
    ("linear SVM", 0.696, 0.753),
    ("linear SVM\n+ char n-grams", 0.712, 0.771),
]


def ladder(metrics: dict) -> None:
    """Every rung that was tried, headline-only against headline+body."""
    names = [r[0] for r in LADDER]
    spots = range(len(LADDER))
    fig, ax = plt.subplots(figsize=(7.0, 2.9))
    ax.bar([x - 0.19 for x in spots], [r[1] for r in LADDER], width=0.38,
           color="#b8c4d4", label="headline + summary")
    ax.bar([x + 0.19 for x in spots], [r[2] for r in LADDER], width=0.38,
           color="#c0392b", label="headline + body")
    for x, row in zip(spots, LADDER):
        ax.text(x + 0.19, row[2] + 0.015, f"{row[2]:.3f}", ha="center", fontsize=6.5)
    ax.set_xticks(list(spots), names, fontsize=7)
    ax.set_ylabel("macro-F1 on validation")
    ax.set_ylim(0, 0.92)
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="upper left", fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "ladder.png", bbox_inches="tight")
    plt.close(fig)


def precision_recall(metrics: dict) -> None:
    """Precision beside recall, because the two fail in opposite directions."""
    rows = sorted(metrics["validation"]["per_class"], key=lambda c: c["f1"])
    names = [r["topic"].replace("_", " ") for r in rows]
    spots = range(len(rows))

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.barh([y + 0.19 for y in spots], [r["precision"] for r in rows], height=0.38,
            color="#2c3e50", label="precision")
    ax.barh([y - 0.19 for y in spots], [r["recall"] for r in rows], height=0.38,
            color="#e08a3c", label="recall")
    ax.set_yticks(list(spots), names, fontsize=7)
    ax.set_xlabel("validation score")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right", fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "precision-recall.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    path = config.ARTIFACT_DIR / "models" / SNAPSHOT_ID / serve.METRICS
    if not path.is_file():
        raise SystemExit(f"no metrics at {path}; run: uv run newsmlv2 train --id {SNAPSHOT_ID}")

    metrics = json.loads(path.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    reliability_and_coverage(metrics, size=(7.0, 2.5), name="calibration.png", font=8)
    reliability_and_coverage(metrics, size=(3.5, 1.7), name="calibration-col.png",
                             font=6)
    per_class(metrics)
    confusion(metrics)
    ladder(metrics)
    precision_recall(metrics)
    print(f"wrote 6 figures to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
