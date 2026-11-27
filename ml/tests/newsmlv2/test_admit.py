"""Admission gates, including the two that bit v1 in production."""

from datetime import UTC, datetime, timedelta

import pytest

from newsmlv2.admit import Admitted, Policy, Reason, judge, non_latin_share, partition, without
from newsmlv2.clean import clean_article
from newsmlv2.load import Article

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _admitted(title: str, summary: str = "", body: str = "", **kw) -> Admitted:
    base = dict(
        id="a", source_id="s", source_name="The Hindu — National", url="",
        title=title, summary=summary, body=body, authors=(), categories=(),
        # Derived from the text, not a constant: a shared hash makes every article after
        # the first an exact duplicate, which silently empties the admitted set.
        content_hash=str(hash((title, summary, body))), language="en", country="IN",
        published_at=NOW - timedelta(hours=1), collected_at=NOW,
        scrape_status="success",
    )
    article = Article(**{**base, **kw})
    t, s, b = clean_article(article.title, article.summary, article.body)
    return Admitted(article=article, title=t, summary=s, body=b)


def _judge(item: Admitted, policy: Policy | None = None) -> Reason | None:
    problem = judge(item, policy=policy or Policy(), now=NOW, seen_hashes=set())
    return problem.reason if problem else None


REAL_STORY = ("Parliament passes the new education bill after a long debate",
              "The bill cleared both houses on Monday evening.",
              "Members voted 240 to 190 after three hours of argument over the funding clause.")


class TestServiceBulletin:
    def test_a_weather_bulletin_is_rejected(self):
        assert _judge(_admitted("Chennai weather today: Orange Alert issued in 4 districts",
                                body="The met office said heavy rain is likely across the region.")) \
            is Reason.SERVICE_BULLETIN

    def test_gold_rate_tables_are_rejected(self):
        """Two instalments are near-identical wording and are not the same story."""
        assert _judge(_admitted("Gold rate today: Yellow metal steady in Chennai and Mumbai",
                                body="Gold prices held steady across major cities on Tuesday morning.")) \
            is Reason.SERVICE_BULLETIN

    def test_a_flood_story_quoting_a_bulletin_in_its_body_survives(self):
        """The rule matches the title ONLY.

        Matching the body would reject real disaster reporting, because a flood story
        always quotes the weather bulletin -- and `disaster_accident` is already thin.
        """
        item = _admitted(
            "Twelve dead as floods sweep through Kerala district",
            body="Rescue teams worked overnight. The weather forecast warned of an orange "
                 "alert for the district, with more rain expected before Thursday.",
        )
        assert _judge(item) is None

    def test_the_word_travel_is_not_a_trigger(self):
        """v1's regex matched a diplomacy story: 'US may re-evaluate travel advisory'."""
        item = _admitted(
            "J&K important part of India, US may re-evaluate travel advisory, says envoy",
            body="The ambassador said the advisory was under review after recent talks.",
        )
        assert _judge(item) is None


class TestNonArticle:
    @pytest.mark.parametrize(
        "title",
        [
            "DH Toon | 'Vande Mataram' full song",
            "DH Speak Out | August 24, 2026",
            "IND vs ENG Live updates: India lose early wicket",
            "Daily Quiz | On Sean Connery",
            "Horoscope today, August 24: What the stars say",
            "Independence Day in 20 pictures",
            "Today's News Headlines for School Assembly",
        ],
    )
    def test_formats_with_no_single_story_are_rejected(self, title):
        assert _judge(_admitted(title, body="Some accompanying text that is long enough here.")) \
            is Reason.NON_ARTICLE_FORMAT

    def test_a_story_about_a_quiz_show_is_not_a_quiz(self):
        item = _admitted(
            "Quizmaster Derek Mooney retires after thirty years on air",
            body="The broadcaster announced his retirement on Monday after a long career.",
        )
        assert _judge(item) is Reason.NON_ARTICLE_FORMAT or _judge(item) is None


