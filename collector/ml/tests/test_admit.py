"""The rejection log must account for 100% of dropped articles, by reason."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import BASE

from newsml import admit, clean
from newsml.admit import Reason

LONG_ENOUGH = "The bench reserved its order in the case after hearing arguments from both sides today."


def _pair(article):
    return article, clean.clean(article.text("title_summary"))


def test_a_good_article_is_admitted(make_article):
    admitted, rejected = admit.partition([_pair(make_article())], now=BASE + timedelta(hours=1), check_language=False)
    assert len(admitted) == 1 and not rejected


def test_every_article_is_accounted_for(make_article):
    """The Phase 2 acceptance criterion, stated as a test rather than a promise."""
    articles = [
        make_article("good"),
        make_article("empty", title="", summary=""),
        make_article("stub", title="Short", summary=""),
        make_article("live", title="Live updates: election results as they come in"),
        make_article("promo", summary="Sponsored content produced by the brand desk for a partner."),
        make_article("future", published_at=BASE + timedelta(days=400)),
        make_article("dupe", content_hash="shared"),
        make_article("dupe2", content_hash="shared"),
    ]
    pairs = [_pair(a) for a in articles]
    admitted, rejected = admit.partition(pairs, now=BASE + timedelta(hours=1), check_language=False)

    assert len(admitted) + len(rejected) == len(pairs)
    assert len({r.article_id for r in rejected}) == len(rejected), "an article was rejected twice"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"title": "", "summary": ""}, Reason.EMPTY_TEXT),
        ({"title": "Two words", "summary": ""}, Reason.TOO_SHORT),
        ({"title": "Live updates: the results as they arrive today", "summary": LONG_ENOUGH}, Reason.NON_ARTICLE_FORMAT),
        ({"title": "Daily horoscope for Friday, all sun signs", "summary": LONG_ENOUGH}, Reason.NON_ARTICLE_FORMAT),
        ({"title": "Top 10 things to see in the city this weekend", "summary": LONG_ENOUGH}, Reason.NON_ARTICLE_FORMAT),
        ({"title": "The week around the world in 20 pictures", "summary": LONG_ENOUGH}, Reason.NON_ARTICLE_FORMAT),
        ({"title": "Chennai weather today: rain likely to continue", "summary": LONG_ENOUGH}, Reason.SERVICE_BULLETIN),
        ({"title": "Expressway closure: traffic police suggest alternate routes", "summary": LONG_ENOUGH},
         Reason.SERVICE_BULLETIN),
        ({"title": "Today news headlines for school assembly, August 3", "summary": LONG_ENOUGH},
         Reason.SERVICE_BULLETIN),
        ({"title": "We published a new topic page on economic inequality", "summary": LONG_ENOUGH},
         Reason.SERVICE_BULLETIN),
        ({"summary": "Sponsored content produced by the brand desk for a partner."}, Reason.SPONSORED),
        ({"title": "TurboTax service codes and discounts",
          "summary": "Save with our TurboTax coupon codes and exclusive discount codes on WIRED."}, Reason.SPONSORED),
        ({"summary": "Subscribe to read the rest of this exclusive report from our desk."}, Reason.PAYWALL),
    ],
)
def test_reason_codes(make_article, kwargs, reason):
    admitted, rejected = admit.partition(
        [_pair(make_article(**kwargs))], now=BASE + timedelta(hours=1), check_language=False
    )
    assert not admitted
    assert rejected[0].reason == reason


def test_a_real_story_that_quotes_a_bulletin_survives(make_article):
    """The service filter reads the title only, so a flood report is not collateral."""
    article = make_article(
        title="Thousands evacuated as the Adyar bursts its banks",
        summary="Rescue teams worked overnight. The weather update issued at noon warned of more rain to come.",
    )
    admitted, rejected = admit.partition([_pair(article)], now=BASE + timedelta(hours=1), check_language=False)
    assert len(admitted) == 1 and not rejected


def test_a_travel_advisory_as_foreign_policy_is_not_a_bulletin(make_article):
    """Caught on the live corpus: `travel advisory` matched a diplomacy story."""
    article = make_article(title="J&K important part of India, US may re-evaluate travel advisory, says envoy")
    admitted, rejected = admit.partition([_pair(article)], now=BASE + timedelta(hours=1), check_language=False)
    assert len(admitted) == 1 and not rejected


def test_future_and_ancient_timestamps_are_separated(make_article):
    _, future = admit.partition(
        [_pair(make_article(published_at=BASE + timedelta(days=30)))], now=BASE, check_language=False
    )
    _, ancient = admit.partition(
        [_pair(make_article(published_at=BASE - timedelta(days=500)))], now=BASE, check_language=False
    )
    assert future[0].reason == Reason.FUTURE_TIMESTAMP
    assert ancient[0].reason == Reason.IMPLAUSIBLE_TIMESTAMP


def test_small_clock_skew_is_tolerated(make_article):
    """Publishers post-date by a few minutes routinely; that is not a bad record."""
    admitted, rejected = admit.partition(
        [_pair(make_article(published_at=BASE + timedelta(hours=2)))], now=BASE, check_language=False
    )
    assert len(admitted) == 1 and not rejected


def test_exact_duplicates_keep_the_first_occurrence(make_article):
    pairs = [_pair(make_article("first", content_hash="same")), _pair(make_article("second", content_hash="same"))]
    admitted, rejected = admit.partition(pairs, now=BASE + timedelta(hours=1), check_language=False)
    assert [a.article.id for a in admitted] == ["first"]
    assert rejected[0].reason == Reason.EXACT_DUPLICATE


def test_language_mismatch_is_detected_when_enabled(make_article):
    """`language` is a source assumption. This is what measures it."""
    french = make_article(
        title="Le conseil municipal a approuve le budget annuel",
        summary="Les elus ont vote jeudi soir en faveur du budget presente par le maire de la ville.",
        language="en",
    )
    _, rejected = admit.partition([_pair(french)], now=BASE + timedelta(hours=1), check_language=True)
    assert rejected and rejected[0].reason == Reason.LANGUAGE_MISMATCH
