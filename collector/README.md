# News collector and AFTERLINE operations

The collector gathers news from RSS and Atom feeds, stores it in MongoDB, and
best-effort enriches it with article text, dates, images and topic classifications.
AFTERLINE is the separate reader and recommendation application built on that data.

**Status: 25 Nov 2026.** [The roadmap](../docs/project/roadmap.md) owns current scope, contracts,
status and decisions. V1 is **not accepted**; its original 15 Nov deadline has not
been replaced. The closed classifier plans are historical evidence, not the current
backlog.

| Area | What is available, and what is not claimed |
| --- | --- |
| Collector source | Scheduled and manual collection, source management, cursor-paged article queries, guarded publisher fetches, full-text enrichment and best-effort classification. The shipped list declares **124 feeds**, all with `language: en`; this is not a live healthy-feed count or an English-only ingestion guarantee. |
| Collector hardening | Revision-aware derived fields, page dates/images, source domains and a bounded C1 backfill are implemented. The roadmap records local test evidence; production backfill, operational recovery work and the full M1 exit remain open. |
| Recorded deployment | The collector has a recorded home-lab deployment. This manual does not verify its running image or database contents. The shipped Coolify stack contains MongoDB, classifier and collector API, not the AFTERLINE reader, ranker, batch pipeline or MCP server. |
| Local AFTERLINE demo | The 24 Nov implementation and local evidence cover a fresh-first feed with archive, a Yesterday page, professional focus, and browser-local saved stories and notes. Snapshots are rebuilt manually; this is not the revision-aware scheduled recommendation pipeline or a V1 release. The roadmap still leaves morning refresh/rehearsal open. |
| Still planned for V1 | Google sign-in, server-side reader state, persistent daily editions, incremental indexing and its freshness acceptance, association rules, read-only MCP, hosted reader/ranker and release evaluation. |

Use [the recommender guide](../docs/services/recommender.md) for the current AFTERLINE setup,
`make demo-refresh`, `make demo-serve`, `make reader`, and their prerequisites and
limitations. The `/` site served by the collector API below is the **legacy feed**,
not the `/stories` AFTERLINE reader on port 8090.

## Historical classifier evidence

The earlier *Beyond the Headline* classifier project is preserved under
[docs/history/ml/](../docs/history/ml/v1/README.md) and [submission/](../docs/history/submission/); its
code is in the top-level [ml/](../ml/README.md) project. Its closed experiment
logs are [docs/history/classifier-plan.md](../docs/history/classifier-plan.md) and [docs/history/ml/v2/plan.md](../docs/history/ml/v2/plan.md).

**Label provenance correction (roadmap D16, 22 Nov): all old and new classifier
labels are AI-generated.** Earlier descriptions of hand labels, human annotators
or human/gold accuracy are withdrawn. The historical scores below measure agreement
with AI reference labels, not human acceptance; they were not remeasured for this
documentation update.

| Historical v2-001 result | Recorded value |
| --- | --- |
| Test macro-F1 | 0.751 [0.719, 0.780], on the once-opened test split |
| Agreement on filed articles | 83.4%, versus 77.7% when forced to answer everything |
| Coverage | 80.7% filed automatically; the remainder is `unsorted`, not a delivered human-review queue |
| Test calibration error | 0.021 against those reference labels |
| Frozen corpus | 14,189 articles, 40 publishers, 8,001 AI-generated labels, 13 classes |
| Inference cost | 0.78 ms per article in that experiment, not a current service benchmark |

The historical body-versus-headline comparison reported +0.059 macro-F1
(0.712 → 0.771), non-overlapping bootstrap intervals and McNemar
*p* = 7.5 × 10⁻⁶. Its four-day, India-heavy collection window and small classes
limit interpretation; it does not measure the current corpus or long-term drift.
Keep the historical test split closed. New local classifier candidates do not
replace the deployed model merely because they have been trained.

## The collector service

The Go collector is the only writer of `articles`: ingest, enrichment,
classification retries and C1 backfill all run through its own code. Python data
preparation and training read the collection and write separate artifacts; the
classifier sidecar returns predictions and cleaned copies to the Go caller.
Classifier unavailability does not prevent valid feed items from being stored.

## Requirements

- Go 1.27, matching `go.mod` and the Go image.
- A reachable MongoDB 7 server; Docker and Docker Compose if using the supplied
  local stack or building containers.
