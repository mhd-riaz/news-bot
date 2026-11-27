"""`newsbot-server`: run the web app for development, or manage invited readers.

    newsbot-server                      serve on NEWS_SERVER_HOST:NEWS_SERVER_PORT (default 127.0.0.1:8090)
    newsbot-server readers invite EMAIL [--name NAME]
    newsbot-server readers revoke EMAIL
    newsbot-server readers list

Production runs the same app with gunicorn:
    gunicorn --config python:newsbot_server.web.gunicorn_conf
"""

from __future__ import annotations

import argparse
import sys

from .. import admin
from ..core import logs
from ..core.settings import SettingsError, environment, load_web_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsbot-server", description="AFTERLINE web app and owner commands.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the development server (the default)")
    admin.add_parser(commands)
    args = parser.parse_args(argv)
    values = environment()
    if args.command == "readers":
        return admin.run(args, values)
    try:
        settings = load_web_settings(values)
    except SettingsError as error:
        print(error, file=sys.stderr)
        return 2
    logs.configure(settings.logging.level, settings.logging.format)
    from .app import create_app
    from .startup import check_listeners

    try:
        check_listeners(settings, [(settings.host, settings.port)])
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2

    app = create_app(settings)
    print(
        f"AFTERLINE on http://{settings.host}:{settings.port} (sign-in {'on' if settings.auth_enabled else 'off'}). "
        "Development server: use gunicorn in production.",
        file=sys.stderr,
    )
    app.run(host=settings.host, port=settings.port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
