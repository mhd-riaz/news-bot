"""Constants that make a run reproducible.

Every artifact written by this package records CLEANING_VERSION and SEED, so any
row in a snapshot can be traced back to the code that produced it.
"""

from __future__ import annotations

import os
from pathlib import Path

# Bump on any change to clean.py or admit.py that alters their output. Snapshots
# are keyed by this: a bump makes existing snapshots stale, not wrong.
CLEANING_VERSION = "1.2.0"

# Fixed seed for every sampling decision. Ground rule 8.
SEED = 20260823

ML_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ML_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ARTIFACT_DIR = ML_ROOT / "artifacts"
REPORT_DIR = ML_ROOT / "reports"
TAXONOMY_PATH = ML_ROOT / "taxonomy.yaml"
SOURCES_PATH = ML_ROOT.parent / "configs" / "sources.yaml"

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017/news"
DOTENV_PATH = ML_ROOT.parent / ".env"

# Title+summary is the only field populated across every source; content is
# present for a minority and correlates with the source, not the topic. Phase 2
# therefore builds the corpus on title+summary and treats full text as a bonus
# variant. See the decision log entry for 2026-08-23.
DEFAULT_TEXT_VARIANT = "title_summary"
TEXT_VARIANTS = ("title", "title_summary", "title_summary_content")


def _uri_from_dotenv(path: Path) -> str:
    """Read the collector's own connection string, with the database spliced in.

    The corpus lives wherever the collector writes, and `.env` is where that is
    declared. Without this the default points at a laptop's local MongoDB, which
    has twice been empty while every `make ml-*` target reported on it happily —
    a silent wrong answer is worse than a missing one.
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
    return os.environ.get("NEWS_ML_MONGO_URI") or _uri_from_dotenv(DOTENV_PATH) or DEFAULT_MONGO_URI
