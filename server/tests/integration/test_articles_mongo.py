"""Article reads against MongoDB, ported from collector/internal/repository/mongo/article_query_integration_test.go."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from mongo_helpers import article

from newsbot_server.core.articles import ArticleCursor, ArticleFilter, ArticleStore, article_query, list_articles

pytestmark = pytest.mark.integration

BASE = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)


def seed(database, count, **overrides):
    docs = [article(i, BASE, **{key: value(i) if callable(value) else value for key, value in overrides.items()}) for i in range(count)]
    database.articles.insert_many(docs)
    return list(reversed(docs))  # newest first


def walk(store, flt, pages=12):
    seen = []
    for _ in range(pages):
        page = list_articles(store, flt)
        seen.extend(doc["_id"] for doc in page.items)
        if not page.has_more:
            return seen
        flt = ArticleFilter(**{**flt.__dict__, "cursor": ArticleCursor.parse(page.next_cursor)})
    raise AssertionError("paging did not finish")


def test_get_by_id_reads_the_whole_article(database):
    seed(database, 1)
    store = ArticleStore(database.articles)
    doc = store.get_by_id("0198f3d2-3333-7000-8000-000000000000")
    assert doc["content"] == "Full text 0" and "dedup_id" not in doc and "normalized_url" not in doc
    assert store.get_by_id("0198f3d2-3333-7000-8000-000000000009") is None


def test_listing_is_newest_first_without_content(database):
    want = seed(database, 3)
    page = list_articles(ArticleStore(database.articles), ArticleFilter(limit=10))
    assert [doc["_id"] for doc in page.items] == [doc["_id"] for doc in want]
    assert all("content" not in doc for doc in page.items) and page.items[0]["summary"] == "Summary 2"
    assert page.items[0]["published_at"].tzinfo is not None


def test_cursor_walks_every_article_exactly_once(database):
    want = seed(database, 7)
    assert walk(ArticleStore(database.articles), ArticleFilter(limit=2)) == [doc["_id"] for doc in want]


def test_cursor_pages_past_a_timestamp_tie(database):
    shared = BASE.replace(microsecond=0)
    seed(database, 4, published_at=shared)
    seen = walk(ArticleStore(database.articles), ArticleFilter(limit=1))
    assert len(seen) == len(set(seen)) == 4


@pytest.mark.parametrize(("flt", "count"), [
    (ArticleFilter(source_id="0198f3d2-1111-7000-8000-00000000aaaa", limit=10), 4),
    (ArticleFilter(source_id="0198f3d2-1111-7000-8000-0000000000ff", limit=10), 0),
    (ArticleFilter(city="Mysuru", limit=10), 2),
    (ArticleFilter(language="kn", limit=10), 2),
    (ArticleFilter(country="IN", state="Karnataka", limit=10), 4),
    (ArticleFilter(country="US", limit=10), 0),
])
def test_filters(database, flt, count):
    seed(database, 4, city=lambda i: "Mysuru" if i % 2 == 0 else "Bengaluru", language=lambda i: "kn" if i % 2 == 0 else "en")
    assert len(list_articles(ArticleStore(database.articles), flt).items) == count


def test_publication_range_is_inclusive(database):
    stored = seed(database, 5)
    flt = ArticleFilter(published_from=stored[3]["published_at"], published_to=stored[1]["published_at"], limit=10)
    assert len(list_articles(ArticleStore(database.articles), flt).items) == 3


def test_collection_time_order_shows_backdated_articles_first(database):
    now = datetime.now(UTC).replace(microsecond=0)
    database.articles.insert_many([
        article(1, BASE, published_at=now - timedelta(hours=72), collected_at=now),
        article(2, BASE, published_at=now - timedelta(hours=1), collected_at=now - timedelta(minutes=30)),
    ])
    store = ArticleStore(database.articles)
    assert list_articles(store, ArticleFilter(sort="published_at")).items[0]["title"] == "Story 2"
    assert list_articles(store, ArticleFilter(sort="collected_at")).items[0]["title"] == "Story 1"


def test_text_search_is_case_insensitive_and_escaped(database):
    database.articles.insert_many([
        article(1, BASE, title="Rain floods BENGALURU roads"),
        article(2, BASE, title="Markets", summary="Prices rose (again) in bengaluru"),
        article(3, BASE, title="Cricket", summary="Nothing here"),
    ])
    store = ArticleStore(database.articles)
    titles = [doc["title"] for doc in list_articles(store, ArticleFilter(text="Bengaluru", limit=10)).items]
    assert sorted(titles) == ["Markets", "Rain floods BENGALURU roads"]
    assert [doc["title"] for doc in list_articles(store, ArticleFilter(text="(again)", limit=10)).items] == ["Markets"]
    assert list_articles(store, ArticleFilter(text=".*", limit=10)).items == []


def test_hydration_is_one_bounded_query_without_bodies(database):
    seed(database, 3)
    store = ArticleStore(database.articles)
    ids = ["0198f3d2-3333-7000-8000-000000000002", "0198f3d2-3333-7000-8000-000000000000", "0198f3d2-3333-7000-8000-000000000099"]
    docs = store.get_by_ids(ids)
    assert sorted(doc["_id"] for doc in docs) == sorted(ids[:2])
    assert all("content" not in doc and "summary" not in doc for doc in docs)
    with pytest.raises(ValueError):
        store.get_by_ids(["0198f3d2-3333-7000-8000-000000000000"] * 31)


@pytest.mark.parametrize("flt", [
    ArticleFilter(),
    ArticleFilter(source_id="0198f3d2-1111-7000-8000-00000000aaaa"),
    ArticleFilter(language="en"),
    ArticleFilter(country="IN", state="Karnataka", city="Bengaluru"),
    ArticleFilter(sort="collected_at"),
    ArticleFilter(cursor=ArticleCursor(datetime.now(UTC), "0198f3d2-3333-7000-8000-000000000001")),
    ArticleFilter(source_id="0198f3d2-1111-7000-8000-00000000aaaa", cursor=ArticleCursor(datetime.now(UTC), "0198f3d2-3333-7000-8000-000000000001")),
    ArticleFilter(language="en", text="rain"),
])
def test_listing_queries_are_answered_from_an_index(database, flt):
    seed(database, 3)
    flt = flt.normalized()
    field = "collected_at" if flt.sort == "collected_at" else "published_at"
    plan = database.command("explain", {
        "find": "articles", "filter": article_query(flt), "sort": {field: -1, "_id": -1}, "limit": flt.limit + 1,
    }, verbosity="queryPlanner")
    winning = str(plan["queryPlanner"]["winningPlan"])
    assert "COLLSCAN" not in winning and "'SORT'" not in winning, winning
