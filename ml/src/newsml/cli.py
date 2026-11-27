"""One entrypoint for every offline task. `python -m newsml <command>`.

Ground rule 10 applied to tooling as well as libraries: a config-driven CLI and a
directory of results is enough at this scale. No experiment-tracking server.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import admit as admit_mod
from . import annotate as annotate_mod
from . import boilerplate as boilerplate_mod
from . import clean as clean_mod
from . import dataset as dataset_mod
from . import neardup as neardup_mod
from . import pairs as pairs_mod
from . import profile as profile_mod
from . import snapshot as snapshot_mod
from . import train as train_mod
from .config import (
    ARTIFACT_DIR,
    CLEANING_VERSION,
    DATA_DIR,
    DEFAULT_TEXT_VARIANT,
    REPORT_DIR,
    SEED,
    SNAPSHOT_DIR,
    TAXONOMY_PATH,
    TEXT_VARIANTS,
    mongo_uri,
)
from .labels import load_taxonomy
from .load import load_articles

REPO_ROOT = Path(__file__).resolve().parents[3]


def _default_snapshot_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d}-{CLEANING_VERSION.replace('.', '')}"


def _cut(value: str | None) -> datetime | None:
    """Parse the corpus cut, and insist it is unambiguous about its timezone."""
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _gold(paths: list[str] | None) -> dict[str, str]:
    """Merge every labelling round, later files winning on a repeated article."""
    merged: dict[str, str] = {}
    for raw in paths or []:
        merged.update(annotate_mod.read_gold(Path(raw)))
    return merged


def cmd_profile(args: argparse.Namespace) -> int:
    articles = load_articles(args.uri, limit=args.limit)
    if not articles:
        print("no articles found — is the collector's MongoDB reachable?", file=sys.stderr)
        return 1
    report = profile_mod.write(articles, Path(args.out))
    print(f"{len(articles):,} articles profiled → {report}")
    return 0


def cmd_boilerplate(args: argparse.Namespace) -> int:
    import yaml

    articles = load_articles(args.uri, limit=args.limit)
    candidates = boilerplate_mod.discover(articles, args.variant)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    document = boilerplate_mod.to_yaml_document(candidates)
    out.write_text(
        "# Learned per-source boilerplate. Regenerate with `make ml-boilerplate`.\n"
        "# Review before trusting: every line here is removed from every article\n"
        "# of its source, and a false positive silently deletes real content.\n"
        + yaml.safe_dump(document, sort_keys=True, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    print(f"{len(candidates)} boilerplate line(s) across {len(document['sources'])} source(s) → {out}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    articles = load_articles(args.uri, limit=args.limit, collected_before=_cut(args.collected_before))
    if not articles:
        print("no articles found — is the collector's MongoDB reachable?", file=sys.stderr)
        return 1
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    gold = _gold(args.gold)
    result = snapshot_mod.build(
        articles,
        snapshot_id=args.id,
        out_root=Path(args.out),
        variant=args.variant,
        repo=REPO_ROOT,
        check_language=not args.no_language_check,
        gold=gold,
        taxonomy_version=taxonomy.version,
        collected_before=_cut(args.collected_before),
    )
    print(json.dumps(result.manifest["counts"], indent=2, sort_keys=True))
    print(f"snapshot → {result.directory}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Rebuild a snapshot into a scratch directory and compare digests.

    This is the acceptance criterion "rebuilds byte-identically", run as a
    command rather than asserted in prose. The cut recorded in the manifest is
    reapplied, so a corpus that has grown since still yields the same rows.
    """
    import shutil
    import tempfile

    original = Path(args.out) / args.id / "manifest.json"
    if not original.exists():
        print(f"no snapshot at {original}", file=sys.stderr)
        return 1
    manifest = json.loads(original.read_text(encoding="utf-8"))
    expected = manifest["digests"]
    cut = _cut(args.collected_before or manifest.get("collected_before"))

    taxonomy = load_taxonomy(TAXONOMY_PATH)
    articles = load_articles(args.uri, limit=args.limit, collected_before=cut)
    scratch = Path(tempfile.mkdtemp(prefix="newsml-verify-"))
    try:
        rebuilt = snapshot_mod.build(
            articles,
            snapshot_id=args.id,
            out_root=scratch,
            variant=args.variant,
            repo=REPO_ROOT,
            check_language=not args.no_language_check,
            gold=_gold(args.gold),
            taxonomy_version=taxonomy.version,
            collected_before=cut,
        )
        mismatched = {k: (v, rebuilt.manifest["digests"].get(k)) for k, v in expected.items()
                      if rebuilt.manifest["digests"].get(k) != v}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if mismatched:
        for name, (want, got) in sorted(mismatched.items()):
            print(f"MISMATCH {name}\n  expected {want}\n  rebuilt  {got}", file=sys.stderr)
        return 1
    print(f"snapshot {args.id} rebuilds byte-identically ({len(expected)} file(s))")
    return 0


