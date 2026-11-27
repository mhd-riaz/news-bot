"""JSON helpers that behave like the Go reader's encoding/json use.

Responses escape <, > and & (and U+2028/U+2029) the way Go's json.Marshal does, so
publisher text can never close a <script> block if a response is ever inlined.
Request and ranker bodies are parsed as exactly one JSON value, and the non-JSON
constants NaN and Infinity are rejected, which Python's json module accepts by default.
"""

from __future__ import annotations

import json
import re
from typing import Any

_HTML_ESCAPES = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"})
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_WHITESPACE = " \t\n\r"


class JSONBodyError(ValueError):
    """A body that is not exactly one JSON value. `reason` is empty, invalid or trailing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def dumps(value: Any) -> bytes:
    """Compact UTF-8 JSON, HTML-safe like Go's encoder."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # The characters escaped here can only appear inside JSON strings.
    text = text.translate(_HTML_ESCAPES)
    # Go replaces invalid UTF-16 surrogates with U+FFFD instead of failing.
    text = _LONE_SURROGATE.sub("\ufffd", text)
    return text.encode("utf-8")


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


_DECODER = json.JSONDecoder(parse_constant=_reject_constant)


def loads_one(data: bytes) -> Any:
    """Parse exactly one JSON value, allowing only surrounding whitespace."""
    text = data.decode("utf-8", errors="replace")
    start = len(text) - len(text.lstrip(_WHITESPACE))
    if start == len(text):
        raise JSONBodyError("empty")
    try:
        value, end = _DECODER.raw_decode(text, start)
    except (ValueError, RecursionError) as error:
        raise JSONBodyError("invalid") from error
    if text[end:].strip(_WHITESPACE):
        raise JSONBodyError("trailing")
    return value


def utf8_len(value: str) -> int:
    """Byte length as Go's len(string) counts it."""
    return len(value.encode("utf-8", errors="surrogatepass"))
