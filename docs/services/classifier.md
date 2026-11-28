# Classifier

The classifier is a small Python web service. The collector sends it news stories.
For each story it answers with:

- a **topic**: one of 13, such as `sport` or `politics`, or `unsorted` when the
  model is not sure enough;
- a **confidence** score;
- cleaned copies of the title, summary and body, with repeated lines such as
  "Subscribe now" removed;
- the language it detected, with a confidence score.

Hard words are explained in the [glossary](../glossary.md).

## At a glance

| Item | Value |
| --- | --- |
| Code | [`ml/classifier/app/api.py`](../../ml/classifier/app/api.py), using the packages in [`ml/src`](../../ml/README.md) |
| Port | 8000 |
| Docker image | `ghcr.io/mhd-riaz/news-collector-classifier`, built from [`ml/classifier/Dockerfile`](../../ml/classifier/Dockerfile) |
| Production model | `v4-ai-072b01a9ceaf-hybrid_svc` (approved by the owner on 27 Nov 2026, roadmap D19) |
| Model list | [`ml/models.toml`](../../ml/models.toml) |
| Topic list | [`ml/taxonomy.yaml`](../../ml/taxonomy.yaml) and the [labelling guide](../../data/labels/labelling-guide.md) |

The 13 topics are `business_economy`, `conflict_war`, `crime_justice`,
`disaster_accident`, `education`, `entertainment_arts`, `environment_climate`,
`health`, `politics`, `science_space`, `society_lifestyle`, `sport` and `technology`.

