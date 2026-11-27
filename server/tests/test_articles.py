"""Ported from collector/internal/domain/article_filter_test.go and the article response rules."""

from datetime import UTC, datetime, timedelta

import pytest

from helpers import ONE_ID, SOURCE_ID, FakeArticles, sample_article
from newsbot_server.core.articles import (
    DEFAULT_LIST_LIMIT,
    ArticleCursor,
    ArticleFilter,
    ArticleNotFound,
    article_query,
    article_response,
    date_kind,
    filter_from_query,
    format_time,
    get_article,
    list_articles,
)
from newsbot_server.core.validation import MAX_LIST_LIMIT, MAX_REGION_LENGTH, ValidationFailed

NOW = datetime(2026, 8, 22, 10, 30, tzinfo=UTC)


def test_filter_normalize_applies_defaults():
    flt = ArticleFilter(
        source_id=f"  {SOURCE_ID}  ", language=" EN ", country=" in ", state="  Karnataka ",
        city=" Bengaluru  ", topic=" Politics ",
    ).normalized()
    assert flt.limit == DEFAULT_LIST_LIMIT and flt.sort == "published_at"
    assert (flt.language, flt.country) == ("en", "IN")
    assert (flt.state, flt.city, flt.topic, flt.source_id) == ("Karnataka", "Bengaluru", "politics", SOURCE_ID)
    flt.validate()


def test_filter_reports_all_nine_problems_at_once():
    flt = ArticleFilter(
        source_id="'; drop everything", language="english", country="IND",
        state="s" * (MAX_REGION_LENGTH + 1), city="c" * (MAX_REGION_LENGTH + 1), topic="t" * (MAX_REGION_LENGTH + 1),
        sort="relevance", limit=MAX_LIST_LIMIT + 1, published_from=NOW, published_to=NOW - timedelta(hours=1),
    )
    with pytest.raises(ValidationFailed) as error:
        flt.validate()
    fields = [item.field for item in error.value.fields]
    assert len(fields) == 9 and fields == sorted(fields)


def test_filter_accepts_an_open_ended_range_and_keeps_go_sort_quirk():
    ArticleFilter(published_from=NOW).normalized().validate()
    with pytest.raises(ValidationFailed):
        ArticleFilter(sort="  ").normalized().validate()
    assert ArticleFilter(limit=0).normalized().limit == DEFAULT_LIST_LIMIT


def test_cursor_round_trips_and_is_url_safe_and_opaque():
    token = ArticleCursor(NOW, ONE_ID).encode()
    decoded = ArticleCursor.parse(token)
    assert decoded == ArticleCursor(NOW, ONE_ID)
    assert not any(char in token for char in "+/=&?#") and "0198f3d2" not in token


def test_cursor_matches_tokens_made_by_the_go_reader():
    decoded = ArticleCursor.parse("MTc2Njk5MDgwMDAwMC4wMTk4ZjNkMi0zMzMzLTcwMDAtODAwMC0wMDAwMDAwMDAwMDE")
    assert decoded.id == ONE_ID and decoded.value == datetime(2025, 12, 29, 6, 46, 40, tzinfo=UTC)


@pytest.mark.parametrize("token", [
    "not base64!!", "YWJjZGVm", "d2hlbmV2ZXIuMDE5OGYzZDItMzMzMy03MDAwLTgwMDAtMDAwMDAwMDAwMDAx",
    "MTIzNDU2Nzg5MC57JG5lOjF9", "", "YWJj=",
])
def test_cursor_rejects_rubbish(token):
    with pytest.raises(ValidationFailed):
        ArticleCursor.parse(token)


def test_cursor_for_uses_the_sorted_field():
    doc = {"_id": ONE_ID, "published_at": NOW - timedelta(days=1), "collected_at": NOW}
    assert ArticleCursor.parse(ArticleFilter(sort="published_at").cursor_for(doc)).value == NOW - timedelta(days=1)
    assert ArticleCursor.parse(ArticleFilter(sort="collected_at").cursor_for(doc)).value == NOW


def test_query_parameters_are_parsed_like_the_go_handler():
    flt = filter_from_query({
        "source_id": SOURCE_ID, "language": "en", "country": "IN", "state": "Karnataka", "city": "Bengaluru",
        "topic": "Politics", "published_from": "2026-08-01T00:00:00Z", "published_to": "2026-08-22T00:00:00Z",
        "sort": "collected_at", "limit": "25",
    })
    assert (flt.sort, flt.limit, flt.topic) == ("collected_at", 25, "Politics")
    assert flt.published_from == datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(ValidationFailed) as error:
        filter_from_query({"limit": "lots", "published_from": "yesterday", "published_to": "tomorrow"})
    assert len(error.value.fields) == 3
    for bad_limit in ("1.5", " 5", "5_0", "１"):
        with pytest.raises(ValidationFailed):
            filter_from_query({"limit": bad_limit})


def test_query_is_built_from_typed_values_only():
    cursor = ArticleCursor(NOW, ONE_ID)
    query = article_query(ArticleFilter(language="en", cursor=cursor, text="a.b(c", sort="published_at", limit=5))
    assert query["language"] == "en"
    assert query["$and"][0]["$or"] == [{"published_at": {"$lt": NOW}}, {"published_at": NOW, "_id": {"$lt": ONE_ID}}]
    assert query["$and"][1]["$or"][0] == {"title": {"$regex": r"a\.b\(c", "$options": "i"}}


def test_article_response_matches_the_go_wire_format():
    body = article_response(sample_article(authors=["A"], categories=[], image_url=""))
    for leaked in ("dedup_id", "normalized_url", "content_hash", "processing_status", "feed_guid"):
        assert leaked not in body
    assert list(body) == [
        "id", "source_id", "source_name", "url", "title", "summary", "content", "authors", "language",
        "country", "state", "city", "published_at", "collected_at",
    ]
    assert body["published_at"] == "2026-08-22T09:00:00Z" and body["collected_at"] == "2026-08-22T10:00:00Z"
    classified = article_response(sample_article(classification_status="classified", topic="politics", confidence=0.9))
    assert (classified["topic"], classified["classification_status"], classified["confidence"]) == ("politics", "classified", 0.9)
    pending = article_response(sample_article(classification_status="pending", topic="politics"))
    assert "topic" not in pending and "confidence" not in pending


def test_times_and_date_kind_follow_go():
    assert format_time(None) == "0001-01-01T00:00:00Z"
    assert format_time(datetime(2026, 8, 1, 0, 0, 0, 123000)) == "2026-08-01T00:00:00.123Z"
    assert date_kind({"published_at": NOW, "collected_at": NOW}) == "Collected"
    assert date_kind({"published_at": NOW, "collected_at": NOW + timedelta(seconds=1)}) == "Stored publication date"


def test_service_validates_before_reading():
    articles = FakeArticles(docs=[sample_article()])
    with pytest.raises(ValidationFailed):
        get_article(articles, "$where")
    with pytest.raises(ArticleNotFound):
        get_article(articles, "0198f3d2-3333-7000-8000-000000000009")
    assert get_article(articles, ONE_ID)["content"] == "The full text of the article."
    with pytest.raises(ValidationFailed):
        list_articles(articles, ArticleFilter(limit=101))
    assert articles.calls == 2
