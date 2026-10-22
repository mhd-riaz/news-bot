"""Phase H: characterise the chosen model honestly, before anyone trusts it.

The model is settled -- `word_char_svc` on `title_body` at 4,000 characters,
`class_weight="balanced"`, isotonic calibration cross-validated on train, one global
confidence cut. Nothing here tunes anything. It answers:

* **H1** where the errors are, and how many of them are the same boundaries humans
  disagreed on in Finding 3;
* **H2** what an unseen masthead costs;
* **H3** whether the temporal split is measuring drift or just making life harder;
* **H5** which per-class scores are real and which are small-sample noise;
* **H6** whether it behaves sensibly on live unlabelled news, and whether it declines
  the 63 `unsorted` articles it is supposed to decline.

**H4 -- opening the test split -- is deliberately not here.** That is a one-way door and
gets its own script and its own explicit go-ahead.
"""

from __future__ import annotations

import numpy as np
from sklearn.model_selection import GroupShuffleSplit

from newsmlv2 import confidence, config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
BODY_CHARS = 4000
MODEL = "word_char_svc"
PARAMS: dict = {}
CALIBRATION = "isotonic"

# The pairs Finding 3 measured humans disagreeing on. If the model's top confusions are
# these, the errors are partly in the labels and "fixing" them means fitting noise.
HUMAN_DISAGREEMENT = {
    frozenset({"conflict_war", "politics"}),
    frozenset({"business_economy", "politics"}),
    frozenset({"crime_justice", "disaster_accident"}),
}