- Python and `uv` only for classifier/recommender tools and the safe target
  inspection command; see [the recommender guide](../docs/services/recommender.md).

Run the commands below from `collector/`, not the repository root.

### Choose the database before running a writer

`make run`, `make up`, `make migrate`, `make seed`, `make collect`,
`make collect-source`, `make scrape`, `make scrape-limit` and `make backfill`
can write to a database. The API migrates and synchronizes sources on startup,
then starts its enabled workers. Do not run these commands against production as
part of local setup or verification.

Before a writer, explicitly select the intended target and use `make -C ../ml rec-inspect`
to check it without displaying the connection URI. Use the same environment
selection for inspection and the writer, and check any Compose overrides too.
The [recommender guide](../docs/services/recommender.md) documents inspection setup.

Go commands load the file selected by `-env`, otherwise `NEWS_ENV_FILE`, otherwise
`.env` in the command's working directory. To use only already-exported values
on this Unix setup, use `NEWS_ENV_FILE=/dev/null` (or `-env /dev/null` with a
binary). **This does not clear an exported production setting.** Compose has
its own explicit `env_file` entries; `NEWS_ENV_FILE` does not disable those.

## Quick start with Docker Compose

This is a local-development stack. It uses `mongo:7`, publishes MongoDB port
27017 and API port 8080 on **all host interfaces**, and does not configure MongoDB
authentication. Use an isolated development machine/network; do not expose it
to the Internet. Coolify's production binding is different (see Deployment).

The Compose services load `collector/.env`, which is gitignored and never baked
into the image. Create local credentials first — the API refuses to start with
auth enabled and no credentials:

```bash
cp .env.example .env
openssl rand -hex 32          # paste into NEWS_AUTH_API_KEYS
```

`make up` builds and starts MongoDB, the classifier and the API. The classifier
mounts `ml/models/classifier/v4-ai-072b01a9ceaf` read-only; download that model first
with `make -C ../ml models`. A container build does not train or supply the model. The API waits for MongoDB, **not** classifier readiness, migrates
the database and applies `configs/sources.yaml` before it serves:

```bash
make up
curl -s localhost:8080/health/live
curl -s localhost:8080/health/ready
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/collection-runs?limit=5'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?limit=5'
make logs
docker compose -f deployments/docker-compose.yml down  # keep the database volume
```

The API process also runs the scheduler, so feeds start being collected as soon
as it is up. Both Compose files enable the classifier, overriding its disabled
YAML default. An unavailable classifier leaves articles pending rather than
stopping collection; API readiness checks MongoDB only.

**`make down` deletes the named MongoDB volume.** Use it only when you intend to
discard the local database, not as the routine stop command.

## Quick start without Docker

```bash
make mongo-up                      # optional Docker MongoDB; see exposure warning above
# After setting and inspecting the intended local target and auth credentials:
NEWS_ENV_FILE=/dev/null make run    # migrate, apply sources.yaml, serve on :8080
```

The Go API's shipped YAML disables classification. Enable it only with a
reachable `NEWS_CLASSIFIER_ENDPOINT` and the appropriate API key. The default
`http://classifier:8000` is a Compose-network name, not a host-side service.

`make migrate` and `make seed` perform the startup steps independently against
the selected MongoDB target; neither requires the API to be running. Manual
collection and enrichment are described below. C1 backfill is a separate
operator action, not part of startup:

```bash
NEWS_ENV_FILE=/dev/null make backfill  # at most 1000 incomplete articles; writes
```

The C1 backfill requires a reachable, compatible classifier even when
`classifier.enabled` is false. It processes at most 50 articles per request, pauses one
second between full batches, and resumes from articles missing required C1 fields.
Each run advances by `_id` so completed or concurrently changed articles are not
rescanned. It fills absent cleaned text, language, date provenance and timestamps;
existing derived values, page provenance, raw text and topics are preserved.
Updates require the revision read for that batch; a concurrent change defers the
article to a later run. Legacy records without `inserted_at` use `collected_at` as
an explicit estimate, not measured ingestion latency. Set `BACKFILL_LIMIT` or
`BACKFILL_DELAY` to adjust a run, then rerun `make backfill` until no work remains.

## Verification gates

```bash
make check                         # gofmt check + go vet + go test ./...
make test-race                     # unit tests under the race detector
make cover                         # coverage summary
make test-integration              # needs MongoDB on localhost:27017
NEWS_ENV_FILE=/dev/null make seed-check  # validate sources.yaml; no database access
make build                         # binaries into ./bin
make ml-test                       # offline ML suite (Python, see below)
```

