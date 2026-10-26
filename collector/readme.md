# Beyond the Headline: Calibrated News Article Classifier

**Supervised Machine Learning — Classification · Mini Project**
Mohamed Riaz · PES1PGE25DS037 · Department of CSE, PES University

A news article goes in; one of 13 topics comes out, with a confidence score you can
actually act on — and the model is allowed to say *"I don't know"* rather than guess.

Everything here was built from scratch: the collector that gathered the corpus, the
8,001 hand labels, the preparation pipeline, the classifier, the evaluation harness and
the demo. No large language model is used anywhere. Every prediction is explainable from
the model's own weights.

## The result

| | |
| --- | --- |
| **Test macro-F1** | **0.751** [0.719, 0.780] — on a split opened exactly once |
| **Accuracy on the articles it files** | **83.4%**, against 77.7% if forced to answer everything |
| **Coverage** | 80.7% filed automatically; the rest routed to a human |
| **Calibration error (test)** | 0.021 — the confidence number is honest |
| Corpus | 14,189 articles · 40 publishers · 8,001 human labels · 13 classes |
| Cost | 0.78 ms per article |

**The research question was whether the article body beats the headline.** It does, by
**+0.059 macro-F1** (0.712 → 0.771), with non-overlapping bootstrap intervals and
McNemar *p* = 7.5 × 10⁻⁶.

**The second finding is that nothing else helped.** Entity scrubbing, feature
engineering, gradient-boosted trees, random forests, sentence embeddings and four
ensembles were each measured against a linear SVM and each lost or tied. The accuracy
came from data preparation, not from model capacity.

## Try it

```bash
cd ml-v2
uv sync --group dev --group demo
uv run newsmlv2 train --id v2-001          # fit + persist the model (~3 min)
uv run streamlit run app/streamlit_app.py  # http://localhost:8501
```

Four tabs: **Classify an article** (paste anything, or press *a real one it is unsure
about* to pull a genuinely hard article out of the corpus), **Validation** (per-class
intervals, reliability diagram, confusion matrix), **Run it on the corpus** (batch
classification over real unlabelled news) and **How it was built**.

Or from the command line:

```bash
uv run newsmlv2 predict \
  --title "Reserve Bank holds repo rate steady as inflation cools" \
  --body  "The monetary policy committee voted five to one to keep the benchmark ..."

# business_economy       0.961   FILED
# (cut 0.584)
#   because of: rate, dollar, growth, bank, bond, inflation, bond yields, reserve
```

## Submission deliverables

| Deliverable | Where |
| --- | --- |
| Working project | [ml-v2/](ml-v2/) — 133 tests, `uv run pytest` |
| User interface | [ml-v2/app/streamlit_app.py](ml-v2/app/streamlit_app.py) |
| Validation evidence | [ml-v2/docs/plan.md](ml-v2/docs/plan.md) · [model card](ml-v2/artifacts/models/v2-001/model-card.md) · Validation tab in the UI |
| 2-page IEEE report | [submission/report/ieee-report.tex](submission/report/ieee-report.tex) |
| Slide deck | [submission/slides/](submission/slides/) — `build_deck.py` writes the `.pptx` |
| Long-form report | [docs/project-report.md](docs/project-report.md) |
| Submission checklist | [submission/README.md](submission/README.md) |

## How it works

```
RSS/Atom feeds ──▶ collector (Go) ──▶ MongoDB
                                        │
                        clean · admit · group near-duplicates
                                        │
                              frozen Parquet snapshot
                                        │
              word 1–2 grams + char 3–5 grams  ──▶  linear SVM
                                        │
                       isotonic calibration ──▶ probability
                                        │
                     above the cut? ──▶ file it.  below? ──▶ hand it to a person
```

Three things in that chain are worth more than the classifier:

- **Boilerplate removal.** 355 repeated furniture lines across 47 sources, including
  multi-sentence author biographies that a length-based rule cannot reach. A cricket
  correspondent's bio inside a business article drags it toward `sport`.
- **Near-duplicate story grouping**, so a syndicated copy of a training article can
  never land in validation. Precision 0.86 at recall 0.81 on 43 hand-judged pairs.
- **Grouped, temporal splits** with bootstrap intervals resampled over *story groups*
  rather than articles, because syndicated copies are not independent observations.

## Repository map

| Path | What it is |
| --- | --- |
| [ml-v2/](ml-v2/) | **The submitted project.** Body-aware classifier, evaluation harness, demo UI |
| `ml-v2/src/newsmlv2/` | clean · admit · dedup · snapshot · splits · models · confidence · serve |
| `ml-v2/scripts/` | one script per experiment phase; results land in the ledger |
| `ml-v2/docs/plan.md` | the full experiment log — every decision with its evidence |
| [ml/](ml/) | version 1, headline-only. Kept as the baseline v2 is measured against |
| [submission/](submission/) | IEEE report, slide deck, figures |
| [docs/](docs/) | long-form project report and the overall plan |
| `cmd/` `internal/` `configs/` | the Go collector that produced the corpus |

## Reproducing the numbers

```bash
cd ml-v2
uv sync --group dev
uv run pytest                                  # 133 tests
uv run newsmlv2 verify --id v2-001             # snapshot digests still match
uv run newsmlv2 train  --id v2-001             # refit, rescore, rewrite the model card
uv run python scripts/build_figures.py         # the report figures
```

The snapshot is frozen at `collected_before = 2026-08-26T12:00:00Z` and its manifest
pins the git SHA, the seed, the cleaning version and a SHA-256 digest of the label file,
so any number traces back to the exact code and labels that produced it.

**The test split has been opened once and is closed.** `scripts/phase_h4_open_test.py`
is the single door, it refuses to run without `--yes`, and it must not be run again — a
held-out split stops being held out the moment it informs a decision.

