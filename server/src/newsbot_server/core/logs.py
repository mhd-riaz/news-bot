"""One structured log line per event. Callers pass fields with extra={"fields": {...}}.

Header values, cookies, tokens, keys, URIs and article text are never passed here.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "warning": logging.WARNING, "error": logging.ERROR}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            line.update(fields)
        if record.exc_info and record.exc_info[0] is not None:
            line["error_type"] = record.exc_info[0].__name__
        return json.dumps(line, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", None)
        suffix = "".join(f" {key}={value}" for key, value in fields.items()) if isinstance(fields, dict) else ""
        return f"{datetime.fromtimestamp(record.created, UTC):%Y-%m-%dT%H:%M:%S}Z {record.levelname} {record.getMessage()}{suffix}"


def configure(level: str = "info", fmt: str = "json", stream=None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JSONFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(_LEVELS.get(level, logging.INFO))
    # The MongoDB driver logs at DEBUG with command details; keep it quiet.
    logging.getLogger("pymongo").setLevel(logging.WARNING)
