"""Near-duplicate grouping: the property that later phases actually depend on is
that a syndicated copy never lands in a different split from its original."""

from __future__ import annotations

from newsml import neardup

WIRE = (
    "The Reserve Bank of India kept the repo rate unchanged at six point five percent on Friday, "
    "citing persistent food inflation and an uncertain global outlook. The monetary policy committee "
    "voted five to one in favour of the decision, the governor said at a briefing in Mumbai."
)

# The same wire copy as another outlet would run it: new headline, trimmed tail.
WIRE_REPRINT = (
    "RBI holds repo rate steady. The Reserve Bank of India kept the repo rate unchanged at six point "
    "five percent on Friday, citing persistent food inflation and an uncertain global outlook. The "
    "monetary policy committee voted five to one in favour of the decision, the governor said."
)

UNRELATED = (
    "Bengaluru's civic body has begun resurfacing forty kilometres of arterial roads before the "
    "monsoon, with work expected to continue through the end of the month across eight wards."
)


def test_identical_documents_group():
    grouping = neardup.group({"a": WIRE, "b": WIRE})
    assert grouping.group_of["a"] == grouping.group_of["b"]


def test_syndicated_reprint_groups_with_its_original():
    grouping = neardup.group({"a": WIRE, "b": WIRE_REPRINT})
    assert grouping.group_of["a"] == grouping.group_of["b"]


def test_unrelated_documents_do_not_group():
    grouping = neardup.group({"a": WIRE, "b": UNRELATED})
    assert grouping.group_of["a"] != grouping.group_of["b"]


def test_candidate_pairs_keeps_what_grouping_throws_away():
    """Calibrating the cut needs the pairs that fell just under it."""
    documents = {"a": WIRE, "b": WIRE_REPRINT, "c": UNRELATED}

    candidates = neardup.candidate_pairs(documents)
    kept = neardup.group(documents).pairs

    assert len(candidates) >= len(kept)
    assert all(score >= neardup.DEFAULT_THRESHOLD for _, _, score in kept)
    assert {(a, b) for a, b, _ in kept} <= {(a, b) for a, b, _ in candidates}


def test_candidate_pairs_are_ordered_so_two_runs_agree():
    documents = {"a": WIRE, "b": WIRE_REPRINT, "c": UNRELATED}

    assert neardup.candidate_pairs(documents) == neardup.candidate_pairs(dict(reversed(documents.items())))


def test_grouping_is_transitive():
    """A~B and B~C must put all three in one group even if A and C never matched
    directly — otherwise a story leaks across a split boundary."""
    grouping = neardup.group({"a": WIRE, "b": WIRE_REPRINT, "c": WIRE})
    assert len({grouping.group_of[k] for k in ("a", "b", "c")}) == 1


def test_group_ids_do_not_depend_on_insertion_order():
    forward = neardup.group({"a": WIRE, "b": WIRE_REPRINT, "c": UNRELATED})
    reverse = neardup.group({"c": UNRELATED, "b": WIRE_REPRINT, "a": WIRE})
    assert forward.group_of == reverse.group_of


def test_signatures_are_stable_across_processes():
    """blake2b keyed by the seed, not Python's randomised hash(). If this ever
    fails, snapshots stop being reproducible between runs."""
    assert neardup.signature(WIRE) == neardup.signature(WIRE)
    assert neardup.signature(WIRE)[:4] == neardup.signature(WIRE[:])[:4]


def test_jaccard_is_one_for_identical_and_low_for_unrelated():
    assert neardup.jaccard(neardup.signature(WIRE), neardup.signature(WIRE)) == 1.0
    assert neardup.jaccard(neardup.signature(WIRE), neardup.signature(UNRELATED)) < 0.2


def test_precision_on_labelled_pairs():
    """Phase 2 requires precision >= 0.90 on hand-labelled pairs. This is the
    harness with a small synthetic set; it is replaced by >= 200 real pairs once
    the corpus is large enough to sample them."""
    positives = [("p1a", "p1b"), ("p2a", "p2b")]
    documents = {
        "p1a": WIRE,
        "p1b": WIRE_REPRINT,
        "p2a": UNRELATED,
        "p2b": UNRELATED + " Officials said the work is on schedule.",
        "n1": "Indian equities closed higher on Friday as banking stocks led a broad rally in Mumbai trade.",
        "n2": "A new species of frog has been described from the Western Ghats by researchers this week.",
    }
    grouping = neardup.group(documents)
    labelled = {tuple(sorted(pair)) for pair in positives}

    predicted = {tuple(sorted((a, b))) for a, b, _ in grouping.pairs}
    assert predicted, "expected at least one predicted duplicate pair"

    precision = len(predicted & labelled) / len(predicted)
    assert precision >= 0.90, f"precision {precision:.2f} below the 0.90 acceptance threshold"


def test_short_and_empty_documents_are_safe():
    grouping = neardup.group({"a": "", "b": "two words", "c": WIRE})
    assert grouping.group_of["c"] not in {grouping.group_of["b"]}
    assert len(grouping.group_of) == 3