## Honest limitations

- The collection window is four days, so nothing here measures topic drift over weeks.
- `society_lifestyle` scores F1 0.42; it is a definitional grab-bag of community, labour
  and lifestyle reporting. It still calibrates honestly, so abstention protects it.
- `education` has 29 validation articles and an interval a quarter of an F1 point wide.
  That is noise, and it is reported as noise.
- ~18.6% of errors sit on class pairs where the human annotators disagreed with each
  other, so macro-F1 has a real ceiling below 1.0.
- English only, and India-heavy.

---

# Reference — the collector service

Everything below documents the Go service that gathered the corpus. It is Phase 1 of the
wider project and is independent of the classifier: the ML pipeline reads its database
read-only and never writes to it.

> **Status: Phase 1 complete (Milestone 6).** Configuration, logging, MongoDB
> connection management, health endpoints, the migration and the container stack
> (M1); the source model, persistence layer, management APIs and seeding CLI
> (M2); the SSRF-guarded HTTP client and the RSS/Atom collector (M3); the article
> model and the processing pipeline (M4); the scheduler, per-source leases, run
> history and the collector CLI (M5); and the article query APIs (M6). Feeds
> are configured, collected on a schedule, deduplicated, stored and readable.

## Requirements

- Go 1.26+
- Docker and Docker Compose (for the local MongoDB and the container build)

## Quick start with Docker Compose

Secrets come from `.env`, which is gitignored and never baked into the image.
Create it first — the API refuses to start with auth enabled and no credentials:

```bash
cp .env.example .env
openssl rand -hex 32          # paste into NEWS_AUTH_API_KEYS
```

Starts MongoDB, then the API — which migrates the database and applies
`configs/sources.yaml` itself before it serves:

```bash
make up
curl -s localhost:8080/health/live
curl -s localhost:8080/health/ready
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/collection-runs?limit=5'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?limit=5'
make logs
make down          # stops the stack and deletes the volume
```

The API process also runs the scheduler, so feeds start being collected as soon
as it is up.

## Quick start without Docker

```bash
make mongo-up                      # MongoDB only, on localhost:27017
make run                           # migrate, apply sources.yaml, serve on :8080
make collect                       # collect everything currently due, once
make backfill                      # backfill up to 1000 legacy articles
```

`make migrate` and `make seed` do the two startup steps on their own, against a
database the API is already serving.

The C1 backfill processes at most 50 articles per classifier request, pauses one
second between full batches, and resumes from articles without `content_rev`.
It writes cleaned text, detected language and date provenance only; raw article
text and existing topics are left untouched. Set `BACKFILL_LIMIT` or
`BACKFILL_DELAY` to adjust a run, then rerun `make backfill` until no work
remains.

## Verification gates

```bash
make check                         # gofmt check + go vet + go test ./...
make test-race                     # unit tests under the race detector
make cover                         # coverage summary
make test-integration              # needs MongoDB on localhost:27017
make seed-check                    # validate configs/sources.yaml, write nothing
make build                         # binaries into ./bin
make ml-test                       # offline ML suite (Python, see below)
```

Unit tests never contact a network service. The integration tests are behind the
`integration` build tag, use a database name unique per run, and drop it afterwards.

## Configuration

Three layers, each overriding the one before: built-in defaults →
[configs/config.yaml](configs/config.yaml) → environment variables. Every key maps to
`NEWS_<SECTION>_<KEY>`. Unknown YAML keys are rejected at startup so a typo fails fast.

