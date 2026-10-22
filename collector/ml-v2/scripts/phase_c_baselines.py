"""Phase C baselines, and the single-variable test of the core hypothesis.

Every model is run twice: once on `title_summary` (what v1 saw) and once on
`title_body`. The difference between those two rows is the entire premise of v2, and it
is measured with a confidence interval and a paired test rather than a subtraction.
"""

from __future__ import annotations

from newsmlv2 import config, evaluate, experiment, snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
MODELS = ["majority", "complement_nb", "tfidf_logreg", "tfidf_linear_svc", "word_char_svc"]
VARIANTS = ["title_summary", "title_body"]


def main() -> None:
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    print(f"snapshot {snap.snapshot_id} | labelled train/val "
          f"{snap.manifest['labelled_by_split']['train']}/{snap.manifest['labelled_by_split']['val']}\n")

    outcomes: dict[tuple[str, str], experiment.Outcome] = {}
    header = f"{'model':<18} {'variant':<15} {'macro-F1 [95% CI]':<26} {'acc':>6} {'Hindu':>7} {'Guardian':>9} {'fit s':>7}"
    print(header)
    print("-" * len(header))

    for model in MODELS:
        for variant in VARIANTS:
            setup = experiment.Setup(
                name=f"{model}:{variant}",
                model=model,
                variant=variant,
                note="phase C baseline",
            )
            outcome = experiment.run(snap, setup)
            experiment.record(outcome, snap)
            outcomes[(model, variant)] = outcome
            h = outcome.holdouts
            print(
                f"{model:<18} {variant:<15} {outcome.val.interval:<26} "
                f"{outcome.val.accuracy:>6.3f} "
                f"{h.get('The Hindu').macro_f1 if h.get('The Hindu') else float('nan'):>7.3f} "
                f"{h.get('The Guardian').macro_f1 if h.get('The Guardian') else float('nan'):>9.3f} "
                f"{outcome.fit_seconds:>7.1f}"
            )

    print("\n" + "=" * 78)
    print("THE BODY A/B  --  does the article body actually help?")
    print("=" * 78)
    for model in MODELS:
        if model == "majority":
            continue
        short, full = outcomes[(model, "title_summary")], outcomes[(model, "title_body")]
        delta = full.val.macro_f1 - short.val.macro_f1
        only_short, only_full, p = evaluate.mcnemar(
            list(full.truth), list(short.predictions), list(full.predictions)
        )
        verdict = (
            "body wins" if p < 0.05 and delta > 0
            else "short wins" if p < 0.05 and delta < 0
            else "no significant difference"
        )
        print(f"\n{model}")
        print(f"  title_summary {short.val.interval}")
        print(f"  title_body    {full.val.interval}")
        print(f"  delta {delta:+.3f} | intervals overlap: {short.val.overlaps(full.val)}")
        print(f"  McNemar: short-only-right {only_short}, body-only-right {only_full}, p={p:.2e}")
        print(f"  --> {verdict}")

    print("\n" + "=" * 78)
    print("WEAKEST CLASSES (best model, title_body)")
    print("=" * 78)
    best = max(
        (o for (m, v), o in outcomes.items() if m != "majority"),
        key=lambda o: o.val.macro_f1,
    )
    print(f"best rung: {best.setup.name}  {best.val.interval}")
    for c in sorted(best.val.per_class, key=lambda c: c.f1):
        print(f"  {c.topic:<22} F1 {c.f1:.3f}  P {c.precision:.3f}  R {c.recall:.3f}  n={c.support}")
    print("\ntop confusions:")
    for a, b, count in evaluate.top_confusions(best.val, 10):
        print(f"  {count:>4}  {a} -> {b}")


if __name__ == "__main__":
    main()
