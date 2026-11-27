"""Readers, sessions, sign-in and the owner CLI against a real MongoDB (throwaway database)."""

from __future__ import annotations

import argparse
import io
from datetime import timedelta

import pytest
from pymongo.errors import DuplicateKeyError

from helpers import PUBLIC_URL, FakeArticles, FakeGoogle, FakeRanker, auth_settings, recommendation_service
from newsbot_server import admin
from newsbot_server.core.readers import ReaderStore, SessionStore, hash_token
from newsbot_server.web.app import Services, create_app
from newsbot_server.web.auth import FlowCookie, GoogleOIDC

pytestmark = pytest.mark.integration
CLIENT_ID = "client-id.apps.googleusercontent.com"


def test_invites_bind_one_google_account_and_revoke(database, clock):
    readers = ReaderStore(database)
    reader, created = readers.invite("reader@example.test", "Reader", now=clock())
    assert created and reader.invited and not reader.google_bound and reader.name == "Reader"
    again, created_again = readers.invite("reader@example.test", "", now=clock())
    assert not created_again and again.id == reader.id and again.name == "Reader"
    assert readers.bind_google_sub(reader.id, "sub-1") and not readers.bind_google_sub(reader.id, "sub-2")
    assert readers.by_google_sub("sub-1").id == reader.id and readers.google_sub_of(reader.id) == "sub-1"
    other, _ = readers.invite("other@example.test")
    with pytest.raises(DuplicateKeyError):
        database.readers.update_one({"_id": other.id}, {"$set": {"google_sub": "sub-1"}})
    with pytest.raises(DuplicateKeyError):
        database.readers.insert_one({"_id": "x", "email": "reader@example.test"})
    readers.record_login(other.id, clock(), "Google Name")
    assert readers.get(other.id).name == "Google Name" and readers.get(other.id).last_login_at == clock()
    readers.record_login(reader.id, clock(), "Not Replacing")
    assert readers.get(reader.id).name == "Reader"
    assert not readers.revoke("reader@example.test").invited and readers.revoke("nobody@example.test") is None


def test_sessions_store_only_a_hash_and_enforce_idle_and_absolute_timeouts(database, clock):
    sessions = SessionStore(database, idle=timedelta(days=7), absolute=timedelta(days=30), clock=clock)
    token, session = sessions.create("reader-1")
    stored = database.reader_sessions.find_one()
    assert stored["_id"] == hash_token(token) == session.token_hash and token not in str(stored)
    assert stored["expires_at"] == clock() + timedelta(days=7)
    assert sessions.lookup(token).reader_id == "reader-1" and sessions.lookup("forged-token") is None

    clock.now += timedelta(days=6)
    assert sessions.lookup(token) is not None
    assert database.reader_sessions.find_one()["expires_at"] == clock() + timedelta(days=7)

    clock.now += timedelta(days=7, seconds=1)
    assert sessions.lookup(token) is None  # idle too long

    token, _ = sessions.create("reader-1")
    for _ in range(31):
        clock.now += timedelta(days=1)
        alive = sessions.lookup(token)
    assert alive is None  # the absolute limit wins over daily use
    assert database.reader_sessions.find_one({"_id": hash_token(token)})["expires_at"] <= clock()

    token, _ = sessions.create("reader-2")
    sessions.delete(token)
    assert sessions.lookup(token) is None
    sessions.create("reader-3")
    sessions.create("reader-3")
    assert sessions.count_for_reader("reader-3") == 2 and sessions.delete_for_reader("reader-3") == 2


def test_session_ttl_index_is_declared(database):
    indexes = {index["name"]: index for index in database.reader_sessions.list_indexes()}
    assert indexes["ttl_expires_at"]["expireAfterSeconds"] == 0 and "ix_reader" in indexes


def test_sign_in_end_to_end_with_mongodb(database, same_origin):
    readers = ReaderStore(database)
    reader, _ = readers.invite("reader@example.test")
    google = FakeGoogle(CLIENT_ID)
    articles = FakeArticles()
    settings = auth_settings()
    services = Services(
        articles=articles,
        recommendations=recommendation_service(FakeRanker(), articles),
        ping_database=lambda: None,
        readers=readers,
        sessions=SessionStore(database, idle=timedelta(days=7), absolute=timedelta(days=30)),
        oidc=GoogleOIDC(CLIENT_ID, "unit-test-client-secret", PUBLIC_URL + "/auth/google/callback", transport=google),
        flow_cookie=FlowCookie("unit-test-client-secret"),
    )
    client = create_app(settings, services).test_client()
    assert client.get("/api/v1/articles").status_code == 401
    login = client.get("/auth/google/login?next=/stories")
    state = google.saw_authorization(login.headers["Location"])["state"]
    done = client.get("/auth/google/callback", query_string={"state": state, "code": "4/x"})
    assert done.status_code == 302 and done.headers["Location"] == "/stories"
    assert readers.get(reader.id).google_bound and database.reader_sessions.count_documents({"reader_id": reader.id}) == 1
    assert client.get("/api/v1/session").get_json()["reader"]["email"] == "reader@example.test"
    assert client.get("/api/v1/articles").status_code == 200
    assert client.post("/auth/logout", headers=same_origin).status_code == 204
    assert database.reader_sessions.count_documents({}) == 0
    assert client.get("/api/v1/articles").status_code == 401

    login = client.get("/auth/google/login")
    state = google.saw_authorization(login.headers["Location"])["state"]
    client.get("/auth/google/callback", query_string={"state": state, "code": "4/y"})
    out = io.StringIO()
    assert admin.run(argparse.Namespace(action="revoke", email="Reader@Example.test"), {}, out=out, database=database) == 0
    assert "ended 1 session(s)" in out.getvalue()
    assert client.get("/api/v1/articles").status_code == 401


def test_owner_cli_invites_lists_and_revokes(database):
    def run(action, email=None, name=""):
        out = io.StringIO()
        code = admin.run(argparse.Namespace(action=action, email=email, name=name), {}, out=out, database=database)
        return code, out.getvalue()

    assert run("list") == (0, "No readers yet. Invite one with: newsbot-server readers invite <email>\n")
    code, text = run("invite", " Brother@Example.test ", "Brother")
    assert code == 0 and text.startswith("Invited brother@example.test")
    assert run("invite", "brother@example.test")[1].startswith("Invite active for brother@example.test")
    code, text = run("list")
    assert "brother@example.test\tinvited=yes\tname=Brother\tgoogle=not yet\tlast_sign_in=never\tsessions=0" in text
    assert run("revoke", "brother@example.test")[0] == 0 and "invited=no" in run("list")[1]
    assert run("revoke", "stranger@example.test")[0] == 1
    assert run("invite", "not-an-email")[0] == 2
