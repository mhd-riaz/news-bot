"""Cross-site request checks and security headers for the web app."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.settings import normalize_origin

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Same-origin scripts and styles only, no inline code; publisher images are hotlinked
# over https (never fetched by the server), and small build assets may be data: URLs.
PAGE_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' https: data:; "
    "font-src 'self'; connect-src 'self'; manifest-src 'self'; form-action 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)
API_POLICY = "default-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"


def is_cross_site(method: str, headers: Mapping[str, str], public_origin: str) -> bool:
    """C10: refuse a state-changing request unless the browser says it is same-origin.

    Sec-Fetch-Site is computed by the browser and cannot be set by a page, so it is
    trusted first: only same-origin or none (a user-typed navigation) pass. Without it,
    Origin must be this site's public URL. A request with neither signal is refused.
    """
    if method.upper() in SAFE_METHODS:
        return False
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site:
        return site not in ("same-origin", "none")
    origin = headers.get("Origin") or ""
    return not origin or normalize_origin(origin) != public_origin


def apply_headers(headers: Any, *, page: bool) -> None:
    """The headers the Go web package set, plus framing and opener isolation."""
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    headers["X-Frame-Options"] = "DENY"
    headers["Cross-Origin-Opener-Policy"] = "same-origin"
    headers["Content-Security-Policy"] = PAGE_POLICY if page else API_POLICY