Unit tests need no external service. The integration tests are behind the
`integration` build tag, use a database name unique per run, and drop it afterwards.
CI starts MongoDB 7 with a readiness check and runs the integration suite.
Synthetic feed and extraction cases are self-contained; captured publisher pages
remain private and their tests skip explicitly when the captures are absent.
Private-label-dependent ML checks likewise skip without the private AI-label file;
synthetic label-loader and filtering checks still run.

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
| `web.enabled`                      | `NEWS_WEB_ENABLED`                      | `true` (legacy feed)        |
| `web.page_size`                    | `NEWS_WEB_PAGE_SIZE`                    | `30`                        |
| `mongo.uri`                        | `NEWS_MONGO_URI`                        | local MongoDB, port 27017   |
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
The table gives shipped effective defaults; authentication is off in the
built-in defaults but on in `configs/config.yaml`.

### Enrichment and classifier settings

These settings use the same environment mapping, for example
`scraper.interval` → `NEWS_SCRAPER_INTERVAL` and
`classifier.enabled` → `NEWS_CLASSIFIER_ENABLED`.

| Key | Default |
| --- | --- |
| `scraper.enabled` | `true` |
| `scraper.interval`, `scraper.batch_size` | `5m`, `50` |
| `scraper.user_agent` | same shipped value as `collector.user_agent` |
| `scraper.request_timeout`, `scraper.max_response_bytes` | `20s`, `20971520` |
| `scraper.allow_private_networks` | `false` |
| `scraper.min_content_words`, `scraper.max_attempts` | `80`, `3` |
| `scraper.retry_base`, `scraper.max_article_age` | `15m`, `720h` (30 days) |
| `scraper.per_host_delay` | `2s`, increased by a longer robots Crawl-delay |
| `scraper.circuit_failure_threshold`, `scraper.circuit_open_for` | `3`, `15m` |
| `scraper.robots_cache_ttl`, `scraper.claim_ttl` | `24h`, `10m` |
| `classifier.enabled`, `classifier.endpoint` | `false`, `http://classifier:8000` |
| `classifier.timeout`, `classifier.batch_size` | `10s`, `50` |
| `classifier.max_attempts`, `classifier.claim_ttl` | `3`, `5m` |
| `classifier.metadata_refresh_interval` | `1h` |
| `NEWS_CLASSIFIER_API_KEY` (environment only) | none; required when classification is enabled in production |

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

Keep local configuration pointed at a local database. A target selected through
the environment takes precedence over YAML and dotenv, so a command named
`make run` is not inherently local. Production secrets belong in Coolify or a
separately managed secure environment; select a production writer only as an
explicit operator action after the target check above.

## Authentication

With the shipped authentication setting, every `/api/v1` route requires a
credential. `/health/live` and `/health/ready`
stay open, because the container healthcheck and the reverse proxy probe them
before any credential is in play. They expose version/status and MongoDB
readiness, not classifier readiness or overall pipeline health.

Two schemes are accepted, and either one alone is sufficient:

```bash
curl -H "X-API-Key: $KEY" localhost:8080/api/v1/sources        # scripts
curl -u "$NEWS_AUTH_BASIC_USERNAME:$NEWS_AUTH_BASIC_PASSWORD" \
  localhost:8080/api/v1/sources                              # basic authentication
```

`$KEY` in this manual means one configured API key, not the entire
comma-separated `NEWS_AUTH_API_KEYS` value.

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
runs the Go, classifier, ML and recommender checks, then builds the Go, classifier
and recommender images, on pull requests to `main`, pushes to `main` and manual
runs. Its `ci-passed` job fails unless every check and image build succeeded, so
it is the one status check to require: add a branch ruleset for `main` that
requires a pull request and the `ci-passed` check, with branches up to date
before merging. The Go image contains every `cmd/*` executable. It can run
either the API or reader command, but packaging the reader does not deploy it
or deliver M3 sign-in.

Publishing is armed separately. Only a `main` run with the repository variable
`DEPLOY_ENABLED` set to `true` pushes the images to GHCR and then calls Coolify's
authenticated deploy webhook; until then a `main` run builds the images and
stops. Remote publishing and the handover from the existing production
publisher remain unverified in the roadmap; a successful local image build is
not deployment evidence. Arm it only once GHCR access and the secrets below are in place, the Coolify
resource deploys this compose file, and no other repository publishes these
images or calls the webhook. Then run the workflow on `main` (Actions →
news-collector → Run workflow) to publish and deploy.

