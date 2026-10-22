"""The one path from raw articles to cleaned, admitted, grouped documents.

Every script and the snapshot builder go through here, so an experiment can never
accidentally use a different cleaning recipe from the snapshot it is compared against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import config, load
from .admit import Admitted, Policy, Rejection, partition
from .boilerplate import Affix, as_lookup, common_affixes, discover
from .clean import clean_article
from .dedup import Doc, Grouping, group


@dataclass(frozen=True, slots=True)
class Prepared:
    admitted: tuple[Admitted, ...]
    rejected: tuple[Rejection, ...]
    grouping: Grouping
    boilerplate: dict[str, frozenset[str]]
    affixes: dict[str, Affix]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "admitted": len(self.admitted),
            "rejected": len(self.rejected),
            "story_groups": self.grouping.group_count,
            "folded": len(self.admitted) - self.grouping.group_count,
            "merged_pairs": len(self.grouping.pairs),
            "blocked_as_template": len(self.grouping.rejected_as_template),
        }


def text_for(item: Admitted, variant: str) -> str:
    """The text a model sees. `title_summary` reproduces v1 for the parity baseline."""
    if variant == "title":
        return item.title.text
    if variant == "title_summary":
        return f"{item.title.text}\n{item.summary.text}".strip()
    if variant == "title_body":
        return f"{item.title.text}\n{item.body.text or item.summary.text}".strip()
    if variant == "full":
        return f"{item.title.text}\n{item.summary.text}\n{item.body.text}".strip()
    raise ValueError(f"unknown text variant: {variant}")


def prepare(
    articles: list[load.Article],
    *,
    policy: Policy | None = None,
    now: datetime | None = None,
    match_variant: str = "title_body",
) -> Prepared:
    """Clean, admit, then group by story.

    Boilerplate is discovered on the *raw* bodies before cleaning, which is the only
    order that works: the point is to learn what a source repeats, and cleaning is what
    consumes that knowledge.

    Discovery is keyed on **publisher**, not the section feed. Chrome belongs to the
    masthead -- the BBC spreads its articles over six feeds, so each one individually
    fell under the discovery floor and its shared footer survived into the text, where
    it merged 21 unrelated articles into one story group.
    """
    bodies = [(a.publisher, a.body) for a in articles if a.has_body]
    lookup = as_lookup(discover(bodies))
    affixes = common_affixes(bodies)

    candidates = []
    for a in articles:
        affix = affixes.get(a.publisher, Affix())
        title, summary, body = clean_article(
            a.title, a.summary, a.body,
            boilerplate=lookup.get(a.publisher),
            prefix=affix.prefix,
            suffix=affix.suffix,
        )
        candidates.append(Admitted(article=a, title=title, summary=summary, body=body))

    kept, rejected = partition(candidates, policy=policy or Policy(), now=now)

    grouping = group(
        [
            Doc(
                id=k.article.id,
                text=text_for(k, match_variant),
                publisher=k.article.publisher,
                published_at=k.article.published_at,
            )
            for k in kept
        ]
    )
    return Prepared(tuple(kept), tuple(rejected), grouping, lookup, affixes)


def prepare_corpus(*, limit: int | None = None, policy: Policy | None = None) -> Prepared:
    """Load the frozen corpus cut and prepare it."""
    cut = datetime.fromisoformat(config.COLLECTED_BEFORE)
    articles = load.load_articles(limit=limit, collected_before=cut)
    return prepare(articles, policy=policy, now=cut)
