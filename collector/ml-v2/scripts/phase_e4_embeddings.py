"""Phase E4 on its own: do dense sentence embeddings beat sparse TF-IDF?

Split out from the rest of Phase E because sentence-transformers forks worker
processes, and under `nohup` (stdin closed) those workers die with a bad file
descriptor. This runs in the foreground.

Encoding is on CPU deliberately: GPU/MPS kernels are not bit-reproducible, and a cached
vector that changes between runs would quietly break snapshot reproducibility.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np

from newsmlv2 import config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = config.CACHE_DIR / SNAPSHOT_ID / "minilm.npy"

# The number to beat, from the same splits.
INCUMBENT = 0.771
INCUMBENT_CI = (0.743, 0.796)


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)

    texts = snap.texts(frame, "title_body", body_chars=BODY_CHARS)
    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    groups = frame["story_group_id"].to_numpy()
    publishers = frame["publisher"].to_numpy()
    print(f"train {is_train.sum()} / val {(~is_train).sum()}")

    if CACHE.exists():
        vectors = np.load(CACHE)
        print(f"loaded cached embeddings {vectors.shape}")
    else:
        from sentence_transformers import SentenceTransformer

        CACHE.parent.mkdir(parents=True, exist_ok=True)
        encoder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        started = time.perf_counter()
        vectors = encoder.encode(
            texts, batch_size=32, show_progress_bar=False,
            convert_to_numpy=True, normalize_embeddings=True,
        )
        print(f"encoded {len(texts)} docs in {time.perf_counter() - started:.0f}s -> {vectors.shape}")
        np.save(CACHE, vectors)

    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier

    heads = [
        ("minilm + logreg", lambda: LogisticRegression(
            max_iter=3000, C=10.0, class_weight="balanced", random_state=config.SEED)),
        ("minilm + xgboost", lambda: models._StringLabels(XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.1,
            tree_method="hist", n_jobs=-1, random_state=config.SEED))),
    ]

    header = f"{'candidate':<22} {'val macro-F1 [CI]':<26} {'Hindu':>7} {'Guardian':>9} {'fit s':>7}"
    print("\n" + header)
    print("-" * len(header))

    for label, build in heads:
        model = build()
        started = time.perf_counter()
        model.fit(vectors[is_train], y[is_train])
        fit_s = time.perf_counter() - started
        val = evaluate.score(y[~is_train], model.predict(vectors[~is_train]), groups[~is_train])

        holds = {}
        for publisher in config.PUBLISHER_HOLDOUTS:
            held = publishers == publisher
            other = build()
            other.fit(vectors[~held], y[~held])
            holds[publisher] = evaluate.score(
                y[held], other.predict(vectors[held]), groups[held]
            ).macro_f1

        print(f"{label:<22} {val.interval:<26} {holds['The Hindu']:>7.3f} "
              f"{holds['The Guardian']:>9.3f} {fit_s:>7.1f}")

        separable = val.macro_f1_low > INCUMBENT_CI[1] or val.macro_f1_high < INCUMBENT_CI[0]
        verdict = (
            "BEATS the linear incumbent" if separable and val.macro_f1 > INCUMBENT
            else "LOSES to the linear incumbent" if separable
            else "tie -> incumbent wins on simplicity"
        )
        print(f"{'':<22} vs incumbent {val.macro_f1 - INCUMBENT:+.3f} -> {verdict}")


if __name__ == "__main__":
    main()