| Key                                | Environment variable                    | Default                     |
| ---------------------------------- | --------------------------------------- | --------------------------- |
| `app.name`                         | `NEWS_APP_NAME`                         | `news-collector`            |
| `app.environment`                  | `NEWS_APP_ENVIRONMENT`                  | `development`               |
| `server.host`                      | `NEWS_SERVER_HOST`                      | `0.0.0.0`                   |
| `server.port`                      | `NEWS_SERVER_PORT`                      | `8080`                      |
| `server.read_header_timeout`       | `NEWS_SERVER_READ_HEADER_TIMEOUT`       | `5s`                        |
| `server.read_timeout`              | `NEWS_SERVER_READ_TIMEOUT`              | `15s`                       |
| `server.write_timeout`             | `NEWS_SERVER_WRITE_TIMEOUT`             | `30s`                       |
| `server.idle_timeout`              | `NEWS_SERVER_IDLE_TIMEOUT`              | `60s`                       |
| `server.shutdown_timeout`          | `NEWS_SERVER_SHUTDOWN_TIMEOUT`          | `15s`                       |
| `server.max_header_bytes`          | `NEWS_SERVER_MAX_HEADER_BYTES`          | `1048576`                   |
| `auth.enabled`                     | `NEWS_AUTH_ENABLED`                     | `true` (via config file)    |
| `auth.api_key_header`              | `NEWS_AUTH_API_KEY_HEADER`              | `X-API-Key`                 |
| —                                  | `NEWS_AUTH_API_KEYS`                    | none                        |
| —                                  | `NEWS_AUTH_BASIC_USERNAME`              | none                        |
| —                                  | `NEWS_AUTH_BASIC_PASSWORD`              | none                        |
| `mongo.uri`                        | `NEWS_MONGO_URI`                        | `mongodb://localhost:27017` |
| `mongo.database`                   | `NEWS_MONGO_DATABASE`                   | `news`                      |
| `mongo.connect_timeout`            | `NEWS_MONGO_CONNECT_TIMEOUT`            | `10s`                       |
| `mongo.server_selection_timeout`   | `NEWS_MONGO_SERVER_SELECTION_TIMEOUT`   | `10s`                       |
| `mongo.operation_timeout`          | `NEWS_MONGO_OPERATION_TIMEOUT`          | `30s`                       |
| `mongo.max_connection_idle_time`   | `NEWS_MONGO_MAX_CONNECTION_IDLE_TIME`    | `0` (keep URI/driver policy) |
| `mongo.max_pool_size`              | `NEWS_MONGO_MAX_POOL_SIZE`              | `50`                        |
| `mongo.min_pool_size`              | `NEWS_MONGO_MIN_POOL_SIZE`              | `0`                         |
| `bootstrap.migrate`                | `NEWS_BOOTSTRAP_MIGRATE`                | `true`                      |
| `bootstrap.sources_path`           | `NEWS_BOOTSTRAP_SOURCES_PATH`           | `configs/sources.yaml`      |
| `bootstrap.timeout`                | `NEWS_BOOTSTRAP_TIMEOUT`                | `2m`                        |
| `collector.user_agent`             | `NEWS_COLLECTOR_USER_AGENT`             | `news-collector/1.0 (...)`  |
| `collector.request_timeout`        | `NEWS_COLLECTOR_REQUEST_TIMEOUT`        | `20s`                       |
| `collector.max_response_bytes`     | `NEWS_COLLECTOR_MAX_RESPONSE_BYTES`     | `10485760`                  |
| `collector.max_redirects`          | `NEWS_COLLECTOR_MAX_REDIRECTS`          | `5`                         |
| `collector.max_items_per_feed`     | `NEWS_COLLECTOR_MAX_ITEMS_PER_FEED`     | `500`                       |
| `collector.allow_private_networks` | `NEWS_COLLECTOR_ALLOW_PRIVATE_NETWORKS` | `false`                     |
| `scheduler.enabled`                | `NEWS_SCHEDULER_ENABLED`                | `true`                      |
| `scheduler.interval`               | `NEWS_SCHEDULER_INTERVAL`               | `60s`                       |
| `scheduler.batch_size`             | `NEWS_SCHEDULER_BATCH_SIZE`             | `50`                        |
| `scheduler.max_concurrent`         | `NEWS_SCHEDULER_MAX_CONCURRENT`         | `4`                         |
| `scheduler.lock_ttl`               | `NEWS_SCHEDULER_LOCK_TTL`               | `5m`                        |
| `logging.level`                    | `NEWS_LOGGING_LEVEL`                    | `info`                      |
| `logging.format`                   | `NEWS_LOGGING_FORMAT`                   | `json`                      |

`NEWS_CONFIG_PATH` selects a different config file without passing `-config`.

### Secrets come from the environment, not the config file

The three credential rows above have no YAML key on purpose. They are read only
from the environment, so a secret cannot be committed in `configs/config.yaml` —
putting one there fails the load rather than being quietly honoured.

Every command loads `.env` before reading its configuration. Variables already
present in the environment are left alone, so the file never shadows a real
value: the same binary reads secrets from `.env` on a laptop and from Coolify's
injected environment in the homelab, with no branch either way. A missing `.env`
is not an error. `NEWS_ENV_FILE` (or `-env`) points at a different file, such as
a mounted secret.

## Authentication

Every `/api/v1` route requires a credential. `/health/live` and `/health/ready`
stay open, because the container healthcheck and the reverse proxy probe them
before any credential is in play and they reveal nothing but liveness.

Two schemes are accepted, and either one alone is sufficient:

```bash
curl -H "X-API-Key: $KEY" localhost:8080/api/v1/sources        # scripts
curl -u operator:secret    localhost:8080/api/v1/sources        # browser, curl
```

- `NEWS_AUTH_API_KEYS` is a comma-separated list, so a key is rotated by adding
  the replacement, moving clients over, then dropping the old one — no window
  where the API is unprotected.
- Keys must be at least 32 characters, basic passwords at least 16.
- The header name is configurable with `NEWS_AUTH_API_KEY_HEADER`, and is
  rejected at startup if it is not a valid HTTP field name.
- Only SHA-256 digests are held in memory, compared in constant time with every
  configured key checked, so neither the value nor the length of a rejected
  credential is observable from timing.
- A rejected request gets `401` with the standard error envelope and a `Basic`
  challenge. It says nothing about which scheme would have worked, and an
  unknown path under `/api/v1` is answered the same way as a known one.
- `auth.enabled: false` is a development convenience and is refused when
  `app.environment` is `production`. Enabling it with no credentials configured
  is a startup error.

## Deployment

[../.github/workflows/news-collector.yml](../.github/workflows/news-collector.yml)
runs the Go, classifier, ML and recommender checks on pull requests and pushes to
`main`. A successful `main` build publishes the Go, classifier and recommender
images to GHCR, then calls Coolify's authenticated deploy webhook. The Go image
contains every `cmd/*` executable; the API and (after M3 authentication is ready)
the reader use the same image with different commands.

On the Coolify side, create a **Docker Compose** resource from
[deployments/coolify.compose.yml](deployments/coolify.compose.yml). It brings up
MongoDB with generated credentials, then starts the API behind a Coolify-issued
domain. There are no one-shot migrate or seed containers: the API reconciles the
schema and the source list itself on every start, because a one-shot container
that has already exited successfully is not guaranteed to be recreated on a
redeploy — and when it is skipped, an edited feed list silently never reaches
the database.

Set these in the Coolify UI before the first deploy — the compose file marks
them required, so a missing one fails the deployment instead of starting an
unguarded API:

