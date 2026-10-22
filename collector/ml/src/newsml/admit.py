"""Admission filters, and a rejection log that accounts for every dropped article.

The Phase 2 acceptance criterion is strict: the rejection log must explain 100%
of the difference between input and output counts, by reason code. So admission
is written as a total function — every article returns either an acceptance or
exactly one `Rejection`, and `partition` asserts the arithmetic before returning.

The cleansing funnel with drop reasons is also one of the report figures, and it
is the figure almost nobody produces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .clean import Cleaned
from .load import Article


class Reason(StrEnum):
    """Why an article did not make it into the snapshot."""

    EMPTY_TEXT = "empty_text"
    TOO_SHORT = "too_short"
    LANGUAGE_MISMATCH = "language_mismatch"
    PAYWALL = "paywall"
    NON_ARTICLE_FORMAT = "non_article_format"
    SERVICE_BULLETIN = "service_bulletin"
    SPONSORED = "sponsored"
    FUTURE_TIMESTAMP = "future_timestamp"
    IMPLAUSIBLE_TIMESTAMP = "implausible_timestamp"
    EXACT_DUPLICATE = "exact_duplicate"


# A title+summary corpus is short by construction; this floor only removes stubs.
MIN_WORDS = 12
MIN_TITLE_WORDS = 3

# Timestamps outside this window are a parser bug, not news.
MAX_FUTURE_SKEW = timedelta(hours=6)
MAX_AGE = timedelta(days=365)

# Formats whose text is not prose and would teach a classifier the wrong thing.
NON_ARTICLE = re.compile(
    r"(?i)\b(?:live\s+(?:blog|updates?|score(?:card)?)|highlights?\s*:|in\s+(?:\d{1,3}\s+)?pictures?|photo\s+gallery"
    r"|horoscope|rashifal|numerology|today'?s\s+panchang|quiz\s+of\s+the\s+day"
    r"|scorecard|points\s+table|full\s+schedule|winning\s+numbers?|lottery\s+result)\b"
)
LISTICLE = re.compile(r"(?i)^\s*(?:top|best|worst)\s+\d{1,3}\b|\b\d{1,3}\s+(?:things|ways|reasons|tips)\b")
# Utility bulletins: real prose from a real newsroom, but a service to readers
# rather than a report of an event. The first gold round put every one of these
# in `unsorted`, which is the tell — they are unlabellable because they are not
# about anything. Matched on the title alone, deliberately: a genuine flood story
# quotes the weather bulletin in its body, and dropping those would starve
# `disaster_accident` further to catch a handful of notices.
SERVICE_BULLETIN = re.compile(
    r"(?i)\bweather\s+(?:today|update|highlights?|forecast|report|alert)\b"
    r"|\btraffic\s+(?:advisory|alert)\b|\balternate\s+routes?\b"
    r"|\bnews\s+headlines\s+for\b|\bthis\s+week\s+in\s+(?:science|tech|business)\b"
    r"|\btopic\s+page\b"
)
# Commercial content wearing a newsroom byline. Affiliate deals copy is the
# common case and matters more than it looks: it carries a real publisher's
# vocabulary, so left in, it teaches the technology class to recognise discount
# copy. Matched on specific bigrams, since a genuine story may mention a discount.
SPONSORED = re.compile(
    r"(?i)\b(?:sponsored(?:\s+(?:content|post|feature))?|partner\s+content|paid\s+post|advertorial"
    r"|brand\s+(?:post|desk)|(?:coupon|promo|discount|voucher)\s+codes?"
    r"|deal\s+of\s+the\s+day|best\s+deals?\b|save\s+\d{1,3}%)\b"
)
PAYWALL = re.compile(
    r"(?i)\b(?:subscribe\s+to\s+(?:read|continue)|this\s+(?:article|story)\s+is\s+for\s+subscribers"
    r"|to\s+continue\s+reading|premium\s+(?:article|story)|already\s+a\s+subscriber)\b"
)


@dataclass(frozen=True, slots=True)
class Rejection:
    """One dropped article, with enough context to audit the decision."""

    article_id: str
    source_id: str
    reason: Reason
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Admitted:
    """An article that passed, paired with its cleaned text."""

    article: Article
    cleaned: Cleaned
    detected_language: str = ""


def _language_of(text: str) -> str:
    """Detect language, deterministically.

    `Article.language` comes from the source configuration — it is an assumption,
    not a measurement. This measures it. langdetect is seeded because it is
    otherwise non-deterministic between runs, which would break ground rule 8.
    """
    try:
        from langdetect import DetectorFactory, LangDetectException, detect
    except ImportError:
        return ""

    DetectorFactory.seed = 0
    try:
        return detect(text)
    except LangDetectException:
        return ""


def judge(
    article: Article,
    cleaned: Cleaned,
    *,
    now: datetime | None = None,
    seen_hashes: set[str] | None = None,
    check_language: bool = True,
) -> Rejection | Admitted:
    """Apply every filter in a fixed order. Returns exactly one outcome."""
    now = now or datetime.now(timezone.utc)

    if not cleaned.text.strip():
        return Rejection(article.id, article.source_id, Reason.EMPTY_TEXT)

    # Content-type verdicts come before length. A paywall stub or a scorecard is
    # not "too short" — it is the wrong kind of document, and the funnel figure is
    # only useful if the reason code says which. Removed lines are searched too,
    # because the trailer rule strips "Subscribe to read..." during cleansing.
    haystack = "\n".join([article.title, cleaned.text, *cleaned.removed_lines])
    if SPONSORED.search(haystack):
        return Rejection(article.id, article.source_id, Reason.SPONSORED)
    if PAYWALL.search(haystack):
        return Rejection(article.id, article.source_id, Reason.PAYWALL)
    if NON_ARTICLE.search(haystack) or LISTICLE.search(article.title):
        return Rejection(article.id, article.source_id, Reason.NON_ARTICLE_FORMAT)
    if SERVICE_BULLETIN.search(article.title):
        return Rejection(article.id, article.source_id, Reason.SERVICE_BULLETIN)

    if len(article.title.split()) < MIN_TITLE_WORDS:
        return Rejection(article.id, article.source_id, Reason.TOO_SHORT, f"title={len(article.title.split())}w")

    if cleaned.word_count < MIN_WORDS:
        return Rejection(article.id, article.source_id, Reason.TOO_SHORT, f"{cleaned.word_count}w")

    # Only articles that are otherwise admissible claim a hash, so a rejected
    # article never suppresses the good copy of the same story.
    if seen_hashes is not None and article.content_hash:
        if article.content_hash in seen_hashes:
            return Rejection(article.id, article.source_id, Reason.EXACT_DUPLICATE, article.content_hash[:12])
        seen_hashes.add(article.content_hash)

    published = article.published_at
    if published > now + MAX_FUTURE_SKEW:
        return Rejection(article.id, article.source_id, Reason.FUTURE_TIMESTAMP, published.isoformat())
    if published < now - MAX_AGE:
        return Rejection(article.id, article.source_id, Reason.IMPLAUSIBLE_TIMESTAMP, published.isoformat())

    detected = _language_of(cleaned.text) if check_language else ""
    if check_language and detected and article.language and not detected.startswith(article.language[:2]):
        return Rejection(
            article.id,
            article.source_id,
            Reason.LANGUAGE_MISMATCH,
            f"declared={article.language} detected={detected}",
        )

    return Admitted(article=article, cleaned=cleaned, detected_language=detected)


def partition(
    pairs: list[tuple[Article, Cleaned]],
    *,
    now: datetime | None = None,
    check_language: bool = True,
) -> tuple[list[Admitted], list[Rejection]]:
    """Split a corpus into accepted and rejected, and prove nothing went missing."""
    seen_hashes: set[str] = set()
    admitted: list[Admitted] = []
    rejected: list[Rejection] = []

    for article, cleaned in pairs:
        outcome = judge(article, cleaned, now=now, seen_hashes=seen_hashes, check_language=check_language)
        if isinstance(outcome, Rejection):
            rejected.append(outcome)
        else:
            admitted.append(outcome)

    # The acceptance criterion, enforced rather than described.
    if len(admitted) + len(rejected) != len(pairs):
        raise AssertionError(f"rejection log does not balance: {len(admitted)}+{len(rejected)} != {len(pairs)}")
    return admitted, rejected