On the Coolify side, create a **Docker Compose** resource from
[deployments/coolify.compose.yml](../deployment/compose/coolify.compose.yml). It defines
MongoDB **7.0.48** with generated root credentials, the classifier and the API
behind a Coolify-issued
domain. MongoDB's port is published on the host's loopback only, so Compass and
mongosh reach it through an SSH tunnel. There are no one-shot migrate or seed
containers: the API reconciles the schema and the source list itself on every
start, because a one-shot container that has already exited successfully is not
guaranteed to be recreated on a redeploy — and when it is skipped, an edited
feed list silently never reaches the database.

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
| `NEWS_CLASSIFIER_IMAGE`       | optional; pin to a compatible classifier SHA tag |

The C1 collector requires classifier responses containing cleaned text, language
and language confidence. Pre-M1.1 classifier images do not satisfy that contract;
roll back to a compatible image, or roll back the collector and classifier as a
compatible pair.

Before the first production deploy, provision the database users as MongoDB
root. Supply `NEWS_MONGO_ROOT_URI`, `NEWS_MONGO_DATABASE`, and distinct
`NEWS_MONGO_{COLLECTOR,BATCH,RANKER,READER,OWNER}_PASSWORD` values through a
secure environment; each password must be generated as 64 hex characters (for
example, `openssl rand -hex 32`). Run:

```bash
mongosh "$NEWS_MONGO_ROOT_URI" --quiet --file deployments/mongo-users.js
```

Store the generated passwords in Coolify secrets. MongoDB enforces each
principal's collection permissions; ownership of reader-added sources is
an application responsibility, not a MongoDB row-level role policy. The current
collector API does not accept a client-supplied `added_by`; authenticated
reader-source management remains future work.
The script can be rerun: it updates managed roles and reapplies the supplied
passwords and role assignments to existing users. Keep the supplied passwords in
sync with the corresponding Coolify secrets.

And these as GitHub repository secrets:

| Secret                    | Notes                                                          |
| ------------------------- | -------------------------------------------------------------- |
| `COOLIFY_WEBHOOK`         | the resource's Deploy Webhook URL                              |
| `COOLIFY_TOKEN`           | Coolify API token with only the deploy permission              |
| `CF_ACCESS_CLIENT_ID`     | Cloudflare Access service token ID, if Access protects Coolify |
| `CF_ACCESS_CLIENT_SECRET` | that service token's secret                                    |

An armed deploy fails if either Coolify secret is missing, or if the response is
not a 2xx: Cloudflare Access answers a request without a valid service token
with a redirect to its login page, which curl would otherwise count as success.
A 2xx means Coolify queued the deployment; follow it in Coolify. The secrets are
sent only as request headers, and the job prints Coolify's messages rather than
the response body, because this repository's workflow logs are public. Roll back
by setting `NEWS_IMAGE` and `NEWS_CLASSIFIER_IMAGE` to an earlier release's `sha-`
tags, both from the same commit so the pair stays compatible, and redeploying;
unset them to follow `latest` again.

`GITHUB_TOKEN` covers every GHCR push and promotion: this workflow created all
three packages, so they are linked to this repository and inherit its public
visibility. Do not publish under a package name that another repository created
— its token cannot push there and the build fails with
`permission_denied: write_package`, which is why the Go image is `news-bot`
rather than `news-collector`. If a package is made private, authenticate the
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

As shipped on 25 Nov, the file has **124 source entries**, all declaring
`language: en` and none explicitly disabled (new sources default to enabled).
This counts configuration, not currently healthy publishers, sources already
stored in any database, or article language detection. Feed availability and
robots policies can change; verify a new source against a local scratch target
before enabling it.

`bootstrap.sources_path` takes a filesystem path or an **https URL**. The default reads
the copy baked into the image, so a new feed needs a rebuild. Point it at the raw URL of
this file on `main` instead and the list is read fresh on every start — adding a feed is
then a commit and a restart, with no image rebuild:

