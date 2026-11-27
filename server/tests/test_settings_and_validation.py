import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from helpers import FIXTURES
from newsbot_server.core import jsonutil
from newsbot_server.core.settings import (
    SettingsError,
    load_mcp_settings,
    load_owner_mongo_settings,
    load_web_settings,
    normalize_origin,
    parse_agent_keys,
    parse_bool,
    parse_duration,
    read_env_file,
)
from newsbot_server.core.validation import parse_rfc3339, valid_domain_tag, valid_id
from newsbot_server.web.startup import check_listeners

DIGEST = "a" * 64
FLAG = "NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK"
ALL_INTERFACES = {"NEWS_AUTH_ENABLED": "false", "NEWS_SERVER_HOST": "0.0.0.0"}


@pytest.mark.parametrize("value", [
    "0198f3d2-3333-7000-8000-000000000001",
    "0198F3D2-3333-7000-8000-00000000000A",
    "urn:uuid:0198f3d2-3333-7000-8000-000000000001",
    "{0198f3d2-3333-7000-8000-000000000001}",
    "0198f3d233337000800000000000000a",
])
def test_ids_accept_what_go_uuid_parse_accepts(value):
    assert valid_id(value)


@pytest.mark.parametrize("value", [
    "", "$where", "invalid", "0198f3d2-3333-7000-8000-00000000000g", "0198f3d2_3333-7000-8000-000000000001",
    "0198f3d2-3333-7000-8000-0000000000011", "urn:uuix:0198f3d2-3333-7000-8000-000000000001", None, 7,
])
def test_ids_reject_anything_else(value):
    assert not valid_id(value)


def test_domain_tags_follow_the_source_rule():
    assert valid_domain_tag("ai") and valid_domain_tag("data-science") and valid_domain_tag("a" * 64)
    for tag in ("AI", "", "-ai", "ai-", "a" * 65, "ai tools", "data_science"):
        assert not valid_domain_tag(tag)


def test_rfc3339_parsing_matches_the_go_layout():
    assert parse_rfc3339("2026-08-22T10:30:00Z") == datetime(2026, 8, 22, 10, 30, tzinfo=UTC)
    assert parse_rfc3339("2026-08-22T16:00:00.5+05:30") == datetime(2026, 8, 22, 10, 30, 0, 500000, tzinfo=UTC)
    assert parse_rfc3339("2026-08-22T10:30:00-01:00").utcoffset() == -timedelta(hours=1)
    for text in ("yesterday", "2026-08-22", "2026-08-22 10:30:00Z", "2026-02-30T00:00:00Z", "2026-08-22T10:30:00"):
        assert parse_rfc3339(text) is None


def test_json_output_escapes_html_like_go():
    body = jsonutil.dumps({"title": "<script>&</script>\u2028", "n": 1})
    assert body == b'{"title":"\\u003cscript\\u003e\\u0026\\u003c/script\\u003e\\u2028","n":1}'
    with pytest.raises(jsonutil.JSONBodyError) as nan:
        jsonutil.loads_one(b'{"x": NaN}')
    assert nan.value.reason == "invalid"
    assert jsonutil.loads_one(b"  {}\n") == {}


def test_dotenv_reader_handles_quotes_exports_and_comments():
    values = read_env_file(FIXTURES / "dotenv.sample")
    assert values["NEWS_MONGO_DATABASE"] == "from_file"
    assert values["NEWS_SERVER_PORT"] == "9090"
    assert values["NEWS_LOGGING_LEVEL"] == "debug"
    assert values["NEWS_PUBLIC_URL"] == "https://quoted.example.test"
    assert values["NEWS_RECOMMENDER_ENDPOINT"] == "http://ranker.example.test:8001"
    assert "BROKEN_LINE_WITHOUT_EQUALS" not in values
    assert read_env_file(FIXTURES / "missing.sample") == {}


def test_go_durations_and_booleans():
    assert parse_duration("15s") == 15 and parse_duration("1h30m") == 5400 and parse_duration("168h") == 604800
    assert parse_duration("1.5s") == 1.5 and parse_duration("500ms") == 0.5 and parse_duration("0") == 0
    for bad in ("", "15", "s", "1x", "1h 30m"):
        with pytest.raises(ValueError):
            parse_duration(bad)
    assert parse_bool("true") and parse_bool("1") and not parse_bool("F")
    with pytest.raises(ValueError):
        parse_bool("yes")


