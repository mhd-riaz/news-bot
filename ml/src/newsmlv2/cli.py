"""Command line for newsmlv2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, labels as labels_mod, snapshot as snapshot_mod
from .pipeline import prepare_corpus


def _snapshot(args: argparse.Namespace) -> int:
    taxonomy = labels_mod.read_taxonomy()
    gold = labels_mod.read_gold()
    print(f"corpus cut {config.COLLECTED_BEFORE} | labels {len(gold)}")

    prepared = prepare_corpus(limit=args.limit)
    print(f"prepared: {prepared.counts}")

    snap = snapshot_mod.build(
        prepared, gold, taxonomy,
        snapshot_id=args.id,
        out_root=Path(args.out) if args.out else None,
    )
    counts = snap.manifest["counts"]
    print(f"\nwrote {snap.directory}")
    print(f"  admitted {counts['admitted']} | rejected {counts['rejected']}")
    print(f"  labelled {counts['labelled']} of {counts['labels_offered']} offered")
    print(f"  splits   {snap.manifest['labelled_by_split']} (labelled)")
    print(f"  boundaries {snap.manifest['split_boundaries']}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    directory = Path(args.out or config.SNAPSHOT_DIR) / args.id
    results = snapshot_mod.verify(directory)
    for name, ok in results.items():
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(results.values()) else 1


def _show(args: argparse.Namespace) -> int:
    directory = Path(args.out or config.SNAPSHOT_DIR) / args.id
    snap = snapshot_mod.read(directory)
    print(json.dumps(snap.manifest, indent=2, default=str))
    return 0


def _report(args: argparse.Namespace) -> int:
    import pandas as pd

    from . import report as report_mod

    directory = Path(args.out or config.SNAPSHOT_DIR) / args.id
    snap = snapshot_mod.read(directory)
    rejections = pd.read_parquet(directory / snapshot_mod.REJECTIONS)
    text = report_mod.write(snap, rejections)

    destination = Path(args.to) if args.to else config.REPORT_DIR / "data-quality.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    print(f"wrote {destination} ({len(text.splitlines())} lines)")
    return 0


def _model_dir(args: argparse.Namespace) -> Path:
    return Path(args.model) if args.model else config.ARTIFACT_DIR / "models" / args.id


def _train(args: argparse.Namespace) -> int:
    from . import release

    out = _model_dir(args)
    print(f"fitting the shipping model on {args.id} (train split only)...")
    metrics = release.build(args.id, out)

    val, test = metrics["validation"], metrics["test"]
    print(f"\nwrote {out}")
    print(f"  validation  macro-F1 {val['macro_f1']:.3f} "
          f"[{val['macro_f1_low']:.3f}, {val['macro_f1_high']:.3f}]  "
          f"accuracy {val['accuracy']:.3f}  ECE {val['ece']:.3f}")
    print(f"  test        macro-F1 {test['macro_f1']:.3f} "
          f"[{test['macro_f1_low']:.3f}, {test['macro_f1_high']:.3f}]  (recorded, not re-run)")
    print(f"  cut {metrics['cut']:.3f}  bundle {metrics['metadata'].get('bundle_mb')} MB  "
          f"{val['predict_ms_per_article']:.2f} ms/article")
    return 0


def _predict(args: argparse.Namespace) -> int:
    from . import serve

    classifier = serve.load(_model_dir(args))
    body = Path(args.file).read_text(encoding="utf-8") if args.file else args.body
    result = classifier.classify(args.title, args.summary, body or "")

    verdict = "FILED" if result.filed else "ABSTAINED — too close to call"
    print(f"{result.topic:<22} {result.confidence:.3f}   {verdict}")
    print(f"(cut {classifier.cut:.3f})\n")
    for topic, probability in result.ranked[:5]:
        print(f"  {topic:<22} {probability:.3f}")
    if result.evidence:
        print("\n  because of: " + ", ".join(term for term, _ in result.evidence[:8]))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsmlv2")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("snapshot", help="freeze a dataset")
    # Required on purpose: v1 derived ids from the date, collided on a same-day rerun,
    # and silently overwrote the previous snapshot in place.
    p.add_argument("--id", required=True, help="snapshot id (must not already exist)")
    p.add_argument("--out", default=None)
    p.add_argument("--limit", type=int, default=None, help="read at most N articles")
    p.set_defaults(func=_snapshot)

    p = sub.add_parser("verify", help="confirm a snapshot still matches its digests")
    p.add_argument("--id", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=_verify)

    p = sub.add_parser("show", help="print a snapshot manifest")
    p.add_argument("--id", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=_show)

    p = sub.add_parser("report", help="write the data quality report")
    p.add_argument("--id", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--to", default=None)
    p.set_defaults(func=_report)

    p = sub.add_parser("train", help="fit the shipping model and write bundle + model card")
    p.add_argument("--id", required=True, help="snapshot id to fit on")
    p.add_argument("--model", default=None, help="output directory for the bundle")
    p.set_defaults(func=_train)

    p = sub.add_parser("predict", help="classify one article")
    p.add_argument("--id", default="v2-001", help="snapshot id the bundle was fitted on")
    p.add_argument("--model", default=None, help="directory holding bundle.joblib")
    p.add_argument("--title", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--body", default="")
    p.add_argument("--file", default=None, help="read the body from a file instead")
    p.set_defaults(func=_predict)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
