"""Assemble the supervised dataset the classifier trains on.

Everything upstream of this module is unsupervised bookkeeping: cleansing,
admission, near-duplicate grouping. This is where an article becomes an
`(x, y)` pair, and where the two decisions that shape v1 are enforced:

* **The taxonomy is fixed and flat (v4).** It went through a two-level, 26-class
  phase first; `group_of_topic`/`collapse_to_group` still exist and are now a
  no-op (every class is already its own group) — kept rather than ripped out so
  a v3-vintage label recorded before the flattening still resolves the same way.
* **A class below `min_per_class` is out of scope, not a class with few
  examples.** Its articles are removed from the supervised set and counted.
  `crime_justice`, `conflict_war` and `disaster_accident` receive no weak label
  at all, so a model trained here can never emit them — reporting how much of
  the corpus that silently excludes is the point of counting it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from . import admit as admit_mod
from . import clean as clean_mod
from . import neardup as neardup_mod
from .config import DEFAULT_TEXT_VARIANT
from .labels import Label, LabelSource, Taxonomy, from_categories, from_feed, from_publisher, resolve
from .load import Article
from .snapshot import Snapshot

# Below this, a class is not thin — it is absent, and pretending otherwise buys
# a class that scores badly and hides the finding. Provisional; see the plan.
MIN_PER_CLASS = 300


@dataclass(frozen=True, slots=True)
class Example:
    """One `(x, y)` pair, carrying the provenance every report needs."""

    article_id: str
    text: str
    topic: str
    label_source: str
    source_name: str
    group_id: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class Dataset:
    train: tuple[Example, ...]
    val: tuple[Example, ...]
    test: tuple[Example, ...]
    classes: tuple[str, ...]
    out_of_scope: tuple[Example, ...]
    unlabelled: int
    rejected: int
    dropped_at_boundary: int
    variant: str
    gold: tuple[Example, ...] = ()
    withheld_for_gold: int = 0
    provenance: dict[str, object] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "val": len(self.val),
            "test": len(self.test),
            "gold": len(self.gold),
            "out_of_scope": len(self.out_of_scope),
            "unlabelled": self.unlabelled,
            "rejected": self.rejected,
            "dropped_at_boundary": self.dropped_at_boundary,
            "withheld_for_gold": self.withheld_for_gold,
        }

    @property
    def unreachable(self) -> dict[str, int]:
        """Gold classes the model cannot emit, because nothing taught it them."""
        missing = Counter(e.topic for e in self.gold if e.topic not in self.classes)
        return dict(sorted(missing.items(), key=lambda kv: -kv[1]))

    def distribution(self, split: str = "train") -> dict[str, int]:
        rows: tuple[Example, ...] = getattr(self, split)
        return dict(sorted(Counter(e.topic for e in rows).items(), key=lambda kv: -kv[1]))

    def xy(self, split: str) -> tuple[list[str], list[str]]:
        rows: tuple[Example, ...] = getattr(self, split)
        return [e.text for e in rows], [e.topic for e in rows]


def group_of_topic(topic: str, taxonomy: Taxonomy) -> str:
    """Walk a child class up to the group it belongs to.

    A no-op since v4: every class is its own group now. Kept so a v3-vintage
    child id, if one ever turns up again, still resolves rather than silently
    entering the class list unrecognised.
    """
    parent = {c.id: c.parent for c in taxonomy.classes}
    seen: set[str] = set()
    while parent.get(topic) and topic not in seen:
        seen.add(topic)
        topic = parent[topic]
    return topic


def _at_level(topic: str, taxonomy: Taxonomy, collapse: bool) -> str:
    return group_of_topic(topic, taxonomy) if collapse else topic


def weak_label(
    article: Article, taxonomy: Taxonomy, *, collapse: bool = True
) -> tuple[str, LabelSource | None]:
    """Resolve every available weak signal into one topic.

    `collapse` is a no-op under the fixed v4 taxonomy (every class is already a
    group); it is a leftover hook from the two-level v3 taxonomy, kept for
    signature stability rather than for anything it still does.
    """
    candidates: list[Label] = [
        label
        for label in (
            from_feed(article, taxonomy),
            from_publisher(article, taxonomy),
            from_categories(article, taxonomy),
        )
        if label is not None
    ]
    resolved = resolve(article.id, candidates, taxonomy)
    topic = group_of_topic(resolved.topic, taxonomy) if collapse else resolved.topic
    return topic, resolved.source


def build(
    articles: list[Article],
    taxonomy: Taxonomy,
    *,
    variant: str = DEFAULT_TEXT_VARIANT,
    min_per_class: int = MIN_PER_CLASS,
    gold: dict[str, str] | None = None,
    holdout: dict[str, str] | None = None,
    collapse_to_group: bool = True,
    use_weak_labels: bool = True,
) -> Dataset:
    """Clean, admit, group, label and split — in that order.

    `gold` overrides the weak label where a human has ruled, keyed by article id.
    A gold label wins outright: that is the whole reason for collecting it, and
    it is the only way a class no RSS section names can enter the class list.

    `holdout` is the opposite arrangement, and the honest one: the same human
    labels are withheld from training entirely and returned as their own split,
    so the model is scored against people instead of against the weak teacher
    that trained it. The whole near-duplicate group of a held-out article is
    withheld too — otherwise a reworded wire copy of a scored article sits in
    train and the number flatters itself.

    Passing both is the arrangement a shipped model needs: one slice of the
    human labels teaches the rare classes, a disjoint slice scores the result.
    Only an article appearing in both is an error, because that is the one case
    where the model is tested on a label it was handed.

    `collapse_to_group` and `use_weak_labels` are v3-era hooks for the retired
    two-level taxonomy. Under the fixed v4 taxonomy every class already is a
    group, so `collapse_to_group=False` no longer produces a finer class list —
    there is no finer level left to fall back to.
    """
    from .splits import SplitRow, make_splits

    if gold and holdout and (taught_and_scored := set(gold) & set(holdout)):
        raise ValueError(
            f"{len(taught_and_scored)} article(s) are in both gold and holdout, so the model "
            f"would be scored on a label it was taught, e.g. {sorted(taught_and_scored)[0]}"
        )

    pairs = [(a, clean_mod.clean(a.text(variant))) for a in articles]
    admitted, rejected = admit_mod.partition(pairs, check_language=False)

    texts = {a.article.id: a.cleaned.text for a in admitted}
    grouping = neardup_mod.group(texts)

    holdout = holdout or {}
    held_groups = {
        grouping.group_of.get(article_id, article_id) for article_id in holdout if article_id in texts
    }

    labelled: list[Example] = []
    gold_rows: list[Example] = []
    unlabelled = 0
    withheld = 0

    for entry in admitted:
        article = entry.article
        group_id = grouping.group_of.get(article.id, article.id)

        def _example(topic: str, source: object) -> Example:
            return Example(
                article_id=article.id,
                text=entry.cleaned.text,
                topic=topic,
                label_source=str(source),
                source_name=article.source_name,
                group_id=group_id,
                published_at=article.published_at,
            )

        if group_id in held_groups:
            human = holdout.get(article.id)
            topic = _at_level(human, taxonomy, collapse_to_group) if human else ""
            # `unsorted` is the absence of a class, not a class. Scoring a topic
            # classifier on it would add a row it can never get right and a
            # zero to the macro average, for an article that is not about
            # anything. Weak labels get the same treatment a few lines below.
            if topic and topic != taxonomy.unsorted:
                gold_rows.append(_example(topic, LabelSource.HUMAN))
            else:
                withheld += 1
            continue

        if gold and (human := gold.get(article.id)):
            topic, source = _at_level(human, taxonomy, collapse_to_group), LabelSource.HUMAN
        elif use_weak_labels:
            topic, source = weak_label(article, taxonomy, collapse=collapse_to_group)
        else:
            unlabelled += 1
            continue

        if topic == taxonomy.unsorted or source is None:
            unlabelled += 1
            continue

        labelled.append(_example(topic, source))

    sizes = Counter(e.topic for e in labelled)
    classes = tuple(sorted(c for c, n in sizes.items() if n >= min_per_class))
    in_scope = [e for e in labelled if e.topic in classes]
    out_of_scope = tuple(e for e in labelled if e.topic not in classes)

    splits = make_splits([SplitRow(e.article_id, e.group_id, e.published_at) for e in in_scope])
    assignment = splits.assignment()
    by_split: dict[str, list[Example]] = {"train": [], "val": [], "test": []}
    for example in in_scope:
        if (name := assignment.get(example.article_id)) is not None:
            by_split[name].append(example)

    return Dataset(
        train=tuple(by_split["train"]),
        val=tuple(by_split["val"]),
        test=tuple(by_split["test"]),
        classes=classes,
        out_of_scope=out_of_scope,
        unlabelled=unlabelled,
        rejected=len(rejected),
        dropped_at_boundary=len(splits.dropped_at_boundary),
        variant=variant,
        gold=tuple(gold_rows),
        withheld_for_gold=withheld,
    )


def from_snapshot(
    snap: Snapshot,
    taxonomy: Taxonomy,
    *,
    min_per_class: int = MIN_PER_CLASS,
) -> Dataset:
    """Assemble the supervised dataset from a frozen snapshot.

    The difference from `build` is what is *not* done here. Cleaning, admission,
    story grouping and the split boundary were all decided when the snapshot was
    written, so this only joins labels onto rows. That is what makes a reported
    number reproducible from a snapshot id: rerun it in a month, against a
    database twice the size, and the same articles land in the same splits.

    The boundary itself is two publication times recorded in the manifest, so it
    is a fact about the snapshot rather than a side effect of whatever happened
    to be labelled on the day someone ran the notebook.
    """
    unsorted = taxonomy.unsorted
    labelled: list[Example] = []
    unlabelled = 0

    for row in snap.rows:
        topic = snap.labels.get(row.article_id)
        # `unsorted` is the absence of a class, not a class: an article no
        # annotator could file is not a row the model should be scored on.
        if not topic or topic == unsorted:
            unlabelled += 1
            continue
        labelled.append(
            Example(
                article_id=row.article_id,
                text=row.text,
                topic=group_of_topic(topic, taxonomy),
                label_source=str(LabelSource.HUMAN),
                source_name=row.source_name,
                group_id=row.story_group_id,
                published_at=row.published_at,
            )
        )

    sizes = Counter(e.topic for e in labelled)
    classes = tuple(sorted(c for c, n in sizes.items() if n >= min_per_class))
    in_scope = [e for e in labelled if e.topic in classes]

    split_of = {row.article_id: row.split for row in snap.rows}
    by_split: dict[str, list[Example]] = {"train": [], "val": [], "test": []}
    dropped = 0
    for example in in_scope:
        if (name := split_of.get(example.article_id)) in by_split:
            by_split[str(name)].append(example)
        else:
            dropped += 1

    counts = snap.manifest.get("counts", {})
    return Dataset(
        train=tuple(by_split["train"]),
        val=tuple(by_split["val"]),
        test=tuple(by_split["test"]),
        classes=classes,
        out_of_scope=tuple(e for e in labelled if e.topic not in classes),
        unlabelled=unlabelled,
        rejected=int(counts.get("rejected", 0)),
        dropped_at_boundary=dropped,
        variant=str(snap.manifest.get("text_variant", DEFAULT_TEXT_VARIANT)),
        provenance=snap.provenance,
    )
