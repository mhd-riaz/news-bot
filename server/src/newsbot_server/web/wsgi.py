"""WSGI entry point for gunicorn: `newsbot_server.web.wsgi:app`."""

from __future__ import annotations

from ..core import logs
from ..core.settings import environment, load_web_settings
from .app import create_app

settings = load_web_settings(environment())
logs.configure(settings.logging.level, settings.logging.format)
app = create_app(settings)
