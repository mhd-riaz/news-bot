"""Choosing a confidence cut is a measurement, so it needs its own tests."""

from __future__ import annotations

import numpy as np
import pytest

from newsml import thresholds

# Three classes, not two: with two, a "winner" scoring 0.40 is not the winner at
# all, and the fixture would quietly test the opposite of what it says.
CLASSES = ["health", "politics", "sport"]


def _proba(rows: list[tuple[str, float]]) -> np.ndarray:
    """Build a probability matrix from (winning class, confidence) pairs."""
    out = np.zeros((len(rows), len(CLASSES)))
    for i, (topic, confidence) in enumerate(rows):
        out[i, :] = (1 - confidence) / (len(CLASSES) - 1)
        out[i, CLASSES.index(topic)] = confidence
    return out


def test_a_class_the_model_is_always_right_about_keeps_the_lowest_cut():
    rows = [("sport", 0.95)] * 12
    proba = _proba(rows)

    chosen = thresholds.choose(CLASSES, proba, ["sport"] * 12, min_kept=2)

    assert chosen.per_class["sport"] == 0.0, "nothing was being got wrong, so nothing should be thrown away"
    assert chosen.coverage == 1.0


def test_the_cut_rises_only_as_far_as_the_target_needs():
    # Six confident and correct, six unsure and wrong. The cut has to land
    # between the two, and no higher.
    rows = [("politics", 0.90)] * 6 + [("politics", 0.55)] * 6
    truths = ["politics"] * 6 + ["sport"] * 6

    chosen = thresholds.choose(CLASSES, _proba(rows), truths, target_precision=0.80, min_kept=2)

    assert chosen.per_class["politics"] == pytest.approx(0.56)
    assert chosen.abstained == 6
    assert chosen.accuracy_on_kept == 1.0
    assert chosen.accuracy_before == 0.5


def test_a_class_no_cut_can_rescue_is_reported_rather_than_hidden():
    """Right and wrong at the same confidence means the score carries no signal."""
    rows = [("politics", 0.60)] * 10
    truths = ["politics"] * 5 + ["sport"] * 5

    chosen = thresholds.choose(CLASSES, _proba(rows), truths, target_precision=0.90, min_kept=2)

    assert "politics" in chosen.unreached
    assert chosen.per_class["politics"] == pytest.approx(0.60), "the highest cut that still files anything"


def test_apply_routes_everything_under_its_cut_to_unsorted():
    rows = [("sport", 0.95), ("politics", 0.40), ("politics", 0.85)]

    decided = thresholds.apply(CLASSES, _proba(rows), {"politics": 0.80, "sport": 0.10})

    assert decided == ["sport", "unsorted", "politics"]


def test_only_the_winning_classs_cut_is_consulted():
    """A runner-up must never be filed. Abstaining is the point of the cut."""
    rows = [("politics", 0.45)]

    decided = thresholds.apply(CLASSES, _proba(rows), {"politics": 0.90, "sport": 0.10})

    assert decided == ["unsorted"], "sport at 0.55 must not win by default"


def test_an_impossible_target_is_refused():
    with pytest.raises(ValueError, match="target_precision"):
        thresholds.choose(CLASSES, _proba([("sport", 0.9)]), ["sport"], target_precision=1.5)


def test_a_class_with_too_few_predictions_to_measure_files_everything():
    """Below `min_kept` there is no precision to read, so no cut can be justified."""
    rows = [("sport", 0.95)] * 3

    chosen = thresholds.choose(CLASSES, _proba(rows), ["sport"] * 3, min_kept=10)

    assert chosen.per_class["sport"] == 0.0
    assert chosen.coverage == 1.0


def test_a_forced_class_never_fires_even_at_perfect_confidence():
    """society_lifestyle ships as a permanent abstainer, not a measured cut."""
    rows = [("politics", 0.95)] * 6 + [("sport", 0.95)] * 6

    chosen = thresholds.choose(
        CLASSES, _proba(rows), ["politics"] * 6 + ["sport"] * 6, force_abstain=frozenset({"politics"})
    )

    politics = next(c for c in chosen.choices if c.topic == "politics")
    assert politics.forced
    assert politics.kept == 0
    assert "politics" in chosen.forced_abstain
    decided = thresholds.apply(CLASSES, _proba(rows), chosen.per_class)
    assert all(topic != "politics" for topic in decided), "a forced class must never be the final answer"


def test_forcing_abstention_is_opt_in_per_class_not_global():
    """Forcing one class must not touch any other class's ordinary cut search."""
    rows = [("politics", 0.90)] * 6 + [("politics", 0.55)] * 6
    truths = ["politics"] * 6 + ["sport"] * 6

    chosen = thresholds.choose(
        CLASSES, _proba(rows), truths, target_precision=0.80, min_kept=2, force_abstain=frozenset({"health"})
    )

    assert not chosen.choices[[c.topic for c in chosen.choices].index("politics")].forced
    assert chosen.per_class["politics"] == pytest.approx(0.56)
