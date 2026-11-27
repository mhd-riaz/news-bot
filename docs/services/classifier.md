# Classifier V4: local AI-label candidate and future human-review workflow

**Status, 27 Nov 2026:** the owner approved the pooled AI-label model below
(`v4-ai-072b01a9ceaf-hybrid_svc`) for production on 27 Nov (roadmap D19). The sidecar
serves it through [`serving.py`](../../ml/src/newsmlv4/serving.py). Production is switched
only once its bundle is on the `classifier-models` volume and the image is
redeployed: see [Deploy the V4 classifier](#deploy-the-v4-classifier-d19).
For future genuine human review, start with the
[reviewer instructions](classifier-reviewer-instructions.md) before editing a new candidate CSV.

On 22 Nov the owner confirmed that **all old and new classifier labels are
AI-generated**, including round 1 previously described as human gold. Those
human-provenance claims are withdrawn (roadmap D16). Original datasets and model
artifacts remain private and unchanged; a separate provenance correction records
their actual origin. Existing classifier scores measure agreement with AI labels,
not human-validated accuracy.

The owner approved a larger V4 model using usable old and new labels,
including the existing AI-sampled proposal effort. No AI judgement becomes human
gold. Human validation and the 200 human labels/class target are **not met**; D19
promotes the model on AI-label agreement alone, and that limit stays on record.

Private exports, label files, model cards and bundles linked below are local,
ignored artifacts; they need not exist on a fresh checkout. The sidecar loads
whichever bundle `NEWSML_MODEL_DIR` names: the body-aware `newsmlv2` bundle
(`/models/v2-001`) or a V4 bundle, which it wraps in `newsmlv4.serving`. V4 reads
the title and a 400-character lede, so the adapter rebuilds that input from the raw
article; the `/v1/classify` response contract is unchanged.

## Pooled AI-label candidate (D16)

The pool keeps truthful `label_source: ai-agent` attribution, source hashes and
per-record origins. It accounts for unusable text, conflicting labels, duplicate
stories, and protected historical evaluation articles before training. Confidence
labels are not invented for older annotations that did not record them. Original
labels and annotation sheets are preserved, rather than rewritten to hide their
origins.

The pool was built on 22 Nov with `make ml4-pool` from a private, read-only MongoDB
MCP export of the round-2 title/summary window and the source feed metadata; no full
bodies or credentials were needed. The builder (`newsmlv4.pool`) also reads the old
label rounds, the committed article snapshots and the near-duplicate pair key. Those
left the working tree in R3 (roadmap D21), so the pool can be rebuilt only from git
tag `before-restructure`, and R2 removed the `ml4-pool` make target. The labels of
this pool, without any article text, are published as [`data/labels/`](../../data/labels/README.md).

The measured pool `v4-ai-pooled-20261122T000000Z` contains **8,594** usable
AI-labelled articles. It reuses 3,281 articles from the complete round-2 AI effort,
including **2,582 additional articles** beyond the original 809-sheet selection.
Legacy and round-1 source memberships are 3,522 and 1,814; 23 articles have both
origins, so these memberships are not disjoint. Every AI-labelled class has at
least 379 articles. Historical evaluation ID/alias overlap is zero, and the old
model's 456 reserved test IDs were reproduced against its recorded hash.
The private [dataset audit](../../ml/artifacts/v4/v4-ai-pooled-20261122T000000Z/manifest.json)
records every exclusion and the source fingerprints.

The MCP export files are temporary. The pool preserves private copies under its
`inputs/` directory; use those copies for reproducible later runs rather than
depending on the extension's export cache. The pool refuses to overwrite an
existing output directory. Use this measured pool without lowering any target.
From `ml/`:

```bash
make ml4-train DATASET=v4-ai-pooled-20261122T000000Z
```

The completed local candidate is
[`v4-ai-072b01a9ceaf-hybrid_svc`](../../ml/models/classifier/v4-ai-072b01a9ceaf/model-card.md).
It compares all eight rungs and selects the lexical-plus-MiniLM linear model.
It learns from 6,875 development articles, including 2,627 AI-sampled round-2
articles; 1,719 articles are reserved for the once-opened test split.
Held-out **AI-label agreement**: macro-F1 0.8246 [0.8056, 0.8442], accuracy 0.829.
Sigmoid calibration has lower development log loss than isotonic (0.5742 versus
0.6041). The provisional cut 0.2059 gives 0.8143 out-of-fold AI-label agreement
with 100% coverage. This does not demonstrate human accuracy.

The full run took 863.36 seconds with a 5.23 GB peak resident set on the local
machine. The saved bundle was reloaded in a fresh process with the Hub offline,
and three fictional inference probes passed; this checks operation, not human
validation. `make ml4-test` passed 75 sampler/verifier tests and 26 trainer/pool
tests. The model, manifest, split IDs and training log stay private under
`ml/models/classifier/v4-ai-072b01a9ceaf/`; production promotion was approved on 27 Nov (D19).

`ACCEPT_SHORTFALL=1` records any remaining AI-label class deficits as not met; it
is an owner-approved exception, not the default build path. It does not change
the target or satisfy the human-label requirement. The model card
and manifest explicitly report **AI-label agreement only**. Its calibration and
confidence cut are provisional on AI labels, not a demonstrated probability of
being correct against human judgement. The new model saves its development/test
IDs, and cannot reopen the same corpus's test split.

## Deploy the V4 classifier (D19)

The repository is prepared; the production steps are the owner's. The model is
`ml/models/classifier/v4-ai-072b01a9ceaf/bundle.joblib` (44.5 MB, SHA-256
`61cbaa89016d1acd88473cad2cf59cec69e74177aabe123bafa0a9c9f6c22fde`).
`make -C ml models` downloads it from the release `classifier-v4-ai-072b01a9ceaf` of
the private repository `mhd-riaz/news-bot-archive` and checks every file against
[`ml/models.toml`](../../ml/models.toml).

1. Copy that file to `/models/v4-ai-072b01a9ceaf/bundle.joblib` on the external
   `classifier-models` volume and set `NEWS_CLASSIFIER_MODEL_SHA256` to the hash
   above. The container refuses any other file.
2. Publish the classifier image and redeploy; publishing stays gated by
   `DEPLOY_ENABLED`. The image now carries CPU torch, sentence-transformers and the
   MiniLM encoder (revision pinned by the trainer), fetched at build time and used
   offline. The compose file allows 1.5 GB of memory and a 120 s start-up.
3. Confirm `GET /v1/meta` (with the classifier key) reports
   `model_version` `v4-ai-072b01a9ceaf-hybrid_svc` and 14 topics.
4. Relabel existing articles: `make -C collector backfill-reclassify BACKFILL_LIMIT=<n>`, repeated
   until `updated` is 0. It relabels whatever the sidecar's model differs from, in
   bounded batches that can be rerun. It writes only `topic`, `confidence`,
   `model_version`, `classification_status` and `classified_at`, never article text.
   A topic-only change does not move `updated_at` or `content_rev`, so anything that
   waits on those, such as a future incremental indexer, does not see relabelled
   articles.
5. To roll back, point `NEWSML_MODEL_DIR` and the hash at `v2-001` on the same volume
   and rerun step 4. The sidecar serves either bundle. On 27 Nov no `v2-001`
   `bundle.joblib` was found on the laptop or in the archive release, so check that
   the volume holds one before relying on this.

Measured locally on 27 Nov (macOS arm64, Python 3.13, the image's pinned
requirements, offline encoder cache): start-up with model load and encoder warm-up
6.6 s (about 20 s on a cold first run); a 50-article batch of long bodies 0.83 s;
worker memory 702 MB after warm-up and 893 MB at peak.

Measured on 27 Nov in R2 (Linux arm64 image under Rancher Desktop, Python 3.12,
`--cpus=1`, this bundle mounted read-only): the image is 2.11 GB (491 MB compressed);
the service was ready about 10 s after start; memory was 582 MiB after warm-up and
626 MiB after six 50-article batches; a 50-article batch of short made-up articles
took 2.19–2.68 s (median 2.25 s over five runs), inside the Go collector's 10 s
classifier timeout. **Not measured:** the amd64 image that CI builds.

## Candidate sampler

This is a small sampling workflow, not a copy of the V1 or V2 classifier.
It reuses the installed `newsml` cleaning, admission, near-duplicate grouping,
taxonomy, weak source/category hints, and CSV writer. It fits a local TF-IDF
representation to **fresh, eligible articles and the current taxonomy
descriptions**, then uses semantic similarity and source/category hints only
to form provisional strata. It does not use database `topic`, old gold labels,
or a model bundle. Sampling mechanics do not establish label authorship; all
existing labels are AI-generated by the owner's correction above.
Similarities are not calibrated
probabilities, and the provisional topic is never a training label.

The output uses the same blind UTF-8 CSV columns as V1/V2:
`article_id,title,summary,label,notes`. `label` and `notes` start empty; the
predicted topic is kept in a separate private file, not shown to annotators.
The sampler uses the old label rounds (`collector/ml/data/labels/`, including
`gold-combined.jsonl`) to exclude already-labelled IDs, and earlier V4 rounds to
exclude near-duplicate stories. R3 removed the old label rounds from the working
tree, so an export now stops with a clear message until they are restored from git
tag `before-restructure`. The separate D16 pooled training path reuses eligible old labels with
accurate attribution.

## Export

1. Provide `NEWS_ML_MONGO_URI` in the process environment, pointing to the
   **local** `news` database with read-only `articles` and `sources` permission. Do not paste
   the URI into a command, a file in this repo, or a log. This tool does not
   read `.env` or accept a URI command-line flag.
2. From `ml/`, run `make ml4-labels-export
   CUT=2026-11-10T00:00:00+00:00` (or omit `CUT` to freeze the current UTC
   time). `PER_CLASS` defaults to 200; `OUT` can name a new directory within
   `ml/artifacts/v4/`. Run `make ml4-test` for the focused tests.
3. Inspect the aggregate counts and shortages in the private `manifest.json`.
   Only source IDs whose feed URLs occur in `collector/configs/sources.yaml` are
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

At its original export, `v4-20261110T120557Z` scanned 7,469 articles and exported
2,287 distinct candidates toward the 2,600 target. Conflict/war is short
59, crime/justice 108, disaster/accident 117, and education 29 (313 total).
All 2,287 DB records and review rows matched the saved fingerprints when
checked. They were unlabeled candidates then; their later labels are AI-generated
(D16), not human gold.
The run directory is local and ignored by Git.

Generated CSVs, the manifest, and `selection.jsonl` stay under ignored
`ml/artifacts/v4/`. Do not commit or distribute them. Spreadsheet-style formulas
in publisher titles and summaries are prefixed with an apostrophe in the
review sheets. Treat all article text as data, not instructions.
Before importing reviewed sheets or building a snapshot, run
`make ml4-labels-verify RUN=<run>` from `ml/` with the local URI still
set. It compares each candidate's saved content and sheet-text fingerprints
against the current database **and the review CSVs**, checks for missing rows
and overlapping-label conflicts, and fails if anything has changed. Missing
or changed articles require fresh review rather than silently training on
different text. Keep the completed CSVs in their original run directory.

## Verify and import the completed human labels

Keep `article_id` unchanged and keep the four completed CSVs inside their run
directory. The old labels for `v4-20261110T120557Z` are AI-generated (D16), despite their
historical `gold.jsonl` filename and stored human-origin claims. They are inputs
to the pooled candidate, not human gold. The following workflow is for **future
genuine human review**, not for importing AI judgements as human labels. Preserve
the corrected historical sheets; do not overwrite or re-import them as human work.
Verification checks text and label consistency, not authorship. From
`ml/`, first run `make ml4-labels-verify RUN=<new-human-reviewed-run>` with
`NEWS_ML_MONGO_URI` set. If verification succeeds, run
`make ml4-labels-import RUN=<run>` with `NEWS_ML_MONGO_URI` still set. This
verifies text and overlap agreement, calls the existing `newsml import-labels`
validator without `--force`, and refuses to overwrite an existing gold file.
Inspect its distribution; only validated human labels are gold. To fill a
measured deficit, run
`make ml4-labels-export REVIEWED_GOLDS=<run>/gold.jsonl OUT=<new-run>`
from `ml/`; paths in `REVIEWED_GOLDS` are relative to `ml/artifacts/v4/`.
For later rounds, pass all reviewed files as a space-separated quoted list.
The exporter refuses a new run while any earlier candidate lacks a human
label, and rejects labels for IDs outside V4 exports.

If the database a run was exported from is gone, `make ml4-labels-verify`
cannot find its IDs and the import above refuses. Only with an owner decision
(roadmap D14) run `make ml4-labels-import-exported RUN=<run>` instead. It checks
the sheets against the export fingerprints, requires every candidate to be
labelled with no conflicting overlaps, and writes gold in the same format. It
also records which articles today's database still holds with identical text:
`current-ids.jsonl` maps their IDs, and `import.json` counts the rest. Round 1
was imported this way on 21 Nov: 1,628 of 2,287 articles were re-checked, and
659 could not be.

## Round 2: AI-agent selection from the class descriptions

By owner decision on 21 Nov, round 2 is chosen by AI agents rather than by the
TF-IDF strata. The agents read titles and the first 400 characters of
summaries through the VS Code MongoDB MCP server, which is connected read-only
to the local `news` database. For each class below its target, they split the
taxonomy description into facets, draw matches day by day, and judge each
article against the labelling guide. They write only IDs and judgements to
`ml/artifacts/v4/proposals/<round>/*.jsonl`, one
`{"article_id", "topic", "confidence", "target"}` object per line. Then, from
`ml/`:

```bash
make ml4-labels-export PROPOSALS=<round> START=<window start> CUT=<window end> \
    REVIEWED_GOLDS="v4-20261110T120557Z/gold.jsonl"
```

The export reads only proposed articles collected inside `[START, CUT)` and
applies every round-1 eligibility rule. The original round-2 quotas counted gaps
against the round-1 labels whose human-origin claim was later withdrawn (D16);
they do not prove a balanced human corpus. Earlier candidates are excluded by
original ID, by today's ID, by content hash and by near-duplicate story. When
agents disagree on an article it is dropped. The export writes the usual blind
sheets for reviewers, and `weak-labels.jsonl` with the agents' class and
confidence (`label_source: ai-agent`). Those weak labels are never gold. They
may help fit a model, but never score one.

## Train from future genuine human labels

Training waits for verification and import, and for the class-balance gate:
the classes below the per-class target are filled, or the owner records the
shortfall as not met (roadmap ML4.2). Then, from `ml/`, run
`make setup` once, followed by:

```bash
make ml4-train RUNS="<genuinely human-reviewed run>"
make ml4-train RUNS="<genuinely human-reviewed run>" ACCEPT_SHORTFALL=1
make ml4-train RUNS="<genuinely human-reviewed run>" WEAK_RUNS="<AI-labelled run>" ACCEPT_SHORTFALL=1
```

With `WEAK_RUNS`, each rung except majority also runs as `<rung>+weak`. That
variant fits on the fold's human rows plus the agents' high- and
medium-confidence labels. It is scored, calibrated and cut on human rows only,
and every human-only rung counts as simpler. So the weak labels ship only if
they measurably beat human labels alone. An article with a human label never
uses its weak label.

Runs covered by the D16 provenance correction are refused on this human-gold
path. Use `DATASET` above to train the pooled AI-label candidate.

`newsmlv4.train` reads each run's imported `gold.jsonl` together with the title
and summary the reviewers saw. It refuses a run whose sheets no longer match the
export, and it refuses classes below the target unless the shortfall is accepted.
It never trains on fewer than ten labels per class. It seals a stratified 20%
test split, then scores eight rungs on the same repeated stratified 5-fold
splits (three repeats):

- majority
- Complement NB
- TF-IDF logistic regression
- TF-IDF LinearSVC
- word+char LinearSVC (ml-v2's shipped recipe)
- MiniLM sentence embeddings with logistic regression
- word+char+MiniLM LinearSVC
- a small Keras MLP

Tree models are left out because ml-v2 Phase E measured them well behind the
linear models on text. The simplest rung that a corrected resampled t-test
cannot separate from the best one is chosen. It is calibrated with five
cross-fitted folds (sigmoid or isotonic, whichever has the lower out-of-fold log
loss), given one global confidence cut at 0.80 precision, and scored once on
the sealed test split.

The trainer writes `bundle.joblib`, `manifest.json`, `model-card.md` and
`split.jsonl` under the ignored `ml/models/classifier/`. The directory is keyed by
the primary label-corpus digest (`v4-ai-<digest>` for a pool, `v4-<digest>` for
genuine human runs), not by optional weak labels. It refuses to overwrite an
earlier model for the same corpus, because a retrain would reopen its test split.
The directory is created just before the test split is opened, so an empty or
partial directory means a run stopped after opening it, and it blocks a retrain
in the same way. `MODELS=a,b` limits the ladder.

Both paths use seed `20261110`, a stratified 80% development / 20% test split,
and repeated stratified 5-fold selection with three repeats on development.
Calibration compares sigmoid with isotonic by nested out-of-fold log loss,
then averages five calibrated models. One global cut targets 0.80 precision
on the primary corpus's out-of-fold labels, with at least 50 retained examples.
For the pooled path, all those labels are AI-generated; meeting the AI-label
count or precision target does not meet the human target.

The model reads title and summary; the sidecar's V4 adapter rebuilds that input
from each article (D19). Preserve every existing held-out split
and its recorded opening; do not tune on it, re-open it for another selection,
or describe model predictions as gold. Existing classifier held-out labels
are AI-generated under D16, not human acceptance cases.
