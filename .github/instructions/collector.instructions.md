---
applyTo: "collector/**"
---

# Collector (Go)

- The collector is the only program that writes to `articles`. Never delete or rewrite original article fields; put new derived data in new fields (hard rule 2).
- `collector/internal/mongodb` owns the database layout for the whole app, including collections the Python server uses. Declare every new collection or index there first, and add a row to roadmap table C14 (hard rule 8).
- Reuse what exists: leases (`internal/repository/mongo/lock.go`), the SSRF guard (`internal/httpclient`), robots rules and rate limits (`internal/robots`, `internal/ratelimit`), JSON-LD extraction (`internal/extract`) and API keys (`handler.Authenticator`).
- Collection must keep running when the classifier, the ranker or the server fails (hard rule 1).
- Settings come from `configs/config.yaml` plus `NEWS_*` environment variables. Make passes `NEWS_ENV_FILE=../deployment/env/local.env` only to commands that run the app; never print its values.
- Check from `collector/`: `make check` (format, vet, unit tests), `make test-race`, and `make test-integration` (needs MongoDB on localhost:27017; the tests use throwaway `news_it_*` databases and drop them).
- Never run `make run`, `make migrate`, `make seed`, `make collect*`, `make scrape*` or `make backfill*` against the production database: they write to it.
