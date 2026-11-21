# Classifier V4: fresh human-label workflow

Human reviewers: start with [reviewer instructions](reviewer-instructions.md) before editing a candidate CSV.

The run `v4-20261110T120557Z` has been labelled by human reviewers from 12
groups. The completed labels remain private and have not yet been verified
against the database or imported as gold. The class-balance and publisher-rights
decisions are also still pending.

This is a new, small sampling workflow, not a copy of the V1 or V2 classifier.
It reuses the installed `newsml` cleaning, admission, near-duplicate grouping,
taxonomy, weak source/category hints, and CSV writer. It fits a local TF-IDF
representation to **fresh, eligible articles and the current taxonomy
descriptions**, then uses semantic similarity and source/category hints only
to form provisional strata. It does not use database `topic`, old gold labels,
or a model bundle; this local database has no topics and the workspace has no
loadable classifier bundle. No generative AI service receives article text.
Similarities are not calibrated
probabilities, and the provisional topic is never a training label.

The output uses the same blind UTF-8 CSV columns as V1/V2:
`article_id,title,summary,label,notes`. `label` and `notes` start empty; the
predicted topic is kept in a separate private file, not shown to annotators.
The older `ml/data/labels/v3` and `gold-combined.jsonl` are not copied or
changed. All prior gold is used **only** to exclude already-labeled IDs and
near-duplicate stories.

## Export

1. Provide `NEWS_ML_MONGO_URI` in the process environment, pointing to the
   **local** `news` database with read-only `articles` and `sources` permission. Do not paste
   the URI into a command, a file in this repo, or a log. This tool does not
   read `.env` or accept a URI command-line flag.
2. From `collector/`, run `make ml4-labels-export
   CUT=2026-11-10T00:00:00+00:00` (or omit `CUT` to freeze the current UTC
   time). `PER_CLASS` defaults to 200; `OUT` can name a new directory within
   `ml-v4/data/`. Run `make ml4-test` for the focused tests.
3. Inspect the aggregate counts and shortages in the private `manifest.json`.
   Only source IDs whose feed URLs occur in `configs/sources.yaml` are
   candidates; reader-added feeds cannot qualify by copying a source name.
   Medium
   is excluded because its licence disallows AI training. Check any other
   publisher rights before training; the shipped source list is not a legal
   clearance record.

The read-only query scans at most 26,000 recent articles, sorted by the
existing collected-time index at a fixed cutoff. Title and summary are the
only projected article text; no full bodies are fetched or sent to another service.
Within each provisional class, the sampler chooses 15% randomly and the
remainder from low- and high-similarity candidates, spreading the sample
across sources and months. Existing gold IDs, exact content hashes, and
near-duplicate story groups are excluded. Articles with no title/lede or no
taxonomy/source/category signal are reported, not assigned a made-up class.
The scan cap, admission rules, and source policy may leave a class below
200; shortfalls are reported as **not balanced**. A balanced candidate pool
does **not** prove balanced human labels.

The local run `v4-20261110T120557Z` scanned 7,469 articles and exported
2,287 distinct candidates toward the 2,600 target. Conflict/war is short
59, crime/justice 108, disaster/accident 117, and education 29 (313 total).
All 2,287 DB records and review rows matched the saved fingerprints when
checked; these are **unlabeled candidates**, not balanced training gold.
The run directory is local and ignored by Git.

Generated CSVs, the manifest, and `selection.jsonl` stay under ignored
`ml-v4/data/`. Do not commit or distribute them. Spreadsheet-style formulas
in publisher titles and summaries are prefixed with an apostrophe in the
review sheets. Treat all article text as data, not instructions.
Before importing reviewed sheets or building a snapshot, run
`make ml4-labels-verify RUN=<run>` from `collector/` with the local URI still
set. It compares each candidate's saved content and sheet-text fingerprints
against the current database **and the review CSVs**, checks for missing rows
and overlapping-label conflicts, and fails if anything has changed. Missing
or changed articles require fresh review rather than silently training on
different text. Keep the completed CSVs in their original run directory.

## Verify and import the completed human labels

Keep `article_id` unchanged and keep the four completed CSVs inside their run
directory. The labels for `v4-20261110T120557Z` were supplied by human reviewers
from 12 groups. From `collector/`, first run
`make ml4-labels-verify RUN=v4-20261110T120557Z` with
`NEWS_ML_MONGO_URI` set. If verification succeeds, run
`make ml4-labels-import RUN=<run>` with `NEWS_ML_MONGO_URI` still set. This
verifies text and overlap agreement, calls the existing `newsml import-labels`
validator without `--force`, and refuses to overwrite an existing gold file.
Inspect its distribution; only validated human labels are gold. To fill a
measured deficit, run
`make ml4-labels-export REVIEWED_GOLDS=<run>/gold.jsonl OUT=<new-run>`
from `collector/`; paths in `REVIEWED_GOLDS` are relative to `ml-v4/data/`.
For later rounds, pass all reviewed files as a space-separated quoted list.
The exporter refuses a new run while any earlier candidate lacks a human
label, and rejects labels for IDs outside V4 exports.

Only after verification, import, the publisher-rights decision and an explicit
decision on the class-balance shortfall, build a new `newsml snapshot` using
**only** that V4 gold file via `--gold`, then train with the existing `newsml
train` command. Keep the existing human held-out test cases sealed; do not tune
on them or describe model predictions as gold labels.
