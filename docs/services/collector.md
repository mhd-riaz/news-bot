# Collector

The collector is the Go program that gathers the news. It reads RSS and Atom
**feeds** (lists of new stories that news sites publish). It saves each new story in
MongoDB. It fetches the full text from the story's web page. It also asks the
classifier for each story's topic.

It is the **only** program that writes stories into the `articles` collection. The
other parts only read them. Collection must keep running even when the classifier,
the ranker or the web server fails (project hard rule 1).

Hard words are explained in the [glossary](../glossary.md). The short checklist for
working on the code is in [`collector/README.md`](../../collector/README.md).

## At a glance

| Item | Value |
| --- | --- |
| Folder | [`collector/`](../../collector/) |
| Language | Go 1.27 (`collector/go.mod`) |
| Main program | `cmd/api`: the web API, the feed scheduler and the background workers |
| Port | 8080 |
| Settings | [`collector/configs/config.yaml`](../../collector/configs/config.yaml) plus `NEWS_*` environment variables |
| Feed list | [`collector/configs/sources.yaml`](../../collector/configs/sources.yaml): 124 feeds, all `language: en`; 34 have topic tags |
| Database layout | [`collector/internal/mongodb`](../../collector/internal/mongodb/collections.go) |
| Docker image | `ghcr.io/mhd-riaz/news-bot`, built from [`collector/Dockerfile`](../../collector/Dockerfile) |

## First, choose the database

Many collector commands **write** to the database they are pointed at. Never run them
against the production database by mistake.

These Make commands write: `make run`, `make migrate`, `make seed`, `make collect`,
`make collect-source`, `make scrape`, `make scrape-limit`, `make backfill` and
`make backfill-reclassify`.

How a command finds its settings file:

1. `make` passes `NEWS_ENV_FILE=../deployment/env/local.env` to the commands that run
   the app. A `NEWS_ENV_FILE` you already set in your shell wins. Tests never get it.
2. Each program then loads the file named by its `-env` flag, or else by
   `NEWS_ENV_FILE`, or else `.env` in the folder you run it from. A missing file is
   not an error.
3. A variable that is already set in your environment always wins over the file.

The env file holds passwords. Never print it, paste it or commit it.

To check which database you will use, run `make -C ../ml rec-inspect` from
`collector/`. It prints the database name, the number of articles and the newest
collection time. It never prints the connection address. It needs the ML setup
first (`make -C ../ml setup`).

## Run it

The easy way is `./run.sh` from the repository root. It starts the collector together
with the other parts. See [Getting started](../getting-started/README.md).

To run only the collector, from `collector/`, against a database on your computer:

```bash
make run    # migrates the database, applies sources.yaml, then serves on :8080
```

Before that, three settings need care:

- **Where it listens.** `configs/config.yaml` sets `server.host: 0.0.0.0`, so
  `make run` listens on every network address of your computer. On a shared network,
  set `NEWS_SERVER_HOST=127.0.0.1` so that only your computer can reach it.
- **Sign-in for the API.** `configs/config.yaml` turns API sign-in on, so the
  program will not start without a way to sign in. Give it a key of at least 32
  characters in `NEWS_AUTH_API_KEYS`. Or give it a user name and a password of at
  least 16 characters in `NEWS_AUTH_BASIC_USERNAME` and `NEWS_AUTH_BASIC_PASSWORD`.
  On a laptop you may set `NEWS_AUTH_ENABLED=false` instead. Production refuses
  that.
- **The classifier.** `configs/config.yaml` turns the classifier off
  (`classifier.enabled: false`). To use it, set `NEWS_CLASSIFIER_ENABLED=true` and
  point `NEWS_CLASSIFIER_ENDPOINT` at it, for example `http://127.0.0.1:8000`. The
  default `http://classifier:8000` is a Docker Compose name and works only inside
  Compose.

When the API is up:

```bash
curl -s localhost:8080/health/live
curl -s localhost:8080/health/ready
curl -s -H "X-API-Key: $KEY" 'localhost:8080/api/v1/articles?limit=5'
```

`$KEY` means one of the keys in `NEWS_AUTH_API_KEYS`.

## The programs

All six programs live in `collector/cmd/`. Each one accepts `-config` (default
`configs/config.yaml`, or `NEWS_CONFIG_PATH`) and `-env` (see above).

