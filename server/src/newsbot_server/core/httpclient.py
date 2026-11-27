"""A small HTTP client on the standard library, used for the ranker and Google's token endpoint."""

from __future__ import annotations

import http.client
import ssl
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 1 << 20

# (method, url, headers, body, timeout seconds) -> (status, body of a 200 response)
Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


def http_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    """One HTTP exchange with a total deadline, no redirects and a capped body.

    Like Go's http.Client with Timeout and CheckRedirect=ErrUseLastResponse: a 3xx is
    returned as is, and only a 200 body is read, to at most MAX_RESPONSE_BYTES + 1 bytes.
    HTTPS verifies certificates with the system trust store.
    """
    parts = urlsplit(url)
    deadline = time.monotonic() + timeout
    if parts.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parts.hostname or "", parts.port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=timeout)

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("HTTP exchange exceeded its deadline")
        if connection.sock is not None:
            connection.sock.settimeout(left)
        return left

    try:
        connection.request(method, parts.path or "/", body=body, headers=dict(headers))
        remaining()
        response = connection.getresponse()
        if response.status != 200:
            return response.status, b""
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_RESPONSE_BYTES:
            remaining()
            chunk = response.read1(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return response.status, b"".join(chunks)
    finally:
        connection.close()