```
NEWS_BOOTSTRAP_SOURCES_PATH=https://raw.githubusercontent.com/mhd-riaz/news-bot/main/collector/configs/sources.yaml
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
The shipped file uses only the four V1 domains, `technology`, `software`, `ai` and
`data-science`; a test rejects any other tag there. These support the local
demo's professional-focus selection and the planned account settings (C8).
They do not restrict collection to those domains or expose an authenticated
reader-added-feed workflow.

## Endpoints

The milestone numbers below refer to the original collector build, not the
current AFTERLINE roadmap. The final three routes belong to the legacy feed.

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

Liveness is deliberately independent of MongoDB so an outage after startup causes
a `503` on readiness rather than a restart loop. The startup bootstrap is an
exception: a failed migration, source synchronization write or local seed-file
load fails startup. An unreadable/invalid remote source list leaves the stored
sources unchanged and allows startup to continue.

Listing sources accepts `enabled`, `type`, `health_status`, `country`, `state`, `city`,
`limit` and `offset`. `limit` defaults to 50 and is capped at 100; asking for more is an
error rather than a silently truncated page, so nobody builds against a page size the
server will not honour.

```bash
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/sources?country=IN&enabled=true&limit=10'

curl -s -H "X-API-Key: $KEY" -X POST localhost:8080/api/v1/sources \
  -H 'Content-Type: application/json' \
  -d '{"name":"Example — Mysuru","feed_url":"https://example.com/feed.xml",
       "type":"rss","language":"en","country":"IN","state":"Karnataka","city":"Mysuru"}'

curl -s -H "X-API-Key: $KEY" -X PATCH 'localhost:8080/api/v1/sources/<id>' \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

The example publisher is a placeholder, not a verified feed.

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
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?country=IN&state=Karnataka&limit=20'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?source_id=<id>&sort=collected_at'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?published_from=2026-08-01T00:00:00Z'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles/<id>'
```

| Parameter                        | Effect                                     |
| -------------------------------- | ------------------------------------------ |
| `source_id`                      | Only articles from one feed                |
| `language`                       | Source-declared two-letter language, not detected text language |
| `country`, `state`, `city`       | The region the source is registered under  |
| `topic`                          | Stored classifier topic, including `unsorted` |
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
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?limit=2'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?limit=2&cursor=MTc2Njk5MDgwMDAwMC4wMTk4...'
```

There is no `total`. Counting a filtered set of an unbounded collection on every page is
the same walk the cursor exists to avoid.

### Retention

`DELETE /api/v1/articles` is a destructive operator tool for expiring old articles.
There is no automatic retention sweep in the shipped stack. Do not run or schedule
one until the owner has approved the retention/content-rights policy in the
roadmap and the intended target has been checked. The examples below illustrate
the API, not an approved production retention policy.

