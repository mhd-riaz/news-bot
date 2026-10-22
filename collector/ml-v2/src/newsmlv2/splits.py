"""Split the corpus so that nothing a model is scored on could have been memorised.

Three constraints, and every one of them came from a mistake:

* **Split on `collected_at`, never `published_at`.** A 2019 article can arrive in the
  feed tomorrow, so publication date says nothing about what the corpus knew when.
* **A story group never straddles a boundary.** Syndicated copy runs at five publishers;
  if one copy trains and another tests the score is memorisation. Groups that straddle
  are dropped whole rather than truncated.
* **Place the cuts using labelled rows, then apply them to everything.** v1 cut on
  quantiles of the *whole* corpus and put 37 labelled articles in a test split of 1,317,
  because labelling stops the day a round is drawn while collection carries on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

TRAIN = "train"
VAL = "val"
TEST = "test"
DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class SplitRow:
    article_id: str
    group_id: str
    collected_at: datetime
    publisher: str = ""
    labelled: bool = False


@dataclass(frozen=True, slots=True)
class Splits:
    train: tuple[str, ...]
    val: tuple[str, ...]
    test: tuple[str, ...]
    dropped_at_boundary: tuple[str, ...]
    train_until: datetime | None = None
    val_until: datetime | None = None

    @property
    def total(self) -> int:
        return len(self.train) + len(self.val) + len(self.test) + len(self.dropped_at_boundary)

    def assignment(self) -> dict[str, str]:
        out = {a: TRAIN for a in self.train}
        out.update({a: VAL for a in self.val})
        out.update({a: TEST for a in self.test})
        out.update({a: DROPPED for a in self.dropped_at_boundary})
        return out

    def counts(self) -> dict[str, int]:
        return {
            TRAIN: len(self.train),
            VAL: len(self.val),
            TEST: len(self.test),
            DROPPED: len(self.dropped_at_boundary),
        }


def _quantile(values: list[datetime], fraction: float) -> datetime:
    index = min(int(len(values) * fraction), len(values) - 1)
    return values[index]


def make_splits(
    rows: list[SplitRow],
    *,
    train_fraction: float = 0.70,
    val_fraction: float = 0.15,
    reference: list[SplitRow] | None = None,
) -> Splits:
    """Grouped, time-ordered train/val/test.

    `reference` supplies the rows the cut times are computed from -- normally the
    labelled ones. The cuts are then applied to every row in `rows`.
    """
    if not rows:
        return Splits((), (), (), ())

    basis = reference if reference else rows
    times = sorted(r.collected_at for r in basis)
    train_until = _quantile(times, train_fraction)
    val_until = _quantile(times, train_fraction + val_fraction)

    def bucket(when: datetime) -> str:
        if when <= train_until:
            return TRAIN
        if when <= val_until:
            return VAL
        return TEST

    by_group: dict[str, list[SplitRow]] = {}
    for row in rows:
        by_group.setdefault(row.group_id, []).append(row)

    train: list[str] = []
    val: list[str] = []
    test: list[str] = []
    dropped: list[str] = []
    target = {TRAIN: train, VAL: val, TEST: test}

    for members in by_group.values():
        buckets = {bucket(m.collected_at) for m in members}
        if len(buckets) == 1:
            target[buckets.pop()].extend(m.article_id for m in members)
        else:
            dropped.extend(m.article_id for m in members)

    return Splits(
        train=tuple(sorted(train)),
        val=tuple(sorted(val)),
        test=tuple(sorted(test)),
        dropped_at_boundary=tuple(sorted(dropped)),
        train_until=train_until,
        val_until=val_until,
    )


def groups_spanning_splits(rows: list[SplitRow], splits: Splits) -> set[str]:
    """Must always be empty. The single invariant the whole design rests on."""
    assignment = splits.assignment()
    seen: dict[str, set[str]] = {}
    for row in rows:
        where = assignment.get(row.article_id)
        if where and where != DROPPED:
            seen.setdefault(row.group_id, set()).add(where)
    return {group for group, places in seen.items() if len(places) > 1}


@dataclass(frozen=True, slots=True)
class PublisherHoldout:
    publisher: str
    fit: tuple[str, ...]
    holdout: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {"fit": len(self.fit), "holdout": len(self.holdout)}


def publisher_holdout(rows: list[SplitRow], publisher: str) -> PublisherHoldout:
    """Everything except one masthead, and that masthead on its own.

    A *publisher*, never a section feed: a feed carries one or two classes, so most
    classes get no support and macro-F1 becomes arithmetic noise. v1 read 0.111 that way
    and mistook it for catastrophic leakage.
    """
    fit = [r.article_id for r in rows if r.publisher != publisher]
    held = [r.article_id for r in rows if r.publisher == publisher]
    return PublisherHoldout(publisher, tuple(sorted(fit)), tuple(sorted(held)))