def test_web_defaults_and_secrets_stay_out_of_repr():
    settings = load_web_settings({
        "NEWS_AUTH_ENABLED": "true", "NEWS_GOOGLE_CLIENT_ID": "id", "NEWS_GOOGLE_CLIENT_SECRET": "very-secret",
        "NEWS_PUBLIC_URL": "https://News.Example.test/", "NEWS_MONGO_URI": "mongodb://user:hunter2@db:27017",
        "NEWS_RECOMMENDER_API_KEY": "ranker-secret",
    })
    assert (settings.host, settings.port, settings.mongo.database) == ("127.0.0.1", 8090, "news")
    assert settings.ranker.endpoint == "http://127.0.0.1:8001"
    assert settings.session_idle_timeout == 7 * 86400 and settings.session_absolute_timeout == 30 * 86400
    assert settings.public_origin == "https://news.example.test"
    text = repr(settings)
    assert "very-secret" not in text and "hunter2" not in text and "ranker-secret" not in text


@pytest.mark.parametrize(("values", "problem"), [
    ({"NEWS_AUTH_ENABLED": "false", "NEWS_APP_ENVIRONMENT": "production"}, "not allowed in production"),
    ({"NEWS_AUTH_ENABLED": "false", "NEWS_SERVER_HOST": "0.0.0.0"}, "loopback"),
    ({"NEWS_AUTH_ENABLED": "true"}, "NEWS_GOOGLE_CLIENT_ID must be set"),
    ({"NEWS_GOOGLE_CLIENT_ID": "i", "NEWS_GOOGLE_CLIENT_SECRET": "s", "NEWS_PUBLIC_URL": "http://news.example.test"}, "must use https"),
    ({"NEWS_GOOGLE_CLIENT_ID": "i", "NEWS_GOOGLE_CLIENT_SECRET": "s", "NEWS_PUBLIC_URL": "https://x.test/app"}, "only a scheme"),
    ({"NEWS_AUTH_ENABLED": "maybe"}, "true or false"),
    ({"NEWS_AUTH_ENABLED": "false", "NEWS_SESSION_IDLE_TIMEOUT": "48h", "NEWS_SESSION_ABSOLUTE_TIMEOUT": "24h"}, "must not be longer"),
    ({"NEWS_AUTH_ENABLED": "false", "NEWS_MONGO_URI": "postgres://x"}, "mongodb://"),
    ({"NEWS_AUTH_ENABLED": "false", "NEWS_SERVER_PORT": "70000"}, "NEWS_SERVER_PORT"),
    ({**ALL_INTERFACES, FLAG: "yes"}, f"{FLAG} must be true or false"),
])
def test_web_settings_refuse_unsafe_or_incomplete_configurations(values, problem):
    with pytest.raises(SettingsError) as error:
        load_web_settings(values)
    assert problem in str(error.value)


def test_sign_in_off_is_allowed_on_loopback_outside_production():
    settings = load_web_settings({"NEWS_AUTH_ENABLED": "false", "NEWS_SERVER_HOST": "::1"})
    assert not settings.auth_enabled and settings.public_url == "http://[::1]:8090"
    local = load_web_settings({"NEWS_GOOGLE_CLIENT_ID": "i", "NEWS_GOOGLE_CLIENT_SECRET": "s", "NEWS_PUBLIC_URL": "http://localhost:8090"})
    assert local.public_origin == "http://localhost:8090"


@pytest.mark.parametrize("values", [
    {**ALL_INTERFACES, FLAG: "true", "NEWS_APP_ENVIRONMENT": "production"},
    {**ALL_INTERFACES, FLAG: "true", "NEWS_APP_ENVIRONMENT": "staging"},
    {FLAG: "true", "NEWS_APP_ENVIRONMENT": "production", "NEWS_GOOGLE_CLIENT_ID": "i",
     "NEWS_GOOGLE_CLIENT_SECRET": "s", "NEWS_PUBLIC_URL": "https://news.example.test"},
])
def test_published_loopback_flag_is_refused_outside_development(values):
    with pytest.raises(SettingsError) as error:
        load_web_settings(values)
    assert f"{FLAG}=true is allowed only when NEWS_APP_ENVIRONMENT=development" in str(error.value)


