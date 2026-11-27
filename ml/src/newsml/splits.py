"""Train/validation/test splits that are both grouped and temporal.

Two constraints, and they fight each other:

* **Grouped** — no story cluster may span two splits. A syndicated story in both
  train and test is memorisation scored as generalisation.
* **Temporal** — every test article is published after every training article.
  Anything else lets the model see the future, and news vocabulary moves fast
  enough that the difference is large.

Satisfying both exactly is impossible when a story straddles a cut point, so the
straddling articles are dropped and counted. Dropping them is honest; silently
relaxing either constraint is not. The drop count is reported and belongs in the
data card.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SplitRow:
    """The minimum a split decision needs to know about an article."""

    article_id: str
    group_id: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class Splits:
    train: tuple[str, ...]
    val: tuple[str, ...]
    test: tuple[str, ...]
    dropped_at_boundary: tuple[str, ...]
    train_until: datetime | None = None
    val_until: datetime | None = None

    def assignment(self) -> dict[str, str]:
        return {
            **{a: "train" for a in self.train},
            **{a: "val" for a in self.val},
            **{a: "test" for a in self.test},
        }

    @property
    def total(self) -> int:
        return len(self.train) + len(self.val) + len(self.test) + len(self.dropped_at_boundary)


def make_splits(
    rows: list[SplitRow],
    *,
    train_fraction: float = 0.70,
    val_fraction: float = 0.15,
    reference: list[SplitRow] | None = None,
) -> Splits:
    """Cut the corpus at two publication times, then assign whole groups.

    Choosing the cut times first is what keeps this robust. The obvious
    alternative — assign groups by order, then set the boundary to the newest
    training article — lets one group that happens to span the corpus drag the
    boundary to the end and empty the later splits.

    `reference` decides *where* the cuts fall while `rows` decides what gets
    assigned. They differ for a good reason: a corpus is labelled up to whenever
    the last labelling round was drawn, and articles collected after that are
    unlabelled. Taking quantiles over everything then puts almost no labelled
    article in the test split — measured at 37 of 1,317 on this corpus. Taking
    them over the labelled rows instead proportions the supervised splits
    correctly, and the boundary is returned so it can be frozen in a manifest.
    """
    if not rows:
        return Splits((), (), (), ())

    times = sorted(r.published_at for r in (reference or rows))
    last = len(times) - 1
    t1 = times[min(last, int(len(times) * train_fraction))]
    t2 = times[min(last, int(len(times) * (train_fraction + val_fraction)))]

    by_group: dict[str, list[SplitRow]] = {}
    for row in rows:
        by_group.setdefault(row.group_id, []).append(row)

    buckets: dict[str, list[SplitRow]] = {"train": [], "val": [], "test": []}
    dropped: list[str] = []

    for group_id in sorted(by_group):
        members = by_group[group_id]
        lo = min(r.published_at for r in members)
        hi = max(r.published_at for r in members)

        # A group straddling a cut point cannot be both whole and on one side of
        # the boundary. Drop it entirely and count it; truncating it instead
        # would put half a story in train and half in test.
        if (lo < t1 <= hi) or (lo < t2 <= hi):
            dropped.extend(r.article_id for r in members)
            continue

        buckets["train" if hi < t1 else "val" if hi < t2 else "test"].extend(members)

    return Splits(
        train=tuple(sorted(r.article_id for r in buckets["train"])),
        val=tuple(sorted(r.article_id for r in buckets["val"])),
        test=tuple(sorted(r.article_id for r in buckets["test"])),
        dropped_at_boundary=tuple(sorted(dropped)),
        train_until=t1,
        val_until=t2,
    )


def groups_spanning_splits(rows: list[SplitRow], splits: Splits) -> set[str]:
    """Every group id that appears in more than one split. Must always be empty."""
    assignment = splits.assignment()
    seen: dict[str, set[str]] = {}
    for row in rows:
        if (name := assignment.get(row.article_id)) is not None:
            seen.setdefault(row.group_id, set()).add(name)
    return {group for group, names in seen.items() if len(names) > 1}
