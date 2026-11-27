"""Settings from the environment, with the collector's NEWS_ naming.

Values come from the process environment, then from a dotenv file
(NEWS_ENV_FILE, or deployment/env/local.env when running from a checkout).
The process environment always wins, as with the Go services. Secret values are
never logged and never appear in a settings repr.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PREFIX = "NEWS_"
_ROOT = Path(__file__).resolve().parents[4]
_DURATION_PART = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)")
_DURATION_UNITS = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "μs": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}
_KEY_ENTRY = re.compile(r"[A-Za-z0-9_.-]{1,64}:[0-9a-f]{64}")


class SettingsError(ValueError):
    """Every invalid or missing setting at once. Messages name keys, never values."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid settings: " + "; ".join(problems))


def checkout_root() -> Path | None:
    """The repository root when this package runs from a source checkout."""
    if (_ROOT / "server" / "pyproject.toml").is_file() and (_ROOT / "deployment").is_dir():
        return _ROOT
    return None


def env_file_path(environ: Mapping[str, str] | None = None) -> Path | None:
    environ = os.environ if environ is None else environ
    if environ.get(PREFIX + "ENV_FILE", "").strip():
        return Path(environ[PREFIX + "ENV_FILE"].strip())
    root = checkout_root()
    return root / "deployment" / "env" / "local.env" if root else None


def read_env_file(path: Path | None) -> dict[str, str]:
    """KEY=VALUE pairs from a dotenv file. A missing file is not an error."""
    if path is None or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            inner = value[1:-1]
            if value[0] == '"':
                inner = inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
            value = inner
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The process environment layered over the dotenv file."""
    environ = os.environ if environ is None else environ
    return {**read_env_file(env_file_path(environ)), **environ}


def parse_duration(text: str) -> float:
    """Seconds from a Go duration string such as 15s, 1h30m or 168h."""
    text = text.strip()
    if text in ("0", "+0", "-0"):
        return 0.0
    sign = -1.0 if text.startswith("-") else 1.0
    body = text.lstrip("+-")
    if not body:
        raise ValueError("empty duration")
    total, position = 0.0, 0
    for match in _DURATION_PART.finditer(body):
        if match.start() != position:
            raise ValueError("invalid duration")
        total += float(match.group(1)) * _DURATION_UNITS[match.group(2)]
        position = match.end()
    if position != len(body) or position == 0:
        raise ValueError("invalid duration")
    return sign * total


def parse_bool(text: str) -> bool:
    """Go's strconv.ParseBool."""
    if text in ("1", "t", "T", "TRUE", "true", "True"):
        return True
    if text in ("0", "f", "F", "FALSE", "false", "False"):
        return False
    raise ValueError("invalid boolean")