| Variable                      | Notes                                            |
| ----------------------------- | ------------------------------------------------ |
| `NEWS_AUTH_API_KEYS`          | `openssl rand -hex 32`, comma-separated          |
| `NEWS_AUTH_BASIC_USERNAME`    |                                                  |
| `NEWS_AUTH_BASIC_PASSWORD`    | at least 16 characters                           |
| `NEWS_MONGO_COLLECTOR_PASSWORD` | 64 hex characters; database-scoped collector user |
| `NEWS_IMAGE`                  | optional; pin to a SHA tag to roll back          |
| `NEWS_BOOTSTRAP_SOURCES_PATH` | optional; an https URL to change feeds unrebuilt |
| `NEWS_CLASSIFIER_API_KEY`     | shared internal API key for the classifier       |
| `NEWS_CLASSIFIER_MODEL_SHA256`| `sha256sum` of `v2-001/bundle.joblib`            |
| `NEWS_CLASSIFIER_IMAGE`       | optional; pin classifier to a SHA tag            |

Before the first production deploy, create the database users once as MongoDB
root. Supply `NEWS_MONGO_ROOT_URI`, `NEWS_MONGO_DATABASE`, and distinct
`NEWS_MONGO_{COLLECTOR,BATCH,RANKER,READER,OWNER}_PASSWORD` values through a
secure environment; each password must be generated as 64 hex characters (for
example, `openssl rand -hex 32`). Run:

```bash
mongosh "$NEWS_MONGO_ROOT_URI" --quiet --file deployments/mongo-users.js
```

Store the generated passwords in Coolify secrets. MongoDB enforces each
principal's collection permissions; ownership of reader-added sources is
checked by the reader application, not by MongoDB roles.

And these as GitHub repository secrets:

| Secret            | Notes                                    |
| ----------------- | ---------------------------------------- |
| `COOLIFY_WEBHOOK` | the resource's Deploy Webhook URL        |
| `COOLIFY_TOKEN`   | Coolify API token with deploy permission |

Both are required for a successful `main` deployment. The deploy-only token is
sent in the `Authorization` header and neither secret is written to logs. Roll
back by setting `NEWS_IMAGE` to a previous `sha-` tag and redeploying.

`GITHUB_TOKEN` covers the GHCR push. If the package is private, authenticate the
homelab's Docker daemon once:

```bash
echo "$GH_TOKEN" | docker login ghcr.io -u <username> --password-stdin
```

## Sources

Feeds are declared in [configs/sources.yaml](configs/sources.yaml). The API applies
them at startup, so adding a feed is an edit and a restart; `make seed` applies an
edited file to a running database without one. Either way it is idempotent and matches
on `feed_url`, so re-running updates rather than duplicates. An omitted optional key
keeps whatever is already stored, so a value tuned through the API is never reset. A
source stored but absent from the file is left alone: this reconciles, it does not
prune. `make seed-check` validates the whole file without writing, and a file containing
an invalid entry is rejected in full rather than applied halfway.

`bootstrap.sources_path` takes a filesystem path or an **https URL**. The default reads
the copy baked into the image, so a new feed needs a rebuild. Point it at the raw URL of
this file on `main` instead and the list is read fresh on every start — adding a feed is
then a commit and a restart, with no image rebuild:

```
NEWS_BOOTSTRAP_SOURCES_PATH=https://raw.githubusercontent.com/mhd-riaz/data-scientist-roadmap/main/semester-1/06-supervised-ml-classification/mini-project/news/configs/sources.yaml
```

Plaintext `http://` is refused: this file decides which URLs the collector then fetches,
so anyone able to rewrite it in transit would be choosing that for us. A remote list that
cannot be read is logged at error level and leaves the stored sources in place rather
than stopping the collector — unlike a local one, where an unreadable or invalid file is
an operator mistake and fails the start. Setting `sources_path` to `""` turns the startup
sync off entirely, for a deployment that manages sources only through the API.

| Field                    | Required | Rule                                   |
| ------------------------ | -------- | -------------------------------------- |
| `name`                   | yes      | 1-200 characters                       |
| `feed_url`               | yes      | `http`/`https`, no credentials, unique |
| `type`                   | yes      | `rss` or `atom`                        |
| `language`               | yes      | two-letter ISO 639-1 code              |
| `country`                | yes      | two-letter ISO 3166-1 alpha-2 code     |
| `state`, `city`          | no       | up to 100 characters                   |
| `domains`                | no       | up to 20 lowercase slug tags (64 chars each) |
| `added_by`               | no       | reader UUID; seed/internal only        |
| `enabled`                | no       | defaults to `true`                     |
| `priority`               | no       | 0-100, defaults to 50                  |
| `fetch_interval_seconds` | no       | 60-604800, defaults to 900             |

`health_status`, `consecutive_failures`, `last_error`, `last_collected_at`,
`next_scheduled_at` and the timestamps are owned by the server. A request that tries to
set one is rejected rather than ignored. `added_by` is also server-owned in the API:
it is returned when present, but API callers cannot set or change it until reader identity
is available. `domains` can be supplied on create or update; an empty list clears the tags.

## Endpoints

| Method   | Path                           | Purpose                                     | Milestone |
| -------- | ------------------------------ | ------------------------------------------- | --------- |
| `GET`    | `/health/live`                 | Process is running; never touches MongoDB   | 1         |
| `GET`    | `/health/ready`                | `200` when MongoDB answers, `503` otherwise | 1         |
| `POST`   | `/api/v1/sources`              | Register a feed                             | 2         |
| `GET`    | `/api/v1/sources`              | List feeds, filtered and paginated          | 2         |
| `GET`    | `/api/v1/sources/{id}`         | Fetch one feed                              | 2         |
| `PATCH`  | `/api/v1/sources/{id}`         | Partially update a feed                     | 2         |
| `DELETE` | `/api/v1/sources/{id}`         | Remove a feed                               | 2         |
| `GET`    | `/api/v1/collection-runs`      | List collection attempts                    | 5         |
| `GET`    | `/api/v1/collection-runs/{id}` | Fetch one collection attempt                | 5         |
| `GET`    | `/api/v1/articles`             | List articles, filtered and paginated       | 6         |
| `DELETE` | `/api/v1/articles`             | Expire articles older than a given date     | 6         |
| `GET`    | `/api/v1/articles/{id}`        | Fetch one article, content included         | 6         |
| `GET`    | `/`                            | Reader feed, newest first                   | 7         |
| `GET`    | `/articles/{id}`               | Reader article page; records the click      | 7         |
| `POST`   | `/read-events`                 | Impression and dwell telemetry              | 7         |

