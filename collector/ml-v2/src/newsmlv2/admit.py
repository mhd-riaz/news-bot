"""Decide which articles are classifiable at all.

Rejection is not cleaning: these are documents that have no topic to predict, or whose
metadata says they cannot be trusted. A quiz, a photo gallery, a gold-rate table and a
weather bulletin all use ordinary news vocabulary while carrying no story.

**Every rule is a switch.** v1 hardcoded ten of these and nobody ever measured what any
of them cost -- one alone rejected 443 articles. `Policy` exists so Phase B can price
each rule by turning it off and re-scoring, instead of inheriting them on faith.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Iterable, Sequence

from .clean import Cleaned
from .load import Article


class Reason(StrEnum):
    EMPTY_TEXT = "empty_text"
    TOO_SHORT = "too_short"
    NON_ARTICLE_FORMAT = "non_article_format"
    SERVICE_BULLETIN = "service_bulletin"
    SPONSORED = "sponsored"
    NON_LATIN_SCRIPT = "non_latin_script"
    FUTURE_TIMESTAMP = "future_timestamp"
    IMPLAUSIBLE_TIMESTAMP = "implausible_timestamp"
    EXACT_DUPLICATE = "exact_duplicate"


# Formats that are not a story: no single topic to predict, or no prose at all.
_NON_ARTICLE = re.compile(
    r"^(dh toon|dh speak out)\b"
    r"|\blive (blog|updates?|coverage|score(card)?s?)\b"
    r"|\b(daily )?quiz\b|\bcrossword\b|\bsudoku\b"
    r"|\bhoroscope\b|\brashifal\b|\btarot\b"
    r"|\bin (\d{1,3} )?pictures?\b|\bphoto ?(gallery|feature)\b|\bpics\b"
    r"|\bcartoon\b"
    r"|\btoday'?s (top )?(news )?headlines\b"
    r"|\bnews (headlines|roundup|wrap|bulletin) (for|of)\b",
    re.IGNORECASE,
)

# Recurring data tables published on a schedule. Two instalments are near-identical in
# wording and are NOT the same story, which is why they distort near-duplicate
# detection as well as training.
#
# Matched on the TITLE ONLY, and this is not a detail: a real flood story quotes the
# weather bulletin in its body, so matching the body would starve `disaster_accident`.
#
# `travel` must never appear here. In v1 it matched "J&K important part of India, US may
# re-evaluate travel advisory, says envoy" -- a diplomacy story.
_SERVICE_BULLETIN = re.compile(
    r"\bweather (forecast|update|report|bulletin)\b"
    r"|\b(orange|red|yellow) alert\b"
    r"|\btraffic (advisory|alert|restrictions?|diversions?)\b"
    r"|\b(gold|silver) (rate|price)s? (today|on)\b"
    r"|\b(petrol|diesel) price(s)? (today|on)\b"
    r"|\bcity weather\b|\bweather today\b"
    r"|\b(today'?s )?(market|stock) (wrap|closing bell)\b",
    re.IGNORECASE,
)

_SPONSORED = re.compile(
    r"\bsponsored (content|post|feature)\b"
    r"|\bbrand (post|connect|story)\b"
    r"|\bpartnered content\b|\bpaid (post|content)\b"
    r"|\b(coupon|promo) codes?\b"
    r"|\bbest deals? on\b|\bdiscount offers?\b",
    re.IGNORECASE,
)

_LATIN_RANGES = ("LATIN", "COMMON", "INHERITED")


@dataclass(frozen=True, slots=True)
class Policy:
    """Which gates run, and where their thresholds sit.

    Turning one off and re-scoring is how Phase B prices it.
    """

    min_words: int = 12
    min_title_words: int = 3
    reject_non_article: bool = True
    reject_service_bulletin: bool = True
    reject_sponsored: bool = True
    reject_exact_duplicates: bool = True
    # v1 rejected 443 articles on declared-vs-detected language alone and never checked
    # whether that helped, so this defaults OFF and Phase B decides.
    reject_non_latin: bool = False
    max_non_latin_share: float = 0.5
    max_future_hours: int = 6
    max_age_days: int = 365

    def as_dict(self) -> dict[str, object]:
        return {
            f: getattr(self, f) for f in self.__dataclass_fields__  # recorded in manifests
        }


@dataclass(frozen=True, slots=True)
class Admitted:
    article: Article
    title: Cleaned
    summary: Cleaned
    body: Cleaned

    @property
    def word_count(self) -> int:
        return self.title.word_count + self.summary.word_count + self.body.word_count


@dataclass(frozen=True, slots=True)
class Rejection:
    article_id: str
    source_name: str
    reason: Reason
    detail: str = ""


def non_latin_share(text: str) -> float:
    """Fraction of letters outside the Latin script.

    A deterministic script ratio, not a language model. `langdetect` samples randomly
    and needs a global seed to reproduce -- an odd thing to hang a frozen snapshot on,
    and it answers a question ("which language") we do not actually need.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    foreign = sum(
        not any(r in unicodedata.name(c, "") for r in _LATIN_RANGES) for c in letters
    )
    return foreign / len(letters)


