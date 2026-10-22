from __future__ import annotations

from pathlib import Path

import pytest

from newsml import config


@pytest.fixture
def dotenv(tmp_path: Path):
    def _write(body: str) -> Path:
        path = tmp_path / ".env"
        path.write_text(body, encoding="utf-8")
        return path

    return _write


def test_env_var_wins_over_the_dotenv_file(monkeypatch, dotenv):
    monkeypatch.setenv("NEWS_ML_MONGO_URI", "mongodb://explicit:27017/news")
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv("NEWS_MONGO_URI=mongodb://ignored:27017"))
    assert config.mongo_uri() == "mongodb://explicit:27017/news"


def test_database_is_spliced_into_a_uri_that_has_none(monkeypatch, dotenv):
    monkeypatch.delenv("NEWS_ML_MONGO_URI", raising=False)
    body = "NEWS_MONGO_URI=mongodb://u:p@10.0.0.1:27017/?authSource=admin\nNEWS_MONGO_DATABASE=news\n"
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv(body))
    assert config.mongo_uri() == "mongodb://u:p@10.0.0.1:27017/news?authSource=admin"


def test_a_uri_that_already_names_a_database_is_left_alone(monkeypatch, dotenv):
    monkeypatch.delenv("NEWS_ML_MONGO_URI", raising=False)
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv("NEWS_MONGO_URI=mongodb://host:27017/other\n"))
    assert config.mongo_uri() == "mongodb://host:27017/other"


def test_comments_and_quotes_are_ignored(monkeypatch, dotenv):
    monkeypatch.delenv("NEWS_ML_MONGO_URI", raising=False)
    body = '# NEWS_MONGO_URI=mongodb://commented:27017\nNEWS_MONGO_URI="mongodb://real:27017/"\n'
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv(body))
    assert config.mongo_uri() == "mongodb://real:27017/news"


def test_falls_back_to_localhost_when_there_is_no_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("NEWS_ML_MONGO_URI", raising=False)
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / "absent.env")
    assert config.mongo_uri() == config.DEFAULT_MONGO_URI