| Program | What it does | Extra flags | Writes? |
| --- | --- | --- | --- |
| `cmd/api` | The web API, plus the feed scheduler, the full-text worker and the classification worker. On start it migrates the database and applies the feed list. | — | Yes |
| `cmd/collector` | Reads the feeds that are due, once. | `-source <id>` (one feed now), `-limit` (default 50), `-timeout` (default 10m) | Yes |
| `cmd/scrape` | Runs one batch of full-text fetching. | `-limit` (0 means `scraper.batch_size`), `-timeout` (default 10m) | Yes |
| `cmd/seed` | Applies a feed list file. | `-sources <path or https URL>`, `-dry-run` (check only) | Yes, unless `-dry-run` |
| `cmd/migrate` | Creates the collections and indexes. | `-timeout` (default 2m) | Yes |
| `cmd/backfill` | Fills missing C1 fields in old articles, or relabels topics with `-reclassify`. | `-limit` (default 1000), `-delay` (default 1s), `-timeout` (default 10m), `-reclassify` | Yes |

## Make commands

Run these from `collector/`. `make help` lists them all.

| Command | What it does | Writes to a database? |
| --- | --- | --- |
| `make check` | Format check, `go vet` and the unit tests | No |
| `make test-race` | Unit tests with Go's race detector | No |
| `make test-integration` | Tests against MongoDB on `localhost:27017`. They make throwaway `news_it_*` databases and delete them | Only throwaway ones |
| `make test`, `make cover` | Unit tests; a coverage summary | No |
| `make fmt`, `make fmt-check`, `make vet`, `make tidy` | Format, check format, vet, tidy `go.mod` | No |
| `make build` | Builds all six programs into `bin/` | No |
| `make run` | Runs `cmd/api` | Yes |
| `make migrate` | Runs `cmd/migrate` | Yes |
| `make seed` | Applies `configs/sources.yaml` | Yes |
| `make seed-check` | Checks `configs/sources.yaml` without writing | No |
| `make collect` | Reads every feed that is due, once | Yes |
| `make collect-source SOURCE=<id>` | Reads one feed now | Yes |
| `make scrape` | One full-text batch of `scraper.batch_size` | Yes |
| `make scrape-limit LIMIT=10` | One full-text batch of the size you give | Yes |
| `make backfill` | Fills missing C1 fields, in batches. Change the size with `BACKFILL_LIMIT` and `BACKFILL_DELAY` | Yes |
| `make backfill-reclassify` | Relabels articles that carry another model's topic | Yes |
| `make mongo-up` | Starts only MongoDB in Compose | No |
| `make clean` | Deletes `bin/` and coverage files | No |

## Settings

Settings load in three layers. Each layer wins over the one before:

1. defaults built into the program;
2. [`configs/config.yaml`](../../collector/configs/config.yaml);
3. environment variables.

Every key has an environment name: `NEWS_` + section + key, in capitals. For example
`scheduler.interval` becomes `NEWS_SCHEDULER_INTERVAL`. A misspelt key in the YAML
file stops the program at start, so typos are caught early.

**Secrets come only from the environment.** These four have no YAML key on purpose,
so they cannot be committed by mistake: `NEWS_AUTH_API_KEYS`,
`NEWS_AUTH_BASIC_USERNAME`, `NEWS_AUTH_BASIC_PASSWORD` and `NEWS_CLASSIFIER_API_KEY`.
The MongoDB address `NEWS_MONGO_URI` can hold a password too, so keep it in the env
file as well.

The values below are the ones in `configs/config.yaml`.