```bash
curl -s -H "X-API-Key: $KEY" -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z'
curl -s -H "X-API-Key: $KEY" -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z&source_id=<id>'
curl -s -H "X-API-Key: $KEY" -X DELETE 'localhost:8080/api/v1/articles?delete_older_than=2026-07-01T00:00:00Z&source_name=The+Hindu'
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

### Listings omit the raw article body

Article bodies can be large, so a listing projects `content` away. A caller who
wants the raw/accepted body reads the article
itself, where `content` is returned when non-empty. A summary-only article may
still have no body. The deduplication keys — `dedup_id`,
`normalized_url`, `content_hash` and `feed_guid` — are internal machinery and are never
served. Filed and `unsorted` articles expose topic, classification status and
confidence. C1 cleaned text, detected language, revisions and date provenance
are stored in MongoDB but are not added to this collector HTTP response contract.

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

The scheduler runs in `cmd/api`; `cmd/collector` runs the same collection service
once by hand. Both use the same per-source leases and processing pipeline.

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
`collector.request_timeout`, plus `classifier.timeout` when classification is
enabled. This is a startup validation
bound, not a measured upper bound for parsing, storage or multiple classifier
batches; size the lease for the actual collection workload.

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
`last_collected_at` records the last successful poll, including `304` and polls
with no new articles; it is not evidence that new articles arrived. A failed
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
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/collection-runs?status=failed&limit=20'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/collection-runs?source_id=<id>'
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/collection-runs/<run-id>'
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
make collect                       # up to 50 currently due sources, once
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

Items are normalised and offered to the optional classifier in bounded batches.
They are then checked and inserted one at a time, so two entries duplicating each
other inside a single feed are caught by the same lookup that catches a duplicate
of yesterday's collection.

Normalising an item produces the article: HTML becomes plain text (tags are removed
before entities are decoded, so escaped markup cannot reappear as real markup), the link
is reduced to a canonical form, the region and language are taken from the source, and a
missing date or one more than an hour ahead falls back to the collection time,
with `published_at_source: collected_fallback` and `date_verified: false`.
An accepted feed date is marked `feed` and verified. An item with
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
scoped to one source and its index is not unique. Different-URL copies of
syndicated text can therefore remain separate articles across publishers.
URL identity is different: `normalized_url` and `dedup_id` are globally unique,
so registering the same article URL under another source does not create a
second copy. `dedup_id` hashes the canonical feed identifier when present,
otherwise the normalized URL; only the `source_id` + `feed_guid` unique key is
source-scoped.

The lookup answers the common case without a write, and `uq_dedup_id`,
`uq_normalized_url` and `uq_source_feed_guid` settle the race it cannot — between the
read and the insert another collector may store the same article, and a duplicate key
there is the expected outcome, not a fault. A batch reports how many items it stored,
skipped as duplicates and rejected as invalid.

### Full-text enrichment

The API also runs the enrichment worker when `scraper.enabled` is true. Feed
bodies shorter than 500 whitespace-separated words are queued; longer feed
bodies are assumed sufficient and are not fetched just to obtain page metadata.
By default the worker checks every five minutes, attempts at most 50 articles
per batch and excludes articles published more than 30 days ago.

Page fetches use the guarded HTTP client, robots checks, a per-host delay and a
failure circuit breaker. JSON-LD and two readability-style extractors compete
on body word count. A replacement must pass the configured extraction minimum,
contain at least 80 words and be strictly longer than the stored body. This is
a length-based safeguard, not a guarantee of complete or better-quality text.

Enrichment is **not limited to body replacement**. A usable page publication
date or missing image URL can be saved even when the extracted body is too
short or no longer than the stored one. Page dates need a timezone; date-only
or timezone-less page values are ignored, as are dates more than an hour ahead.
A page date is marked `page` and verified. Existing feed images are preserved;
only image URLs are stored, never downloaded images.

```bash
make scrape                        # one bounded enrichment batch
make scrape-limit LIMIT=10          # at most ten attempts
go run ./cmd/scrape -limit 10 -timeout 10m
```

These are writers against the selected database and take the same article
claims as the background worker. Transient failures retry with backoff;
blocked, gone and robots-disallowed pages stop retrying. Failed extraction
has a two-attempt cap, within the shared attempt budget.

### Classification and C1 revisions

Classification is best-effort at ingest, with an API-process backlog worker
when enabled. It retries pending work at `scheduler.interval`, up to
`classifier.batch_size` attempts per tick and `classifier.max_attempts` per
article. Exhausted attempts become `failed`; an outage is not an unlimited
retry guarantee. A below-cut prediction becomes `unsorted`, not a human task.

The sidecar returns `clean_title`, `clean_summary`, `clean_body`,
`detected_language` (its response calls this `language`) and
`language_confidence`. These are stored separately from raw article text and
the source-declared `language`. The collector does **not** reject all
non-English articles: declared and detected language can differ, and disabled
or unavailable classification leaves detected language/cleaned fields empty.
English-only recommendation eligibility is a downstream concern, not a global
ingestion promise.

New articles start at `content_rev: 1`; the repository stamps `inserted_at` and
`updated_at` immediately before insert, separately from `collected_at`.
Material enrichment changes (body, date/provenance or missing image) increment
the revision, update `updated_at` and reset classification to pending with a
fresh attempt budget. Classification increments it only when cleaned text or
detected-language fields change. Backfill fills absent C1 fields with a
revision check and never rewrites topics or raw text. See roadmap C1 for the
contract; having these fields in code does not complete the M2 index pipeline.

## Data model

Six collector collections, declared in `internal/mongodb`, created and indexed
by `make migrate` (or the default API bootstrap):

| Collection            | Purpose                                                      |
| --------------------- | ------------------------------------------------------------ |
| `sources`             | Configured RSS/Atom feeds, their region, schedule and health |
| `articles`            | Article metadata, raw/accepted body and separate C1 derived fields |
| `collection_runs`     | One audit record per collection attempt                      |
| `feed_cache_metadata` | ETag and Last-Modified per source, for HTTP 304              |
| `application_locks`   | TTL leases that stop two collectors sharing a source         |
| `read_events`         | Legacy feed click/impression/dwell telemetry, not AFTERLINE recommendation signals |

The repository applies the deduplication lookup order (normalized URL → canonical
URL → source + feed GUID → source + content hash). Three unique indexes settle
insert races; they do not themselves implement that lookup order. `content_hash`
is indexed but **not** unique, because two sources may legitimately syndicate
identical content.
`application_locks` carries a TTL index so a crashed collector cannot hold a lock forever.

The common article-listing indexes end in
`published_at` (or `collected_at`) followed by `_id` — the exact order a page is read
in. Without the `_id` the database cannot order two articles sharing a timestamp from
the index alone, and has to sort the whole filtered set to hand back one page of it:
`ix_published_cursor` and `ix_collected_cursor` carry the two timelines,
`ix_source_published_cursor`, `ix_language_published_cursor` and
`ix_topic_published_cursor` cover those publication-time filters, and
`ix_region_published_cursor` covers the fully specified regional query. Integration
checks cover selected listing shapes, not a guarantee that every supported
combination of filters and sort orders avoids a collection scan or blocking sort.
The C1 plan also includes `{updated_at: 1, _id: 1}` for revision scans and
`{date_verified: 1, detected_language: 1, published_at: -1}`.

MongoDB refuses to recreate an existing index name with different keys, so an index that
gains a field is retired under its old name rather than edited in place. `ObsoleteIndexes`
lists those names and `make migrate` drops them before applying the plan, so upgrading an
existing deployment is still `make migrate` and nothing else.

## The legacy collector reader site

This is not AFTERLINE. `web.enabled` serves two pages on the same port and behind the same credentials as
the API: a feed at `/` and an article at `/articles/{id}`. They are Go templates plus
one hand-written stylesheet, embedded in the binary with `go:embed`. There is no
JavaScript build step, no bundler and no Node at runtime, and the pages work with
JavaScript disabled.

They retain the original anonymous read-event telemetry. These `read_events`
are not recommendation signals in the current product contract (roadmap C14);
they are distinct from the planned authenticated reader events. Three kinds
are recorded:

| Kind         | Recorded by                     | Why it matters                                                          |
| ------------ | ------------------------------- | ----------------------------------------------------------------------- |
| `click`      | the server, on the page load    | Free, and survives with JavaScript off                                  |
| `impression` | `IntersectionObserver`          | Records that a card was shown, even if it was not opened                |
| `dwell`      | a timer plus `visibilitychange` | Separates a misleading headline from one that delivered                 |

Every event carries its position in the feed for offline analysis of position
bias. A visit with no feed
position — a bookmark, a shared link — records `-1` rather than `0`, because claiming
it was the top story would poison exactly that correction.

Browser event uploads report *how long ago* they happened, never a timestamp. The server dates them
from its own clock, so a wrong or hostile client clock cannot reach the data. They are
written to `read_events`; there is no HTTP read path for the log.

Browser telemetry uploads use `POST /read-events` with cross-origin defence:
it accepts `Sec-Fetch-Site:
same-origin`, falls back to a matching `Origin`, and refuses a request carrying
neither. The legacy article `GET` also records a click server-side. These
legacy protections do not deliver V1 reader sessions or their CSRF contract.

## Offline ML pipeline

Data preparation and training are offline Python tools. They read the collection
read-only and write derived artifacts; they do not own collector article writes.
They live in the top-level [ml/](../ml/README.md) project. `src/newsml` is the closed
headline-only baseline. `src/newsmlv2` contains the body-aware classifier and shared
cleaning/admission code, `src/newsrec` the recommender, and `classifier/` the serving code.
It is **not all offline**: the classifier image is part of the collector stack,
and the ranker has a separate image but is demonstrated locally rather than
deployed by the shipped Coolify file. `src/newsmlv4` holds the V4 classifier tools;
a new V4 model is not an automatic production upgrade.

The current reader/recommender commands are in
[docs/recommender.md](../docs/services/recommender.md). Historical classifier phase logs
remain in [docs/history/classifier-plan.md](../docs/history/classifier-plan.md) and
[docs/history/ml/v2/plan.md](../docs/history/ml/v2/plan.md); do not take current product tasks from them.
The older v1 targets below are for that baseline, not for updating the current
AFTERLINE demo. Rebuilding its old snapshots needs the label rounds that R3 removed;
they remain at git tag `before-restructure`.

```bash
cd ../ml
make setup                         # create ml/.venv with every dependency group
make ml-test                       # the v1 test suite
make ml-profile                    # corpus profile report and figures -> ml/reports
make ml-boilerplate                # discover per-source template lines for review
```

The older `ml/` tools accept `NEWS_ML_MONGO_URI`. Do not assume that this legacy
override selects the target for the Go collector or the current recommender;
follow the relevant tool's configuration and target-inspection instructions.

A snapshot is the boundary between data preparation and training. Once one exists,
training reads a directory rather than a database, and its contents are a pure function
of `(git SHA, cleaning_version, seed, corpus)` — which `newsml verify` checks by
rebuilding into a scratch directory and comparing SHA-256 digests.

Snapshot payloads are gitignored. They contain third-party article text collected for
study, so the manifest and data card are committed and the text itself is not.

## Project layout

```text
cmd/api           HTTP server and the collection scheduler
cmd/migrate       collection and index migration
cmd/seed          source seeding CLI
cmd/collector     manual collection CLI
cmd/scrape        manual full-text enrichment batch
cmd/backfill      bounded, revision-checked C1 derived-field backfill
cmd/reader        separate read-only AFTERLINE server, not cmd/api's legacy feed