def is_loopback_host(host: str) -> bool:
    host = host.strip().strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _Reader:
    """Reads NEWS_ keys, collecting every problem instead of stopping at the first."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = values
        self.problems: list[str] = []

    def raw(self, key: str) -> str:
        return self.values.get(PREFIX + key, "").strip()

    def text(self, key: str, default: str = "") -> str:
        return self.raw(key) or default

    def integer(self, key: str, default: int, minimum: int, maximum: int) -> int:
        raw = self.raw(key)
        if not raw:
            return default
        if not re.fullmatch(r"[+-]?[0-9]+", raw) or not minimum <= int(raw) <= maximum:
            self.problems.append(f"{PREFIX}{key} must be an integer from {minimum} to {maximum}")
            return default
        return int(raw)

    def boolean(self, key: str, default: bool) -> bool:
        raw = self.raw(key)
        if not raw:
            return default
        try:
            return parse_bool(raw)
        except ValueError:
            self.problems.append(f"{PREFIX}{key} must be true or false")
            return default

    def duration(self, key: str, default: float, positive: bool = True) -> float:
        raw = self.raw(key)
        if not raw:
            return default
        try:
            value = parse_duration(raw)
        except ValueError:
            self.problems.append(f"{PREFIX}{key} must be a duration such as 15s or 168h")
            return default
        if positive and value <= 0:
            self.problems.append(f"{PREFIX}{key} must be greater than zero")
            return default
        return value

    def one_of(self, key: str, default: str, allowed: tuple[str, ...]) -> str:
        value = self.text(key, default)
        if value not in allowed:
            self.problems.append(f"{PREFIX}{key} must be one of {', '.join(allowed)}")
            return default
        return value


@dataclass(frozen=True)
class MongoSettings:
    uri: str = field(repr=False)
    database: str
    app_name: str
    connect_timeout: float = 10.0
    server_selection_timeout: float = 10.0
    operation_timeout: float = 30.0
    max_pool_size: int = 50
    min_pool_size: int = 0
    max_idle_time: float = 60.0


@dataclass(frozen=True)
class RankerSettings:
    endpoint: str
    api_key: str = field(default="", repr=False)


@dataclass(frozen=True)
class LogSettings:
    level: str = "info"
    format: str = "json"


@dataclass(frozen=True)
class WebSettings:
    environment: str
    host: str
    port: int
    public_url: str
    auth_enabled: bool
    google_client_id: str
    google_client_secret: str = field(repr=False)
    session_idle_timeout: float
    session_absolute_timeout: float
    static_dir: Path
    mongo: MongoSettings
    ranker: RankerSettings
    logging: LogSettings
    # Development only: sign-in may be off while listening beyond loopback, because the
    # operator promises the port is published on 127.0.0.1 only (for example by Docker).
    trust_published_loopback: bool = False

    @property
    def public_origin(self) -> str:
        return normalize_origin(self.public_url) or ""


@dataclass(frozen=True)
class AgentKey:
    name: str
    digest: str = field(repr=False)


@dataclass(frozen=True)
class McpSettings:
    environment: str
    host: str
    port: int
    agent_keys: tuple[AgentKey, ...] = field(repr=False)
    rate_limit_per_minute: int
    allowed_hosts: tuple[str, ...]
    mongo: MongoSettings
    ranker: RankerSettings
    logging: LogSettings


def normalize_origin(value: str) -> str | None:
    """scheme://host[:port] in lower case, without a default port; None if not an origin."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is None or (parts.scheme, port) in (("http", 80), ("https", 443)):
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def _mongo(reader: _Reader, uri_key: str, app_name: str, default_uri: str | None) -> MongoSettings:
    uri = reader.raw(uri_key) or (default_uri or "")
    if not uri:
        reader.problems.append(f"{PREFIX}{uri_key} must be set")
    elif not uri.startswith(("mongodb://", "mongodb+srv://")):
        reader.problems.append(f"{PREFIX}{uri_key} must be a mongodb:// or mongodb+srv:// URI")
    database = reader.text("MONGO_DATABASE", "news")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database):
        reader.problems.append(f"{PREFIX}MONGO_DATABASE must contain only letters, numbers, _ or -")
    return MongoSettings(
        uri=uri,
        database=database,
        app_name=app_name,
        connect_timeout=reader.duration("MONGO_CONNECT_TIMEOUT", 10.0),
        server_selection_timeout=reader.duration("MONGO_SERVER_SELECTION_TIMEOUT", 10.0),
        operation_timeout=reader.duration("MONGO_OPERATION_TIMEOUT", 30.0),
        max_pool_size=reader.integer("MONGO_MAX_POOL_SIZE", 50, 1, 1000),
        min_pool_size=reader.integer("MONGO_MIN_POOL_SIZE", 0, 0, 1000),
        max_idle_time=reader.duration("MONGO_MAX_CONNECTION_IDLE_TIME", 60.0),
    )


def _ranker(reader: _Reader) -> RankerSettings:
    return RankerSettings(
        endpoint=reader.text("RECOMMENDER_ENDPOINT", "http://127.0.0.1:8001"),
        api_key=reader.raw("RECOMMENDER_API_KEY"),
    )


def _logging(reader: _Reader) -> LogSettings:
    return LogSettings(
        level=reader.one_of("LOGGING_LEVEL", "info", ("debug", "info", "warn", "warning", "error")),
        format=reader.one_of("LOGGING_FORMAT", "json", ("json", "text")),
    )


