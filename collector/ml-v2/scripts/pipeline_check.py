"""Does the full pipeline still merge unrelated articles?"""

from __future__ import annotations

from collections import Counter

from newsmlv2 import labels as labels_mod
from newsmlv2.pipeline import prepare_corpus, text_for


def main() -> None:
    prepared = prepare_corpus()
    print({k: v for k, v in prepared.counts.items()})
    print(f"affixes discovered for {len(prepared.affixes)} sources")
    for source, affix in list(prepared.affixes.items())[:6]:
        if affix.suffix:
            print(f"  suffix {source[:26]:<26} {affix.suffix[:70]!r}")
        if affix.prefix:
            print(f"  prefix {source[:26]:<26} {affix.prefix[:70]!r}")

    by_id = {k.article.id: k for k in prepared.admitted}
    members: dict[str, list[str]] = {}
    for aid, gid in prepared.grouping.group_of.items():
        members.setdefault(gid, []).append(aid)
    sizes = Counter(len(v) for v in members.values())
    print(f"\ngroup sizes: {dict(sorted(sizes.items()))}")

    for cluster in sorted(members.values(), key=len, reverse=True)[:3]:
        print(f"\n=== group of {len(cluster)} ===")
        for aid in cluster[:5]:
            k = by_id[aid]
            print(f"  {k.article.source_name[:26]:<26} {k.title.text[:62]}")

    gold = labels_mod.read_gold()
    labelled = [k for k in prepared.admitted if k.article.id in gold]
    groups: dict[str, set[str]] = {}
    for k in labelled:
        groups.setdefault(prepared.grouping.group_of[k.article.id], set()).add(gold[k.article.id])
    print(f"\nlabelled {len(labelled)} in {len(groups)} groups; "
          f"label-disagreeing groups {sum(len(v) > 1 for v in groups.values())}")

    words = sorted(len(text_for(k, 'title_body').split()) for k in prepared.admitted)
    print(f"title_body words p10/p50/p90: "
          f"{words[len(words)//10]}/{words[len(words)//2]}/{words[9*len(words)//10]}")


if __name__ == "__main__":
    main()
