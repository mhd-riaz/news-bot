"""Phase D: how much body, and how much should the headline count?

The body averages ~500 words against a ~10-word headline, so left alone it drowns the
title -- and titles are the most informative single field in news. Two cheap levers:
truncate the body, and repeat the title so it carries proportionate weight.

The title repetition is deliberately the crude version of a weighted FeatureUnion. If
the crude one matches, it wins: same result, far less machinery.
"""

from __future__ import annotations

import numpy as np

from newsmlv2 import config, evaluate, models
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
MODEL = "word_char_svc"

BODY_LENGTHS = [0, 256, 512, 1024, 2048, 4000, 8000, None]
TITLE_REPEATS = [1, 2, 3, 5]


def _assemble(frame, body_chars, title_repeat, *, head_tail=False):
    title = frame["title"].fillna("")
    summary = frame["summary"].fillna("")
    body = frame["body"].fillna("")

    if body_chars == 0:
        payload = summary
    elif body_chars is None:
        payload = body.where(body.str.strip() != "", summary)
    elif head_tail:
        half = body_chars // 2
        payload = body.str.slice(0, half) + " " + body.str.slice(-half)
        payload = payload.where(body.str.strip() != "", summary)
    else:
        payload = body.str.slice(0, body_chars)
        payload = payload.where(body.str.strip() != "", summary)

    return ((title + "\n") * title_repeat + payload).tolist()


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)

    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    groups = frame["story_group_id"].to_numpy()
    publishers = frame["publisher"].to_numpy()
    print(f"train {is_train.sum()} / val {(~is_train).sum()}\n")

    def evaluate_texts(texts):
        texts = np.array(texts, dtype=object)
        model = models.build(MODEL)
        model.fit(texts[is_train], y[is_train])
        val = evaluate.score(y[~is_train], model.predict(texts[~is_train]), groups[~is_train])
        holds = {}
        for publisher in config.PUBLISHER_HOLDOUTS:
            held = publishers == publisher
            other = models.build(MODEL)
            other.fit(texts[~held], y[~held])
            holds[publisher] = evaluate.score(y[held], other.predict(texts[held]), groups[held]).macro_f1
        return val, holds

    header = f"{'body chars':>11} {'title x':>8} {'val macro-F1 [CI]':<26} {'Hindu':>7} {'Guardian':>9}"
    print(header)
    print("-" * len(header))

    results = {}
    for length in BODY_LENGTHS:
        val, holds = evaluate_texts(_assemble(frame, length, 1))
        results[(length, 1)] = val
        label = "none" if length == 0 else ("full" if length is None else str(length))
        print(f"{label:>11} {1:>8} {val.interval:<26} "
              f"{holds['The Hindu']:>7.3f} {holds['The Guardian']:>9.3f}")

    best_length = max(
        (l for l in BODY_LENGTHS if l != 0),
        key=lambda l: results[(l, 1)].macro_f1,
    )
    print(f"\nbest body length: {best_length}. Now sweeping title weight at that length.\n")
    print(header)
    print("-" * len(header))
    for repeat in TITLE_REPEATS:
        val, holds = evaluate_texts(_assemble(frame, best_length, repeat))
        results[(best_length, repeat)] = val
        print(f"{str(best_length):>11} {repeat:>8} {val.interval:<26} "
              f"{holds['The Hindu']:>7.3f} {holds['The Guardian']:>9.3f}")

    print("\nhead+tail instead of head only:")
    print(header)
    print("-" * len(header))
    for length in (1024, 2048, 4000):
        val, holds = evaluate_texts(_assemble(frame, length, 1, head_tail=True))
        print(f"{length:>11} {'1 h+t':>8} {val.interval:<26} "
              f"{holds['The Hindu']:>7.3f} {holds['The Guardian']:>9.3f}")

    print("\n" + "=" * 78)
    baseline = results[(4000, 1)]
    best_key = max(results, key=lambda k: results[k].macro_f1)
    best = results[best_key]
    print(f"baseline (4000 chars, title x1): {baseline.interval}")
    print(f"best      {best_key}: {best.interval}")
    print(f"delta {best.macro_f1 - baseline.macro_f1:+.3f} | "
          f"intervals overlap: {baseline.overlaps(best)}")
    if baseline.overlaps(best):
        print("--> overlapping intervals: the extra tuning bought nothing measurable.")


if __name__ == "__main__":
    main()