Liveness is deliberately independent of MongoDB so a transient database outage causes
a `503` on readiness rather than a restart loop.

Listing sources accepts `enabled`, `type`, `health_status`, `country`, `state`, `city`,
`limit` and `offset`. `limit` defaults to 50 and is capped at 100; asking for more is an
error rather than a silently truncated page, so nobody builds against a page size the
server will not honour.

```bash
curl -s 'localhost:8080/api/v1/sources?country=IN&enabled=true&limit=10'

curl -s -X POST localhost:8080/api/v1/sources \
  -H 'Content-Type: application/json' \
  -d '{"name":"Deccan Herald — Mysuru","feed_url":"https://www.deccanherald.com/rss/mysuru.xml",
       "type":"rss","language":"en","country":"IN","state":"Karnataka","city":"Mysuru"}'

curl -s -X PATCH localhost:8080/api/v1/sources/<id> \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

Every error uses one envelope. Validation failures report every broken rule at once, so
one round trip is enough to fix a payload:

```json
{
  "error": {
    "code": "invalid_input",
    "message": "the request payload is invalid",
    "fields": [{ "field": "priority", "message": "must be between 0 and 100, got 500" }]
  }
}
```

| Code             | Status | Meaning                                   |
| ---------------- | ------ | ----------------------------------------- |
| `invalid_input`  | 400    | The payload or a query parameter is bad   |
| `not_found`      | 404    | No such source, collection run or article |
| `conflict`       | 409    | That feed URL is already registered       |
| `unavailable`    | 503    | A dependency did not answer in time       |
| `internal_error` | 500    | Anything else; detail stays in the logs   |

## Article queries

```bash
curl -s 'localhost:8080/api/v1/articles?country=IN&state=Karnataka&limit=20'
curl -s 'localhost:8080/api/v1/articles?source_id=<id>&sort=collected_at'
curl -s 'localhost:8080/api/v1/articles?published_from=2026-08-01T00:00:00Z'
curl -s localhost:8080/api/v1/articles/<id>
```

| Parameter                        | Effect                                     |
| -------------------------------- | ------------------------------------------ |
| `source_id`                      | Only articles from one feed                |
| `language`                       | Two-letter ISO 639-1 code                  |
| `country`, `state`, `city`       | The region the source is registered under  |
| `published_from`, `published_to` | RFC 3339 bounds on the publication date    |
| `sort`                           | `published_at` (default) or `collected_at` |
| `limit`                          | Defaults to 50, capped at 100              |
| `cursor`                         | The `next_cursor` of the previous page     |

Both orders are newest first, and each is served by its own index. `collected_at` is the
one to poll on: a publisher back-dating an article cannot make it appear behind a reader
who has already paged past that date.

### Paging is by cursor, not offset

Sources page by `offset` and articles do not, and the inconsistency is deliberate.
Sources are an operator-sized set; articles accumulate without bound and arrive
continuously. `offset=10000` makes MongoDB walk and discard ten thousand index entries,
and because new articles land above the reader, an offset walk shows some articles twice
and skips others.

A page therefore returns `has_more` and an opaque `next_cursor` naming the last article
on it; passing that back resumes strictly after it. The token encodes the sort value and
the article id, and both halves are validated on the way in, so a tampered cursor is a
`400` rather than a silent restart from the top — a reader that quietly restarted would
process the same articles again.

```bash
curl -s 'localhost:8080/api/v1/articles?limit=2'
curl -s 'localhost:8080/api/v1/articles?limit=2&cursor=MTc2Njk5MDgwMDAwMC4wMTk4...'
```

There is no `total`. Counting a filtered set of an unbounded collection on every page is
the same walk the cursor exists to avoid.

### Retention

Articles accumulate without bound, so `DELETE /api/v1/articles` expires the old ones. It
is meant to be run on a schedule — a nightly cron against the API is enough.

```bash
curl -s -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z'
curl -s -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z&source_id=<id>'
curl -s -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z&source_name=The+Hindu'
```

| Parameter           | Effect                                                     |
| ------------------- | ---------------------------------------------------------- |
| `delete_older_than` | Required. RFC 3339; deletes articles published before it   |
| `source_id`         | Optional. Only expire one feed's articles                  |
| `source_name`       | Optional. The same, matched on the name stored on articles |

The bound is required and has no default: without one, a mistyped request would empty the
collection. It is exclusive, so an article published exactly at the bound survives and
re-running the same sweep is a no-op. The response is the count, because a caller cannot
otherwise tell a sweep that expired a month of articles from one that matched nothing:

```json
{ "deleted": 1284 }
```

Deleting is by publication date rather than collection date, so it lines up with the
`published_from`/`published_to` bounds a caller already filters listings by.

### Listings omit the article text

An article's `content` is capped at 200 KB, so fifty of them is a response nobody asked
for. A listing projects it away and a caller who wants the text reads the article
itself, where it is always present. The deduplication keys — `dedup_id`,
`normalized_url`, `content_hash` and `feed_guid` — are internal machinery and are never
served.

## Feed collection

A collection is one conditional `GET` through the guarded HTTP client, followed by a
parse. RSS 2.0, RSS 1.0/RDF and Atom are all handled, and the dialect is detected from
the body rather than trusted from the source's `type`, because publishers relabel feeds
more often than they tell anyone.

The stored `ETag` and `Last-Modified` are replayed as `If-None-Match` and
`If-Modified-Since`. A `304` returns no items and leaves the previous collection
standing, which is the cheapest possible poll for both sides.

An entry is dropped when it has no link, or a link that is not an absolute `http`/`https`
URL — a `javascript:` link, for instance. Dropping is counted rather than fatal: one
unusable row must not cost the other fifty articles in the feed. Relative links are
resolved against the feed's declared home page, titles have their line breaks collapsed,
author emails are discarded, and every field is capped before it can reach the database.
An Atom entry that carries only `updated` uses it as its publication date.

Nothing schedules a collection yet: the scheduler and the manual collection CLI arrive
in Milestone 5.

## Scheduling

The scheduler runs inside the API process. Every `scheduler.interval` it asks for the
enabled sources whose `next_scheduled_at` has passed, highest `priority` first, takes at
most `scheduler.batch_size` of them, and collects up to `scheduler.max_concurrent` at
once. A tick starts only once the previous one has finished, so a slow batch delays the
next rather than stacking on top of it, and shutdown waits for the collections already
in flight instead of abandoning them — within the same `server.shutdown_timeout` the
HTTP server gets, so one slow publisher cannot hold the process open. A collection still
running when that elapses loses its lease to the TTL instead of releasing it.

Before collecting a source, a collector takes a lease on it in `application_locks`, and
the resource name is the document `_id`, so the primary key itself is what makes the
lease exclusive — there is no gap between checking for a holder and becoming one. A
source already held is skipped rather than queued, because by the time the lease frees,
the holder has already collected it. The lease expires after `scheduler.lock_ttl`
whether or not it is released, so a collector that crashes mid-collection cannot park a
source forever, and `scheduler.lock_ttl` is required to be longer than
`collector.request_timeout` so a lease can never expire underneath its own fetch.

This is what makes more than one replica safe, and it is why the API and the scheduler
can share a process.

After a collection the source's own schedule and health are rewritten:

| Outcome                 | Health                                   | Next collection                         |
| ----------------------- | ---------------------------------------- | --------------------------------------- |
| Articles stored, or 304 | `healthy`, failure count cleared         | one `fetch_interval_seconds` later      |
| Failed                  | `degraded`, then `failing` at 3 in a row | doubling each failure, capped at 7 days |

Backing a failing source off matters in both directions: it stops this system spending
every tick on a feed that is down, and it stops a publisher being polled every fifteen
minutes for a week after it has broken. A success clears the history immediately, so a
recovered feed returns to its normal interval on its first good poll.
`last_collected_at` answers "when did this feed last give us articles", so a failed
attempt deliberately leaves it alone.

## Collection history

Every attempt is recorded in `collection_runs`, whether it stored articles or not — a
source that has quietly stopped answering is only visible in the record of the attempts
that got nothing.

| Status         | Meaning                                                              |
| -------------- | -------------------------------------------------------------------- |
| `success`      | The feed was read and everything usable in it was stored             |
| `not_modified` | The publisher answered 304; the previous collection is still current |
| `partial`      | Articles were stored, but entries were dropped or the feed was cut   |
| `failed`       | Nothing was collected; `error` says why                              |

`partial` is separate from `success` on purpose: both stored what they could, but a
source shedding entries on every poll is worth being able to find.

```bash
curl -s 'localhost:8080/api/v1/collection-runs?status=failed&limit=20'
curl -s 'localhost:8080/api/v1/collection-runs?source_id=<id>'
curl -s localhost:8080/api/v1/collection-runs/<run-id>
```

The stored `error` is a fixed phrase — "the publisher answered HTTP 404", "the feed
could not be parsed as RSS, RDF or Atom" — chosen from the failure class rather than
copied from the underlying error. The same phrase becomes the source's `last_error`.
Both fields are served by the API, and a raw error there would publish a DNS message, a
driver error or an internal host name to anyone who can reach the port; the full error
goes to the logs instead.

Collections are never triggered over HTTP. The history is read-only.

## Collecting by hand

```bash
make collect                       # everything currently due, once
make collect-source SOURCE=<id>    # one feed now, whatever its schedule says

