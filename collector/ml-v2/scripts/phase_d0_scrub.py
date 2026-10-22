"""Phase D0: does scrubbing publisher fingerprints actually help?

The acceptance test is deliberately awkward: a rule must improve the **publisher
holdout more than validation**. Validation shares publishers with training, so a
shortcut still pays there -- only the holdout exposes it. A rule that lifts validation
alone removed information rather than noise, and gets reverted.
"""

from __future__ import annotations

import time

import numpy as np

from newsmlv2 import config, evaluate, labels as labels_mod, models, scrub
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
MODEL = "word_char_svc"
VARIANT = "title_body"
ANNOTATION = config.CACHE_DIR / SNAPSHOT_ID / "annotated.parquet"

POLICIES = [
    scrub.ScrubPolicy(),
    scrub.ScrubPolicy(mask_person=True),
    scrub.ScrubPolicy(mask_place=True),
    scrub.ScrubPolicy(mask_numbers=True),
    scrub.ScrubPolicy(lemmatise=True),
    scrub.ScrubPolicy(mask_person=True, mask_place=True),
    scrub.ScrubPolicy(mask_person=True, mask_place=True, mask_numbers=True),
    scrub.ScrubPolicy(mask_person=True, mask_place=True, mask_numbers=True, lemmatise=True),
]


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    taxonomy = labels_mod.read_taxonomy()
    frame = snap.frame
    frame = frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]
    frame = frame[frame["split"].isin(["train", "val"])].reset_index(drop=True)
    print(f"labelled train+val: {len(frame)}")

    texts = snap.texts(frame, VARIANT, body_chars=2500)
    ids = frame["article_id"].tolist()

    if ANNOTATION.exists():
        cached_ids, annotated = scrub.load(ANNOTATION)
        order = {a: i for i, a in enumerate(cached_ids)}
        annotated = [annotated[order[a]] for a in ids]
        print(f"loaded annotations from {ANNOTATION.name}")
    else:
        print("running the spaCy pass once (this is the expensive part)...")
        started = time.perf_counter()
        annotated = scrub.annotate(texts)
        print(f"  annotated {len(annotated)} docs in {time.perf_counter() - started:.0f}s")
        scrub.save(annotated, ids, ANNOTATION)

    is_train = (frame["split"] == "train").to_numpy()
    y = frame["topic"].to_numpy()
    groups = frame["story_group_id"].to_numpy()
    publishers = frame["publisher"].to_numpy()

    header = (f"{'policy':<38} {'val macro-F1 [CI]':<26} {'Hindu':>7} {'Guardian':>9} "
              f"{'pub probe':>10}")
    print("\n" + header)
    print("-" * len(header))

    baseline: dict[str, float] = {}
    for policy in POLICIES:
        rendered = np.array(scrub.render_all(annotated, policy, taxonomy.geography))

        model = models.build(MODEL)
        model.fit(rendered[is_train], y[is_train])
        predicted = model.predict(rendered[~is_train])
        val = evaluate.score(y[~is_train], predicted, groups[~is_train])

        holdouts = {}
        for publisher in config.PUBLISHER_HOLDOUTS:
            held = publishers == publisher
            if not held.any():
                continue
            other = models.build(MODEL)
            other.fit(rendered[~held], y[~held])
            holdouts[publisher] = evaluate.score(y[held], other.predict(rendered[held]), groups[held])

        probe = scrub.publisher_probe(list(rendered[is_train][:3000]), list(publishers[is_train][:3000]))

        label = policy.label()
        if policy.is_noop:
            baseline = {"val": val.macro_f1, "probe": probe,
                        **{p: s.macro_f1 for p, s in holdouts.items()}}

        print(f"{label:<38} {val.interval:<26} "
              f"{holdouts.get('The Hindu').macro_f1 if 'The Hindu' in holdouts else float('nan'):>7.3f} "
              f"{holdouts.get('The Guardian').macro_f1 if 'The Guardian' in holdouts else float('nan'):>9.3f} "
              f"{probe:>10.3f}")

        if not policy.is_noop and baseline:
            d_val = val.macro_f1 - baseline["val"]
            d_hold = np.mean([holdouts[p].macro_f1 - baseline[p] for p in holdouts if p in baseline])
            d_probe = probe - baseline["probe"]
            verdict = (
                "KEEP  (holdout gains more than val)" if d_hold > d_val and d_hold > 0
                else "reject (val only, or worse)"
            )
            print(f"{'':<38} d_val {d_val:+.3f}  d_holdout {d_hold:+.3f}  "
                  f"d_probe {d_probe:+.3f}  -> {verdict}")

    print("\nThe probe should FALL as fingerprints are removed; the holdout should RISE.")


if __name__ == "__main__":
    main()
