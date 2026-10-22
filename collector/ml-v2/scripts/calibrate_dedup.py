"""Calibrate the near-duplicate threshold against v1's hand-judged pair census.

43 pairs, judged one by one: 31 the same story, 12 not. That census is a *census*, not
a sample -- it is every pair that existed in the 0.40-0.95 boundary region -- so it is
the only honest way to pick a cut.

v1's finding to beat: with a single MinHash threshold, precision could not exceed 0.80
at any cut, because its false positives were four structural kinds. This measures
whether the time-gap guard moves that ceiling.
"""

from __future__ import annotations

import csv
import json


from newsmlv2 import config
from newsmlv2.dedup import Doc, is_recurring_template, scores_for
from newsmlv2.pipeline import prepare_corpus, text_for

PAIRS_DIR = config.DATA_DIR / "pairs"
SHEET = PAIRS_DIR / "pairs.csv"
KEY = PAIRS_DIR / "pairs-key.jsonl"


def _judgements() -> dict[str, str]:
    with SHEET.open(encoding="utf-8-sig") as fh:  # the sheet is BOM'd
        return {r["pair_id"]: (r["same_story"] or "").strip().lower() for r in csv.DictReader(fh)}


def main() -> None:
    judged = _judgements()
    key = [json.loads(l) for l in KEY.read_text().splitlines() if l.strip()]
    truth = {
        (r["article_a"], r["article_b"]): judged.get(r["pair_id"], "")
        for r in key
        if judged.get(r["pair_id"]) in {"y", "n"}
    }
    print(f"judged pairs: {len(truth)}  (same story {sum(v == 'y' for v in truth.values())})")

    prepared = prepare_corpus()
    docs = [
        Doc(
            id=k.article.id,
            text=text_for(k, "title_body"),
            publisher=k.article.publisher,
            published_at=k.article.published_at,
        )
        for k in prepared.admitted
    ]
    by_id = {d.id: d for d in docs}
    print(f"admitted articles: {len(docs)}")

    reachable = {p: v for p, v in truth.items() if p[0] in by_id and p[1] in by_id}
    print(f"pairs still present after admission: {len(reachable)} of {len(truth)}")

    scores = scores_for(docs, list(reachable))
    print(f"\n{'cut':>5} {'guard':>6} {'TP':>4} {'FP':>4} {'FN':>4} {'prec':>6} {'rec':>6} {'F1':>6}")
    print("-" * 52)

    best = None
    for guard in (False, True):
        for cut_value in [round(x * 0.02, 2) for x in range(15, 46)]:
            tp = fp = fn = 0
            for pair, verdict in reachable.items():
                score = scores.get(pair, 0.0)
                merged = score >= cut_value
                if merged and guard and is_recurring_template(by_id[pair[0]], by_id[pair[1]]):
                    merged = False
                if verdict == "y":
                    tp += merged
                    fn += not merged
                else:
                    fp += merged
            precision = tp / (tp + fp) if tp + fp else 1.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            if cut_value in (0.44, 0.46, 0.50, 0.54, 0.60, 0.70, 0.72) or (
                best is None or f1 > best[0]
            ):
                print(f"{cut_value:>5.2f} {str(guard):>6} {tp:>4} {fp:>4} {fn:>4} "
                      f"{precision:>6.2f} {recall:>6.2f} {f1:>6.3f}")
            if guard and (best is None or f1 > best[0]):
                best = (f1, cut_value, precision, recall)

    print(f"\nbest with guard: cut={best[1]:.2f} F1={best[0]:.3f} "
          f"precision={best[2]:.2f} recall={best[3]:.2f}")
    print("v1 for comparison: precision could not exceed 0.80 at ANY single-threshold cut")

    print("\npairs the guard reclassified as recurring templates:")
    for pair, verdict in reachable.items():
        if is_recurring_template(by_id[pair[0]], by_id[pair[1]]):
            a, b = by_id[pair[0]], by_id[pair[1]]
            mark = "correct" if verdict == "n" else "WRONG (was same story)"
            print(f"  [{mark}] {scores.get(pair, 0):.2f} {a.source_name[:24]}")
            print(f"      {a.text.splitlines()[0][:74]}")
            print(f"      {b.text.splitlines()[0][:74]}")


if __name__ == "__main__":
    main()