def cmd_export_labels(args: argparse.Namespace) -> int:
    """Draw a sample and write blind labelling sheets, one per annotator.

    `--collected-before` must match the cut of the snapshot the labels will be
    trained from. Round 3 was drawn without it and **77 of 342 labels (23%) were
    unusable** — not wrong, just spent on articles collected after the cut, which
    no snapshot can ever join. Sampling outside the frozen corpus wastes an
    annotator's afternoon and gives nothing back.
    """
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    cut = _cut(args.collected_before)
    articles = load_articles(args.uri, limit=args.limit, collected_before=cut)
    if not articles:
        print("no articles found \u2014 is the collector's MongoDB reachable?", file=sys.stderr)
        return 1
    if cut is None:
        print("warning: no --collected-before, so this samples the live corpus. Any article",
              file=sys.stderr)
        print("         collected after the next snapshot's cut will be labelled for nothing.",
              file=sys.stderr)

    # Only admitted articles: no one should spend attention labelling a
    # horoscope that the pipeline is going to drop anyway.
    pairs = [(a, clean_mod.clean(a.text(args.variant))) for a in articles]
    admitted, _ = admit_mod.partition(pairs, check_language=False)
    grouping = neardup_mod.group({a.article.id: a.cleaned.text for a in admitted})

    if args.seeds:
        seeds = annotate_mod.read_gold(Path(args.seeds))
        targeted = annotate_mod.choose_targeted_sample(
            [a.article for a in admitted],
            {a.article.id: a.cleaned.text for a in admitted},
            taxonomy,
            per_class=args.per_class,
            seeds=seeds,
            group_of=grouping.group_of,
            random_share=args.random_share,
            exclude=args.exclude,
            seed=SEED,
        )
        sample = targeted.articles
        held = Counter(seeds.values())
        excluded = set(args.exclude or ())
        served = [
            c for c in annotate_mod._leaf_classes(taxonomy) if c not in targeted.quota and c not in excluded
        ]
        print(f"targeting {args.per_class} labels per class, {len(seeds):,} already held")
        print(f"{len(served)} class(es) already at the target, sampled zero times:"
              f" {', '.join(f'{c} {held.get(c, 0)}' for c in served) or 'none'}")
        if excluded:
            print(f"excluded regardless of shortfall: {', '.join(sorted(excluded))}\n")
        else:
            print()
        print(f"  {'class':<24}{'have':>6}{'short':>7}{'retrieve':>10}{'precision':>11}")
        for topic, gap in sorted(targeted.quota.items(), key=lambda kv: -kv[1]):
            rate = targeted.precision.get(topic)
            print(f"  {topic:<24}{held.get(topic, 0):>6}{gap:>7}{targeted.asked_for[topic]:>10}"
                  f"{(f'{rate:.0%}' if rate is not None else '-'):>11}")
        print(f"  {'(random control)':<24}{'':>6}{'':>7}{targeted.asked_for['random']:>10}")
        if targeted.shortfall:
            print("the corpus could not supply enough candidates for:")
            for topic, missing in sorted(targeted.shortfall.items(), key=lambda kv: -kv[1]):
                print(f"  {topic:<26}{missing:>5} short")
    else:
        sample = annotate_mod.choose_sample(
            [a.article for a in admitted], size=args.size, seed=SEED, group_of=grouping.group_of
        )

    out = Path(args.out)
    sheets = annotate_mod.write_sheets(
        sample, out, shards=args.shards, overlap=args.overlap, seed=SEED
    )
    guide = annotate_mod.write_guide(taxonomy, out / "labelling-guide.md", overlap=args.overlap)

    print(f"{len(sample)} articles sampled from {len(admitted)} admitted ({grouping.group_count} story groups)")
    for sheet in sheets:
        print(f"  {sheet}")
    print(f"guide  {guide}")
    return 0


