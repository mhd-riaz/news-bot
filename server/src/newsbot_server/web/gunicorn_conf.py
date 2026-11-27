"""gunicorn settings: `gunicorn --config python:newsbot_server.web.gunicorn_conf`.

The bind address comes from NEWS_SERVER_HOST and NEWS_SERVER_PORT. With sign-in off,
every listening socket must be a loopback address, or the server refuses to start;
in development, NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK=true allows other addresses with
one warning (see newsbot_server.web.startup).
"""

from __future__ import annotations

from newsbot_server.core import logs
from newsbot_server.core.settings import environment, load_web_settings
from newsbot_server.web.startup import check_listeners

_settings = load_web_settings(environment())
_host = f"[{_settings.host}]" if ":" in _settings.host else _settings.host

wsgi_app = "newsbot_server.web.wsgi:app"
bind = [f"{_host}:{_settings.port}"]
worker_class = "gthread"
workers = 2
threads = 4
timeout = 30
graceful_timeout = 15
keepalive = 5
accesslog = None  # the app writes one structured line per request
errorlog = "-"
loglevel = "warning"


def when_ready(server) -> None:  # noqa: ANN001 - gunicorn hook, runs once in the master process
    logs.configure(_settings.logging.level, _settings.logging.format)
    check_listeners(_settings, [listener.sock.getsockname() for listener in server.LISTENERS])
