"""Integration tests against a real MongoDB, each in its own throwaway `news_it_py_*` database.

NEWS_TEST_MONGO_URI selects the server (default mongodb://localhost:27017). When it
is not set and nothing answers on localhost, these tests are skipped.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

import pytest
from mongo_helpers import create_index_plan
from pymongo import MongoClient
from pymongo.errors import PyMongoError

def _client() -> MongoClient:
    explicit = os.environ.get("NEWS_TEST_MONGO_URI")
    client = MongoClient(explicit or "mongodb://localhost:27017", serverSelectionTimeoutMS=3000, tz_aware=True, tzinfo=UTC)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        if explicit:
            raise
        pytest.skip("MongoDB is not reachable on localhost:27017")
    return client


@pytest.fixture
def database():
    client = _client()
    name = f"news_it_py_{time.time_ns()}"
    assert name.startswith("news_it_")
    database = client[name]
    create_index_plan(database)
    try:
        yield database
    finally:
        client.drop_database(name)
        client.close()


@pytest.fixture
def clock():
    class Clock:
        def __init__(self) -> None:
            self.now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)

        def __call__(self) -> datetime:
            return self.now

    return Clock()
