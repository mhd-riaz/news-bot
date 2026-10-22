"""Normalise text and strip the furniture publishers wrap around it.

Two things make this different from v1's cleaner, which only ever saw headlines:

* Title, summary and body are cleaned **separately**. A body carries navigation,
  bylines, promos and author bios that a headline never does, and collapsing them into
  one string first makes them impossible to treat differently.
* Removal is **line-based**, because body furniture arrives as whole lines. Measured on
  400 sampled bodies: `Story continues below this ad` in 75% of Indian Express bodies,
  `- Ends` / `Published On:` in 62% of India Today, `Who's behind this story?` in 86%
  of Phys.org.

Why bother: those phrases are near-perfect predictors of *which publisher* wrote the
article, and publishers skew toward particular classes. Left in, they become a
publisher-to-class shortcut that scores well on validation and collapses on a masthead
the model has never seen.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# NFKC leaves curly quotes and en/em dashes alone, so two copies of the same wire story
# can differ by nothing but punctuation and still miss each other in near-duplicate
# detection. This fold is what makes them compare equal.
_PUNCTUATION_FOLD = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
        "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ",
        "\u2026": "...", "\u00ad": "",
    }
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# Indian and international wire services. Kept as a field rather than deleted outright:
# "(With inputs from PTI)" says nothing about the topic, but which agency filed a story
# is worth recording for the leakage audit.
WIRE_AGENCIES = (
    "PTI", "ANI", "IANS", "Reuters", "AFP", "AP", "Bloomberg", "TNN", "UNI", "DPA",
)
_WIRE_LINE = re.compile(
    r"^\s*\(?\s*with\s+(?:inputs|input|agency\s+inputs)\s+from\s+[^)\n]{0,60}\)?\s*$",
    re.IGNORECASE,
)
_WIRE_TRAILER = re.compile(
    rf"^\s*[-\u2014(]?\s*(?:{'|'.join(WIRE_AGENCIES)})\s*\)?\s*$", re.IGNORECASE
)

# "NEW DELHI: " or "VIJAYAWADA, Aug 24 (PTI) -- " opening a body. The city is a place,
# and places are exactly the shortcut Phase D0 exists to remove, so it comes out of the
# text and goes into a field.
_DATELINE = re.compile(
    r"^\s*(?P<city>[A-Z][A-Z .'\u2019-]{2,30})"
    r"(?:\s*,\s*(?P<date>[A-Z][a-z]{2,8}\.?\s+\d{1,2}))?"
    r"(?:\s*\(\s*(?P<agency>[A-Za-z]{2,12})\s*\))?"
    r"\s*[:\u2014-]\s+"
)

# Whole lines that are site chrome. Anchored, so a sentence that merely mentions one of
# these phrases inside real prose is left alone.
_FURNITURE_LINES = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^story continues below( this)? ad\.?$",
        r"^advertisement$",
        r"^ad(vertisement)?s?\s*[:\u2014-]?\s*$",
        r"^(also|must|do)\s+read\s*[:\u2014-]?\s*$",
        r"^read more\s*[:\u2014-]?\s*$",
        r"^related (stories|news|articles)\s*[:\u2014-]?\s*$",
        r"^more from [\w\s]{0,40}$",
        r"^tags?\s*[:\u2014-]?\s*$",
        r"^(topics|keywords)\s*[:\u2014-]?\s*$",
        r"^about the author$",
        r"^(who'?s behind this story\??|publication details|more information)$",
        r"^(published|updated) (on|by|at)\s*[:\u2014-]?\s*$",
        r"^\d+\s*min(ute)?s?\s+read$",
        r"^-+\s*ends?\s*-*$",
        r"^\u00a9.*$",
        r"^all rights reserved\.?$",
        r"^(skip past |after )?newsletter promotion$",
        r"^sign up (to|for) .{0,60}$",
        r"^subscribe (to|now|for) .{0,60}$",
        r"^follow us on .{0,40}$",
        r"^(share|tweet|whatsapp|telegram)( this)?( (story|article))?$",
        r"^click here to .{0,60}$",
        r"^download the .{0,30}app.{0,20}$",
        r"^(image|photo|picture) (caption|credit)\s*[:,\u2014-]?\s*$",
        r"^(watch|listen)\s*[:\u2014-]?\s*$",
        r"^see (more|less)$",
        r"^stay updated with .{0,60}$",
        r"^check out more of our .{0,40}$",
        r"^prefer \w+ ?on \w+$",
        r"^comments?$",
        r"^trending( now| topics)?$",
        r"^summary$",
    )
)


@dataclass(frozen=True, slots=True)
class Cleaned:
    text: str
    dateline_city: str = ""
    wire_agency: str = ""
    removed_lines: tuple[str, ...] = ()

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def __bool__(self) -> bool:
        return bool(self.text)


# A scraped "body" that is really a navigation menu or video carousel: many lines, almost
# all of them a word or two. Measured at 25 of 13,133 bodies (0.19%), nearly all BBC, so
# this stays a blunt one-line rule rather than a rejection reason with its own machinery.
# Per-source boilerplate cannot catch them -- every carousel lists different video titles.
_NAV_MIN_LINES = 10
_NAV_SHORT_WORDS = 6
_NAV_SHORT_SHARE = 0.8


def is_navigation(text: str) -> bool:
    lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
    if len(lines) < _NAV_MIN_LINES:
        return False
    short = sum(len(ln.split()) <= _NAV_SHORT_WORDS for ln in lines)
    return short / len(lines) > _NAV_SHORT_SHARE



def normalise(text: str) -> str:
    """Unicode, punctuation and whitespace only. No content is removed."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_FOLD)
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _SPACES.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", "\n".join(line.strip() for line in text.split("\n"))).strip()


