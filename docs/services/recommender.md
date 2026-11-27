# Recommender (the ranker)

The recommender picks stories a reader may like. It looks at what the stories say,
and at the reader's own choices: the stories they liked, and the ones they marked
"not interested". It does not learn from other people's reading history.

It has two halves:

- **The snapshot build.** A command you run by hand. It copies a set of stories out
  of MongoDB into a **snapshot** folder and trains three ranking methods on it.
- **The ranker.** A small web service. It loads one snapshot and answers "which
  stories next?" with a list of story IDs.

Hard words are explained in the [glossary](../glossary.md). Measured results are on
the [status page](../project/status.md) and, in full, in
[recommender-results.md](../project/recommender-results.md).

## At a glance

| Item | Value |
| --- | --- |
| Code | [`ml/src/newsrec`](../../ml/src/newsrec/): `data.py` prepares, `model.py` trains, `index.py` ranks, `api.py` serves, `evaluate.py` scores, `cli.py` is the `newsrec` command |
| Service files | [`ml/recommender/`](../../ml/recommender/): `Dockerfile` and `requirements.txt` (20 pinned packages; no TensorFlow) |
| Port | 8001 |
| Docker image | `ghcr.io/mhd-riaz/news-recommender` |
| Snapshots | `ml/artifacts/recommender/<id>/`. Git ignores this folder |
| Default method | TF-IDF |

## The three methods

1. **TF-IDF** (the default). It compares the words two stories share, giving more
   weight to rare words. It uses single words and word pairs, at most 25,000 terms.
2. **SVD.** It squeezes the TF-IDF numbers into 256 numbers per story, so stories
   about the same idea match even with different words.
3. **Neural.** A small **neural network** (a denoising **autoencoder**) learns to
   squeeze each story into 64 numbers: SVD features, plus a little noise, then
   128 → 64 → 128 → back. It has about 82,500 parameters. It is trained on your own
   computer with TensorFlow. Serving it does not need TensorFlow.

All three find stories that are close to each other by **cosine similarity** (how
much two lists of numbers point the same way). A score is not the chance that a
reader will like a story.

TF-IDF is the default because it did best in both recorded comparisons (see the
[status page](../project/status.md)). The neural method has not passed the V1
human-quality target.

## Make a fresh snapshot

From the repository root:

```bash
make -C ml rec-inspect     # check which database you will read; never prints its address
make -C ml demo-refresh    # build a new recent-first snapshot and train all three methods
make -C ml demo-serve      # serve the newest one on http://127.0.0.1:8001
```

`demo-refresh` does this:

1. It runs `newsrec inspect` and shows the database name, the article count and the
   newest collection time.
2. It names the snapshot `demo-<UTC date and time>` and uses a cut-off two minutes
   in the past.
3. It keeps the stories collected in the last 7 days first, newest first, and then
   fills up with an older random sample. It reads at most 40,000 candidates and
   keeps at most 30,000 stories. Change these with `DEMO_RECENT_DAYS`,
   `DEMO_CANDIDATES` and `DEMO_LIMIT`.
4. It fits TF-IDF and SVD, then trains the neural method.
5. Only if every step worked, it writes the snapshot's name into
   `ml/artifacts/recommender/LATEST_DEMO`.

It does **not** restart a running ranker. Stop the old one and run `demo-serve`
again after each refresh. Nothing refreshes snapshots on a timer yet.

When the app runs with `run.sh`, use `./run.sh refresh` instead. It builds a snapshot
the same way (the same 7 days, 40,000 candidates and 30,000 stories) and then
restarts the ranker for you.

The last recorded run (24 Nov 2026, roadmap DEMO.5) built `demo-20261124T084052Z`:
30,000 articles, 16,330 of them recent, 29,954 with a verified date and 3,432 from
sources with topic tags. It took 341.5 s.

Commands that read the database use the settings file `deployment/env/local.env`,
or the file named in `NEWS_ENV_FILE`. A variable already set in your environment wins.

## Make a named snapshot

Use a new name every time. Preparation refuses to overwrite a snapshot. From `ml/`:

```bash
make rec-prepare REC_ID=archive-20261125 CUT=2026-11-25T00:00:00+00:00
make rec-baseline REC_ID=archive-20261125
make rec-train REC_ID=archive-20261125
make rec-serve REC_ID=archive-20261125
```

`CUT` must be a past time with a time zone. Without `--recent-days`, preparation
takes a seeded random sample: at most 30,000 candidates, keeping up to 20,000
stories.

Always pass `REC_ID`. Its default is `stories-002`, the historical 22 Oct edition,
whose private files may not be on your computer.

## What preparation does

- **English only.** A real script and language check rejects clearly non-English
  stories. The source's `language: en` is not trusted on its own.
- **Cleaning.** It reuses the project's cleaner and its repeated-line rules
  ([`ml/configs/boilerplate.yaml`](../../ml/configs/boilerplate.yaml)).
- **Input text.** Headline plus the first 250 cleaned body words. If there is no
  body, it uses the summary, then the headline.
- **Copies.** It groups near-copies of the same story, so a reader is not shown the
  same news twice.
- **Dates.** Each row keeps the story's `source_id`, the source's `domains`, and
  whether its date is verified.
- **Training split.** The oldest 80% of stories (by collection time) train the
  methods. The newest 20% check them.
- **Topic circles.** Eight content groups (MiniBatchKMeans) give the "threads" in the
  reader. Their labels are top words from real stories, not checked topics.

## What a snapshot folder holds

