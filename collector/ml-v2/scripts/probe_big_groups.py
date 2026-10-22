"""Why are unrelated BBC articles merging into giant story groups?"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from newsmlv2 import config, load
from newsmlv2.admit import Admitted, Policy, partition
from newsmlv2.boilerplate import as_lookup, discover
from newsmlv2.clean import clean_article, is_navigation
from newsmlv2.dedup import Doc, group


def main() -> None:
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(collected_before=cut)
    lookup = as_lookup(discover([(a.source_name, a.body) for a in articles if a.has_body]))

    candidates = []
    for a in articles:
        t, s, b = clean_article(a.title, a.summary, a.body, boilerplate=lookup.get(a.source_name))
        candidates.append(Admitted(article=a, title=t, summary=s, body=b))
    kept, _ = partition(candidates, policy=Policy(), now=cut)
    by_id = {k.article.id: k for k in kept}

    docs = [
        Doc(k.article.id, f"{k.title.text}\n{k.body.text or k.summary.text}",
            k.article.source_name, k.article.published_at)
        for k in kept
    ]
    g = group(docs)

    members: dict[str, list[str]] = {}
    for aid, gid in g.group_of.items():
        members.setdefault(gid, []).append(aid)

    biggest = sorted(members.values(), key=len, reverse=True)[:3]
    for cluster in biggest:
        print(f"\n=== group of {len(cluster)} ===")
        srcs = Counter(by_id[a].article.source_name for a in cluster)
        print(f"sources: {dict(srcs)}")
        for aid in cluster[:6]:
            k = by_id[aid]
            body = k.body.text
            lines = [ln for ln in body.split("\n") if ln.strip()]
            short = sum(len(ln.split()) <= 6 for ln in lines)
            print(f"\n  {k.article.source_name[:28]:<28} {k.title.text[:60]}")
            print(f"    body chars={len(body):<6} lines={len(lines):<4} "
                  f"short={short:<4} share={short / max(len(lines), 1):.0%} "
                  f"nav={is_navigation(body)}")
            print(f"    first 160: {body[:160]!r}")


if __name__ == "__main__":
    main()
