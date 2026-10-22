"""Deterministic, versioned cleansing: bronze text in, silver text out.

Two properties are load-bearing and are asserted by tests:

* **Deterministic** — the same input produces byte-identical output, always.
* **Non-destructive by default** — anything removed that carries meaning
  (dateline, wire agency, byline) is returned as a structured field rather than
  discarded, so a later phase can use it as a feature or as a leakage check.

Aggressive cleaning is worse than none: it removes real sentences, and the
damage stays invisible until a model has already trained on the result. Every
rule here is either anchored to a line boundary or to a specific marker.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --- Page furniture -------------------------------------------------------
# The floor: ported from internal/extract/text.go so Python and Go agree on what
# a clean article looks like. Phase 4's golden fixtures assert that agreement.
# Learned per-source boilerplate (boilerplate.py) sits on top of this.
FURNITURE = (
    re.compile(r"(?i)\bADVERTISEMENT\b"),
    re.compile(r"(?i)\bPublished\s*[-\u2013\u2014]\s*\w+\s+\d{1,2},\s*\d{4}[^.\n]*\b(?:IST|GMT|UTC|EST|EDT)\b"),
    re.compile(r"(?i)\|\s*Photo Credit:[^\n.]*"),
    re.compile(r"(?i)\bLast Updated\s*:[^\n]*\b(?:IST|GMT|UTC)\b"),
    re.compile(r"(?i)\bDownload the [A-Za-z0-9 ]{1,25} app\."),
    re.compile(r"(?i)\bFollow us on [A-Za-z ]{1,30}\b"),
    re.compile(r"(?i)\bGet the latest [^.\n]{1,80}\."),
)

# Cross-promotional interjections. Anchored to the start of a line, because
# "also read" occurs inside legitimate sentences.
CROSS_PROMO = re.compile(
    r"(?im)^\s*(?:also\s+read|read\s+more|watch|must\s+read|see\s+also|related\s+news|explained)\s*[:\u2013\u2014-].*$"
)

# Trailing calls to action and disclaimers, matched only in the last few lines.
TRAILER = re.compile(
    r"(?i)^\s*(?:"
    r"\(?with inputs? from[^)]*\)?"
    r"|disclaimer\s*[:\u2013\u2014-].*"
    r"|the views expressed .*"
    r"|this (?:article|story) (?:was|has been) .*"
    r"|subscribe to .*"
    r"|for (?:more|all the latest) .*"
    r"|click here to .*"
    r"|\(the story has been published from a syndicated feed\.?\)?"
    r")\s*$"
)

# Wire agencies that syndicate across Indian outlets. Detected, recorded, then
# removed — the agency is a real feature, but leaving "(PTI)" in the body lets a
# classifier learn the agency instead of the topic.
WIRE_AGENCIES = ("PTI", "ANI", "IANS", "Reuters", "AFP", "AP", "Bloomberg", "TNN")
_WIRE = re.compile(
    r"\(\s*(" + "|".join(WIRE_AGENCIES) + r")\s*\)|(?<![A-Za-z])(" + "|".join(WIRE_AGENCIES) + r")(?![A-Za-z])"
)

# A dateline opens the body with the city the report was filed from, e.g.
# "NEW DELHI: ..." or "Bengaluru, Aug 23 (PTI) -- ...". Both forms appear.
_DATELINE = re.compile(
    r"^\s*(?P<city>[A-Z][A-Za-z]*(?:[ \-][A-Z][A-Za-z]*){0,3})"
    r"(?:\s*,\s*(?P<date>[A-Z][a-z]{2}\.?\s+\d{1,2}))?"
    r"\s*(?:\(\s*(?P<agency>[A-Z]{2,9})\s*\))?"
    r"\s*[:\u2013\u2014-]{1,2}\s+"
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[^\S\n]+")
_BLANKS = re.compile(r"\n{2,}")

# NFKC deliberately leaves curly quotes and dashes alone, so fold them by hand.
# Two outlets running the same wire copy with different quote styles must produce
# identical shingles, or near-duplicate detection misses the pair.
_PUNCT_FOLD = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2026": "...",
})


@dataclass(frozen=True, slots=True)
class Cleaned:
    """Silver text plus everything that was pulled out of it on the way."""

    text: str
    dateline_city: str = ""
    wire_agency: str = ""
    removed_lines: tuple[str, ...] = field(default=())

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def normalise(s: str) -> str:
    """Unicode NFKC, punctuation folding, and control-character removal.

    NFKC folds the typographic variants that scraped text is full of —
    non-breaking spaces, ligatures, full-width digits — so that two articles
    differing only in encoding hash to the same shingles. It does not touch
    curly quotes or dashes, so `_PUNCT_FOLD` handles those separately.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).translate(_PUNCT_FOLD)
    return _CONTROL.sub("", s)


def collapse(s: str) -> str:
    """Runs of spaces become one; runs of blank lines become one."""
    s = _SPACES.sub(" ", s)
    s = _BLANKS.sub("\n", s)
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def line_key(line: str) -> str:
    """The form a line is compared in when detecting repeated boilerplate.

    Case, punctuation and digits are dropped so that "Updated: Aug 22, 2026" and
    "Updated: Aug 23, 2026" collapse to the same template line.
    """
    key = unicodedata.normalize("NFKC", line).casefold()
    key = re.sub(r"\d+", "#", key)
    key = re.sub(r"[^\w#]+", " ", key)
    return " ".join(key.split())


def _extract_dateline(text: str) -> tuple[str, str, str]:
    """Pull a leading dateline off the body. Returns (text, city, agency)."""
    m = _DATELINE.match(text)
    if not m:
        return text, "", ""
    city = (m.group("city") or "").strip()
    # A dateline city is short. A longer match is the opening of a sentence that
    # happens to start with capitalised words, and removing it would eat content.
    if not city or len(city.split()) > 4 or len(city) > 40:
        return text, "", ""
    return text[m.end() :], city, (m.group("agency") or "").strip()


def _extract_wire(text: str) -> tuple[str, str]:
    """Record the first wire agency mentioned, then strip every mention."""
    m = _WIRE.search(text)
    if not m:
        return text, ""
    agency = (m.group(1) or m.group(2) or "").strip()
    return _WIRE.sub(" ", text), agency


def clean(
    raw: str,
    *,
    boilerplate: frozenset[str] | None = None,
) -> Cleaned:
    """Apply every cleansing rule, in a fixed order, and report what was removed.

    `boilerplate` is the set of learned line keys for this article's source, as
    produced by boilerplate.py. Passing None applies the regex floor only.
    """
    text = normalise(raw)
    if not text.strip():
        return Cleaned(text="")

    for pattern in FURNITURE:
        text = pattern.sub(" ", text)
    text = CROSS_PROMO.sub("", text)

    removed: list[str] = []
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if boilerplate and line_key(stripped) in boilerplate:
            removed.append(stripped)
            continue
        if TRAILER.match(stripped):
            removed.append(stripped)
            continue
        kept.append(stripped)

    text = collapse("\n".join(kept))
    text, city, dateline_agency = _extract_dateline(text)
    text, wire_agency = _extract_wire(text)

    return Cleaned(
        text=collapse(text),
        dateline_city=city,
        wire_agency=wire_agency or dateline_agency,
        removed_lines=tuple(removed),
    )
