"""The near-duplicate threshold sheet: blind going out, weighted coming back."""

from __future__ import annotations

import csv

import pytest

from newsml import pairs

CANDIDATES = tuple(
    (f"a{i:03d}", f"b{i:03d}", score)
    for i, score in enumerate(
        [0.05, 0.10, 0.30]  # below the boundary, not in doubt
        + [0.45, 0.47, 0.52, 0.58, 0.63, 0.68, 0.74, 0.81, 0.88, 0.92]
        + [0.97, 0.99]  # above the boundary, not in doubt either
    )
)


def test_only_the_boundary_region_is_sampled():
    drawn = pairs.choose_pairs(CANDIDATES, size=100, seed=1)

    assert drawn, "the fixture has boundary pairs, so something should be drawn"
    assert all(pairs.BOUNDARY_LOW <= p.score < pairs.BOUNDARY_HIGH for p in drawn)


def test_the_sample_spreads_across_the_range_rather_than_where_pairs_are_dense():
    drawn = pairs.choose_pairs(CANDIDATES, size=100, seed=1)

    assert len({p.stratum for p in drawn}) > 1


def test_the_sheet_shows_no_score_and_the_key_does(tmp_path):
    drawn = pairs.choose_pairs(CANDIDATES, size=6, seed=1)
    titles = {a: f"title for {a}" for a, _, _ in CANDIDATES} | {b: f"title for {b}" for _, b, _ in CANDIDATES}
    texts = {k: f"body of {k}" for k in titles}

    sheet, key = pairs.write_sheet(drawn, titles, texts, tmp_path)

    with sheet.open(encoding=pairs.ENCODING, newline="") as handle:
        header = next(csv.reader(handle))
    assert header == list(pairs.COLUMNS)
    assert "score" not in header, "a labeller shown the score will agree with it"
    assert "score" in key.read_text(encoding="utf-8")


def test_pair_ids_are_stable_across_a_write_and_read(tmp_path):
    drawn = pairs.choose_pairs(CANDIDATES, size=6, seed=1)
    titles = texts = {a: a for a, _, _ in CANDIDATES} | {b: b for _, b, _ in CANDIDATES}

    _, key = pairs.write_sheet(drawn, titles, texts, tmp_path)

    assert [p.pair_id for p in pairs.read_key(key)] == [p.pair_id for p in drawn]


def test_unreadable_answers_are_reported_not_guessed(tmp_path):
    sheet = tmp_path / "pairs.csv"
    with sheet.open("w", encoding=pairs.ENCODING, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(pairs.COLUMNS)
        writer.writerow(["p001", "y", "", "", "", "", ""])
        writer.writerow(["p002", "n", "", "", "", "", "headline barely overlaps"])
        writer.writerow(["p003", "maybe", "", "", "", "", ""])
        writer.writerow(["p004", "", "", "", "", "", ""])

    filled = pairs.read_judgements(sheet)

    assert filled.judgements == {"p001": True, "p002": False}
    assert filled.notes == {"p002": "headline barely overlaps"}
    assert len(filled.problems) == 1 and "p003" in filled.problems[0]
    assert "p004" not in filled.judgements, "an unanswered row is not a 'no'"


def test_the_guide_states_the_rule_nobody_gets_right_unaided(tmp_path):
    """Two instalments of a daily feature read as near-identical and are not one story."""
    guide = pairs.write_guide(tmp_path / "labelling-guide.md", count=43)

    text = guide.read_text(encoding="utf-8")

    assert "43" in text
    assert "A different day is a different story" in text
    assert "blank" in text, "an annotator who cannot tell must know not to guess"


def test_precision_rises_with_the_threshold_when_the_score_is_informative():
    labelled = tuple(
        pairs.Pair(pair_id=f"p{i}", article_a="a", article_b="b", score=score, stratum=0)
        for i, score in enumerate([0.45, 0.55, 0.65, 0.75, 0.85])
    )
    # Only the top two are really the same story.
    judgements = {"p0": False, "p1": False, "p2": False, "p3": True, "p4": True}

    scored = {row.threshold: row for row in pairs.calibrate(labelled, judgements)}

    assert scored[0.40].precision == 0.4
    assert scored[0.70].precision == 1.0
    assert scored[0.70].recall == 1.0


def test_a_dense_stratum_counts_for_more_than_a_sparse_one():
    """Strata are sampled evenly; the corpus is not evenly populated."""
    labelled = (
        pairs.Pair("p0", "a", "b", 0.45, stratum=0, population=900, sampled=1),
        pairs.Pair("p1", "c", "d", 0.85, stratum=5, population=10, sampled=1),
    )

    scored = {row.threshold: row for row in pairs.calibrate(labelled, {"p0": False, "p1": True})}

    assert scored[0.40].precision == pytest.approx(10 / 910)
    assert scored[0.80].precision == 1.0