def test_published_loopback_flag_allows_sign_in_off_on_all_interfaces_in_development(caplog):
    settings = load_web_settings({**ALL_INTERFACES, FLAG: "true", "NEWS_APP_ENVIRONMENT": "development"})
    assert not settings.auth_enabled and settings.trust_published_loopback and settings.host == "0.0.0.0"
    assert settings.public_url == "http://127.0.0.1:8090"
    caplog.set_level(logging.WARNING, logger="newsbot.web")
    check_listeners(settings, [("0.0.0.0", 8090)])
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1 and "127.0.0.1 only" in warnings[0].getMessage()
    assert warnings[0].fields == {"listen": "0.0.0.0:8090", "setting": FLAG}


def test_all_interfaces_without_the_flag_is_refused_in_development(caplog):
    with pytest.raises(SettingsError) as error:
        load_web_settings({**ALL_INTERFACES, "NEWS_APP_ENVIRONMENT": "development"})
    assert "needs NEWS_SERVER_HOST on a loopback address" in str(error.value)
    # A socket opened beyond loopback anyway (gunicorn --bind 0.0.0.0:...) is refused too.
    loopback = load_web_settings({"NEWS_AUTH_ENABLED": "false"})
    with pytest.raises(RuntimeError):
        check_listeners(loopback, [("0.0.0.0", 8090)])
    caplog.set_level(logging.WARNING, logger="newsbot.web")
    check_listeners(loopback, [("127.0.0.1", 8090), ("::1", 8090, 0, 0), "/run/newsbot.sock"])
    assert not caplog.records


def test_origins_are_normalized():
    assert normalize_origin("HTTPS://News.Example.test:443") == "https://news.example.test"
    assert normalize_origin("http://127.0.0.1:8090") == "http://127.0.0.1:8090"
    assert normalize_origin("null") is None and normalize_origin("https://x.test/path") is None


def test_agent_keys_are_name_and_sha256_pairs():
    keys = parse_agent_keys(f"claude:{DIGEST}, laptop:{'B' * 64},")
    assert [(key.name, key.digest) for key in keys] == [("claude", DIGEST), ("laptop", "b" * 64)]
    for bad in ("claude", f"claude:{'a' * 63}", f"two words:{DIGEST}", f"a:{DIGEST},a:{'b' * 64}", f":{DIGEST}"):
        with pytest.raises(ValueError):
            parse_agent_keys(bad)


def test_mcp_settings_need_their_own_login_and_keys_for_http():
    with pytest.raises(SettingsError) as error:
        load_mcp_settings({"NEWS_MONGO_URI": "mongodb://localhost:27017"})
    assert "NEWS_MCP_MONGO_URI must be set" in str(error.value) and "NEWS_MCP_API_KEYS" in str(error.value)
    stdio = load_mcp_settings({"NEWS_MCP_MONGO_URI": "mongodb://mcp:pw@localhost:27017"}, require_keys=False)
    assert stdio.port == 8091 and stdio.allowed_hosts[0] == "127.0.0.1:8091" and stdio.rate_limit_per_minute == 60
    assert "pw@" not in repr(stdio)
    http = load_mcp_settings({"NEWS_MCP_MONGO_URI": "mongodb://x", "NEWS_MCP_API_KEYS": f"agent:{DIGEST}"})
    assert http.agent_keys[0].name == "agent" and DIGEST not in repr(http)


def test_owner_login_falls_back_to_the_reader_uri():
    assert load_owner_mongo_settings({"NEWS_OWNER_MONGO_URI": "mongodb://owner@db"}).uri == "mongodb://owner@db"
    assert load_owner_mongo_settings({"NEWS_MONGO_URI": "mongodb://reader@db"}).uri == "mongodb://reader@db"


def test_aware_timezone_offsets_are_kept():
    assert parse_rfc3339("2026-01-01T00:00:00+05:30").tzinfo == timezone(timedelta(hours=5, minutes=30))
