BIN_DIR   := bin
VERSION   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
LDFLAGS   := -s -w -X main.version=$(VERSION)
COMPOSE   := docker compose -f ../deployment/compose/compose.yaml
CONFIG    ?= configs/config.yaml
SOURCES   ?= configs/sources.yaml
BACKFILL_LIMIT ?= 1000
BACKFILL_DELAY ?= 1s

# Commands that run the app read this environment's settings; the file is never
# committed. An NEWS_ENV_FILE already set in the shell wins. Tests do not get it.
ENV_FILE  ?= ../deployment/env/local.env
RUN_ENV   := NEWS_ENV_FILE=$${NEWS_ENV_FILE:-$(ENV_FILE)}

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: tidy
tidy: ## Sync go.mod and go.sum
	go mod tidy

.PHONY: fmt
fmt: ## Format all Go sources
	gofmt -w .

.PHONY: fmt-check
fmt-check: ## Fail if any file is unformatted
	@unformatted=$$(gofmt -l .); \
	if [ -n "$$unformatted" ]; then echo "unformatted files:"; echo "$$unformatted"; exit 1; fi

.PHONY: vet
vet: ## Run go vet
	go vet ./...

.PHONY: build
build: ## Build every command into $(BIN_DIR)
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/api ./cmd/api
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/migrate ./cmd/migrate
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/seed ./cmd/seed
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/collector ./cmd/collector
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/scrape ./cmd/scrape
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/backfill ./cmd/backfill

.PHONY: test
test: ## Run unit tests (no external dependencies)
	go test ./...

.PHONY: test-race
test-race: ## Run unit tests with the race detector
	go test -race ./...

.PHONY: test-integration
test-integration: ## Run integration tests (requires MongoDB on localhost:27017)
	go test -tags=integration -count=1 ./...

.PHONY: cover
cover: ## Report unit-test coverage per package
	go test -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out | tail -1

.PHONY: check
check: fmt-check vet test ## Check Go formatting, vet and unit tests; race/integration are separate

.PHONY: run
run: ## Run the collector/API; migrates and writes to the configured database
	$(RUN_ENV) go run ./cmd/api -config $(CONFIG)

.PHONY: migrate
migrate: ## Apply collection/index schema migrations to the configured database
	$(RUN_ENV) go run ./cmd/migrate -config $(CONFIG)

.PHONY: seed
seed: ## Apply the sources declared in $(SOURCES)
	$(RUN_ENV) go run ./cmd/seed -config $(CONFIG) -sources $(SOURCES)

.PHONY: seed-check
seed-check: ## Validate the seed file without writing to the database
	$(RUN_ENV) go run ./cmd/seed -config $(CONFIG) -sources $(SOURCES) -dry-run

.PHONY: collect
collect: ## Collect every source that is currently due
	$(RUN_ENV) go run ./cmd/collector -config $(CONFIG)

.PHONY: collect-source
collect-source: ## Collect one source now: make collect-source SOURCE=<id>
	$(RUN_ENV) go run ./cmd/collector -config $(CONFIG) -source $(SOURCE)

.PHONY: scrape
scrape: ## Run one full-text enrichment batch against scraper.batch_size
	$(RUN_ENV) go run ./cmd/scrape -config $(CONFIG)

.PHONY: scrape-limit
scrape-limit: ## Run one enrichment batch of a given size: make scrape-limit LIMIT=10
	$(RUN_ENV) go run ./cmd/scrape -config $(CONFIG) -limit $(LIMIT)

.PHONY: backfill
backfill: ## Fill missing C1 article fields in bounded, resumable batches
	$(RUN_ENV) go run ./cmd/backfill -config $(CONFIG) -limit $(BACKFILL_LIMIT) -delay $(BACKFILL_DELAY)

.PHONY: backfill-reclassify
backfill-reclassify: ## Relabel articles that carry another model's topic with the sidecar's current model (writes the configured database)
	$(RUN_ENV) go run ./cmd/backfill -config $(CONFIG) -reclassify -limit $(BACKFILL_LIMIT) -delay $(BACKFILL_DELAY)

.PHONY: mongo-up
mongo-up: ## Start only MongoDB, for local test runs
	$(COMPOSE) up -d mongo

.PHONY: clean
clean: ## Remove build and coverage artefacts
	rm -rf $(BIN_DIR) coverage.out coverage.html