| Key | Value | Meaning |
| --- | --- | --- |
| `app.name` | `news-collector` | The name in logs |
| `app.environment` | `development` | `development`, `staging` or `production`. Production adds safety checks |
| `server.host`, `server.port` | `0.0.0.0`, `8080` | Where the API listens |
| `server.read_header_timeout`, `read_timeout`, `write_timeout`, `idle_timeout` | `5s`, `15s`, `30s`, `60s` | Time limits for one web request |
| `server.shutdown_timeout` | `15s` | How long a clean stop may take |
| `server.max_header_bytes` | `1048576` | Largest request header (1 MiB) |
| `auth.enabled` | `true` | API sign-in on or off. Production refuses `false` |
| `auth.api_key_header` | `X-API-Key` | The header that carries an API key |
| `mongo.uri`, `mongo.database` | `mongodb://localhost:27017`, `news` | Which database to use |
| `mongo.connect_timeout`, `server_selection_timeout`, `operation_timeout` | `10s`, `10s`, `30s` | Time limits for the database |
| `mongo.max_pool_size`, `mongo.min_pool_size` | `50`, `0` | How many database connections to keep |
| `mongo.max_connection_idle_time` | not in the file; built-in `0` | Close idle connections after this long. `0` keeps the driver's own rule |
| `bootstrap.migrate` | `true` | Create collections and indexes on start |
| `bootstrap.sources_path` | `configs/sources.yaml` | The feed list to apply on start: a file or an `https` address. `""` turns this off |
| `bootstrap.timeout` | `2m` | Time limit for those start-up steps |
| `collector.user_agent` | `news-collector/1.0 (+https://github.com/mhd-riaz/news-bot)` | The name the collector gives to news sites |
| `collector.request_timeout` | `20s` | Time limit for one feed download |
| `collector.max_response_bytes` | `10485760` | Largest feed (10 MiB) |
| `collector.max_redirects` | `5` | Most redirects to follow |
| `collector.max_items_per_feed` | `500` | Most items read from one feed |
| `collector.allow_private_networks` | `false` | Allow fetching from private addresses. Production refuses `true` |
| `scheduler.enabled`, `scheduler.interval` | `true`, `60s` | How often the scheduler looks for due feeds |
| `scheduler.batch_size`, `scheduler.max_concurrent` | `50`, `4` | Most feeds per round, and most read at the same time |
| `scheduler.lock_ttl` | `5m` | How long a lease on one feed lasts. It must be longer than `collector.request_timeout`, plus `classifier.timeout` when the classifier is on |
| `scraper.enabled`, `scraper.interval`, `scraper.batch_size` | `true`, `5m`, `50` | The full-text worker: how often, and how many stories per round |
| `scraper.user_agent` | same as `collector.user_agent` | The name it gives to news sites |
| `scraper.request_timeout`, `scraper.max_response_bytes` | `20s`, `20971520` | Time and size limits for one page (20 MiB) |
| `scraper.allow_private_networks` | `false` | As for the collector. Production refuses `true` |
| `scraper.min_content_words` | `80` | A fetched text must have at least this many words |
| `scraper.max_attempts`, `scraper.retry_base` | `3`, `15m` | Tries per story, and the first wait before a retry |
| `scraper.max_article_age` | `720h` | Skip stories published more than 30 days ago |
| `scraper.per_host_delay` | `2s` | Wait between pages from one site. A longer robots `Crawl-delay` wins |
| `scraper.circuit_failure_threshold`, `scraper.circuit_open_for` | `3`, `15m` | After 3 failures in a row, leave that site alone for 15 minutes |
| `scraper.robots_cache_ttl`, `scraper.claim_ttl` | `24h`, `10m` | How long to remember a site's `robots.txt`, and how long a worker holds a story |
| `classifier.enabled` | `false` | Ask the classifier for topics. Compose files turn it on |
| `classifier.endpoint` | `http://classifier:8000` | The classifier's address |
| `classifier.timeout`, `classifier.batch_size` | `10s`, `50` | Time limit for one call, and stories per call |
| `classifier.max_attempts`, `classifier.claim_ttl` | `3`, `5m` | Tries per story, and how long a worker holds a story |
| `logging.level`, `logging.format` | `info`, `json` | How much to log, and in what form |

Production also refuses a classifier that is turned on without `NEWS_CLASSIFIER_API_KEY`.

## The web API

The API is for the owner and for scripts. Readers never use it.

