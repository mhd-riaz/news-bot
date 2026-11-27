"""Owner commands for the invite list: `newsbot-server readers invite|revoke|list`.

They write `readers` with the owner's MongoDB login (NEWS_OWNER_MONGO_URI, else
NEWS_MONGO_URI). Revoking also deletes that reader's sessions, so it takes effect at once.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import timedelta
from typing import TextIO

from pymongo.errors import DuplicateKeyError, PyMongoError

from .core.mongo import connect
from .core.readers import ReaderStore, SessionStore, normalize_email
from .core.settings import SettingsError, load_owner_mongo_settings


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    readers = subparsers.add_parser("readers", help="manage the invited readers (owner login)")
    actions = readers.add_subparsers(dest="action", required=True)
    invite = actions.add_parser("invite", help="invite an email address, or re-enable it")
    invite.add_argument("email")
    invite.add_argument("--name", default="", help="display name (optional; Google's name is used otherwise)")
    revoke = actions.add_parser("revoke", help="stop an email from signing in and end its sessions")
    revoke.add_argument("email")
    actions.add_parser("list", help="show every reader")


def run(args: argparse.Namespace, values: Mapping[str, str], out: TextIO = sys.stdout, database=None) -> int:
    if database is None:
        try:
            mongo = load_owner_mongo_settings(values)
        except SettingsError as error:
            print(error, file=sys.stderr)
            return 2
        database = connect(mongo)[mongo.database]
    store = ReaderStore(database)
    sessions = SessionStore(database, idle=timedelta(days=1), absolute=timedelta(days=1))
    try:
        if args.action == "list":
            readers = store.all()
            if not readers:
                print("No readers yet. Invite one with: newsbot-server readers invite <email>", file=out)
            for reader in readers:
                last = reader.last_login_at.strftime("%Y-%m-%d %H:%M UTC") if reader.last_login_at else "never"
                print(
                    f"{reader.email}\tinvited={'yes' if reader.invited else 'no'}\tname={reader.name or '-'}\t"
                    f"google={'bound' if reader.google_bound else 'not yet'}\tlast_sign_in={last}\t"
                    f"sessions={sessions.count_for_reader(reader.id)}",
                    file=out,
                )
            return 0
        try:
            email = normalize_email(args.email)
        except ValueError:
            print("That is not an email address.", file=sys.stderr)
            return 2
        if args.action == "invite":
            reader, created = store.invite(email, args.name.strip())
            print(f"{'Invited' if created else 'Invite active for'} {email} (reader {reader.id}).", file=out)
            return 0
        reader = store.revoke(email)
        if reader is None:
            print(f"{email} is not on the invite list.", file=sys.stderr)
            return 1
        ended = sessions.delete_for_reader(reader.id)
        print(f"Revoked {email}; ended {ended} session(s).", file=out)
        return 0
    except DuplicateKeyError:
        print("That email was invited at the same moment by another command; run it again.", file=sys.stderr)
        return 1
    except PyMongoError as error:
        print(f"Database error ({type(error).__name__}). Check the owner login and that MongoDB is running.", file=sys.stderr)
        return 2