def cmd_adjudicate(args: argparse.Namespace) -> int:
    """Collect every article the sheets disagreed on into one ruling sheet.

    Reads no database: the overlap block is the only place disagreement can
    arise, and both the labels and the text under dispute are already in the
    sheets.
    """
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    labels: list = []
    for raw in args.sheets:
        path = Path(raw)
        if not path.exists():
            print(f"no such sheet: {path}", file=sys.stderr)
            return 1
        found, _ = annotate_mod.read_sheet(path, taxonomy, annotator=path.stem)
        labels.extend(found)

    texts = annotate_mod.read_sheet_texts(Path(raw) for raw in args.sheets)
    disputed = annotate_mod.conflicts(labels, texts)
    if not disputed:
        print("no disagreements to adjudicate")
        return 0

    parent_of = {c.id: (c.parent or c.id) for c in taxonomy.classes}
    cross = sum(1 for c in disputed if c.crosses_groups(parent_of))
    out = annotate_mod.write_adjudication_sheet(disputed, Path(args.out))

    print(f"{len(disputed)} disputed article(s), {cross} of them across groups \u2192 {out}")
    print("\nTie-breaks that apply (now also in the generated guide):")
    for number, rule in enumerate(annotate_mod.TIE_BREAKS, start=1):
        print(f"  {number}. {rule}")
    print(f"\nFill the `label` column, then re-run import-labels with --adjudicated {out}")
    return 0


