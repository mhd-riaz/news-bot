"""Google sign-in (OpenID Connect authorization code flow with PKCE) and session cookies (C10).

Endpoints are Google's published discovery values
(https://accounts.google.com/.well-known/openid-configuration). The ID token comes
straight from Google's token endpoint over verified HTTPS, authenticated with the
client secret, so its signature check may be skipped (OpenID Connect Core 1.0
§3.1.3.7 step 6; Google's "Obtain user information from the ID token"). Every claim
that matters (issuer, audience, expiry, nonce, verified email) is still checked.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from pymongo.errors import DuplicateKeyError

from ..core import jsonutil
from ..core.httpclient import Transport, http_transport
from ..core.readers import Reader, ReaderStore, normalize_email, utcnow

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"
CALLBACK_PATH = "/auth/google/callback"
LOGIN_PATH = "/auth/google/login"
SESSION_COOKIE = "__Host-newsbot_session"
FLOW_COOKIE = "__Host-newsbot_signin"
FLOW_SECONDS = 600
CLOCK_SKEW = 60


class SignInFailed(Exception):
    """Any sign-in failure other than an uninvited email. The message is for logs only."""


class NotInvited(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_pair() -> tuple[str, str]:
    """A 43-character verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(32)
    return verifier, _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def safe_next(value: str | None) -> str:
    """A same-site path to return to after sign-in; anything else becomes "/"."""
    if not value or len(value) > 2048 or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.path.startswith("/auth/"):
        return "/"
    return value


@dataclass(frozen=True)
class LoginFlow:
    state: str
    nonce: str
    verifier: str
    next: str
    expires: int

    @classmethod
    def start(cls, next_path: str, now: float | None = None) -> LoginFlow:
        verifier, _ = pkce_pair()
        return cls(
            state=secrets.token_urlsafe(24),
            nonce=secrets.token_urlsafe(24),
            verifier=verifier,
            next=safe_next(next_path),
            expires=int((now or time.time()) + FLOW_SECONDS),
        )

    @property
    def challenge(self) -> str:
        return _b64(hashlib.sha256(self.verifier.encode("ascii")).digest())


class FlowCookie:
    """The pending sign-in, kept in a short-lived HttpOnly cookie signed with a key derived from the client secret."""

    def __init__(self, client_secret: str) -> None:
        self._key = hmac.new(client_secret.encode("utf-8"), b"newsbot sign-in flow cookie v1", hashlib.sha256).digest()

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest())

    def encode(self, flow: LoginFlow) -> str:
        payload = _b64(json.dumps(asdict(flow), separators=(",", ":")).encode("utf-8"))
        return f"{payload}.{self._sign(payload)}"

    def decode(self, value: str | None, now: float | None = None) -> LoginFlow:
        if not value or len(value) > 4096 or value.count(".") != 1:
            raise SignInFailed("missing or malformed sign-in cookie")
        payload, signature = value.split(".")
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise SignInFailed("sign-in cookie signature mismatch")
        try:
            raw = json.loads(_unb64(payload))
            flow = LoginFlow(**{key: raw[key] for key in ("state", "nonce", "verifier", "next", "expires")})
        except (ValueError, KeyError, TypeError):
            raise SignInFailed("unreadable sign-in cookie") from None
        if not isinstance(flow.expires, int) or flow.expires < (now or time.time()):
            raise SignInFailed("sign-in took too long")
        return flow


class GoogleOIDC:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self._transport = transport or http_transport
        self._clock = clock

    def authorization_url(self, flow: LoginFlow) -> str:
        query = urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": flow.state,
            "nonce": flow.nonce,
            "code_challenge": flow.challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    def exchange(self, code: str, flow: LoginFlow) -> dict[str, Any]:
        """Redeem the code (with the PKCE verifier) and return the checked ID token claims."""
        if not code or len(code) > 2048:
            raise SignInFailed("missing authorization code")
        body = urlencode({
            "code": code,
            "client_id": self.client_id,
            "client_secret": self._secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": flow.verifier,
        }).encode("ascii")
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        try:
            status, data = self._transport("POST", TOKEN_ENDPOINT, headers, body, 10.0)
        except (OSError, ValueError) as error:
            raise SignInFailed(f"token endpoint unreachable: {type(error).__name__}") from None
        if status != 200:
            raise SignInFailed(f"token endpoint status {status}")
        try:
            token = jsonutil.loads_one(data)
            id_token = token["id_token"]
            _header, payload_b64, _signature = id_token.split(".")
            claims = json.loads(_unb64(payload_b64))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SignInFailed("unreadable token response") from None
        if not isinstance(claims, dict):
            raise SignInFailed("unreadable ID token")
        self.check_claims(claims, flow.nonce)
        return claims

    def check_claims(self, claims: Mapping[str, Any], nonce: str) -> None:
        now = self._clock()
        if claims.get("iss") not in ISSUERS:
            raise SignInFailed("wrong issuer")
        audience = claims.get("aud")
        if isinstance(audience, list):
            if self.client_id not in audience or claims.get("azp") != self.client_id:
                raise SignInFailed("wrong audience")
        elif audience != self.client_id:
            raise SignInFailed("wrong audience")
        if "azp" in claims and claims.get("azp") != self.client_id:
            raise SignInFailed("wrong authorized party")
        expires, issued = claims.get("exp"), claims.get("iat")
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or now >= expires + CLOCK_SKEW:
            raise SignInFailed("expired ID token")
        if isinstance(issued, (int, float)) and not isinstance(issued, bool) and issued > now + 5 * CLOCK_SKEW:
            raise SignInFailed("ID token issued in the future")
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise SignInFailed("nonce mismatch")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not 0 < len(subject) <= 255 or not subject.isascii():
            raise SignInFailed("missing subject")
        if claims.get("email_verified") not in (True, "true"):
            raise SignInFailed("email not verified")
        if not isinstance(claims.get("email"), str):
            raise SignInFailed("missing email")


def admit(readers: ReaderStore, claims: Mapping[str, Any]) -> Reader:
    """Only invited readers sign in. The first sign-in binds the Google account (`sub`) to the invite."""
    subject = claims["sub"]
    try:
        email = normalize_email(claims["email"])
    except ValueError:
        raise SignInFailed("unusable email") from None
    reader = readers.by_google_sub(subject)
    if reader is None:
        invite = readers.by_email(email)
        if invite is None or not invite.invited:
            raise NotInvited(email)
        if invite.google_bound:
            raise SignInFailed("invite is bound to another Google account")
        try:
            bound = readers.bind_google_sub(invite.id, subject)
        except DuplicateKeyError:
            raise SignInFailed("Google account already bound") from None
        reader = readers.get(invite.id) if bound else readers.by_google_sub(subject)
        if reader is None:
            raise SignInFailed("could not bind the Google account")
    if not reader.invited:
        raise NotInvited(reader.email)
    name = claims.get("name") if isinstance(claims.get("name"), str) else ""
    readers.record_login(reader.id, utcnow(), name)
    return reader
