"""Phase F1: is there anything left for an ensemble to combine?

An ensemble only pays when its members are **complementary** -- wrong in different
places. Phase E measured every alternative family as uniformly weaker: 0.04-0.09 below
the incumbent on validation *and* on both publisher holdouts simultaneously. That is
the profile of a worse model, not a differently-wrong one, and averaging a worse model
into a better one usually costs accuracy.

This script refuses to assume that. It reuses the Phase E candidate set, caches every
model's validation predictions once, and then measures:

* per-model error sets and how much they overlap;
* pairwise disagreement, split into "the incumbent could be rescued here" and
  "both are wrong anyway";
* the **oracle** -- what a perfect selector would score. That is a loose ceiling by
  construction (with ten models, something is nearly always right), so it is reported
  alongside a **hard majority vote**, which is what an ensemble can actually reach with
  no new fitting.

The decision rule: if the reachable vote does not clear the incumbent's interval, F2 is
not run and the negative result is recorded.
"""

from __future__ import annotations

import time
from collections import Counter

import numpy as np

from newsmlv2 import config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
INCUMBENT = "E1 linear C=1"

PREDICTION_CACHE = config.CACHE_DIR / SNAPSHOT_ID / "phase_f_val_predictions.npz"
EMBED_CACHE = config.CACHE_DIR / SNAPSHOT_ID / "minilm.npy"

# The Phase E set unchanged. The near-identical C=0.5 / C=3 rungs stay in on purpose:
# they are the control for "how much disagreement is just tuning noise".
CANDIDATES: list[tuple[str, str, dict]] = [
    ("E1 linear C=0.5", "word_char_svc", {"C": 0.5}),
    (INCUMBENT, "word_char_svc", {}),
    ("E1 linear C=3", "word_char_svc", {"C": 3.0}),
    ("E1 logreg C=10", "tfidf_logreg", {"C": 10.0}),
    ("E2 xgboost svd256", "svd_xgboost", {"n_components": 256}),
    ("E2 xgboost svd512 deep", "svd_xgboost", {"n_components": 512, "max_depth": 8}),
    ("E3 random forest", "svd_random_forest", {}),
    ("E3 extra trees", "svd_extra_trees", {}),
]

# Families, for the "does diversity help" question. Two models from the same family
# make each other's mistakes; the interesting oracle is the cross-family one.
FAMILY = {
    "E1 linear C=0.5": "linear",
    INCUMBENT: "linear",
    "E1 linear C=3": "linear",
    "E1 logreg C=10": "linear",
    "E2 xgboost svd256": "tree",
    "E2 xgboost svd512 deep": "tree",
    "E3 random forest": "tree",
    "E3 extra trees": "tree",
    "E4 minilm + logreg": "embedding",
    "E4 minilm + xgboost": "embedding",
}


def _fit_predict(texts, is_train, y) -> dict[str, np.ndarray]:
    """Validation predictions for every candidate, cached so F2 costs nothing."""
    if PREDICTION_CACHE.exists():
        cached = np.load(PREDICTION_CACHE, allow_pickle=True)
        print(f"loaded cached predictions for {len(cached.files)} models\n")
        return {name: cached[name] for name in cached.files}

    predictions: dict[str, np.ndarray] = {}
    for label, model_name, params in CANDIDATES:
        model = models.build(model_name, **params)
        started = time.perf_counter()
        model.fit(texts[is_train], y[is_train])
        predictions[label] = np.asarray(model.predict(texts[~is_train]), dtype=object)
        print(f"  fitted {label:<26} {time.perf_counter() - started:>6.1f}s")

    vectors = np.load(EMBED_CACHE)
    if len(vectors) != len(texts):
        raise SystemExit(
            f"embedding cache has {len(vectors)} rows, frame has {len(texts)} -- "
            "the Phase E cache was built from a different frame; delete it and re-run "
            "scripts/phase_e_families.py"
        )

    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier

    heads = [
        ("E4 minilm + logreg", LogisticRegression(
            max_iter=2000, C=10.0, class_weight="balanced", random_state=config.SEED)),
        ("E4 minilm + xgboost", models._StringLabels(XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.1,
            tree_method="hist", n_jobs=-1, random_state=config.SEED))),
    ]
    for label, head in heads:
        started = time.perf_counter()
        head.fit(vectors[is_train], y[is_train])
        predictions[label] = np.asarray(head.predict(vectors[~is_train]), dtype=object)
        print(f"  fitted {label:<26} {time.perf_counter() - started:>6.1f}s")

    PREDICTION_CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(PREDICTION_CACHE, **predictions)
    print(f"\ncached -> {PREDICTION_CACHE}\n")
    return predictions


def _majority_vote(members: list[str], predictions: dict[str, np.ndarray],
                   tiebreak: np.ndarray) -> np.ndarray:
    """Plurality vote, ties broken by the incumbent -- the free ensemble."""
    stacked = np.vstack([predictions[m] for m in members])
    out = np.empty(stacked.shape[1], dtype=object)
    for i in range(stacked.shape[1]):
        counts = Counter(stacked[:, i])
        top = max(counts.values())
        winners = {label for label, c in counts.items() if c == top}
        out[i] = tiebreak[i] if len(winners) > 1 and tiebreak[i] in winners else sorted(winners)[0]
    return out


