"""Phase A smoke test: does the data layer see the corpus and the labels correctly?"""

import collections

from newsmlv2 import config, labels, load


def main() -> None:
    tax = labels.read_taxonomy()
    print(f"taxonomy v{tax.version}: {len(tax.classes)} classes")
    print(f"  {', '.join(tax.classes)}")
    print(f"  geography stoplist {len(tax.geography)} terms, non_topical {len(tax.non_topical)}")

    gold = labels.read_gold()
    train = labels.trainable(gold, tax)
    abstain = labels.abstention_set(gold)
    print(f"\ngold rows {len(gold)} | trainable {len(train)} | abstention set {len(abstain)}")
    print(f"gold digest {config.digest(config.LABEL_PATH)[:16]}…")

    counts = collections.Counter(train.values())
    floor = min(counts.values())
    print(f"\nderived class floor = {floor} ({counts.most_common()[-1][0]})")
    for topic, n in counts.most_common():
        print(f"  {topic:<22} {n:>5}")
    assert len(counts) == 13, f"expected 13 trainable classes, got {len(counts)}"
    assert config.UNSORTED not in counts, "unsorted leaked into the trainable set"

    from datetime import datetime

    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    print(f"\ncorpus before {cut:%Y-%m-%d}: {len(articles)} articles")

    with_body = sum(a.has_body for a in articles)
    print(f"  with body    {with_body:>6} ({with_body / len(articles):.1%})")
    print(f"  with summary {sum(bool(a.summary) for a in articles):>6}")
    print(f"  no lede      {sum(not a.lede for a in articles):>6}")

    pubs = load.by_publisher(articles)
    print(f"\npublishers {len(pubs)} (from {len({a.source_name for a in articles})} feeds)")
    for name in config.PUBLISHER_HOLDOUTS:
        print(f"  holdout {name!r}: {len(pubs.get(name, []))} articles")
    for name, arts in sorted(pubs.items(), key=lambda kv: -len(kv[1]))[:6]:
        print(f"  {name:<28} {len(arts):>5}")

    joined = sum(1 for a in articles if a.id in gold)
    print(f"\ngold ids joining this corpus cut: {joined} of {len(gold)}")


if __name__ == "__main__":
    main()