def _timestamp_problem(article: Article, policy: Policy, now: datetime) -> Rejection | None:
    published = article.published_at
    if published is None:
        return None
    if published > now + timedelta(hours=policy.max_future_hours):
        return Rejection(article.id, article.source_name, Reason.FUTURE_TIMESTAMP, published.isoformat())
    if published < now - timedelta(days=policy.max_age_days):
        return Rejection(article.id, article.source_name, Reason.IMPLAUSIBLE_TIMESTAMP, published.isoformat())
    return None


def judge(
    admitted: Admitted,
    *,
    policy: Policy,
    now: datetime,
    seen_hashes: set[str] | None = None,
) -> Rejection | None:
    """The first reason this article cannot be classified, or None."""
    article = admitted.article
    title = admitted.title.text

    problem = _timestamp_problem(article, policy, now)
    if problem is not None:
        return problem

    if policy.reject_exact_duplicates and seen_hashes is not None and article.content_hash:
        if article.content_hash in seen_hashes:
            return Rejection(article.id, article.source_name, Reason.EXACT_DUPLICATE, article.content_hash[:12])
        seen_hashes.add(article.content_hash)

    if policy.reject_non_article and _NON_ARTICLE.search(title):
        return Rejection(article.id, article.source_name, Reason.NON_ARTICLE_FORMAT, title[:80])

    if policy.reject_service_bulletin and _SERVICE_BULLETIN.search(title):
        return Rejection(article.id, article.source_name, Reason.SERVICE_BULLETIN, title[:80])

    if policy.reject_sponsored and (_SPONSORED.search(title) or _SPONSORED.search(admitted.summary.text)):
        return Rejection(article.id, article.source_name, Reason.SPONSORED, title[:80])

    if not title and not admitted.summary.text and not admitted.body.text:
        return Rejection(article.id, article.source_name, Reason.EMPTY_TEXT)

    if admitted.title.word_count < policy.min_title_words:
        return Rejection(article.id, article.source_name, Reason.TOO_SHORT, f"title={admitted.title.word_count}w")

    if admitted.word_count < policy.min_words:
        return Rejection(article.id, article.source_name, Reason.TOO_SHORT, f"total={admitted.word_count}w")

    if policy.reject_non_latin:
        # Measured on the body alone. An English headline over a wholly Hindi body scores
        # 0.47 when the two are pooled -- under any sane threshold -- so pooling hides
        # exactly the case this gate exists to catch.
        target = admitted.body.text or f"{title} {admitted.summary.text}"
        share = non_latin_share(target)
        if share > policy.max_non_latin_share:
            return Rejection(article.id, article.source_name, Reason.NON_LATIN_SCRIPT, f"{share:.0%}")

    return None


def partition(
    candidates: Sequence[Admitted] | Iterable[Admitted],
    *,
    policy: Policy | None = None,
    now: datetime | None = None,
) -> tuple[list[Admitted], list[Rejection]]:
    """Split cleaned articles into those worth classifying and those that are not."""
    policy = policy or Policy()
    now = now or datetime.now(UTC)
    seen: set[str] = set()

    kept: list[Admitted] = []
    rejected: list[Rejection] = []
    for item in candidates:
        problem = judge(item, policy=policy, now=now, seen_hashes=seen)
        if problem is None:
            kept.append(item)
        else:
            rejected.append(problem)
    return kept, rejected


def without(policy: Policy, rule: str) -> Policy:
    """A copy of `policy` with one gate disabled, for pricing it in Phase B."""
    return replace(policy, **{rule: False})