internal/app             composition root shared by the commands
internal/config          layered configuration
internal/observability   slog setup, request ID, access log, panic recovery
internal/mongodb         connection management, collection names, index plan
internal/handler         thin HTTP handlers, request and response contracts
internal/web             embedded legacy feed and AFTERLINE templates, CSS and JavaScript
internal/classifier      trusted internal sidecar client and topic metadata cache
internal/domain          models and rules
internal/repository      persistence interfaces and storage-neutral errors
internal/repository/mongo MongoDB implementations
internal/service         application orchestration
internal/httpclient      SSRF-guarded HTTP client
internal/collector/rss   gofeed-based RSS/Atom collector
internal/processor       staged processing pipeline
internal/extract         article body, page date and image URL extraction
internal/robots          robots.txt decisions and cache for article fetching
internal/ratelimit       per-host article-fetch pacing and circuit breaker
internal/scheduler       collection, enrichment and classification loops

configs/      default configuration and the source seed file
fixtures/     offline feed fixtures for tests
deployments/  Dockerfile, local Docker Compose, Coolify Compose stack
scripts/      developer helper scripts
.env.example  template for the gitignored .env holding secrets

docs/roadmap.md current product contracts, status, decisions and work log
```

Dependencies point inward only: handlers depend on services, services depend on
repository interfaces, and the MongoDB implementation is never imported by domain code.
Source identifiers are time-ordered UUIDv7 values with a random component, not
sequential counters. They expose creation-time information and are not an
authorization boundary. Source listings use `_id` order for stable pagination.

## Collector security and limits

- With shipped auth enabled, every `/api/v1` route requires an API key or basic
  credentials. The public probes are `/health/live` and `/health/ready`; they
  expose version, process status and MongoDB availability.
- The guarded routes live on their own mux, so what authentication covers is
  decided by which handlers are registered behind it rather than by matching the
  request path in a middleware, which is where prefix-comparison bypasses come from.
- Credentials are held only as SHA-256 digests and compared with
  `crypto/subtle`, with every configured key checked on every request, so
  neither the value nor the length of a rejected credential leaks through timing.
- Configuration rejects disabled auth in `production`, and enabled auth without
  credentials is a startup error. Development mode can disable auth; do not
  expose that mode to untrusted clients.
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
- Legacy read-event uploads require `Sec-Fetch-Site: same-origin` or a matching
  `Origin`, and reject requests carrying neither.
- Configuration is validated at startup, including the MongoDB URI scheme and database name.
- The container image runs as UID 10001, never root.
- Request bodies are capped at 64 KiB and must be `application/json`; unknown fields are
  rejected, so a caller cannot set a server-owned field such as `health_status`.
- Query filters are assembled field by field from typed, enum-validated values, so no
  part of a request is ever spliced into a query document as an operator.
- Feed URLs must be `http` or `https` and must not embed credentials, so a stored feed
  cannot leak a password into a log line.
- Source identifiers are UUIDv7, not secrets or per-reader access controls.
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

Untrusted feed, article and robots fetches use `internal/httpclient`. The
trusted classifier uses its separate bounded, redirect-free internal client.
Remote bootstrap source lists use a separate HTTPS client; do not describe
either client as covered by the publisher-fetch network guard.

**There is still no identity layer** — a valid credential is a credential, with no
notion of who holds it and no per-caller scoping or rate limit. Keep the service on a
trusted network.
