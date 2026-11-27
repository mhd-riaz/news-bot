"""Serves the React build (frontend/dist): index.html for the app routes, hashed files under /assets/."""

from __future__ import annotations

from pathlib import Path

from flask import Response, send_from_directory
from werkzeug.exceptions import NotFound

ASSET_MAX_AGE = 365 * 24 * 3600


class Frontend:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def built(self) -> bool:
        return (self.directory / "index.html").is_file()

    def index(self) -> Response:
        response = send_from_directory(self.directory, "index.html", max_age=0)
        # Revalidate every time so a new build is picked up; hashed assets are cached for a year.
        response.headers["Cache-Control"] = "no-cache"
        return response

    def asset(self, name: str) -> Response:
        response = send_from_directory(self.directory / "assets", name, max_age=ASSET_MAX_AGE)
        response.headers["Cache-Control"] = f"public, max-age={ASSET_MAX_AGE}, immutable"
        return response

    def root_file(self, name: str) -> Response:
        """Top-level files Vite copies from public/ (for example favicon.svg)."""
        if name == "index.html" or name.startswith("."):
            raise NotFound()
        response = send_from_directory(self.directory, name, max_age=3600)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response
