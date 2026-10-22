"""Weak labels, their provenance, and how disagreement between them is resolved.

Provenance is load-bearing: every label records where it came from, so a
publisher prior, a publisher's category and a human decision stay distinguishable
after the fact and can be measured against one another.

Two signals are available before any human looks at an article: the topic its
publisher mostly covers, and the publisher's own categories. Neither is trusted
alone — the pilot gold set measured a lone signal at 58% group-level agreement.
Where the two concur the label is accepted; otherwise the article goes to review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .load import Article


class LabelSource(StrEnum):
    """Where a label came from. Ordered by how much it should be trusted."""

    HUMAN = "human"
    FEED = "feed"
    PUBLISHER = "publisher"
    CATEGORY = "category"


# A human decision is final. A section feed is structural: everything on
# theguardian.com/sport/rss is sport. A publisher prior is not — the pilot caught
# it naming the wrong group 42% of the time — and a publisher's own categories
# are noisier still, since publishers fragment and reuse their vocabulary freely.
_PRIORITY = {
    LabelSource.HUMAN: 0,
    LabelSource.FEED: 1,
    LabelSource.PUBLISHER: 2,
    LabelSource.CATEGORY: 3,
}


@dataclass(frozen=True, slots=True)
class TopicClass:
    id: str
    description: str
    excludes: str = ""
    iptc: str = ""
    parent: str = ""


@dataclass(frozen=True, slots=True)
class Label:
    article_id: str
    topic: str
    source: LabelSource
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Resolved:
    """The outcome for one article, and whether a human still needs to see it."""

    article_id: str
    topic: str
    source: LabelSource | None
    agreement: bool
    needs_review: bool
    candidates: tuple[Label, ...]


@dataclass(frozen=True, slots=True)
class Taxonomy:
    version: int
    unsorted: str
    classes: tuple[TopicClass, ...]
    feed_topics: dict[str, str]
    publisher_topics: dict[str, str]
    category_map: dict[str, str]
    geography: frozenset[str]
    non_topical: frozenset[str]

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(c.id for c in self.classes)

    @property
    def groups(self) -> tuple[TopicClass, ...]:
        """Every class, in declaration order.

        Named `groups` from the v3 two-level taxonomy, where this meant
        "top-level only". Since v4 is flat, every class has no parent, so this
        is now simply all of them — kept under the old name for call-site
        stability.
        """
        return tuple(c for c in self.classes if not c.parent)

    def children_of(self, group_id: str) -> tuple[TopicClass, ...]:
        """Always empty under the fixed v4 taxonomy — no class has a parent any more."""
        return tuple(c for c in self.classes if c.parent == group_id)

    def collapse(self, topic: str, starved: frozenset[str]) -> str:
        """Fold a starved child into its parent, repeatedly if needed.

        A no-op under the fixed v4 taxonomy: no class has a parent to fold into,
        so a starved class is reported as out of scope instead (see
        `dataset.MIN_PER_CLASS`). Kept for any v3-vintage child id that still
        turns up in old data.
        """
        by_id = {c.id: c for c in self.classes}
        seen: set[str] = set()
        while topic in starved and topic not in seen:
            seen.add(topic)
            parent = by_id[topic].parent if topic in by_id else ""
            if not parent or parent == topic:
                return topic
            topic = parent
        return topic

    def canonical(self, value: str) -> str | None:
        """Return the class id if `value` names one, else None.

        Every externally produced label passes through here. A spreadsheet
        round-trip capitalises, autocompletes and substitutes values freely, so
        nothing becomes a label without matching the allow-list.
        """
        candidate = (value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        return candidate if candidate in self.ids else None


def load_taxonomy(path: Path) -> Taxonomy:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Taxonomy(
        version=int(raw["version"]),
        unsorted=str(raw.get("unsorted", "unsorted")),
        classes=tuple(
            TopicClass(id=str(c["id"]), description=str(c.get("description", "")).strip(),
                       excludes=str(c.get("excludes", "")).strip(),
                       iptc=str(c.get("iptc", "")).strip(),
                       parent=str(c.get("parent", "")).strip())
            for c in raw["classes"]
        ),
        feed_topics={str(k): str(v) for k, v in (raw.get("feed_topics") or {}).items()},
        publisher_topics={str(k): str(v) for k, v in (raw.get("publisher_topics") or {}).items()},
        category_map={str(k).casefold(): str(v) for k, v in (raw.get("category_map") or {}).items()},
        geography=frozenset(str(g).casefold() for g in (raw.get("geography") or [])),
        non_topical=frozenset(str(n).casefold() for n in (raw.get("non_topical") or [])),
    )


def from_feed(article: Article, taxonomy: Taxonomy) -> Label | None:
    """The section a feed names applies to every article that arrives on it."""
    topic = taxonomy.feed_topics.get(article.source_name)
    if topic is None or taxonomy.canonical(topic) is None:
        return None
    return Label(article.id, topic, LabelSource.FEED, article.source_name)


def from_publisher(article: Article, taxonomy: Taxonomy) -> Label | None:
    """The topic a publisher mostly covers. A prior, never a fact on its own."""
    topic = taxonomy.publisher_topics.get(article.source_name)
    if topic is None or taxonomy.canonical(topic) is None:
        return None
    return Label(article.id, topic, LabelSource.PUBLISHER, article.source_name)


def from_categories(article: Article, taxonomy: Taxonomy) -> Label | None:
    """Map the publisher's own categories, when any of them names a topic.

    Sorted before the first match so the result never depends on the order the
    publisher happened to emit its categories in.
    """
    for raw in sorted(c.casefold() for c in article.categories):
        if (topic := taxonomy.category_map.get(raw)) and taxonomy.canonical(topic):
            return Label(article.id, topic, LabelSource.CATEGORY, raw)
    return None


def is_geography_only(article: Article, taxonomy: Taxonomy) -> bool:
    """True when an article carries categories but none of them names a topic."""
    values = {c.casefold() for c in article.categories}
    return bool(values) and all(v in taxonomy.geography or v in taxonomy.non_topical for v in values)


def resolve(article_id: str, candidates: list[Label], taxonomy: Taxonomy) -> Resolved:
    """Reconcile every signal for one article into a single decision."""
    if not candidates:
        return Resolved(article_id, taxonomy.unsorted, None, False, True, ())

    ordered = tuple(sorted(candidates, key=lambda c: (_PRIORITY[c.source], c.source, c.topic)))

    human = next((c for c in ordered if c.source is LabelSource.HUMAN), None)
    if human is not None:
        return Resolved(article_id, human.topic, LabelSource.HUMAN, True, False, ordered)

    best = ordered[0]
    topics = {c.topic for c in ordered}

    # Two signals concurring is the strongest evidence available without a human.
    if len(ordered) > 1 and len(topics) == 1:
        return Resolved(article_id, best.topic, best.source, True, False, ordered)

    # A lone section feed still stands on its own, because the section is a fact
    # about the feed rather than a guess about the article. A lone publisher
    # prior or category does not: the pilot measured those at 58% group
    # agreement with gold, which is not good enough to accept unseen.
    trusted = best.source is LabelSource.FEED and len(topics) == 1
    return Resolved(article_id, best.topic, best.source, False, not trusted, ordered)
