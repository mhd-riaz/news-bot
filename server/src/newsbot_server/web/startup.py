"""Start-up checks shared by gunicorn (`when_ready`) and the development server.

With sign-in off, the web app may only listen on a loopback address. The one
exception is NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK=true, which settings accept only in
development: the app then listens beyond loopback (for example on 0.0.0.0 inside a
container) and logs one warning that the port must be published on 127.0.0.1 only.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..core.settings import WebSettings, is_loopback_host

log = logging.getLogger("newsbot.web")

PUBLISHED_LOOPBACK_WARNING = (
    "Sign-in is off and the web app listens beyond loopback because "
    "NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK=true (development only). Publish this port on "
    "127.0.0.1 only, for example \"127.0.0.1:8090:8090\" in Docker Compose: anyone who "
    "can reach it uses the app as the Local reader."
)


def _is_local(address: object) -> bool:
    if isinstance(address, tuple) and address:
        return is_loopback_host(str(address[0]))
    return isinstance(address, str)  # a Unix socket is local to the machine


def _describe(address: object) -> str:
    if isinstance(address, tuple) and len(address) >= 2:
        host = str(address[0])
        return f"[{host}]:{address[1]}" if ":" in host else f"{host}:{address[1]}"
    return str(address)


def check_listeners(settings: WebSettings, addresses: Iterable[object]) -> None:
    """Refuse sign-in off beyond loopback, unless the development flag allows it; then warn once."""
    if settings.auth_enabled:
        return
    exposed = [_describe(address) for address in addresses if not _is_local(address)]
    if not exposed:
        return
    if not settings.trust_published_loopback:
        raise RuntimeError("sign-in is off, so the server may only listen on a loopback address")
    log.warning(PUBLISHED_LOOPBACK_WARNING, extra={"fields": {
        "listen": ", ".join(exposed), "setting": "NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK",
    }})
