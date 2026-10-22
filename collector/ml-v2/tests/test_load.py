"""Publisher derivation is the unit the holdout depends on, so it gets its own tests.

v1 held out a *section feed* and read a macro-F1 of 0.111 as catastrophic leakage. It
was arithmetic: a section feed carries one or two classes, so the rest had zero support.
"""

from datetime import UTC, datetime

from newsmlv2.load import Article, publisher_of


def _article(**kw) -> Article:
    base = dict(
        id="a", source_id="s", source_name="The Hindu — National", url="",
        title="t", summary="", body="", authors=(), categories=(), content_hash="",
        language="en", country="IN",
        published_at=datetime(2026, 8, 24, tzinfo=UTC),
        collected_at=datetime(2026, 8, 24, tzinfo=UTC),
        scrape_status="success",
    )
    return Article(**{**base, **kw})


def test_section_feeds_collapse_into_one_publisher():
    for feed in (
        "The Indian Express — Technology",
        "The Indian Express — World",
        "The Indian Express — Education",
    ):
        assert publisher_of(feed) == "The Indian Express"


def test_a_publisher_with_no_section_is_left_alone():
    assert publisher_of("Phys.org") == "Phys.org"
    assert publisher_of("The New Indian Express") == "The New Indian Express"


def test_en_dash_and_spaced_hyphen_split_too():
    assert publisher_of("NDTV – Latest") == "NDTV"
    assert publisher_of("Deccan Herald - All stories") == "Deccan Herald"


def test_hyphenated_publisher_names_survive():
    """An unspaced hyphen is part of the name, not a section separator."""
    assert publisher_of("Al-Jazeera") == "Al-Jazeera"


def test_lede_prefers_the_summary():
    a = _article(summary="The dek.", body="The body text.")
    assert a.lede == "The dek."


def test_lede_falls_back_to_the_body_when_there_is_no_summary():
    """25% of articles have no summary at all; v1 gave those a bare headline."""
    a = _article(summary="", body="word " * 200)
    assert a.lede.startswith("word")
    assert len(a.lede) <= 400
    assert not a.lede.endswith("wor"), "must clip at a word boundary"


def test_title_only_articles_have_an_empty_lede_not_the_string_none():
    a = _article(summary="", body="")
    assert a.lede == ""
    assert a.has_body is False