def _is_furniture(line: str, extra: frozenset[str]) -> bool:
    if line.casefold() in extra:
        return True
    return any(p.match(line) for p in _FURNITURE_LINES)


# Several scrapers emit a whole body as one line, hiding a shared phrase inside it that
# line-level matching can never see. Long lines are therefore also checked sentence by
# sentence, and rejoined so the body keeps its original shape.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_LONG_LINE_WORDS = 25


def _strip_within_line(line: str, extra: frozenset[str]) -> str:
    if not extra or len(line.split()) <= _LONG_LINE_WORDS:
        return line
    parts = [s.strip() for s in _SENTENCE.split(line) if s.strip()]
    if len(parts) < 2:
        return line
    kept = [s for s in parts if not _is_furniture(s, extra)]
    return " ".join(kept) if kept else ""



def clean(
    text: str,
    *,
    boilerplate: frozenset[str] | None = None,
    dateline: bool = False,
    prefix: str = "",
    suffix: str = "",
) -> Cleaned:
    """Normalise, then drop furniture lines and any per-source boilerplate.

    `boilerplate` is the per-source line set discovered by `boilerplate.discover` --
    case-folded exact lines, because a phrase generic enough to hardcode is already in
    `_FURNITURE_LINES` and anything else is specific to one masthead.

    `prefix`/`suffix` strip chrome that is concatenated on without punctuation, which
    neither line nor sentence splitting can reach.

    `dateline` is only meaningful for a body; a headline never carries one.
    """
    extra = boilerplate or frozenset()
    kept: list[str] = []
    removed: list[str] = []
    agency = ""

    source = normalise(text)
    if prefix and source.startswith(prefix):
        removed.append(prefix)
        source = source[len(prefix):].lstrip()
    if suffix and source.endswith(suffix):
        removed.append(suffix)
        source = source[: -len(suffix)].rstrip()

    for line in source.split("\n"):
        if not line:
            kept.append(line)
            continue
        if _WIRE_LINE.match(line) or _WIRE_TRAILER.match(line):
            removed.append(line)
            for name in WIRE_AGENCIES:
                if re.search(rf"\b{name}\b", line, re.IGNORECASE):
                    agency = agency or name
                    break
            continue
        if _is_furniture(line, extra):
            removed.append(line)
            continue
        trimmed = _strip_within_line(line, extra)
        if trimmed != line:
            removed.append(line)
        if trimmed:
            kept.append(trimmed)

    body = _BLANK_LINES.sub("\n\n", "\n".join(kept)).strip()

    city = ""
    if dateline and body:
        match = _DATELINE.match(body)
        if match:
            city = (match.group("city") or "").strip(" .-'")
            agency = agency or (match.group("agency") or "")
            body = body[match.end():].lstrip()

    return Cleaned(
        text=body,
        dateline_city=city,
        wire_agency=agency.upper(),
        removed_lines=tuple(removed),
    )


def clean_article(
    title: str,
    summary: str,
    body: str,
    *,
    boilerplate: frozenset[str] | None = None,
    prefix: str = "",
    suffix: str = "",
) -> tuple[Cleaned, Cleaned, Cleaned]:
    """Clean the three fields separately, which is the whole point of this module.

    Only the body gets dateline extraction, per-source boilerplate and affix removal; a
    headline carries none of them. A body that turns out to be a navigation menu is
    dropped rather than rejected -- the title and summary are still perfectly good, so
    the article simply falls back to the short text v1 always used.
    """
    cleaned_body = clean(body, boilerplate=boilerplate, dateline=True, prefix=prefix, suffix=suffix)
    if is_navigation(cleaned_body.text):
        cleaned_body = Cleaned(text="", removed_lines=(cleaned_body.text,))
    return clean(title), clean(summary), cleaned_body