def _public_url_problem(url: str, environment_name: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "must be an absolute http(s) URL"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "must be an absolute http(s) URL"
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        return "must be only a scheme, host and optional port"
    if port == 0:
        return "must not use port 0"
    if parts.scheme == "http" and (environment_name == "production" or not is_loopback_host(parts.hostname)):
        return "must use https unless it is a loopback address outside production"
    return None


def load_web_settings(values: Mapping[str, str]) -> WebSettings:
    """Web settings from an already merged mapping; see `environment()`."""
    reader = _Reader(values)
    environment_name = reader.one_of("APP_ENVIRONMENT", "development", ("development", "staging", "production"))
    host = reader.text("SERVER_HOST", "127.0.0.1")
    port = reader.integer("SERVER_PORT", 8090, 1, 65535)
    auth_enabled = reader.boolean("AUTH_ENABLED", True)
    trust_published_loopback = reader.boolean("AUTH_TRUST_PUBLISHED_LOOPBACK", False)
    if trust_published_loopback and environment_name != "development":
        reader.problems.append(
            f"{PREFIX}AUTH_TRUST_PUBLISHED_LOOPBACK=true is allowed only when {PREFIX}APP_ENVIRONMENT=development"
        )
    client_id = reader.raw("GOOGLE_CLIENT_ID")
    client_secret = reader.raw("GOOGLE_CLIENT_SECRET")
    public_url = reader.raw("PUBLIC_URL")
    if auth_enabled:
        if not client_id:
            reader.problems.append(f"{PREFIX}GOOGLE_CLIENT_ID must be set when sign-in is on")
        if not client_secret:
            reader.problems.append(f"{PREFIX}GOOGLE_CLIENT_SECRET must be set when sign-in is on")
        if not public_url:
            reader.problems.append(f"{PREFIX}PUBLIC_URL must be set when sign-in is on")
    else:
        if environment_name == "production":
            reader.problems.append(f"{PREFIX}AUTH_ENABLED=false is not allowed in production")
        if not is_loopback_host(host) and not trust_published_loopback:
            reader.problems.append(
                f"{PREFIX}AUTH_ENABLED=false needs {PREFIX}SERVER_HOST on a loopback address, or "
                f"{PREFIX}AUTH_TRUST_PUBLISHED_LOOPBACK=true in development with the port published on 127.0.0.1 only"
            )
        if not public_url:
            # Behind a port published on 127.0.0.1, the browser reaches the app there.
            local = host if is_loopback_host(host) else "127.0.0.1"
            public_url = f"http://{'[' + local + ']' if ':' in local else local}:{port}"
    if public_url:
        problem = _public_url_problem(public_url, environment_name)
        if problem:
            reader.problems.append(f"{PREFIX}PUBLIC_URL {problem}")
        public_url = public_url.rstrip("/")
    idle = reader.duration("SESSION_IDLE_TIMEOUT", 7 * 24 * 3600.0)
    absolute = reader.duration("SESSION_ABSOLUTE_TIMEOUT", 30 * 24 * 3600.0)
    if idle > absolute:
        reader.problems.append(f"{PREFIX}SESSION_IDLE_TIMEOUT must not be longer than {PREFIX}SESSION_ABSOLUTE_TIMEOUT")
    root = checkout_root()
    default_static = root / "frontend" / "dist" if root else Path("/app/static")
    static_dir = Path(reader.text("STATIC_DIR", str(default_static)))
    settings = WebSettings(
        environment=environment_name,
        host=host,
        port=port,
        public_url=public_url,
        auth_enabled=auth_enabled,
        google_client_id=client_id,
        google_client_secret=client_secret,
        session_idle_timeout=idle,
        session_absolute_timeout=absolute,
        static_dir=static_dir,
        mongo=_mongo(reader, "MONGO_URI", "news-server", "mongodb://localhost:27017"),
        ranker=_ranker(reader),
        logging=_logging(reader),
        trust_published_loopback=trust_published_loopback,
    )
    if reader.problems:
        raise SettingsError(reader.problems)
    return settings


def parse_agent_keys(raw: str) -> tuple[AgentKey, ...]:
    """`name:sha256hex` pairs, comma-separated (C11, D9). Raises ValueError without echoing input."""
    keys: list[AgentKey] = []
    names: set[str] = set()
    for position, entry in enumerate(part.strip() for part in raw.split(",")):
        if not entry:
            continue
        name, _, digest = entry.partition(":")
        digest = digest.strip().lower()
        name = name.strip()
        if not _KEY_ENTRY.fullmatch(f"{name}:{digest}"):
            raise ValueError(f"entry {position + 1} must be name:<64 hex characters of sha256(key)>")
        if name in names:
            raise ValueError(f"entry {position + 1} repeats an agent name")
        names.add(name)
        keys.append(AgentKey(name=name, digest=digest))
    return tuple(keys)


def load_mcp_settings(values: Mapping[str, str], *, require_keys: bool = True) -> McpSettings:
    """MCP settings from an already merged mapping; see `environment()`."""
    reader = _Reader(values)
    environment_name = reader.one_of("APP_ENVIRONMENT", "development", ("development", "staging", "production"))
    host = reader.text("MCP_HOST", "127.0.0.1")
    port = reader.integer("MCP_PORT", 8091, 1, 65535)
    keys: tuple[AgentKey, ...] = ()
    try:
        keys = parse_agent_keys(reader.raw("MCP_API_KEYS"))
    except ValueError as error:
        reader.problems.append(f"{PREFIX}MCP_API_KEYS {error}")
    if require_keys and not keys:
        reader.problems.append(f"{PREFIX}MCP_API_KEYS must list at least one name:sha256 pair for the HTTP transport")
    hosts_raw = reader.raw("MCP_ALLOWED_HOSTS")
    if hosts_raw:
        allowed = tuple(part.strip() for part in hosts_raw.split(",") if part.strip())
    else:
        allowed = (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")
    settings = McpSettings(
        environment=environment_name,
        host=host,
        port=port,
        agent_keys=keys,
        rate_limit_per_minute=reader.integer("MCP_RATE_LIMIT", 60, 1, 6000),
        allowed_hosts=allowed,
        mongo=_mongo(reader, "MCP_MONGO_URI", "news-mcp", None),
        ranker=_ranker(reader),
        logging=_logging(reader),
    )
    if reader.problems:
        raise SettingsError(reader.problems)
    return settings


def load_owner_mongo_settings(values: Mapping[str, str]) -> MongoSettings:
    """The owner's login for `newsbot-server readers`: NEWS_OWNER_MONGO_URI, else NEWS_MONGO_URI."""
    reader = _Reader(values)
    key = "OWNER_MONGO_URI" if reader.raw("OWNER_MONGO_URI") else "MONGO_URI"
    settings = _mongo(reader, key, "news-owner", "mongodb://localhost:27017")
    if reader.problems:
        raise SettingsError(reader.problems)
    return settings