go run ./cmd/collector -limit 5    # the first five due sources
```

The CLI takes the same leases the scheduler does, so running it against a live
deployment cannot collide with the scheduled collection of the same source. A feed that
fails is a recorded run, not a command failure: the exit code stays zero so one broken
publisher does not abandon the rest of the batch.

`-source` refuses a disabled feed rather than collecting it. Disabled has to mean the
same thing everywhere, or switching a feed off would still leave one way to pull
articles from it.

## Article processing

Each collected item is normalised, checked against what is already stored, and inserted
— one item at a time, so two entries duplicating each other inside a single feed are
caught by the same lookup that catches a duplicate of yesterday's collection.

Normalising an item produces the article: HTML becomes plain text (tags are removed
before entities are decoded, so escaped markup cannot reappear as real markup), the link
is reduced to a canonical form, the region and language are taken from the source, and a
missing or impossible publication date falls back to the collection time. An item with
no headline or no usable link is counted as invalid and skipped rather than failing the
batch.

URL normalisation is what makes the same article arriving by two routes one article:
lower-case scheme and host, no `www.`, no default port, no fragment, no `utm_*`/`gclid`/
`fbclid`-style tracking parameters, the remaining parameters in a stable order, and no
trailing slash.

The deduplication keys are then tried in order:

| Order | Key                          | Why it comes here                                               |
| ----- | ---------------------------- | --------------------------------------------------------------- |
| 1     | `normalized_url`             | Cheapest and strongest: the same URL is the same article        |
| 2     | `canonical_url`              | The publisher's permalink, kept stable across a link change     |
| 3     | `source_id` + `feed_guid`    | The publisher's own identifier, unique within its feed          |
| 4     | `source_id` + `content_hash` | The same text republished under a new URL by the same publisher |

`canonical_url` is the feed's own identifier when that identifier is itself a URL, which
is what RSS permalink GUIDs and most Atom ids are. The content hash is deliberately
scoped to one source: two publishers syndicating the same story are two articles, which
is also why its index is not unique.

The lookup answers the common case without a write, and `uq_dedup_id`,
`uq_normalized_url` and `uq_source_feed_guid` settle the race it cannot — between the
read and the insert another collector may store the same article, and a duplicate key
there is the expected outcome, not a fault. A batch reports how many items it stored,
skipped as duplicates and rejected as invalid.

## Data model

Five collections, created and indexed by `make migrate`:

| Collection            | Purpose                                                      |
| --------------------- | ------------------------------------------------------------ |
| `sources`             | Configured RSS/Atom feeds, their region, schedule and health |
| `articles`            | Normalized, deduplicated article metadata                    |
| `collection_runs`     | One audit record per collection attempt                      |
| `feed_cache_metadata` | ETag and Last-Modified per source, for HTTP 304              |
| `application_locks`   | TTL leases that stop two collectors sharing a source         |

The deduplication order (normalized URL → canonical URL → source + feed GUID → content
hash) is enforced by three unique indexes on `articles`. `content_hash` is indexed but
**not** unique, because two sources may legitimately syndicate identical content.
`application_locks` carries a TTL index so a crashed collector cannot hold a lock forever.

Every article listing is index-served, and every listing index ends in
`published_at` (or `collected_at`) followed by `_id` — the exact order a page is read
in. Without the `_id` the database cannot order two articles sharing a timestamp from
the index alone, and has to sort the whole filtered set to hand back one page of it:
`ix_published_cursor` and `ix_collected_cursor` carry the two timelines,
`ix_source_published_cursor` and `ix_language_published_cursor` carry those filters, and
`ix_region_published_cursor` carries the regional query this system exists to answer. An
integration test explains each listing shape and fails the build if MongoDB answers any
of them with a collection scan **or** a blocking sort.

MongoDB refuses to recreate an existing index name with different keys, so an index that
gains a field is retired under its old name rather than edited in place. `ObsoleteIndexes`
lists those names and `make migrate` drops them before applying the plan, so upgrading an
existing deployment is still `make migrate` and nothing else.

## The reader site

`web.enabled` serves two pages on the same port and behind the same credentials as
the API: a feed at `/` and an article at `/articles/{id}`. They are Go templates plus
one hand-written stylesheet, embedded in the binary with `go:embed`. There is no
JavaScript build step, no bundler and no Node at runtime, and the pages work with
JavaScript disabled.

They exist mainly to accumulate read events, which is the one input to a later ranker
that cannot be back-filled. Three kinds are recorded:

| Kind         | Recorded by                     | Why it matters                                                          |
| ------------ | ------------------------------- | ----------------------------------------------------------------------- |
| `click`      | the server, on the page load    | Free, and survives with JavaScript off                                  |
| `impression` | `IntersectionObserver`          | A card shown and not clicked is the only negative example a ranker gets |
| `dwell`      | a timer plus `visibilitychange` | Separates a misleading headline from one that delivered                 |

Every event carries its position in the feed, so a later ranker can correct for the
fact that items at the top are clicked regardless of quality. A visit with no feed
position — a bookmark, a shared link — records `-1` rather than `0`, because claiming
it was the top story would poison exactly that correction.

Events report *how long ago* they happened, never a timestamp. The server dates them
from its own clock, so a wrong or hostile client clock cannot reach the data. They are
written to `read_events` and read only offline; there is no HTTP read path.

`POST /read-events` is the only state-changing request a browser makes here, so it is
also the only one needing cross-origin defence: it accepts `Sec-Fetch-Site:
same-origin`, falls back to a matching `Origin`, and refuses a request carrying
neither.

## Offline ML pipeline

Everything under `ml/` and `ml-v2/` is Python, runs on a laptop, and is never deployed.
It reads the collection read-only and writes derived artifacts; the collector never
depends on it, so a failure here cannot affect collection. `ml/` is version 1
(headline-only, macro-F1 0.720); `ml-v2/` is the submitted rewrite described at the top
of this file. Phase plans live in [docs/plan.md](docs/plan.md) and
[ml-v2/docs/plan.md](ml-v2/docs/plan.md).

```bash
make ml-setup                      # create ml/.venv and install pinned dependencies
make ml-test                       # the offline test suite
make ml-profile                    # corpus profile report and figures -> ml/reports
make ml-boilerplate                # discover per-source template lines for review
make ml-snapshot ID=20260823-100   # freeze a dataset
make ml-verify   ID=20260823-100   # rebuild it and confirm byte-identical digests
```

Point it at a different database with `NEWS_ML_MONGO_URI`; it defaults to
`mongodb://127.0.0.1:27017/news`.

