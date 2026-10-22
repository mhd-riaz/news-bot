"""Constants that make a run reproducible.

Every artifact written by this package records CLEANING_VERSION, TAXONOMY_VERSION,
SEED and the gold-label digest, so any row in a snapshot traces back to the code and
the labels that produced it.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Bump on any change to clean.py, admit.py or dedup.py that alters their output.
# Snapshots are keyed by this: a bump makes existing snapshots stale, not wrong.
CLEANING_VERSION = "2.0.0"

# Fixed seed for every sampling decision.
SEED = 20260823

ML_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ML_ROOT / "data"
LABEL_PATH = DATA_DIR / "labels" / "gold.jsonl"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CACHE_DIR = DATA_DIR / "cache"
ARTIFACT_DIR = ML_ROOT / "artifacts"
LEDGER_PATH = ARTIFACT_DIR / "experiments" / "ledger.jsonl"
REPORT_DIR = ML_ROOT / "reports"
CONFIG_DIR = ML_ROOT / "configs"
TAXONOMY_PATH = ML_ROOT / "taxonomy.yaml"

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017/news"
DOTENV_PATH = ML_ROOT.parent / ".env"

# The corpus cut. Frozen for the whole experiment programme: a mid-project re-cut
# makes every earlier number incomparable. A re-cut is a new round, not a continuation.
#
# Two constraints pin this timestamp, and both bite:
#   1. It must fall AFTER the last gold label was collected (2026-08-26T09:49:39Z) or
#      labelled articles are silently dropped -- midnight today lost 477 of 8,001.
#   2. It must fall in the PAST, or the collector keeps adding articles inside the
#      window and the snapshot stops being reproducible.
COLLECTED_BEFORE = "2026-08-26T12:00:00+00:00"

# Held out whole, never as a section feed: a section feed carries one or two classes,
# so most classes get zero support and macro-F1 collapses to a meaningless number.
# The Indian Express is excluded despite being the obvious candidate -- at 1,683 of
# 8,001 gold articles it is 21% of the labels, so removing it would confound
# "generalises to an unseen publisher" with "trained on 21% less data".
PUBLISHER_HOLDOUTS = ("The Hindu", "The Guardian")

# Not a class. A gold row labelled `unsorted` is the absence of a class, so it never
# trains; it is the evaluation set for the abstention mechanism instead.
UNSORTED = "unsorted"


def _uri_from_dotenv(path: Path) -> str:
    """Read the collector's own connection string, with the database spliced in.

    The corpus lives wherever the collector writes, and `.env` is where that is
    declared. Without this the default points at a laptop's local MongoDB, which has
    twice been empty while every make target reported on it happily -- a silent wrong
    answer is worse than a missing one.
    """
    if not path.is_file():
        return ""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")

    uri = values.get("NEWS_MONGO_URI", "")
    database = values.get("NEWS_MONGO_DATABASE", "news")
    if not uri:
        return ""

    scheme, _, rest = uri.partition("://")
    authority, sep, query = rest.partition("?")
    if "/" not in authority:
        authority = f"{authority}/{database}"
    elif authority.endswith("/"):
        authority = f"{authority}{database}"
    return f"{scheme}://{authority}{sep}{query}"


def mongo_uri() -> str:
    """Connection string for the bronze corpus. Read-only by convention."""
    return (
        os.environ.get("NEWSMLV2_MONGO_URI")
        or _uri_from_dotenv(DOTENV_PATH)
        or DEFAULT_MONGO_URI
    )


def digest(path: Path) -> str:
    """sha256 of a file, recorded in manifests.

    The gold labels are vendored rather than committed, so this digest is the only
    integrity anchor tying a snapshot to the labels it was built from.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
