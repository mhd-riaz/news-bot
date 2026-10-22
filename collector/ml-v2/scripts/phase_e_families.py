"""Phase E: do any of the other model families beat the linear baseline?

Four families, none assumed to win:

* **E1 linear** -- a C sweep on the incumbent.
* **E2 XGBoost** -- on SVD-reduced features, never raw sparse TF-IDF.
* **E3 bagging** -- Random Forest and Extra Trees on the same dense space. Expected to
  lose on text; the phase exists to prove it rather than assert it.
* **E4 embeddings** -- MiniLM sentence vectors, encoded once on CPU so the cache stays
  reproducible, with a linear and a tree head.

The bar is not "is it higher" but "is the interval separable". Anything overlapping the
incumbent loses on simplicity.
"""

from __future__ import annotations

import time

import numpy as np

from newsmlv2 import config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
INCUMBENT = ("word_char_svc", {})

CANDIDATES: list[tuple[str, str, dict]] = [
    ("E1 linear C=0.5", "word_char_svc", {"C": 0.5}),
    ("E1 linear C=1 (incumbent)", "word_char_svc", {}),
    ("E1 linear C=3", "word_char_svc", {"C": 3.0}),
    ("E1 logreg C=10", "tfidf_logreg", {"C": 10.0}),
    ("E2 xgboost svd256", "svd_xgboost", {"n_components": 256}),
    ("E2 xgboost svd512 deep", "svd_xgboost", {"n_components": 512, "max_depth": 8}),
    ("E3 random forest", "svd_random_forest", {}),
    ("E3 extra trees", "svd_extra_trees", {}),
]

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_CACHE = config.CACHE_DIR / SNAPSHOT_ID / "minilm.npy"


def _embed(texts: list[str]) -> np.ndarray:
    """Encode on CPU. GPU/MPS kernels are not bit-reproducible, and the cache must be."""
    import pandas as pd
    from sentence_transformers import SentenceTransformer

    if EMBED_CACHE.exists():
        return np.load(EMBED_CACHE)
    EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
    encoder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    started = time.perf_counter()
    vectors = encoder.encode(texts, batch_size=64, show_progress_bar=False,
                             convert_to_numpy=True, normalize_embeddings=True)
    print(f"  encoded {len(texts)} docs in {time.perf_counter() - started:.0f}s")
    np.save(EMBED_CACHE, vectors)
    return vectors


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
    print(f"train {is_train.sum()} / val {(~is_train).sum()}\n")

    def run(name, build, x):
        model = build()
        started = time.perf_counter()
        model.fit(x[is_train], y[is_train])
        fit_s = time.perf_counter() - started
        predicted = model.predict(x[~is_train])
        val = evaluate.score(y[~is_train], predicted, groups[~is_train])

        holds = {}
        for publisher in config.PUBLISHER_HOLDOUTS:
            held = publishers == publisher
            other = build()
            other.fit(x[~held], y[~held])
            holds[publisher] = evaluate.score(y[held], other.predict(x[held]), groups[held]).macro_f1
        return val, holds, fit_s, predicted

    header = f"{'candidate':<28} {'val macro-F1 [CI]':<26} {'Hindu':>7} {'Guardian':>9} {'fit s':>7}"
    print(header)
    print("-" * len(header))

    results: dict[str, tuple] = {}
    for label, model_name, params in CANDIDATES:
        val, holds, fit_s, predicted = run(label, lambda: models.build(model_name, **params), texts)
        results[label] = (val, predicted)
        print(f"{label:<28} {val.interval:<26} {holds['The Hindu']:>7.3f} "
              f"{holds['The Guardian']:>9.3f} {fit_s:>7.1f}")

    print("\nE4 embeddings (MiniLM, CPU, cached)")
    vectors = _embed(list(texts))
    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier

    embedding_heads = [
        ("E4 minilm + logreg", lambda: LogisticRegression(max_iter=2000, C=10.0,
                                                          class_weight="balanced",
                                                          random_state=config.SEED)),
        ("E4 minilm + xgboost", lambda: models._StringLabels(
            XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.1,
                          tree_method="hist", n_jobs=-1, random_state=config.SEED))),
    ]
    for label, build in embedding_heads:
        val, holds, fit_s, predicted = run(label, build, vectors)
        results[label] = (val, predicted)
        print(f"{label:<28} {val.interval:<26} {holds['The Hindu']:>7.3f} "
              f"{holds['The Guardian']:>9.3f} {fit_s:>7.1f}")

    print("\n" + "=" * 78)
    print("AGAINST THE INCUMBENT (word_char_svc, C=1)")
    print("=" * 78)
    incumbent_val, incumbent_pred = results["E1 linear C=1 (incumbent)"]
    truth = y[~is_train]
    for label, (val, predicted) in results.items():
        if label == "E1 linear C=1 (incumbent)":
            continue
        a, b, p = evaluate.mcnemar(list(truth), list(incumbent_pred), list(predicted))
        separable = not incumbent_val.overlaps(val)
        verdict = (
            "BEATS incumbent" if separable and val.macro_f1 > incumbent_val.macro_f1
            else "loses" if separable
            else "tie (intervals overlap) -> incumbent wins on simplicity"
        )
        print(f"{label:<28} {val.macro_f1 - incumbent_val.macro_f1:+.3f}  p={p:.3f}  {verdict}")


if __name__ == "__main__":
    main()