## Its API

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/health/live`, `/health/ready` | Answers `{"status": "ok", "model_version": ...}` once the model has loaded |
| `GET` | `/v1/meta` | The model's name, its confidence cut and its topics |
| `POST` | `/v1/classify` | Sorts a batch of stories (see below) |

A request to `/v1/classify` looks like this:

```json
{"items": [{"id": "a1", "title": "...", "summary": "...", "body": "...", "source": "..."}]}
```

Each answer item has `id`, `topic`, `confidence`, `filed` (whether the confidence
passed the cut), `clean_title`, `clean_summary`, `clean_body`, `language` and
`language_confidence`. An item with no text at all gets an `error` instead.

When `NEWSML_API_KEY` is set, every request except `/health/...` must send the same
key in the `X-Classifier-Key` header. A wrong key gets `401`.

## Settings

| Variable | Meaning |
| --- | --- |
| `NEWSML_MODEL_DIR` | The folder that holds `bundle.joblib`. Required |
| `NEWSML_API_KEY` | The shared key. The collector sends it from `NEWS_CLASSIFIER_API_KEY` |
| `NEWSML_MAX_BATCH` | Most stories in one request. Default 100 |
| `NEWSML_MAX_REQUEST_BYTES` | Largest request. Default 1 MiB |
| `NEWSML_TAXONOMY_PATH` | Another topic list to use. Optional |
| `NEWSML_MODEL_SHA256` | Used only by the production start command. It checks `bundle.joblib` against this **SHA-256** fingerprint before starting |

The image runs gunicorn (a web server for Python programs) with 1 worker, 4 threads
and a 120-second time limit. It loads its sentence encoder from inside the image,
with no internet (`HF_HUB_OFFLINE=1`).

## Get the model

Model files are big, so they are **not in git**. [`ml/models.toml`](../../ml/models.toml)
lists each model: where to download it, and the SHA-256 fingerprint of every file. A
fingerprint changes if even one byte of the file changes.

The production model is the file `classifier-v4-ai-072b01a9ceaf.tar.gz` in the
project's **public** Google Drive folder (its link is in `ml/models.toml`). Anyone can
download it; no sign-in is needed. A backup copy is the release of the same name in the
private repository `mhd-riaz/news-bot-archive`. From the repository root, run:

```bash
make -C ml models         # downloads into ml/models/ and checks every fingerprint
make -C ml models-check   # only checks; downloads nothing
```

The model lands in `ml/models/classifier/v4-ai-072b01a9ceaf/`, with three files:
`bundle.joblib`, `manifest.json` and `model-card.md`. A file that is already there
with the right fingerprint is not downloaded again. The laptop Compose file mounts
this folder, and `run.sh` downloads it for you.

## Deploy the V4 classifier (D19)

The owner approved this model for production on 27 Nov 2026 (roadmap D19). The code
is ready. The production steps are the owner's, and they have **not been done yet**.

**The production checksum.** Production must use exactly this `bundle.joblib`
(44.5 MB). Its SHA-256 is:

```text
61cbaa89016d1acd88473cad2cf59cec69e74177aabe123bafa0a9c9f6c22fde
```

It is the same value as `bundle.joblib` in `ml/models.toml`.
[`coolify.compose.yml`](../../deployment/compose/coolify.compose.yml) uses it unless
`NEWS_CLASSIFIER_MODEL_SHA256` is set in Coolify. The production start command refuses
any other file.

Steps:

1. Publish the classifier image and redeploy. Publishing happens only when the GitHub
   variable `DEPLOY_ENABLED` is `true`; see [Operations](../operations/README.md). On
   its first start, the classifier downloads the model from Google Drive into its
   `classifier-models` volume and checks every file; nothing needs copying by hand.
   It gets 1.5 GB of memory and 120 seconds to start.
2. Check that `GET /v1/meta` (with the classifier key) reports `model_version`
   `v4-ai-072b01a9ceaf-hybrid_svc` and 14 topics (the 13 topics plus `unsorted`).
3. Relabel the stories already in the database. From the repository root, run
   `make -C collector backfill-reclassify BACKFILL_LIMIT=<n>` with production
   settings, or run the same program inside the production `api` container
   (`/app/backfill -reclassify`). Repeat it until it reports `updated` as 0. It
   changes only `topic`, `confidence`, `model_version`, `classification_status` and
   `classified_at`. It never touches the story text.

Until step 3 runs, older stories keep the topics of the earlier model `v2-001`.

A topic-only change does not move a story's `updated_at` or `content_rev`. So a
future pipeline that watches those fields will not notice relabelled stories.

## Roll back

`v2-001` is not in `ml/models.toml`, so the classifier cannot download it. On 27 Nov
2026 no `v2-001` `bundle.joblib` was found on the laptop or in the archive release.
The only copy may be on the production machine's old external `classifier-models`
volume, which was filled by hand and is no longer mounted. To look:
`docker run --rm -v classifier-models:/m alpine ls /m`. If it is there:

1. In `coolify.compose.yml`, mount that volume instead (`external: true`), point
   `NEWSML_MODEL_DIR` at its `v2-001` folder, set `NEWS_CLASSIFIER_MODEL_SHA256` to that
   bundle's SHA-256, and remove the download line from the start command.
2. Redeploy, then run `make -C collector backfill-reclassify` again.

## Measured speed and memory

On a laptop, 27 Nov 2026 (macOS arm64, Python 3.13, the image's pinned packages):
start-up with model load and warm-up took 6.6 s (about 20 s on a cold first run). A
batch of 50 long stories took 0.83 s. Memory was 702 MB after warm-up and 893 MB at
its highest.

In the Linux arm64 image, 27 Nov 2026 (Python 3.12, one CPU, roadmap RS2): the image
is 2.11 GB (491 MB compressed). It was ready about 10 s after start. Memory was
582 MiB after warm-up and 626 MiB after six 50-story batches. A batch of 50 short
made-up stories took 2.19–2.68 s (median 2.25 s over five runs). That is inside the
collector's 10-second limit. With the whole app running on 27 Nov (Docker Compose and
k3s, roadmap RS6/RS7), the classifier used 0.75–0.98 GB, under its 1.5 GB limit.

**Not measured:** the amd64 image that CI builds.

## How the model was made

The model was trained on the labels in [`data/labels/`](../../data/labels/README.md):
8,594 articles. 6,875 were used for training, and 1,719 were kept apart as a
**test set**. That README says how the labels were made, and so what the scores below
mean.

The trainer (`newsmlv4.train`) compared eight methods on the same splits. It chose
the simplest one that no other method clearly beat: `hybrid_svc`, which uses word
features plus MiniLM sentence features with a linear model.

| Measure | Recorded result |
| --- | --- |
| Macro-F1 on the test set (opened once) | 0.8246 [0.8056, 0.8442] |
| Accuracy on the test set | 0.829 |
| Calibration | sigmoid; log loss 0.5742, against 0.6041 for isotonic |
| Confidence cut | 0.2059; 0.8143 agreement in cross-validation, with every story filed |
| Training time and memory | 863.36 s; 5.23 GB at its highest |

**Not met:** checking by people (human validation), and 200 labels made by people for
each topic. The owner approved production use without them (D19).

The model card and manifest are private. They are in the downloaded folder
`ml/models/classifier/v4-ai-072b01a9ceaf/`.

## Train a new model

From `ml/`, after `make setup`:

```bash
make ml4-train DATASET=v4-ai-pooled-20261122T000000Z
```

The pooled label set lives in the private folder `ml/artifacts/v4/`, which git
ignores. The trainer writes a new folder under `ml/models/classifier/`. It refuses to
overwrite a model that already exists, because training again on the same labels
would reopen their test set.

A new model goes to production only with the owner's approval (project hard rule 5).
The [update-classifier-model skill](../../.github/skills/update-classifier-model/SKILL.md)
lists how to publish one so that `make -C ml models` can download it.

## Label more articles

The owner may still ask people to label more articles (roadmap ML4.5, now an open
choice under RS3). Labels made by people must go in a separate file. Never mix them
into `data/labels/labels.jsonl` (project hard rule 4).

- Reviewers follow the [labelling guide](../../data/labels/labelling-guide.md) and the
  [reviewer instructions](../../data/labels/reviewer-instructions.md).
- The Make commands, all run from `ml/`, are:
  - `make ml4-labels-export` writes blind CSV sheets for reviewers. It needs
    `NEWS_ML_MONGO_URI` pointing at a **local**, read-only copy of the database. It
    stops with a message until the old label rounds are restored from git tag
    `before-restructure`. It needs them to skip stories that were already labelled.
  - `make ml4-labels-verify RUN=<run>` checks that the stories and the sheets have
    not changed since the export.
  - `make ml4-labels-import RUN=<run>` checks the filled sheets and writes their
    labels.
  - `make ml4-labels-import-exported RUN=<run>` imports when the database used for
    the export is gone. Use it only with an owner decision (roadmap D14).
  - `make ml4-train RUNS="<run>"` trains from labels made by people. Add
    `WEAK_RUNS=` for extra labels that may help training but never score a model.
    Add `ACCEPT_SHORTFALL=1` only when the owner accepts a topic with too few labels.

The older, longer version of this guide is in git history: `collector/ml-v4/README.md`
at tag `before-restructure`, and the earlier versions of this file.

## Checks

From `ml/`:

```bash
make classifier-test   # the web service tests
make ml4-test          # the V4 sampler, label pool, trainer and serving tests
make test              # every ML test
```