A snapshot is the boundary between data preparation and training. Once one exists,
training reads a directory rather than a database, and its contents are a pure function
of `(git SHA, cleaning_version, seed, corpus)` — which `make ml-verify` checks by
rebuilding into a scratch directory and comparing SHA-256 digests.

Snapshot payloads are gitignored. They contain third-party article text collected for
study, so the manifest and data card are committed and the text itself is not.

## Project layout

```text
cmd/api           HTTP server and the collection scheduler
cmd/migrate       collection and index migration
cmd/seed          source seeding CLI
cmd/collector     manual collection CLI

internal/app             composition root shared by the commands
internal/config          layered configuration
internal/observability   slog setup, request ID, access log, panic recovery
internal/mongodb         connection management, collection names, index plan
internal/handler         thin HTTP handlers, request and response contracts
internal/web             reader pages: html/template, embedded CSS and telemetry JS
internal/domain          models and rules
internal/repository      persistence interfaces and storage-neutral errors
internal/repository/mongo MongoDB implementations
internal/service         application orchestration
internal/httpclient      SSRF-guarded HTTP client
internal/collector/rss   gofeed-based RSS/Atom collector
internal/processor       staged processing pipeline
internal/scheduler       the collection loop and its concurrency bounds

configs/      default configuration and the source seed file
fixtures/     offline feed fixtures for tests
deployments/  Dockerfile, local Docker Compose, Coolify Compose stack
scripts/      developer helper scripts
.env.example  template for the gitignored .env holding secrets

ml/src/newsml offline data preparation: profile, clean, admit, neardup, splits, snapshot
ml/tests      the offline test suite
ml/reports    corpus profile and figures
ml/data       frozen dataset snapshots (payloads gitignored)
```

