# Collector

The collector is the Go program that gathers the news. It reads 124 RSS and Atom
feeds day and night. It saves each new story in MongoDB, fetches the full text from
the story's web page, and asks the classifier for a topic.

It is the **only** program that writes the `articles` collection. It also owns the
database layout for the whole app: every collection and index is declared in
[`internal/mongodb`](internal/mongodb/collections.go), and the collector creates them
when it starts. Collection must keep running even when the classifier, the ranker or
the web server fails.

The full guide, with the API, every setting and the data stored, is
[docs/services/collector.md](../docs/services/collector.md).

## Checks

You need Go 1.27. Run these from this `collector/` folder:

```bash
make check              # format check, go vet and the unit tests
make test-race          # the unit tests with Go's race detector
make test-integration   # tests against MongoDB on localhost:27017
```

The integration tests make throwaway `news_it_*` databases and delete them
afterwards. `make mongo-up` starts a MongoDB in Docker for them. `make help` lists
every command.

## Settings

- [`configs/config.yaml`](configs/config.yaml) holds the settings. Any setting can be
  changed with an environment variable: `NEWS_` + section + key in capitals, for
  example `NEWS_SCHEDULER_INTERVAL`.
- [`configs/sources.yaml`](configs/sources.yaml) is the feed list. The collector
  applies it every time it starts. `make seed-check` checks it without writing.
- Secrets come only from the environment: `NEWS_AUTH_API_KEYS`,
  `NEWS_AUTH_BASIC_USERNAME`, `NEWS_AUTH_BASIC_PASSWORD` and
  `NEWS_CLASSIFIER_API_KEY`. Keep the database address `NEWS_MONGO_URI` there too.
- `make` passes `NEWS_ENV_FILE=../deployment/env/local.env` to the commands that run
  the app. That file is ignored by git. Never print it or commit it.

## Careful: these commands write

`make run`, `make migrate`, `make seed`, `make collect`, `make collect-source`,
`make scrape`, `make scrape-limit`, `make backfill` and `make backfill-reclassify`
write to the database they are given. Never run them against the
production database by mistake. `make -C ../ml rec-inspect` shows which database
you will use, without printing its address.

## Folder map

| Path | What it is |
| --- | --- |
| `cmd/api` | The web API, the feed scheduler and the background workers |
| `cmd/collector`, `cmd/scrape` | Read due feeds once; fetch full text once |
| `cmd/seed`, `cmd/migrate` | Apply the feed list; create collections and indexes |
| `cmd/backfill` | Fill missing fields in old stories, or relabel topics (`-reclassify`) |
| `internal/app` | Wires the parts together for each command |
| `internal/bootstrap` | Applies the feed list and migrations at start |
| `internal/classifier` | The client that calls the classifier |
| `internal/collector/rss` | Reads RSS and Atom feeds |
| `internal/config` | Loads settings |
| `internal/domain` | The data types and their rules |
| `internal/extract` | Finds the story text, page date and picture link in a web page |
| `internal/handler` | The web API's routes |
| `internal/httpclient` | The guarded HTTP client that refuses private addresses |
| `internal/mongodb` | The database connection, collection names and indexes |
| `internal/observability` | Logs, request IDs and crash recovery |
| `internal/processor` | Turns feed items into stories and saves them |
| `internal/ratelimit`, `internal/robots` | Polite fetching: waits per site, and `robots.txt` rules |
| `internal/repository` | Reading and writing MongoDB |
| `internal/scheduler`, `internal/service` | The timed loops, and the work they do |
| `configs/` | Settings and the feed list |
| `testdata/` | Small made-up feeds for the tests |
| `Dockerfile` | Builds the `news-bot` image with every program in it |
