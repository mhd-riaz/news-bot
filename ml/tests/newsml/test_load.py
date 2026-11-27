from __future__ import annotations

from newsml.load import LEDE_CHARS


def test_lede_prefers_the_publishers_own_summary(make_article):
    article = make_article(summary="A short dek.", content="A much longer body that should not be used.")
    assert article.lede == "A short dek."


def test_lede_falls_back_to_the_body_when_the_feed_ships_no_summary(make_article):
    article = make_article(summary="", content="Police said the driver lost control near the junction.")
    assert article.lede == "Police said the driver lost control near the junction."


def test_lede_caps_both_fields_at_the_same_length(make_article):
    long_summary = make_article(summary="word " * 200, content="")
    long_content = make_article(summary="", content="word " * 200)
    assert len(long_summary.lede) <= LEDE_CHARS
    assert len(long_content.lede) <= LEDE_CHARS


def test_lede_never_halves_a_word(make_article):
    article = make_article(summary="", content=("abcdefghij " * 60))
    assert not article.lede.endswith("abcde")
    assert article.lede.endswith("abcdefghij")


def test_lede_is_empty_when_the_article_has_neither_field(make_article):
    assert make_article(summary="", content="").lede == ""


def test_title_summary_variant_uses_the_lede(make_article):
    article = make_article(title="Headline", summary="", content="Body opening.")
    assert article.text("title_summary") == "Headline\nBody opening."
