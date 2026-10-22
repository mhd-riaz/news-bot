"""Per-class confidence cuts, and the `unsorted` route below them.

A reader would much rather see an article marked `unsorted` than filed
confidently under the wrong topic, so the model is allowed to decline. That
trades coverage — how many articles get a topic at all — against precision on
the ones it does file.

The cut is **per class, not global**, because the classes are not equally hard.
`sport` is separable from a headline and earns its label at a low score;
`society_lifestyle` is a grab-bag and a mid-range score there means very little.
One global cut set high enough to protect the weak classes would throw away most
of the strong ones for nothing.

Nothing here is fitted. A threshold is chosen on validation and then applied, so
the choice is a measurement on data the model did not train on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import accuracy_score, f1_score

# The cut is searched on this grid. It stops below 1.0 because a cut at the very
# top files nothing, and a class that files nothing has no precision to report.
GRID = np.round(np.arange(0.0, 0.96, 0.01), 2)

# Below this many kept articles a precision figure is noise, and choosing a cut
# from noise is how a threshold ends up looking excellent and behaving badly.
MIN_KEPT = 10

# `society_lifestyle` ships as a permanent abstainer, not a class that just
# hasn't found its cut yet. It never reaches the 80% precision target, and its
# best-available fallback (0.33 cut, 0.64 precision) is still worse than every
# other class's *target*, not just its cut. Two rounds of evidence ruled out
# the usual fixes: more labels moved its F1 the wrong way (0.328 -> 0.300,
# +185 train rows), and the 26-class experiment already showed it is three
# unrelated things glued together, each failing on its own (lifestyle_living
# 0.00, society_community 0.29, labour_work 0.46 F1). Filing anything under it
# costs a reader a wrong label about a third of the time with no way to tell,
# so it stays in the taxonomy and keeps training, but the model is barred from
# ever emitting it directly. See docs/plan.md's decision log, 2026-08-25.
FORCE_ABSTAIN: frozenset[str] = frozenset({"society_lifestyle"})


@dataclass(frozen=True, slots=True)
class Choice:
    """One class's cut, and the evidence for it."""

    topic: str
    cut: float
    precision: float
    kept: int
    predicted: int
    reached_target: bool
    forced: bool = False

    @property
    def coverage(self) -> float:
        return self.kept / self.predicted if self.predicted else 0.0


@dataclass(frozen=True, slots=True)
class Thresholds:
    """The chosen cuts and what they cost, measured on one split."""

    per_class: dict[str, float]
    target_precision: float
    choices: tuple[Choice, ...]
    coverage: float
    accuracy_on_kept: float
    macro_f1_on_kept: float
    accuracy_before: float
    abstained: int
    n: int

    @property
    def unreached(self) -> tuple[str, ...]:
        """Classes that never hit the target at any cut. Each needs an answer."""
        return tuple(c.topic for c in self.choices if not c.reached_target)

    @property
    def forced_abstain(self) -> tuple[str, ...]:
        """Classes barred from ever being emitted, by decision rather than measurement."""
        return tuple(c.topic for c in self.choices if c.forced)


def choose(
    classes: list[str],
    proba: NDArray[np.float64],
    truths: list[str],
    *,
    target_precision: float = 0.80,
    min_kept: int = MIN_KEPT,
    unsorted: str = "unsorted",
    force_abstain: frozenset[str] = FORCE_ABSTAIN,
) -> Thresholds:
    """Pick the lowest cut per class that reaches `target_precision`.

    Lowest, not highest: any cut above the one that reaches the target throws
    away articles the model was already getting right. Where no cut reaches the
    target, the class keeps the highest cut that still files `min_kept`
    articles and is reported as unreached — an honest "this class is not good
    enough yet" rather than a silently lowered bar.

    `force_abstain` skips the search entirely for named classes: no cut is
    measured, the class is simply barred from ever being emitted. That is a
    decision recorded elsewhere (see `FORCE_ABSTAIN`), not something this
    function discovers on its own.
    """
    if not 0.0 < target_precision <= 1.0:
        raise ValueError(f"target_precision must be in (0, 1], got {target_precision}")

    truth = np.asarray(truths)
    top = np.asarray(classes)[proba.argmax(axis=1)]
    confidence = proba.max(axis=1)

    choices: list[Choice] = []
    for topic in classes:
        filed = top == topic
        correct = filed & (truth == topic)
        predicted = int(filed.sum())

        if topic in force_abstain:
            choices.append(
                Choice(
                    topic=topic,
                    cut=math.inf,
                    precision=math.nan,
                    kept=0,
                    predicted=predicted,
                    reached_target=False,
                    forced=True,
                )
            )
            continue

        chosen, best_precision, best_kept, reached = 0.0, 0.0, predicted, False
        fallback: tuple[float, float, int] | None = None

        for cut in GRID:
            kept = int((filed & (confidence >= cut)).sum())
            if kept < min_kept:
                break
            precision = float((correct & (confidence >= cut)).sum()) / kept
            fallback = (float(cut), precision, kept)
            if precision >= target_precision:
                chosen, best_precision, best_kept, reached = float(cut), precision, kept, True
                break

        if not reached and fallback is not None:
            chosen, best_precision, best_kept = fallback
        elif not reached:
            # Too few predictions to measure anything. File everything and say so.
            best_precision = float(correct.sum()) / predicted if predicted else 0.0

        choices.append(
            Choice(
                topic=topic,
                cut=chosen,
                precision=best_precision,
                kept=best_kept,
                predicted=predicted,
                reached_target=reached,
            )
        )

    per_class = {c.topic: c.cut for c in choices}
    decided = apply(classes, proba, per_class, unsorted=unsorted)
    kept_rows = [i for i, topic in enumerate(decided) if topic != unsorted]

    if kept_rows:
        kept_truth = [truths[i] for i in kept_rows]
        kept_guess = [decided[i] for i in kept_rows]
        accuracy_on_kept = float(accuracy_score(kept_truth, kept_guess))
        macro_on_kept = float(
            f1_score(kept_truth, kept_guess, labels=classes, average="macro", zero_division=0)
        )
    else:
        accuracy_on_kept, macro_on_kept = 0.0, 0.0

    return Thresholds(
        per_class=per_class,
        target_precision=target_precision,
        choices=tuple(choices),
        coverage=len(kept_rows) / len(truths) if truths else 0.0,
        accuracy_on_kept=accuracy_on_kept,
        macro_f1_on_kept=macro_on_kept,
        accuracy_before=float(accuracy_score(truths, list(top))) if truths else 0.0,
        abstained=len(truths) - len(kept_rows),
        n=len(truths),
    )


def apply(
    classes: list[str],
    proba: NDArray[np.float64],
    per_class: dict[str, float],
    *,
    unsorted: str = "unsorted",
) -> list[str]:
    """Predict with abstention: the winning class, or `unsorted` below its cut.

    Only the winning class's cut is consulted. Falling back to the runner-up when
    the winner abstains would file the article under a class the model liked
    *less*, which is the opposite of what the abstention is for.
    """
    names = np.asarray(classes)
    winners = names[proba.argmax(axis=1)]
    confidence = proba.max(axis=1)
    return [
        str(topic) if score >= per_class.get(str(topic), 0.0) else unsorted
        for topic, score in zip(winners, confidence, strict=True)
    ]