| Files | What they are |
| --- | --- |
| `documents.jsonl`, `manifest.json`, `boilerplate.json` | The prepared stories, their IDs and dates, and a fingerprint of the content |
| `groups.json`, `train.npy`, `baseline.json` | Near-copy groups, the training split and the baseline settings |
| `preprocessing.joblib`, `tfidf.npz`, `svd.npy` | The fitted TF-IDF and SVD |
| `autoencoder.keras`, `encoder.keras`, `latent_center.npy` | The trained neural network |
| `neural.npy`, `assignments.npy`, `topics.json`, `clusters.joblib` | Story vectors, content groups and starter stories |
| `training.json` | Versions, seeds, sizes, losses, timings and fingerprints |
| `benchmark.json`, `evaluation-cases.json`, `judgements.jsonl` | Written by `rec-benchmark`: the test cases and a blind sheet for people to grade |
| `relevance*.json`, `ai-*.json*`, `api-latency.json`, `rehearsal.json` | Results, when they have been measured |

Snapshot folders hold publishers' text, so they stay out of git. Load only snapshots
you built yourself: `joblib` files can run code when loaded.

## The ranker service

`make -C ml demo-serve` or `make -C ml rec-serve REC_ID=<id>` serves on
`127.0.0.1:8001`. In a container, gunicorn runs `newsrec.api:create_app()` with 1
worker and 4 threads, and `NEWSREC_MODEL_DIR` names the snapshot folder.

| Setting | Meaning |
| --- | --- |
| `NEWSREC_MODEL_DIR` | The snapshot folder to load. Required for gunicorn |
| `NEWS_RECOMMENDER_API_KEY` | If set, every request except `/health/...` must send it in the `X-Recommender-Key` header. Never put it in browser code |

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/health/live`, `/health/ready` | `{"status": "ready", "snapshot_id": ...}` |
| `GET` | `/v1/meta` | The snapshot's details, its topic circles, counts and `default_method` |
| `POST` | `/v1/recommend` | Ranked story IDs (see below) |

A request to `/v1/recommend` may have these fields:

| Field | Meaning | Limit |
| --- | --- | --- |
| `method` | `tfidf` (the default), `svd` or `neural` | — |
| `limit` | How many stories to return; default 12 | 1–30 |
| `seed_id` | A story to find related stories for | — |
| `liked`, `disliked` | Story IDs the reader chose | 50 each |
| `viewed` | Story IDs to leave out | 2,000 |
| `topic` | One topic circle | — |
| `window` | `fresh`, `yesterday`, `archive`, or empty for everything | — |
| `domains` | Keep only sources with these tags | 8 tags |

The body may be at most 128 KiB. An unknown story ID gets `404`; any other bad input
gets `400`.

The windows:

- **`fresh`**: a verified publish date, 0 to 30 days old (roadmap C2).
- **`yesterday`**: verified, and published on the latest edition day in India time
  (Asia/Kolkata). The edition for a day opens at 06:00 the next morning. It is
  worked out on each request, not stored.
- **`archive`**: everything that is not fresh, including stories with unverified
  dates.

The ranker leaves out the seed story, the reader's chosen and viewed stories, and
their near-copies. It also spreads results across publishers.

The web server's `POST /api/v1/recommendations` passes these fields to the ranker,
then adds each story's details from MongoDB. See the [server guide](server.md).

**Limits today:** a snapshot is a fixed copy. New stories appear only after a new
snapshot and a ranker restart. "Fresh" and "Yesterday" follow the clock, so an old
snapshot can show an empty Fresh or Yesterday view.

## Grade the results

```bash
make -C ml rec-benchmark REC_ID=<id>
```

This picks 40 fixed test cases (30 article queries and 10 made-up interest
profiles). It writes a blind sheet, `judgements.jsonl`, that pools each method's top
five without method names. A person grades each line: 0 = unrelated, 1 = loosely
related, 2 = useful. Then, from `ml/`:

```bash
uv run --no-sync newsrec score --id <id> --judgements artifacts/recommender/<id>/judgements.jsonl
```

- Add `--case <case-id>` (more than once) to score only some cases.
- Grades made by an AI go in a separate sheet and need `--label-source ai-assisted`.
  The scorer refuses to mix the two kinds (project hard rule 4).
- `newsrec measure --id <id>` times the web API on the same cases (by default
  `http://127.0.0.1:8090`). It was written for the old Go reader. The Python server
  keeps the same paths, but `measure` has not been run against it yet.

The V1 target (roadmap C13) is a human "useful" Precision@5 of at least 0.65, and
not below TF-IDF, over 50 frozen cases. It has **not** been met or measured yet.

## Ideas for later

These ideas came from coursework. They are **not approved work**. Each one needs an
owner-approved roadmap task with a measurable goal first.

- Check the eight content groups against other group counts (WCSS, silhouette), and
  read sample stories.
- Add a simple "most popular" baseline next to TF-IDF, on the same test split.
- Measure whether association rules (planned in M5) improve held-out results.
- Tune neural models only on development data, and compare them with TF-IDF and SVD.
- Try PCA as an alternative to SVD; use t-SNE only for pictures.
- Compare other distance measures with cosine, on the same cases.
- Try a small, limited amount of exploration (for example epsilon-greedy) to show
  readers new topics.
- Sequence models (LSTM, GRU) or reinforcement learning only if there is much more
  reader data. There is not today.

Reconstruction loss, cluster scores and topic agreement are only hints. They are not
proof of useful recommendations.

## Checks

From `ml/`:

```bash
make rec-test                                         # the recommender tests
uv run --no-sync pytest --cov=newsrec --cov-branch    # the same, with coverage
```