With `auth.enabled: true`, every `/api/v1` route needs a key (in the `X-API-Key`
header) or the basic user name and password. The two `/health` routes are open, so
health checks can reach them.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/health/live` | Is the program running? Never touches the database |
| `GET` | `/health/ready` | `200` when MongoDB answers, `503` when it does not. It does not check the classifier |
| `POST` | `/api/v1/sources` | Add a feed |
| `GET` | `/api/v1/sources` | List feeds. Filters: `enabled`, `type`, `health_status`, `country`, `state`, `city`. Pages: `limit` (default 50, most 100) and `offset` |
| `GET` | `/api/v1/sources/{id}` | One feed |
| `PATCH` | `/api/v1/sources/{id}` | Change part of a feed, for example `{"enabled": false}` |
| `DELETE` | `/api/v1/sources/{id}` | Remove a feed |
| `GET` | `/api/v1/collection-runs` | List attempts to read feeds. Filters: `status`, `source_id`. Pages: `limit` and `offset` |
| `GET` | `/api/v1/collection-runs/{id}` | One attempt |
| `GET` | `/api/v1/articles` | List stories, newest first |
| `GET` | `/api/v1/articles/{id}` | One story, with its body |
| `DELETE` | `/api/v1/articles` | Delete stories published before a date (see below) |

There are no web pages any more. The old `/archive` and `/articles/{id}` pages were
removed on 27 Nov 2026 (roadmap RS5). The Python web server now serves readers.

**Listing stories.** Filters: `source_id`, `language` (the language the source
declares), `country`, `state`, `city`, `topic`, `published_from` and `published_to`
(dates like `2026-11-01T00:00:00Z`). `sort` is `published_at` (the default) or
`collected_at`. `limit` is 50 by default and at most 100. A list leaves out the full
body; ask for one story to get it.

**Pages use a cursor.** Each page of stories ends with `has_more` and a
`next_cursor`. Send `cursor=<next_cursor>` to get the next page. This stays correct
while new stories arrive. There is no total count.

**Deleting old stories.** `DELETE /api/v1/articles?delete_older_than=<date>` deletes
stories published before that date. You can add `source_id` or `source_name`. The
answer is the number deleted, for example `{"deleted": 1284}`. Nothing runs this
automatically. How long to keep stories is the owner's decision; do not run it
without that decision.

**Errors** always look like `{"error": {"code": "...", "message": "..."}}`. The codes
are `invalid_input` (400), `not_found` (404), `conflict` (409, the feed address is
already there), `unavailable` (503) and `internal_error` (500). A bad request lists
every broken rule at once.

## The feed list

Feeds are declared in [`configs/sources.yaml`](../../collector/configs/sources.yaml).
On 27 Nov 2026 it has 124 feeds. All say `language: en`. 34 have `domains` tags:
`technology` 14, `ai` 14, `software` 7 and `data-science` 4. This counts the file, not
the feeds that work today.

The collector applies the file every time it starts. It matches feeds on
`feed_url`, so an edit updates a feed instead of making a copy. A key you leave out
keeps its stored value. A feed that is in the database but not in the file is left
alone. `make seed-check` checks the whole file without writing. A file with one bad
entry is refused as a whole.

| Key | Needed? | Rule |
| --- | --- | --- |
| `name` | yes | 1–200 characters |
| `feed_url` | yes | `http` or `https`, no password inside, unique |
| `type` | yes | `rss` or `atom` |
| `language` | yes | two letters, for example `en` |
| `country` | yes | two letters, for example `IN` |
| `state`, `city` | no | up to 100 characters |
| `domains` | no | up to 20 tags. The shipped file may use only `technology`, `software`, `ai` and `data-science` |
| `enabled` | no | default `true` |
| `priority` | no | 0–100, default 50. Higher is read first |
| `fetch_interval_seconds` | no | 60–604800, default 900 |
| `added_by` | no | the reader who added it. Only trusted code may set it; the API refuses it |

The test `TestShippedSourcesFileIsValid` in `internal/bootstrap` checks every entry.
The [add-news-source skill](../../.github/skills/add-news-source/SKILL.md) walks
through adding a feed.

`bootstrap.sources_path` may also be an `https` address, such as the raw GitHub copy
of the file. Then a new feed needs only a commit and a restart. Plain `http` is
refused. If the remote file cannot be read, the stored feeds stay as they are and
the collector keeps running. By an owner decision on 26 Oct (roadmap §8), production
reads the copy built into the image.

## How collection works

**Scheduling.** Every `scheduler.interval` (60 s), the scheduler asks for enabled
feeds whose next time has passed. It takes the highest `priority` first, at most 50,
and reads at most 4 at once. A new round starts only after the last one ends.

**Leases.** Before reading a feed, the collector takes a **lease** on it in
`application_locks`. A lease ends by itself after `scheduler.lock_ttl` (5 minutes).
So two collectors never read the same feed at once, and a crashed collector cannot
block a feed for ever.

**Reading a feed.** The collector sends the feed's last `ETag` and `Last-Modified`
values. If the site answers "not modified" (HTTP 304), nothing is downloaded. RSS
2.0, RSS 1.0 (RDF) and Atom all work. An item without a usable `http` or `https`
link is dropped and counted.

**Feed health.** After each attempt the feed's record is updated:

| Result | Health | Next attempt |
| --- | --- | --- |
| Stories saved, or "not modified" | `healthy`; the failure count goes back to 0 | after its normal wait (`fetch_interval_seconds`) |
| Failed | `degraded`, then `failing` after 3 failures in a row | the wait doubles each time, up to 7 days |

Every attempt is saved in `collection_runs` with a status: `success`,
`not_modified`, `partial` (some items were dropped) or `failed`. The error is a fixed
phrase, such as "the publisher answered HTTP 404", so no internal detail leaks out.

**Copies.** Four keys find a story the collector already has, in this order:

1. `normalized_url`: the link in a tidy form (lower case, no `www.`, no tracking
   parameters like `utm_*`, no trailing slash);
2. `canonical_url`: the publisher's own permanent link;
3. `source_id` + `feed_guid`: the feed's own ID for the item;
4. `source_id` + `content_hash`: a fingerprint of the text, within one source.

Three **unique indexes** (`uq_dedup_id`, `uq_normalized_url` and
`uq_source_feed_guid`) stop two collectors saving the same story at the same moment.

**Dates.** A feed date is used if it is not more than an hour in the future. Then
`published_at_source` is `feed` and `date_verified` is `true`. With no good date,
the collection time is used, `published_at_source` is `collected_fallback`, and
`date_verified` is `false`.

**Full text.** Stories whose feed body has fewer than 500 words wait in a queue. The
full-text worker (the **scraper**) fetches their pages every 5 minutes, 50 at a time,
and skips stories older than 30 days. It reads JSON-LD data and two
"readability"-style extractors, and keeps the longest text. A new text must have at
least 80 words and be longer than the stored one. The worker also saves the page's
date, but only if that date has a time zone; then `published_at_source` becomes
`page`. If the story had no picture link, it saves the page's one. It never downloads
pictures. Pages that are blocked,
gone or disallowed by `robots.txt` are not tried again.

**Topics.** Each batch of new stories goes to the classifier, up to 50 at a time,
with a 10 s time limit. The answer gives `topic`, `confidence` and `model_version`.
A story the model is not sure about gets the topic `unsorted`. If the classifier is
off or down, the story is saved with `classification_status: pending`. A worker
inside `cmd/api` tries again every `scheduler.interval`, up to 3 times per story;
then the status becomes `failed`.

**Revisions (roadmap C1).** Each story has a `content_rev` number. It starts at 1. It
goes up when the text, the cleaned text, the detected language, the date or the
picture link changes. `updated_at` changes at the same time. A full-text change also
sends the story back to the classifier. A topic-only change does not change
`content_rev` or `updated_at`.

**Not English-only.** The collector does not throw away non-English stories by
itself. The source's `language` and the detected language can differ. English-only
filtering happens later, when snapshots are built.

## Filling old articles (backfill)

`make backfill` fills missing C1 fields in older stories: cleaned text, detected
language, date source and timestamps. It needs a running classifier, even when
`classifier.enabled` is `false`. It works in batches of 50, pauses 1 second between
batches, and stops after 1,000 stories by default. Run it again until nothing is
left. It never changes topics or the original text. If a story changes while a batch
runs, that story waits for a later run.

`make backfill-reclassify` relabels stories whose `model_version` differs from the
classifier's current model. It writes only `topic`, `confidence`, `model_version`,
`classification_status` and `classified_at`. Run it again until it reports
`updated` as 0. The [classifier guide](classifier.md#deploy-the-v4-classifier-d19)
says when to use it.

**Status:** both commands are built and tested. Neither has been run on the
production database yet (roadmap M1.5 and ML4.7, now carried by RS6).

## What is stored

### `articles`

| Group | Fields |
| --- | --- |
| Identity and source | `_id`, `dedup_id`, `source_id`, `source_name`, `feed_guid`, `url`, `normalized_url`, `canonical_url` |
| Original text | `title`, `summary`, `content`, `authors`, `categories`, `image_url` (a link only), `content_hash` |
| Place and language | `language` (from the source), `country`, `state`, `city`, `detected_language`, `language_confidence` |
| Dates | `published_at`, `collected_at`, `published_at_source` (`feed`, `page` or `collected_fallback`), `date_verified` |
| Cleaned copies | `clean_title`, `clean_summary`, `clean_body` |
| Revisions | `content_rev`, `inserted_at`, `updated_at` |
| Full-text work | `processing_status`, `scrape_status`, `scrape_attempts`, `scraped_at`, `next_scrape_at` |
| Topic | `classification_status`, `classification_claimed_at`, `classification_attempts`, `classified_at`, `topic`, `confidence`, `model_version` |

The API never shows the copy-finding keys (`dedup_id`, `normalized_url`,
`content_hash`, `feed_guid`). It does not show the C1 fields either; they are only in
the database.

Indexes on `articles` (all declared in
[`internal/mongodb/indexes.go`](../../collector/internal/mongodb/indexes.go)):
`uq_dedup_id`, `uq_normalized_url`, `uq_source_feed_guid`, `ix_canonical_url`,
`ix_content_hash`, `ix_source_published_cursor`, `ix_published_cursor`,
`ix_collected_cursor`, `ix_language_published_cursor`,
`ix_region_published_cursor`, `ix_status_collected`, `ix_scrape_backlog`,
`ix_classification_backlog`, `ix_updated_cursor`, `ix_verified_language_published`
and `ix_topic_published_cursor`.

### `sources`

Fields: `_id`, `name`, `feed_url`, `type`, `enabled`, `priority`, `language`,
`country`, `state`, `city`, `domains`, `added_by`, `fetch_interval_seconds`,
`next_scheduled_at`, `last_collected_at`, `health_status`, `consecutive_failures`,
`last_error`, `created_at` and `updated_at`. The program owns the schedule and
health fields; a request that tries to set them is refused. IDs are UUIDv7 values.
They are not secret and are not a way to control access.

Indexes: `uq_feed_url`, `ix_due_for_collection`, `ix_due_by_priority`, `ix_health`,
`ix_region` and `ix_type_enabled`.

### The other collections

`collection_runs`, `feed_cache_metadata`, `application_locks`, `read_events`,
`readers` and `reader_sessions` are also declared here. `readers` and
`reader_sessions` belong to the web server; the collector only creates them. Who may
read and write each one is on the [architecture page](../architecture/README.md#who-may-read-and-write).

`make migrate` (or the start of `cmd/api`) also drops old index names listed in
`ObsoleteIndexes`, because MongoDB cannot change an index in place.

## Safety

- **Outside addresses only.** Feed and page downloads go through a guarded HTTP
  client (`internal/httpclient`). It refuses private, loopback and link-local
  addresses (such as `169.254.169.254`), and any port other than 80 and 443. It checks
  again after each redirect, and caps redirects and download sizes.
- **Polite fetching.** Pages follow `robots.txt` (`internal/robots`), a wait per site
  and a pause after repeated failures (`internal/ratelimit`).
- **API keys.** Only SHA-256 hashes of keys are kept in memory. They are compared in
  constant time. A wrong key gets `401` and no hint.
- **Requests.** Bodies are at most 64 KiB and must be JSON. Unknown fields are refused.
- **Stored text.** Feed text is stored as plain text with the HTML removed, and every
  field has a size limit.
- **Logs.** The MongoDB password is hidden before the address is logged. Request
  headers are never logged.
- **The container** runs as user 10001, never as root.

## Checks

From `collector/`:

```bash
make check              # format check, vet, unit tests
make test-race          # unit tests with the race detector
make test-integration   # needs MongoDB on localhost:27017
```

CI runs `make fmt-check vet test-race test-integration` with a MongoDB 7 service
([`ci.yml`](../../.github/workflows/ci.yml)).