def _oracle(members: list[str], predictions: dict[str, np.ndarray],
            truth: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """What a perfect selector would predict: the truth wherever any member has it."""
    right = np.zeros(len(truth), dtype=bool)
    for m in members:
        right |= predictions[m] == truth
    return np.where(right, truth, fallback)


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)

    texts = np.array(snap.texts(frame, "title_body", body_chars=BODY_CHARS), dtype=object)
    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    groups = frame["story_group_id"].to_numpy()
    truth = y[~is_train]
    val_groups = groups[~is_train]
    print(f"train {is_train.sum()} / val {(~is_train).sum()}\n")

    predictions = _fit_predict(texts, is_train, y)
    names = list(predictions)
    scores = {n: evaluate.score(truth, predictions[n], val_groups) for n in names}
    correct = {n: predictions[n] == truth for n in names}
    incumbent = scores[INCUMBENT]

    print("=" * 78)
    print("F1a  Where each model is right")
    print("=" * 78)
    header = f"{'model':<26} {'val macro-F1 [CI]':<26} {'right':>7} {'wrong':>7}"
    print(header)
    print("-" * len(header))
    for n in names:
        hits = int(correct[n].sum())
        print(f"{n:<26} {scores[n].interval:<26} {hits:>7} {len(truth) - hits:>7}")

    print("\n" + "=" * 78)
    print("F1b  Pairwise structure against the incumbent")
    print("=" * 78)
    print("'rescuable' = articles the incumbent gets wrong and this model gets right.")
    print("That is the only place an ensemble can gain; 'both wrong' is unreachable.\n")
    header = (f"{'model':<26} {'disagree':>9} {'rescuable':>10} {'would lose':>11} "
              f"{'both wrong':>11} {'net':>6}")
    print(header)
    print("-" * len(header))
    base = correct[INCUMBENT]
    for n in names:
        if n == INCUMBENT:
            continue
        other = correct[n]
        disagree = int((predictions[n] != predictions[INCUMBENT]).sum())
        rescuable = int((~base & other).sum())
        lost = int((base & ~other).sum())
        both_wrong = int((~base & ~other).sum())
        print(f"{n:<26} {disagree:>9} {rescuable:>10} {lost:>11} {both_wrong:>11} "
              f"{rescuable - lost:>+6}")

    print("\n" + "=" * 78)
    print("F1c  Oracle ceilings -- what a PERFECT selector would score")
    print("=" * 78)
    print("A loose upper bound by construction: with N models something is usually")
    print("right. It answers 'is there anything to select between', not 'will voting")
    print("work'. The vote below is the reachable number.\n")
    header = f"{'member set':<30} {'n':>3} {'oracle macro-F1':<26} {'oracle acc':>11}"
    print(header)
    print("-" * len(header))
    sets: list[tuple[str, list[str]]] = [
        ("incumbent alone", [INCUMBENT]),
        ("linear family", [n for n in names if FAMILY[n] == "linear"]),
        ("incumbent + best tree", [INCUMBENT, "E2 xgboost svd256"]),
        ("incumbent + best embedding", [INCUMBENT, "E4 minilm + logreg"]),
        ("one per family", [INCUMBENT, "E2 xgboost svd256", "E4 minilm + logreg"]),
        ("everything", names),
    ]
    for label, members in sets:
        predicted = _oracle(members, predictions, truth, predictions[INCUMBENT])
        sc = evaluate.score(truth, predicted, val_groups)
        print(f"{label:<30} {len(members):>3} {sc.interval:<26} {sc.accuracy:>11.3f}")

    print("\n" + "=" * 78)
    print("F1d  Hard majority vote -- the ensemble that needs no new fitting")
    print("=" * 78)
    header = f"{'member set':<30} {'n':>3} {'val macro-F1 [CI]':<26} {'vs incumbent':>13}"
    print(header)
    print("-" * len(header))
    vote_sets: list[tuple[str, list[str]]] = [
        ("one per family", [INCUMBENT, "E2 xgboost svd256", "E4 minilm + logreg"]),
        ("linear family", [n for n in names if FAMILY[n] == "linear"]),
        ("top 5 by macro-F1", sorted(names, key=lambda n: -scores[n].macro_f1)[:5]),
        ("everything", names),
    ]
    best_vote = None
    for label, members in vote_sets:
        predicted = _majority_vote(members, predictions, predictions[INCUMBENT])
        sc = evaluate.score(truth, predicted, val_groups)
        delta = sc.macro_f1 - incumbent.macro_f1
        print(f"{label:<30} {len(members):>3} {sc.interval:<26} {delta:>+13.3f}")
        if best_vote is None or sc.macro_f1 > best_vote[1].macro_f1:
            best_vote = (label, sc, predicted)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    label, sc, predicted = best_vote
    a, b, p = evaluate.mcnemar(list(truth), list(predictions[INCUMBENT]), list(predicted))
    print(f"incumbent      {incumbent.interval}")
    print(f"best vote      {sc.interval}   ({label})")
    print(f"delta {sc.macro_f1 - incumbent.macro_f1:+.3f}  McNemar p={p:.4f}  "
          f"(incumbent-only-right {a}, vote-only-right {b})")
    if incumbent.overlaps(sc) or sc.macro_f1 <= incumbent.macro_f1:
        print("\n--> The reachable ensemble does not clear the incumbent's interval.")
        print("    F2 (soft voting / stacking) is NOT justified. Record and move to G.")
    else:
        print("\n--> The vote separates from the incumbent. F2 is justified.")


if __name__ == "__main__":
    main()