Dependencies point inward only: handlers depend on services, services depend on
repository interfaces, and the MongoDB implementation is never imported by domain code.
Source identifiers are UUIDv7, so they are neither guessable nor enumerable, and because
they sort chronologically the `_id` index alone gives listings a stable order.

## Security posture in this milestone

- Every `/api/v1` route requires an API key or basic credentials; only `/health`
  is open, and it exposes nothing but liveness.
- The guarded routes live on their own mux, so what authentication covers is
  decided by which handlers are registered behind it rather than by matching the
  request path in a middleware, which is where prefix-comparison bypasses come from.
- Credentials are held only as SHA-256 digests and compared with
  `crypto/subtle`, with every configured key checked on every request, so
  neither the value nor the length of a rejected credential leaks through timing.
- Auth cannot be disabled in production, and enabling it without credentials is
  a startup error, so no path leads to an unguarded deployment.
- Secrets are accepted only from the environment. The credential fields carry no
  YAML tag, so a key placed in the config file fails the load; `.env` is
  gitignored and excluded from the Docker build context.
- `.env` never overrides a variable already set, so a platform-injected secret
  always beats a stale local file.
- The `WWW-Authenticate` realm is a fixed constant rather than configuration, so
  no configured value can inject into a response header, and the configured API
  key header name is validated as an HTTP field name at startup.
- MongoDB credentials are redacted before the connection target is logged.
- Request and response headers are never logged, so bearer tokens cannot leak.
- Driver errors are mapped to fixed codes; readiness reports `unavailable`, never the
  server-selection message naming internal hosts.
- Panics return an opaque `500` and are logged server-side without a stack in the body.
- Client-supplied `X-Request-Id` values are ignored; the server always generates its own.
- All JSON responses carry `X-Content-Type-Options: nosniff`.
- Reader pages render every article field through `html/template`, whose contextual
  escaping is what stands between scraped third-party text and stored XSS. They ship a
  `default-src 'none'` CSP with no inline script or style as the second line of defence,
  plus `frame-ancestors 'none'` and `Referrer-Policy: no-referrer`.
- The read-event endpoint is the only state-changing browser request; it requires
  `Sec-Fetch-Site: same-origin` or a matching `Origin`, and refuses a request that
  carries neither.
- Configuration is validated at startup, including the MongoDB URI scheme and database name.
- The container image runs as UID 10001, never root.
- Request bodies are capped at 64 KiB and must be `application/json`; unknown fields are
  rejected, so a caller cannot set a server-owned field such as `health_status`.
- Query filters are assembled field by field from typed, enum-validated values, so no
  part of a request is ever spliced into a query document as an operator.
- Feed URLs must be `http` or `https` and must not embed credentials, so a stored feed
  cannot leak a password into a log line.
- Source identifiers are UUIDv7 rather than sequential or timestamp-derived values.
- Outbound fetches refuse any destination that is not publicly routable — loopback,
  private, link-local (including the `169.254.169.254` metadata endpoint), multicast,
  carrier-grade NAT and the reserved ranges — and any port other than 80 and 443.
- That check runs in the dialer, after DNS resolution and immediately before the socket
  connects, so a name that resolves to a public address and is then re-pointed at an
  internal one is still refused. Every redirect hop is re-validated the same way.
- Redirects are capped, response bodies are capped after decompression so a compression
  bomb is inert, and an over-large body is rejected rather than truncated.
- `collector.allow_private_networks` turns the address guard off for local development
  and is refused outright when `app.environment` is `production`.
- Feed content is stored as plain text with its markup removed, and every article field
  is bounded before it reaches the database, so a publisher cannot use a feed to plant
  markup or an unbounded document in the store.
- A collection failure is stored as a fixed phrase chosen from its failure class, never
  the underlying error, so the run history and a source's `last_error` cannot leak a
  DNS message, a driver error or an internal host name to an API caller.
- Each collector process holds its leases under an identifier of its own, so one
  collector cannot release another's lease, and every lease expires on its own whether
  or not it is released.
- The scheduler bounds both how many sources one tick takes and how many it collects at
  once, so a backlog cannot open unbounded sockets or exhaust the MongoDB pool the API
  shares.
- A panic inside a collection is contained in its own goroutine: a background worker
  must not take down the API it shares a process with.
- The collection history is read-only over HTTP; a collection can only be started by the
  scheduler or by an operator running the collector command.
- Article listings are cursor-paged and index-served, and the cursor's two halves are
  parsed and validated before either reaches a query, so a crafted token cannot smuggle
  a comparison operator into one — nor can any filter, which are all enum-, UUID- or
  date-validated and assembled field by field.
- Article responses expose no deduplication key, so how articles are matched is not
  inferable from the API.

Every outbound request in the application goes through `internal/httpclient`, so no
caller can reach the network without those guards.

**There is still no identity layer** — a valid credential is a credential, with no
notion of who holds it and no per-caller scoping or rate limit. Keep the service on a
trusted network.