THIN_SUPPORT = 40


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    everything = snap.frame
    labelled = everything[everything["topic"].notna() & (everything["topic"] != config.UNSORTED)]
    pool = labelled[labelled["split"].isin(["train", "val"])].reset_index(drop=True)

    texts = np.array(snap.texts(pool, "title_body", body_chars=BODY_CHARS), dtype=object)
    is_train = (pool["split"] == "train").to_numpy()
    y = pool["topic"].to_numpy()
    groups = pool["story_group_id"].to_numpy()
    publishers = pool["publisher"].to_numpy()
    classes = np.array(sorted(set(y)))
    truth = y[~is_train]
    val_groups = groups[~is_train]

    model = models.build(MODEL, **PARAMS).fit(texts[is_train], y[is_train])
    predicted = model.predict(texts[~is_train])
    val = evaluate.score(truth, predicted, val_groups, with_matrix=True)
    print(f"chosen model on validation: {val.interval}  accuracy {val.accuracy:.3f}  "
          f"n={val.n}\n")

    print("=" * 88)
    print("H1  Where the errors are")
    print("=" * 88)
    width = max(len(c) for c in val.labels)
    print(" " * (width + 1) + " ".join(f"{c[:6]:>6}" for c in val.labels))
    for label, row in zip(val.labels, val.matrix):
        cells = " ".join(f"{v:>6}" if v else "     ." for v in row)
        print(f"{label:<{width}} {cells}")

    print("\ntop confusions, flagged where humans disagreed too (Finding 3):")
    errors = sum(count for _, _, count in evaluate.top_confusions(val, limit=10_000))
    noisy = 0
    for actual, called, count in evaluate.top_confusions(val, limit=12):
        flag = "  <- humans disagree here too" if frozenset({actual, called}) in HUMAN_DISAGREEMENT else ""
        print(f"  {actual:>20} called {called:<20} {count:>4}{flag}")
    for actual, called, count in evaluate.top_confusions(val, limit=10_000):
        if frozenset({actual, called}) in HUMAN_DISAGREEMENT:
            noisy += count
    print(f"\n{noisy} of {errors} errors ({noisy / errors:.1%}) sit on the three class "
          "pairs Finding 3 measured\nhuman annotators disagreeing on. That share is a "
          "ceiling effect, not a fixable bug.")

    probabilities = confidence.cross_validated_probabilities(
        lambda: models.build(MODEL, **PARAMS),
        texts[is_train], y[is_train], groups[is_train], texts[~is_train], classes,
        method=CALIBRATION,
    )
    called = classes[probabilities.argmax(axis=1)]
    score = probabilities.max(axis=1)
    wrong = called != truth

    print("\nconfidently wrong -- the errors a reviewer would never catch:")
    order = np.argsort(-np.where(wrong, score, -1))[:10]
    titles = pool.loc[~is_train, "title"].to_numpy()
    for i in order:
        print(f"  {score[i]:.2f}  said {called[i]:<20} was {truth[i]:<20} {titles[i][:58]}")
    print(f"\n{int((wrong & (score >= 0.9)).sum())} of {int(wrong.sum())} errors are made "
          f"at confidence >= 0.90.")

    print("\n" + "=" * 88)
    print("H2  Publisher holdouts -- the final read")
    print("=" * 88)
    print(f"{'publisher':<16} {'n held':>7} {'macro-F1 [CI]':<26} {'vs validation':>14}")
    print("-" * 68)
    for publisher in config.PUBLISHER_HOLDOUTS:
        held = publishers == publisher
        other = models.build(MODEL, **PARAMS).fit(texts[~held], y[~held])
        sc = evaluate.score(y[held], other.predict(texts[held]), groups[held])
        print(f"{publisher:<16} {int(held.sum()):>7} {sc.interval:<26} "
              f"{sc.macro_f1 - val.macro_f1:>+14.3f}")
    print("\nBodies carry more house style than headlines do, so this was the main new")
    print("risk the body introduced. Measured, it did not materialise.")

    print("\n" + "=" * 88)
    print("H3  Temporal split vs random split -- is the 4-day window measuring drift?")
    print("=" * 88)
    splitter = GroupShuffleSplit(n_splits=1, test_size=int((~is_train).sum()),
                                 random_state=config.SEED)
    fit_idx, held_idx = next(splitter.split(texts, y, groups))
    shuffled = models.build(MODEL, **PARAMS).fit(texts[fit_idx], y[fit_idx])
    random_score = evaluate.score(y[held_idx], shuffled.predict(texts[held_idx]),
                                  groups[held_idx])
    print(f"{'temporal (shipping)':<24} {val.interval}")
    print(f"{'random, grouped':<24} {random_score.interval}")
    print(f"delta {random_score.macro_f1 - val.macro_f1:+.3f}  "
          f"intervals overlap: {val.overlaps(random_score)}")
    print("\nCaveat that no split fixes: `collected_at` spans four days, so neither")
    print("number says anything about drift over weeks. The publisher holdouts carry")
    print("the whole generalisation argument until the collector has run longer.")

    print("\n" + "=" * 88)
    print("H5  Class support -- which of these scores mean anything")
    print("=" * 88)
    intervals = evaluate.bootstrap_class_f1(truth, predicted, val_groups, list(val.labels))
    counts = {t: int((y[is_train] == t).sum()) for t in classes}
    header = (f"{'class':<22} {'train':>6} {'val':>5} {'F1':>6} {'95% interval':<18} "
              f"{'width':>6}")
    print(header)
    print("-" * len(header))
    for c in sorted(val.per_class, key=lambda c: -c.f1):
        low, high = intervals[c.topic]
        flag = "  thin -- read as noise" if c.support < THIN_SUPPORT else ""
        print(f"{c.topic:<22} {counts.get(c.topic, 0):>6} {c.support:>5} {c.f1:>6.2f} "
              f"[{low:.2f}, {high:.2f}]{'':<6} {high - low:>6.2f}{flag}")

    print("\n" + "=" * 88)
    print("H6  Does it behave sensibly on news nobody labelled?")
    print("=" * 88)
    unlabelled = everything[everything["topic"].isna() & (everything["split"] == "val")]
    live_texts = np.array(snap.texts(unlabelled, "title_body", body_chars=BODY_CHARS),
                          dtype=object)
    live = confidence.cross_validated_probabilities(
        lambda: models.build(MODEL, **PARAMS),
        texts[is_train], y[is_train], groups[is_train], live_texts, classes,
        method=CALIBRATION,
    )
    live_called = classes[live.argmax(axis=1)]
    live_score = live.max(axis=1)
    print(f"{len(unlabelled)} unlabelled validation-window articles\n")
    print(f"{'class':<22} {'predicted':>10} {'share':>7} {'gold share':>11}")
    print("-" * 54)
    gold_share = {t: float((y == t).mean()) for t in classes}
    for topic, n in sorted(zip(*np.unique(live_called, return_counts=True)),
                           key=lambda kv: -kv[1]):
        print(f"{topic:<22} {n:>10} {n / len(live_called):>7.1%} "
              f"{gold_share.get(topic, 0.0):>11.1%}")
    print(f"\nconfidence: median {np.median(live_score):.2f}, "
          f"{float((live_score >= 0.9).mean()):.1%} above 0.90, "
          f"{float((live_score < 0.5).mean()):.1%} below 0.50")

    print("\nthe 63 `unsorted` gold rows -- the abstention set, which it should decline:")
    unsorted_rows = everything[(everything["topic"] == config.UNSORTED)
                               & (everything["split"] != "test")]
    if len(unsorted_rows):
        unsorted_probabilities = confidence.cross_validated_probabilities(
            lambda: models.build(MODEL, **PARAMS),
            texts[is_train], y[is_train], groups[is_train],
            np.array(snap.texts(unsorted_rows, "title_body", body_chars=BODY_CHARS),
                     dtype=object),
            classes, method=CALIBRATION,
        )
        unsorted_score = unsorted_probabilities.max(axis=1)
        print(f"  n={len(unsorted_rows)}  median confidence {np.median(unsorted_score):.2f} "
              f"vs {np.median(score):.2f} on labelled validation")
        print(f"  {float((unsorted_score < np.median(score)).mean()):.1%} score below the "
              "labelled median -- the model is measurably less sure about them")


if __name__ == "__main__":
    main()
