"""The bounded prepare → baseline → train → benchmark → serve workflow."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from . import data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsrec")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    for name in ("prepare", "baseline", "train", "benchmark", "measure", "score", "serve"):
        command = sub.add_parser(name)
        command.add_argument("--id", required=True)
        command.add_argument("--root", type=Path, default=data.ROOT)
        if name == "prepare":
            command.add_argument("--cut", type=datetime.fromisoformat, required=True)
            command.add_argument("--limit", type=int, default=20_000)
            command.add_argument("--candidates", type=int, default=30_000)
        elif name == "train":
            command.add_argument("--epochs", type=int, default=30)
        elif name == "benchmark":
            command.add_argument("--queries", type=int, default=40)
        elif name == "measure":
            command.add_argument("--api-url", default="http://127.0.0.1:8090")
        elif name == "score":
            command.add_argument("--judgements", type=Path, required=True)
            command.add_argument("--case", action="append", dest="case_ids")
            command.add_argument("--label-source", choices=("human", "ai-assisted"), default="human")
        elif name == "serve":
            command.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        print(json.dumps(data.inspect_database(), indent=2))
        return 0
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.id):
        parser.error("id must be a short filesystem-safe snapshot name")
    directory = args.root / args.id
    if args.command == "prepare":
        result = data.freeze(directory, cut=args.cut, limit=args.limit, candidates=args.candidates)
    elif args.command in ("baseline", "train"):
        from . import model

        result = model.baseline(directory) if args.command == "baseline" else model.train(
            directory, epochs=args.epochs
        )
    elif args.command in ("benchmark", "measure", "score"):
        from . import evaluate

        if args.command == "benchmark":
            result = evaluate.benchmark(directory, queries=args.queries)
        elif args.command == "measure":
            result = evaluate.api_latency(directory, api_url=args.api_url)
        else:
            result = evaluate.score(
                directory, args.judgements, case_ids=args.case_ids, label_source=args.label_source
            )
    else:
        from .api import create_app
        from .index import Index

        if not 1 <= args.port <= 65535:
            parser.error("port must be between 1 and 65535")
        create_app(Index(directory)).run(host="127.0.0.1", port=args.port, debug=False)
        return 0
    print(json.dumps(result, indent=2))
    return 0
