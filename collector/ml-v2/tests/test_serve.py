"""Serving-time text assembly must match what the snapshot produced at training time."""

from __future__ import annotations

import pandas as pd
import pytest

from newsmlv2 import serve, snapshot


def _frame(title: str, summary: str, body: str) -> pd.DataFrame:
    return pd.DataFrame([{"title": title, "summary": summary, "body": body}])


@pytest.mark.parametrize(
    "title,summary,body",
    [
        ("Headline", "A summary.", "A body with several words in it."),
        ("Headline", "A summary.", ""),          # falls back to the summary
        ("Headline", "", "Body only."),
        ("", "", "Body with no headline."),
    ],
)
def test_serving_text_matches_the_snapshot_recipe(title, summary, body):
    """The one place train and serve could silently diverge, so it is pinned by a test."""
    expected = snapshot.Snapshot(None, {}, _frame(title, summary, body)).texts(
        _frame(title, summary, body), "title_body", body_chars=serve.BODY_CHARS
    )[0]
    assert serve.text_for(title, summary, body) == expected


def test_the_body_is_truncated_not_summarised():
    long_body = "word " * 5_000
    text = serve.text_for("T", "", long_body, body_chars=100)
    assert len(text) <= 100 + len("T\n")


def test_pasted_text_is_cleaned_with_the_corpus_rules():
    title, _, body = serve.prepare(
        "A  headline\u2014with  a dash",
        "",
        "Read more\nThe actual first sentence.\nStory continues below this ad",
    )
    assert title == "A headline-with a dash"          # punctuation folded, spaces collapsed
    assert "Read more" not in body
    assert "The actual first sentence." in body


def test_an_empty_article_is_refused_rather_than_guessed_at():
    classifier = serve.Classifier(folds=(), classes=None, cut=0.5, metadata={})
    with pytest.raises(ValueError, match="nothing to classify"):
        classifier.classify("   ", "", "")
