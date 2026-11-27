"""Input rules shared by the web routes and the MCP tools, ported from the Go domain package."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from .jsonutil import utf8_len

# Go: domain.DefaultListLimit, MaxListLimit, MaxRegionLength, MaxDomainLength.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
MAX_REGION_LENGTH = 100
MAX_DOMAIN_LENGTH = 64

# Go: recommendation.windows. Yesterday is computed per request by the ranker, not
# the persisted reader edition that C9 requires.
WINDOWS = frozenset({"", "fresh", "yesterday", "archive"})
METHODS = frozenset({"", "tfidf", "svd", "neural"})

_HEX = re.compile(r"[0-9A-Fa-f]{32}")
_DOMAIN_TAG = re.compile(r"[a-z0-9-]+")
_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})"
)


def valid_id(value: object) -> bool:
    """Accept what github.com/google/uuid.Parse accepts, as Go's domain.ValidateID does."""
    if not isinstance(value, str):
        return False
    if len(value) == 32:
        return bool(_HEX.fullmatch(value))
    if len(value) == 45:
        if value[:9].lower() != "urn:uuid:":
            return False
        value = value[9:]
    elif len(value) == 38:
        if value[0] != "{" or value[-1] != "}":
            return False
        value = value[1:-1]
    elif len(value) != 36:
        return False
    if value[8] != "-" or value[13] != "-" or value[18] != "-" or value[23] != "-":
        return False
    return bool(_HEX.fullmatch(value.replace("-", "")) and value.count("-") == 4)


def valid_domain_tag(tag: object) -> bool:
    """Go: domain.ValidDomainTag. Readers filter on the same tags sources carry."""
    if not isinstance(tag, str) or not tag or len(tag) > MAX_DOMAIN_LENGTH:
        return False
    if tag[0] == "-" or tag[-1] == "-":
        return False
    return bool(_DOMAIN_TAG.fullmatch(tag))


def two_letters(value: str) -> bool:
    """Go: isAlpha(s, 2): exactly two ASCII letters."""
    return len(value) == 2 and value.isascii() and value.isalpha()


def too_long(value: str, limit: int = MAX_REGION_LENGTH) -> bool:
    return utf8_len(value) > limit


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


class ValidationFailed(ValueError):
    """Every broken rule at once, sorted by field like Go's domain.ValidationError."""

    def __init__(self, fields: list[FieldError]) -> None:
        self.fields = sorted(fields, key=lambda item: item.field)
        super().__init__("; ".join(f"{item.field}: {item.message}" for item in self.fields))


class FieldErrors:
    def __init__(self) -> None:
        self._fields: list[FieldError] = []

    def add(self, field: str, message: str) -> None:
        self._fields.append(FieldError(field, message))

    def __bool__(self) -> bool:
        return bool(self._fields)

    def raise_if_any(self) -> None:
        if self._fields:
            raise ValidationFailed(self._fields)


def parse_rfc3339(raw: str) -> datetime | None:
    """Parse an RFC 3339 timestamp (Go's time.RFC3339 layout, fractional seconds allowed).

    Returns an aware datetime, or None when the text is not RFC 3339.
    """
    match = _RFC3339.fullmatch(raw)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.group(1, 2, 3, 4, 5, 6))
    fraction, zone = match.group(7), match.group(8)
    micros = int((fraction[1:] + "000000")[:6]) if fraction else 0
    if zone == "Z":
        tz = UTC
    else:
        hours, minutes = int(zone[1:3]), int(zone[4:6])
        if hours > 23 or minutes > 59:
            return None
        offset = timedelta(hours=hours, minutes=minutes)
        tz = timezone(-offset if zone[0] == "-" else offset)
    try:
        return datetime(year, month, day, hour, minute, second, micros, tzinfo=tz)
    except ValueError:
        return None


def parse_go_int(raw: str) -> int | None:
    """Go's strconv.Atoi: optional sign and ASCII digits only, within int64."""
    if not re.fullmatch(r"[+-]?[0-9]+", raw):
        return None
    value = int(raw)
    if not -(2**63) <= value < 2**63:
        return None
    return value
