"""Run cleaning and admission over the whole corpus and report what was dropped.

Every new rule gets eyeballed against real data before a snapshot depends on it. v1
shipped a regex that matched a diplomacy story because nobody looked at the hits.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from newsmlv2 import config, labels as labels_mod, load
from newsmlv2.admit import Admitted, Policy, partition
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean_article


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    gold = labels_mod.read_gold()
    lookup = as_lookup(discover([(a.source_name, a.body) for a in articles if a.has_body]))

    candidates = []
    for a in articles:
        t, s, b = clean_article(a.title, a.summary, a.body, boilerplate=lookup.get(a.source_name))
        candidates.append(Admitted(article=a, title=t, summary=s, body=b))

    kept, rejected = partition(candidates, policy=Policy(), now=cut)
    print(f"in      {len(articles)}")
    print(f"kept    {len(kept)} ({len(kept) / len(articles):.1%})")
    print(f"dropped {len(rejected)} ({len(rejected) / len(articles):.1%})\n")

    by_reason = Counter(r.reason for r in rejected)
    gold_by_reason: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for r in rejected:
        if r.article_id in gold:
            gold_by_reason[r.reason] += 1
        if len(examples[r.reason]) < 6:
            examples[r.reason].append(f"{r.source_name[:24]:<24} {r.detail[:70]}")

    print(f"{'reason':<24} {'n':>6} {'gold lost':>10}")
    print("-" * 44)
    for reason, n in by_reason.most_common():
        print(f"{reason:<24} {n:>6} {gold_by_reason[reason]:>10}")

    print(f"\ngold labels surviving admission: {sum(1 for a in kept if a.article.id in gold)} of {len(gold)}")

    for reason, _ in by_reason.most_common():
        print(f"\n--- {reason} ---")
        for line in examples[reason]:
            print(f"  {line}")

    bodies = sum(1 for a in kept if a.body.text)
    print(f"\nkept articles with a usable body: {bodies} ({bodies / len(kept):.1%})")
    words = sorted(a.word_count for a in kept)
    print(f"word count p10/p50/p90: {words[len(words)//10]}/{words[len(words)//2]}/{words[9*len(words)//10]}")


if __name__ == "__main__":
    main()
