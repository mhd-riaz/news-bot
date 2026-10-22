"""Illustrative-only: SVM vs logistic regression on synthetic 2D data.

Not part of the news pipeline and quotes no project metrics. Purpose is purely to
show *why* the two decision boundaries differ (margin vs probability contours).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.datasets import make_blobs  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.svm import SVC  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "reports" / "figures" / "svm-vs-logreg.png"

X, y = make_blobs(n_samples=120, centers=2, cluster_std=1.6, random_state=7)

svm = SVC(kernel="linear", C=1.0).fit(X, y)
logreg = LogisticRegression().fit(X, y)

xx, yy = np.meshgrid(
    np.linspace(X[:, 0].min() - 1, X[:, 0].max() + 1, 300),
    np.linspace(X[:, 1].min() - 1, X[:, 1].max() + 1, 300),
)
grid = np.c_[xx.ravel(), yy.ravel()]

plt.rcParams.update({"font.size": 9, "axes.grid": False, "figure.dpi": 150})
fig, axes = plt.subplots(1, 2, figsize=(9, 4.2))

# Left: SVM — margin (distance to the separating hyperplane), not a probability.
margin = svm.decision_function(grid).reshape(xx.shape)
axes[0].contourf(xx, yy, margin, levels=np.linspace(margin.min(), margin.max(), 15),
                  cmap="RdBu", alpha=0.6)
axes[0].contour(xx, yy, margin, levels=[-1, 0, 1], colors="k",
                 linestyles=["--", "-", "--"], linewidths=1.0)
axes[0].scatter(*svm.support_vectors_.T, s=90, facecolors="none", edgecolors="k",
                 linewidths=1.2, label="support vectors")
axes[0].scatter(*X.T, c=y, cmap="RdBu", edgecolors="k", linewidths=0.4, s=20)
axes[0].set_title("SVM: max-margin hyperplane")
axes[0].legend(frameon=False, loc="upper left", fontsize=7)

# Right: logistic regression — a smooth probability surface, no margin concept.
proba = logreg.predict_proba(grid)[:, 1].reshape(xx.shape)
cf = axes[1].contourf(xx, yy, proba, levels=15, cmap="RdBu", alpha=0.6)
axes[1].contour(xx, yy, proba, levels=[0.5], colors="k", linewidths=1.0)
axes[1].scatter(*X.T, c=y, cmap="RdBu", edgecolors="k", linewidths=0.4, s=20)
axes[1].set_title("Logistic regression: probability contours")
fig.colorbar(cf, ax=axes[1], label="P(class=1)", fraction=0.046, pad=0.04)

for ax in axes:
    ax.set_xticks([])
    ax.set_yticks([])

fig.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, bbox_inches="tight")
print(f"wrote {OUT}")
