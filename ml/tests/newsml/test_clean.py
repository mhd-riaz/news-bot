"""Cleansing must be deterministic and must not eat real sentences."""

from __future__ import annotations

from newsml import clean


def test_is_deterministic_across_runs():
    raw = "NEW DELHI: The bench reserved its order. ADVERTISEMENT\nAlso Read: something else\n(PTI)"
    assert clean.clean(raw) == clean.clean(raw)


def test_is_idempotent():
    """Cleaning already-clean text must change nothing. If it does, re-running
    the pipeline on a silver artifact would drift."""
    once = clean.clean("NEW DELHI: The bench reserved its order in the bonds case.")
    twice = clean.clean(once.text)
    assert twice.text == once.text


def test_nfkc_folds_typographic_variants():
    curly = clean.clean("The court\u2019s order\u00a0was clear").text
    straight = clean.clean("The court's order was clear").text
    assert curly == straight


def test_control_characters_are_removed():
    assert "\x00" not in clean.clean("Order\x00 issued\x07 today").text


def test_dateline_is_extracted_not_just_deleted():
    result = clean.clean("NEW DELHI: The bench reserved its order in the case.")
    assert result.dateline_city == "NEW DELHI"
    assert result.text.startswith("The bench reserved")


def test_dateline_with_agency_and_date():
    result = clean.clean("Bengaluru, Aug 23 (PTI) - The council met on Friday to discuss the proposal.")
    assert result.dateline_city == "Bengaluru"
    assert result.wire_agency == "PTI"
    assert "PTI" not in result.text


def test_sentence_opening_with_capitals_is_not_mistaken_for_a_dateline():
    """The guard that matters: a dateline is short. Without the length check this
    rule silently truncates the first sentence of an article."""
    raw = (
        "Prime Minister Narendra Modi And Home Minister Amit Shah And Others Attended The Event "
        "Which Was Held Today: the ceremony ran late."
    )
    result = clean.clean(raw)
    assert result.dateline_city == ""
    assert result.text.startswith("Prime Minister")


def test_wire_agency_recorded_and_stripped():
    result = clean.clean("The council met on Friday to discuss the new proposal in detail. (PTI)")
    assert result.wire_agency == "PTI"
    assert "PTI" not in result.text


def test_cross_promo_lines_are_removed_but_inline_mentions_survive():
    result = clean.clean("Also Read: Another story entirely\nThe bench reserved its order today.")
    assert "Another story entirely" not in result.text

    kept = clean.clean("Readers should also read the full judgment before commenting on it.")
    assert "also read the full judgment" in kept.text


def test_trailing_disclaimer_is_removed():
    result = clean.clean("The council met on Friday.\nDisclaimer: views are personal.")
    assert "views are personal" not in result.text
    assert "The council met on Friday." in result.text


def test_page_furniture_floor_matches_the_go_extractor():
    result = clean.clean("ADVERTISEMENT\nThe bench reserved its order today after hearing both sides.")
    assert "ADVERTISEMENT" not in result.text


def test_learned_boilerplate_is_applied_per_source():
    line = "Follow our channel for updates"
    keys = frozenset({clean.line_key(line)})
    raw = f"{line}\nThe bench reserved its order today after hearing both sides at length."

    assert line not in clean.clean(raw, boilerplate=keys).text
    assert line in clean.clean(raw).text  # unchanged when no list is supplied


def test_removed_lines_are_reported_not_silently_dropped():
    line = "Follow our channel for updates"
    result = clean.clean(f"{line}\nThe bench reserved its order.", boilerplate=frozenset({clean.line_key(line)}))
    assert result.removed_lines == (line,)


def test_line_key_collapses_digits_so_dated_templates_match():
    assert clean.line_key("Updated: Aug 22, 2026") == clean.line_key("Updated: Aug 29, 2026")


def test_empty_input_is_handled():
    assert clean.clean("").text == ""
    assert clean.clean("   \n\n  ").text == ""
