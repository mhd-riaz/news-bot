"""How much does body-based grouping fold, and does it beat v1's title-based grouping?

Phase B2's prediction: materially more. A reworded headline hides a duplicate that an
identical body exposes, so grouping on title+summary alone should miss syndicated copy.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from newsmlv2 import config, labels as labels_mod, load
from newsmlv2.admit import Admitted, Policy, partition
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean_article
from newsmlv2.dedup import Doc, group


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    gold = labels_mod.read_gold()
    lookup = as_lookup(discover([(a.source_name, a.body) for a in articles if a.has_body]))

    candidates = []
    for a in articles:
        t, s, b = clean_article(a.title, a.summary, a.body, boilerplate=lookup.get(a.source_name))
        candidates.append(Admitted(article=a, title=t, summary=s, body=b))
    kept, _ = partition(candidates, policy=Policy(), now=cut)
    print(f"admitted {len(kept)}\n")

    def docs_for(variant: str) -> list[Doc]:
        out = []
        for k in kept:
            if variant == "title_summary":
                text = f"{k.title.text}\n{k.summary.text}"
            else:
                text = f"{k.title.text}\n{k.body.text or k.summary.text}"
            out.append(
                Doc(k.article.id, text, k.article.source_name, k.article.published_at)
            )
        return out

    results = {}
    for variant in ("title_summary", "title_body"):
        g = group(docs_for(variant))
        sizes = Counter(g.sizes().values())
        folded = len(kept) - g.group_count
        results[variant] = g
        print(f"--- {variant} ---")
        print(f"  story groups        {g.group_count}")
        print(f"  articles folded     {folded} ({folded / len(kept):.2%})")
        print(f"  pairs merged        {len(g.pairs)}")
        print(f"  blocked as template {len(g.rejected_as_template)}")
        print(f"  group sizes         {dict(sorted(sizes.items()))}")

    body = results["title_body"]
    short = results["title_summary"]
    extra = (len(kept) - body.group_count) - (len(kept) - short.group_count)
    print(f"\nbody-based grouping folds {extra} more articles than title+summary")
    if short.group_count:
        print(f"  = {extra / max(len(kept) - short.group_count, 1):+.0%} relative to v1's approach")

    # A duplicate that only the body catches: the pairs body finds and title does not.
    short_pairs = {(p.a, p.b) for p in short.pairs}
    only_body = [p for p in body.pairs if (p.a, p.b) not in short_pairs]
    by_id = {k.article.id: k for k in kept}
    print(f"\npairs only the body catches: {len(only_body)}")
    for p in sorted(only_body, key=lambda p: -p.score)[:8]:
        a, b = by_id[p.a], by_id[p.b]
        print(f"\n  {p.score:.2f}")
        print(f"    {a.article.source_name[:26]:<26} {a.title.text[:66]}")
        print(f"    {b.article.source_name[:26]:<26} {b.title.text[:66]}")

    labelled = [k for k in kept if k.article.id in gold]
    groups_with_labels: dict[str, set[str]] = {}
    for k in labelled:
        groups_with_labels.setdefault(body.group_of[k.article.id], set()).add(gold[k.article.id])
    multi = {g: v for g, v in groups_with_labels.items() if len(v) > 1}
    print(f"\nlabelled articles {len(labelled)} in {len(groups_with_labels)} groups")
    print(f"  groups whose gold labels disagree: {len(multi)}")


if __name__ == "__main__":
    main()