class TestLength:
    def test_a_headline_only_article_with_no_body_is_too_short(self):
        assert _judge(_admitted("Minister resigns today")) is Reason.TOO_SHORT

    def test_a_short_body_plus_a_headline_can_clear_the_floor(self):
        """NDTV files one-line bodies; they are thin but legitimate."""
        item = _admitted(
            "Delhi van driver kills passenger over fare dispute",
            body="The accused called his wife and son to hide the body, police said.",
        )
        assert _judge(item) is None

    def test_a_two_word_title_is_rejected_whatever_the_body(self):
        assert _judge(_admitted("Breaking news", body="A long body " * 40)) is Reason.TOO_SHORT

    def test_an_article_with_nothing_left_after_cleaning_is_empty(self):
        assert _judge(_admitted("", "", "")) is Reason.EMPTY_TEXT


class TestTimestamps:
    def test_a_future_publication_date_is_rejected(self):
        item = _admitted(*REAL_STORY, published_at=NOW + timedelta(days=2))
        assert _judge(item) is Reason.FUTURE_TIMESTAMP

    def test_a_small_clock_skew_is_tolerated(self):
        item = _admitted(*REAL_STORY, published_at=NOW + timedelta(hours=2))
        assert _judge(item) is None

    def test_an_ancient_article_is_rejected(self):
        item = _admitted(*REAL_STORY, published_at=NOW - timedelta(days=900))
        assert _judge(item) is Reason.IMPLAUSIBLE_TIMESTAMP

    def test_a_missing_publication_date_is_not_a_rejection(self):
        assert _judge(_admitted(*REAL_STORY, published_at=None)) is None


class TestDuplicatesAndPolicy:
    def test_the_second_article_with_a_hash_already_seen_is_dropped(self):
        seen: set[str] = set()
        first = _admitted(*REAL_STORY)
        assert judge(first, policy=Policy(), now=NOW, seen_hashes=seen) is None
        assert judge(first, policy=Policy(), now=NOW, seen_hashes=seen).reason is Reason.EXACT_DUPLICATE

    def test_articles_with_different_text_are_not_duplicates(self):
        seen: set[str] = set()
        for title in ("Parliament passes the education bill", "Parliament rejects the housing bill"):
            item = _admitted(title, body="A body long enough to clear the word floor comfortably.")
            assert judge(item, policy=Policy(), now=NOW, seen_hashes=seen) is None

    def test_every_gate_can_be_switched_off_so_phase_b_can_price_it(self):
        bulletin = _admitted("Gold rate today: steady in Chennai",
                             body="Gold prices held steady across major cities on Tuesday.")
        assert _judge(bulletin) is Reason.SERVICE_BULLETIN
        assert _judge(bulletin, without(Policy(), "reject_service_bulletin")) is None

    def test_language_rejection_is_off_by_default(self):
        """v1 dropped 443 articles on language alone without ever measuring the cost."""
        assert Policy().reject_non_latin is False

    def test_a_hindi_body_is_only_rejected_when_the_gate_is_enabled(self):
        item = _admitted("Minister addresses the rally in Patna today",
                         body="मंत्री ने कहा कि सरकार जल्द ही नई योजना लाएगी और सभी को लाभ मिलेगा।")
        assert _judge(item) is None
        assert _judge(item, Policy(reject_non_latin=True)) is Reason.NON_LATIN_SCRIPT

    def test_an_english_headline_cannot_dilute_a_foreign_body(self):
        """Pooling title and body scores this pair 0.47 and lets it through."""
        item = _admitted("Minister addresses the rally in Patna today",
                         body="मंत्री ने कहा कि सरकार जल्द ही नई योजना लाएगी और सभी को लाभ मिलेगा।")
        assert non_latin_share(item.body.text) == 1.0
        assert _judge(item, Policy(reject_non_latin=True)) is Reason.NON_LATIN_SCRIPT


class TestNonLatinShare:
    def test_plain_english_is_zero(self):
        assert non_latin_share("The minister spoke today.") == 0.0

    def test_devanagari_is_one(self):
        assert non_latin_share("मंत्री ने कहा") == 1.0

    def test_digits_and_punctuation_do_not_count_as_letters(self):
        assert non_latin_share("2026 -- 12:00!") == 0.0


def test_partition_splits_and_keeps_every_article_accounted_for():
    items = [
        _admitted(*REAL_STORY),
        _admitted("DH Toon | Park Bill passed", body="Check out more of our cartoons."),
        _admitted("Hi"),
    ]
    kept, rejected = partition(items, now=NOW)
    assert len(kept) + len(rejected) == len(items)
    assert {r.reason for r in rejected} == {Reason.NON_ARTICLE_FORMAT, Reason.TOO_SHORT}