def cmd_import_labels(args: argparse.Namespace) -> int:
    """Read completed sheets, validate every cell, and write the gold set."""
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    articles = {a.id: a for a in load_articles(args.uri, limit=args.limit)}

    labels: list = []
    problems: list = []
    for raw in args.sheets:
        path = Path(raw)
        if not path.exists():
            print(f"no such sheet: {path}", file=sys.stderr)
            return 1
        found, issues = annotate_mod.read_sheet(
            path, taxonomy, known_ids=frozenset(articles), annotator=path.stem
        )
        labels.extend(found)
        problems.extend(issues)

    if args.adjudicated:
        path = Path(args.adjudicated)
        if not path.exists():
            print(f"no such adjudication sheet: {path}", file=sys.stderr)
            return 1
        rulings, issues = annotate_mod.read_sheet(
            path, taxonomy, known_ids=frozenset(articles), annotator="adjudicated"
        )
        problems.extend(issues)
        # A ruling replaces the votes rather than joining them, so an adjudicated
        # article stops counting as a disagreement.
        ruled = {label.article_id: label for label in rulings}
        labels = [x for x in labels if x.article_id not in ruled] + list(ruled.values())
        print(f"{len(ruled)} article(s) resolved by adjudication")

    for problem in problems:
        print(f"  {problem.sheet}:{problem.row} {problem.article_id} \u2014 {problem.detail}", file=sys.stderr)

    gold = {label.article_id: label.topic for label in labels}
    disagreed = annotate_mod.disagreements(labels)
    parent_of = {c.id: (c.parent or c.id) for c in taxonomy.classes}

    print(f"{len(labels)} label(s) over {len(gold)} article(s) from {len(args.sheets)} sheet(s)")
    print(f"{len(problems)} problem(s), {len(disagreed)} article(s) with annotator disagreement")

    print("\n=== distribution ===")
    coarse: dict[str, int] = {}
    fine: dict[str, int] = {}
    for topic in gold.values():
        coarse[parent_of.get(topic, topic)] = coarse.get(parent_of.get(topic, topic), 0) + 1
        fine[topic] = fine.get(topic, 0) + 1

    for group, total in sorted(coarse.items(), key=lambda kv: -kv[1]):
        flag = "  <-- starved" if total < args.min_per_class else ""
        print(f"{group:<22} {total:>4}  {100 * total / len(gold):5.1f}%{flag}")
        for topic, count in sorted(fine.items(), key=lambda kv: -kv[1]):
            if parent_of.get(topic, topic) == group and topic != group:
                print(f"   {topic:<19} {count:>4}")

    unsorted_n = fine.get(taxonomy.unsorted, 0)
    fallback = sum(c for t, c in fine.items() if taxonomy.children_of(t))
    print(f"\nunsorted           {unsorted_n:>4}  {100 * unsorted_n / len(gold):5.1f}%   (taxonomy fits if < 15%)")
    print(f"group fallback     {fallback:>4}  {100 * fallback / len(gold):5.1f}%   (children are specific if rare)")

    report = annotate_mod.weak_vs_gold(gold, articles, taxonomy)
    print("\n=== weak label vs gold: the ceiling Phase 3 cannot exceed ===")
    print(f"coverage           {report.covered:>4}  {100 * report.coverage:5.1f}%")
    print(f"  no weak label    {report.no_weak_label:>4}")
    print(f"  geography only   {report.geography_only:>4}")
    if report.covered:
        print(f"exact class        {report.exact:>4}  {100 * report.exact / report.covered:5.1f}%")
        print(f"right group        {report.same_group:>4}  {100 * report.same_group / report.covered:5.1f}%")
        print(f"wrong group        {report.wrong_group:>4}  {100 * report.wrong_group / report.covered:5.1f}%")
        print(f"group agreement    {'':>4}  {100 * report.group_agreement:5.1f}%")
    for truth, weak, title in report.examples:
        print(f"  gold={truth:<20} weak={weak:<18} {title}")

    if problems and not args.force:
        print("\nrefusing to write while problems remain; fix them or pass --force", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for label in sorted(labels, key=lambda x: (x.article_id, x.detail)):
            handle.write(json.dumps({
                "article_id": label.article_id,
                "topic": label.topic,
                "label_source": str(label.source),
                "annotator": label.detail,
                "taxonomy_version": taxonomy.version,
            }, sort_keys=True) + "\n")
    print(f"\ngold set -> {out}")
    return 0


def cmd_export_pairs(args: argparse.Namespace) -> int:
    """Write a blind sheet of near-duplicate pairs from the boundary region.

    The threshold this calibrates is currently derived from the LSH banding and
    has never been checked against a person. Only the boundary is sampled: the
    ends of the range are not in doubt.
    """
    snap = snapshot_mod.read(Path(args.snapshot))
    texts = {row.article_id: row.text for row in snap.rows}
    titles = {row.article_id: row.title for row in snap.rows}

    candidates = neardup_mod.candidate_pairs(texts, bands=args.bands)
    sample = pairs_mod.choose_pairs(
        candidates, size=args.size, low=args.low, high=args.high, seed=SEED
    )
    if not sample:
        print(f"no candidate pairs scored between {args.low} and {args.high}", file=sys.stderr)
        return 1

    sheet, key = pairs_mod.write_sheet(sample, titles, texts, Path(args.out))
    guide = pairs_mod.write_guide(
        Path(args.out) / "labelling-guide.md",
        count=len(sample),
        sources=len({row.source_name for row in snap.rows}),
    )

    in_range = sum(1 for _, _, score in candidates if args.low <= score < args.high)
    print(f"{len(candidates):,} candidate pair(s) at {args.bands} bands; "
          f"{in_range:,} in the boundary region")
    print(f"{len(sample)} sampled across {len({p.stratum for p in sample})} strata\n")
    print(f"  {'band':<16}{'in corpus':>11}{'sampled':>9}")
    for stratum in sorted({p.stratum for p in sample}):
        members = [p for p in sample if p.stratum == stratum]
        lo = args.low + stratum * (args.high - args.low) / pairs_mod.STRATA
        hi = lo + (args.high - args.low) / pairs_mod.STRATA
        print(f"  {f'{lo:.2f}-{hi:.2f}':<16}{members[0].population:>11,}{len(members):>9}")
    print(f"\nsheet  {sheet}\nguide  {guide}\nkey    {key}   (do not open this before labelling)")
    print("\nSend the sheet and the guide together. The guide explains the one rule that")
    print("nobody gets right unaided: two instalments of a daily feature are NOT one story.")
    return 0


def cmd_import_pairs(args: argparse.Namespace) -> int:
    """Score every candidate threshold against the labelled pairs."""
    key = pairs_mod.read_key(Path(args.key))
    filled = pairs_mod.read_judgements(Path(args.sheet))
    for problem in filled.problems:
        print(f"  {problem}", file=sys.stderr)

    judgements = filled.judgements
    scored = pairs_mod.calibrate(key, judgements)
    if not scored:
        print("no readable judgements in the sheet", file=sys.stderr)
        return 1

    same = sum(1 for v in judgements.values() if v)
    unanswered = len(key) - len(judgements)
    print(f"{len(judgements)} of {len(key)} pair(s) judged; {same} are the same story")
    if unanswered:
        print(f"{unanswered} left blank — counted as unanswered, not as 'different'")
    print()
    print(f"  {'threshold':>10}{'precision':>11}{'recall':>9}{'F1':>8}{'folds':>10}{'misses':>9}")
    for row in scored:
        flag = "  <-- current" if abs(row.threshold - neardup_mod.DEFAULT_THRESHOLD) < 1e-9 else ""
        print(f"  {row.threshold:>10.2f}{row.precision:>11.3f}{row.recall:>9.3f}"
              f"{row.f1:>8.3f}{row.folded:>10,.0f}{row.missed:>9,.0f}{flag}")

    passing = [r for r in scored if r.precision >= args.min_precision]
    if passing:
        best = max(passing, key=lambda r: r.recall)
        print(f"\nlowest threshold holding precision >= {args.min_precision:.2f}: "
              f"{best.threshold:.2f} (recall {best.recall:.3f})")
    else:
        print(f"\nno threshold reaches precision {args.min_precision:.2f} on these pairs")

    if filled.notes:
        print(f"\n{len(filled.notes)} note(s) from the annotator:")
        for pair_id, note in sorted(filled.notes.items()):
            print(f"  {pair_id}  {note}")

    print("\nCounts are weighted by stratum and conditional on the boundary region;")
    print("pairs above it were never sampled and are not claimed to be measured.")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    """Fit the shipping model from a frozen snapshot and write the bundle."""
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    snap = snapshot_mod.read(Path(args.snapshot))
    if not snap.labels:
        print(f"snapshot {snap.snapshot_id} carries no labels; re-cut it with --gold", file=sys.stderr)
        return 1

    data = dataset_mod.from_snapshot(snap, taxonomy, min_per_class=args.min_per_class)
    if not data.train or not data.val:
        print(f"not enough labelled data to train: {data.counts}", file=sys.stderr)
        return 1

    print("=== provenance ===")
    for key, value in snap.provenance.items():
        print(f"  {key:<20}{value}")

    print("\n=== dataset ===")
    for key, value in data.counts.items():
        print(f"  {key:<20}{value:>7,}")
    print(f"  {'classes':<20}{len(data.classes):>7}   {', '.join(data.classes)}")
    if data.out_of_scope:
        below = Counter(e.topic for e in data.out_of_scope)
        print(f"  below the {args.min_per_class}-article floor: "
              f"{', '.join(f'{t} {n}' for t, n in below.most_common())}")

    report = train_mod.run(
        snap,
        taxonomy,
        data,
        out_root=Path(args.out),
        repo=REPO_ROOT,
        target_precision=args.target_precision,
        seed=SEED,
    )

    print("\n=== the ladder, on validation ===")
    print(f"  {'model':<24}{'macro-F1':>10}{'accuracy':>10}{'fit s':>8}{'ms/doc':>9}")
    for result in report.ladder:
        print(f"  {result.name:<24}{result.macro_f1:>10.3f}{result.accuracy:>10.3f}"
              f"{result.fit_seconds:>8.2f}{result.predict_ms_per_doc:>9.3f}")

    print("\n=== which rung can say how sure it is ===")
    print(f"  {'model':<24}{'macro-F1':>10}{'coverage':>10}{'acc kept':>10}{'unreached':>11}")
    for name, row in report.abstention.items():
        mark = "  <-- shipped" if name == report.chosen else ""
        print(f"  {name:<24}{row['macro_f1']:>10.3f}{row['coverage']:>10.1%}"
              f"{row['accuracy_on_kept']:>10.3f}{int(row['unreached']):>11}{mark}")

    cuts = report.thresholds
    print(f"\n=== per-class cuts at {cuts.target_precision:.0%} target precision ===")
    print(f"  {'class':<24}{'cut':>6}{'precision':>11}{'kept':>7}{'filed':>7}")
    for choice in sorted(cuts.choices, key=lambda c: (c.forced, -c.cut)):
        if choice.forced:
            print(f"  {choice.topic:<24}{'--':>6}{'--':>11}{choice.kept:>7}{choice.predicted:>7}"
                  "  <-- forced abstain, never emitted")
            continue
        flag = "  <-- never reaches the target" if not choice.reached_target else ""
        print(f"  {choice.topic:<24}{choice.cut:>6.2f}{choice.precision:>11.3f}"
              f"{choice.kept:>7}{choice.predicted:>7}{flag}")

    print(f"\naccuracy {cuts.accuracy_before:.3f} over everything"
          f"  ->  {cuts.accuracy_on_kept:.3f} over the {cuts.coverage:.1%} it still files")
    print(f"{cuts.abstained:,} of {cuts.n:,} validation articles routed to unsorted")
    print(f"\nbundle {report.bundle_bytes / 1e6:.1f} MB -> {report.directory}")
    print("the test split has not been opened")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsml", description=__doc__)
    parser.add_argument("--uri", default=None, help=f"MongoDB URI (default: {mongo_uri()})")
    parser.add_argument("--limit", type=int, default=None, help="read at most N articles")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="write the corpus profile report and figures")
    p.add_argument("--out", default=str(REPORT_DIR))
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("boilerplate", help="discover per-source template lines for review")
    p.add_argument("--out", default=str(ARTIFACT_DIR / "boilerplate.yaml"))
    p.add_argument("--variant", default="title_summary_content", choices=TEXT_VARIANTS)
    p.set_defaults(func=cmd_boilerplate)

    p = sub.add_parser("export-labels", help="write blind labelling sheets for human annotators")
    p.add_argument("--out", default=str(DATA_DIR / "labels" / "pilot"))
    p.add_argument("--size", type=int, default=150, help="articles to sample")
    p.add_argument("--shards", type=int, default=4, help="one sheet per annotator")
    p.add_argument("--overlap", type=int, default=20, help="articles shared by every sheet")
    p.add_argument("--variant", default=DEFAULT_TEXT_VARIANT, choices=TEXT_VARIANTS)
    p.add_argument(
        "--seeds",
        default=None,
        help="an existing gold.jsonl; turns on targeted sampling and ignores --size",
    )
    p.add_argument("--per-class", type=int, default=150, help="labels each class should end up with")
    p.add_argument("--random-share", type=float, default=0.15, help="fraction drawn at random anyway")
    p.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        help="class(es) to skip regardless of shortfall, e.g. a class more labels won't fix",
    )
    p.add_argument(
        "--collected-before",
        default=None,
        help="ISO timestamp; must match the snapshot cut, or the labels cannot be joined to it",
    )
    p.set_defaults(func=cmd_export_labels)

    p = sub.add_parser("adjudicate", help="write a ruling sheet for the articles sheets disagree on")
    p.add_argument("--sheets", nargs="+", required=True)
    p.add_argument("--out", default=str(DATA_DIR / "labels" / "adjudicate.csv"))
    p.set_defaults(func=cmd_adjudicate)

    p = sub.add_parser("export-pairs", help="write a blind near-duplicate sheet from the boundary region")
    p.add_argument("--snapshot", required=True, help="a frozen snapshot directory")
    p.add_argument("--out", default=str(DATA_DIR / "pairs"))
    p.add_argument("--size", type=int, default=100, help="pairs to sample")
    p.add_argument("--low", type=float, default=pairs_mod.BOUNDARY_LOW)
    p.add_argument("--high", type=float, default=pairs_mod.BOUNDARY_HIGH)
    p.add_argument("--bands", type=int, default=pairs_mod.SHEET_BANDS,
                   help="looser than the shipping banding, which cannot propose the pairs in doubt")
    p.set_defaults(func=cmd_export_pairs)

    p = sub.add_parser("import-pairs", help="calibrate the near-duplicate threshold from a labelled sheet")
    p.add_argument("--sheet", default=str(DATA_DIR / "pairs" / "pairs.csv"))
    p.add_argument("--key", default=str(DATA_DIR / "pairs" / "pairs-key.jsonl"))
    p.add_argument("--min-precision", type=float, default=0.90)
    p.set_defaults(func=cmd_import_pairs)

    p = sub.add_parser("train", help="fit the shipping classifier from a snapshot and write the bundle")
    p.add_argument("--snapshot", required=True, help="a frozen snapshot directory")
    p.add_argument("--out", default=str(ARTIFACT_DIR / "models"))
    p.add_argument("--min-per-class", type=int, default=40,
                   help="below this a class is absent, not thin, and is left out of scope")
    p.add_argument("--target-precision", type=float, default=0.80,
                   help="precision each class's confidence cut aims for")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("import-labels", help="validate completed sheets and write the gold set")
    p.add_argument("--sheets", nargs="+", required=True)
    p.add_argument("--adjudicated", default=None, help="ruling sheet that overrides sheet votes")
    p.add_argument("--out", default=str(DATA_DIR / "labels" / "gold.jsonl"))
    p.add_argument("--min-per-class", type=int, default=40)
    p.add_argument("--force", action="store_true", help="write even if problems were reported")
    p.set_defaults(func=cmd_import_labels)

    for name, func, help_text in (
        ("snapshot", cmd_snapshot, "freeze a dataset"),
        ("verify", cmd_verify, "rebuild a snapshot and compare digests"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--id", default=_default_snapshot_id())
        p.add_argument("--out", default=str(SNAPSHOT_DIR))
        p.add_argument("--variant", default=DEFAULT_TEXT_VARIANT, choices=TEXT_VARIANTS)
        p.add_argument("--no-language-check", action="store_true", help="skip langdetect (much faster)")
        p.add_argument(
            "--collected-before",
            default=None,
            help="ISO timestamp; keep only articles collected before it, so the cut is re-cuttable",
        )
        p.add_argument("--gold", nargs="*", default=None, help="gold.jsonl file(s) to freeze alongside the corpus")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)
