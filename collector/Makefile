BIN_DIR   := bin
VERSION   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
LDFLAGS   := -s -w -X main.version=$(VERSION)
COMPOSE   := docker compose -f deployments/docker-compose.yml
CONFIG    ?= configs/config.yaml
SOURCES   ?= configs/sources.yaml
BACKFILL_LIMIT ?= 1000
BACKFILL_DELAY ?= 1s

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
	go build -trimpath -ldflags="$(LDFLAGS)" -o $(BIN_DIR)/reader ./cmd/reader

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
check: fmt-check vet test ## Run every gate required before a milestone is done

.PHONY: run
run: ## Run the API against the local config
	go run ./cmd/api -config $(CONFIG)

.PHONY: migrate
migrate: ## Create MongoDB collections and indexes
	go run ./cmd/migrate -config $(CONFIG)

.PHONY: seed
seed: ## Apply the sources declared in $(SOURCES)
	go run ./cmd/seed -config $(CONFIG) -sources $(SOURCES)

.PHONY: seed-check
seed-check: ## Validate the seed file without writing to the database
	go run ./cmd/seed -config $(CONFIG) -sources $(SOURCES) -dry-run

.PHONY: collect
collect: ## Collect every source that is currently due
	go run ./cmd/collector -config $(CONFIG)

.PHONY: collect-source
collect-source: ## Collect one source now: make collect-source SOURCE=<id>
	go run ./cmd/collector -config $(CONFIG) -source $(SOURCE)

.PHONY: scrape
scrape: ## Run one full-text enrichment batch against scraper.batch_size
	go run ./cmd/scrape -config $(CONFIG)

.PHONY: scrape-limit
scrape-limit: ## Run one enrichment batch of a given size: make scrape-limit LIMIT=10
	go run ./cmd/scrape -config $(CONFIG) -limit $(LIMIT)

.PHONY: backfill
backfill: ## Fill missing C1 article fields in bounded, resumable batches
	go run ./cmd/backfill -config $(CONFIG) -limit $(BACKFILL_LIMIT) -delay $(BACKFILL_DELAY)

.PHONY: up
up: ## Start MongoDB, run the migration and start the API
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop the stack and remove its volumes
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Follow the API logs
	$(COMPOSE) logs -f api

.PHONY: classifier-test
classifier-test: ## Run Flask classifier API tests
	cd ml-v2 && uv run pytest tests/test_api.py

.PHONY: classifier-build
classifier-build: ## Build the classifier serving image
	docker build -f deployments/classifier.Dockerfile -t news-classifier:dev .

.PHONY: classifier-up
classifier-up: ## Start the internal classifier service
	$(COMPOSE) up --build -d classifier

.PHONY: classifier-smoke
classifier-smoke: ## Submit one classification request; pass NEWS_CLASSIFIER_API_KEY when configured
	@$(COMPOSE) exec -T classifier python -c 'import json; from urllib.request import Request, urlopen; request = Request("http://127.0.0.1:8000/v1/classify", data=json.dumps({"items":[{"id":"smoke","title":"Market update","summary":"","body":""}]}).encode(), headers={"Content-Type":"application/json"}); print(urlopen(request).read().decode())'

.PHONY: mongo-up
mongo-up: ## Start only MongoDB, for local test runs
	$(COMPOSE) up -d mongo

.PHONY: clean
clean: ## Remove build and coverage artefacts
	rm -rf $(BIN_DIR) coverage.out coverage.html

# --- Offline ML (ml/, Python) ------------------------------------------------
# Training and data preparation never run on the homelab; the 2 GB budget is a
# serving budget. These targets are laptop-only and never touch the Go build.

.PHONY: ml-setup
ml-setup: ## Create the ml/ virtualenv and install pinned dependencies
	cd ml && uv sync --group dev

.PHONY: ml-test
ml-test: ## Run the offline ML test suite
	cd ml && uv run pytest

.PHONY: ml-profile
ml-profile: ## Write the corpus profile report and figures to ml/reports
	cd ml && uv run newsml profile

.PHONY: ml-boilerplate
ml-boilerplate: ## Discover per-source template lines for review
	cd ml && uv run newsml boilerplate

.PHONY: ml-snapshot
ml-snapshot: ## Freeze a dataset with its labels: make ml-snapshot CUT=2026-08-25T00:00:00+00:00
	cd ml && uv run newsml snapshot $(if $(ID),--id $(ID),) $(if $(CUT),--collected-before $(CUT),) \
		--no-language-check --gold data/labels/v1/gold.jsonl data/labels/v2/gold.jsonl

.PHONY: ml-train
ml-train: ## Fit the shipping classifier from a snapshot: make ml-train SNAPSHOT=data/snapshots/20260825-120
	cd ml && uv run newsml train --snapshot $(SNAPSHOT)

.PHONY: ml-labels-export
ml-labels-export: ## Write blind labelling sheets: make ml-labels-export SIZE=150 SHARDS=4 CUT=2026-08-25T00:00:00+00:00
	cd ml && uv run newsml export-labels $(if $(SIZE),--size $(SIZE),) $(if $(SHARDS),--shards $(SHARDS),) $(if $(OVERLAP),--overlap $(OVERLAP),) $(if $(CUT),--collected-before $(CUT),)

.PHONY: ml-labels-import
ml-labels-import: ## Validate completed sheets and write the gold set: make ml-labels-import SHEETS="a.csv b.csv"
	cd ml && uv run newsml import-labels --sheets $(SHEETS)

.PHONY: ml-pairs-export
ml-pairs-export: ## Write the blind near-duplicate sheet: make ml-pairs-export SNAPSHOT=data/snapshots/20260825-120
	cd ml && uv run newsml export-pairs --snapshot $(SNAPSHOT)

.PHONY: ml-pairs-import
ml-pairs-import: ## Calibrate the near-duplicate threshold from the labelled sheet
	cd ml && uv run newsml import-pairs

.PHONY: ml-verify
ml-verify: ## Rebuild a snapshot and confirm byte-identical digests
	cd ml && uv run newsml verify $(if $(ID),--id $(ID),) $(if $(CUT),--collected-before $(CUT),) \
		--no-language-check --gold data/labels/v1/gold.jsonl data/labels/v2/gold.jsonl

# nbconvert is pulled in for the run only. A notebook that has rotted is worth
# catching, but not worth a permanent dependency.
.PHONY: ml-notebook
ml-notebook: ## Execute every notebook headlessly and fail if one has rotted
	cd ml && uv run --with nbconvert --with ipykernel jupyter nbconvert \
		--to notebook --execute notebooks/*.ipynb --output-dir /tmp/newsml-nb

# --- ml-v2 (body-aware classifier, POC) --------------------------------------
# A standalone package, not an evolution of ml/. It classifies on the article body
# as well as the headline, and reruns v1's configuration on its own snapshot so the
# two are comparable. See ml-v2/docs/plan.md.

.PHONY: ml2-setup
ml2-setup: ## Create the ml-v2 virtualenv and install dependencies
	cd ml-v2 && uv sync --group dev && uv run python -m spacy download en_core_web_sm

.PHONY: ml2-test
ml2-test: ## Run the ml-v2 test suite
	cd ml-v2 && uv run pytest

.PHONY: ml2-labels
ml2-labels: ## Re-vendor the gold labels from ml/ and print the digest that pins them
	cp ml/data/labels/gold-combined.jsonl ml-v2/data/labels/gold.jsonl
	@shasum -a 256 ml-v2/data/labels/gold.jsonl

.PHONY: ml2-report
ml2-report: ## Write the data-quality report to ml-v2/reports
	cd ml-v2 && uv run newsmlv2 report

.PHONY: ml2-snapshot
ml2-snapshot: ## Freeze a dataset: make ml2-snapshot ID=v2-001 (--id is mandatory, ids must never collide)
	cd ml-v2 && uv run newsmlv2 snapshot --id $(ID)

.PHONY: ml2-verify
ml2-verify: ## Rebuild a snapshot and confirm byte-identical digests
	cd ml-v2 && uv run newsmlv2 verify --id $(ID)

.PHONY: ml2-run
ml2-run: ## Run one experiment config: make ml2-run CONFIG=configs/experiments/baseline.yaml
	cd ml-v2 && uv run newsmlv2 run --config $(CONFIG)

# --- Read-only recommendation demo -----------------------------------------
REC_ID ?= stories-002

.PHONY: rec-setup
rec-setup: ## Install the existing Python project with recommendation/serving/test extras
	cd ml-v2 && uv sync --group recommend --group serve --group dev --group demo

.PHONY: rec-inspect
rec-inspect: ## Verify which news database the app will read, without displaying its URI
	cd ml-v2 && uv run --no-sync newsrec inspect

.PHONY: rec-prepare
rec-prepare: ## Freeze a new cohort; pass REC_ID=<new-id> CUT=<past ISO timestamp>
	@test -n "$(CUT)" || (echo "CUT must be a past ISO timestamp with timezone"; exit 1)
	cd ml-v2 && uv run --no-sync newsrec prepare --id "$(REC_ID)" --cut "$(CUT)"

.PHONY: rec-baseline
rec-baseline: ## Fit TF-IDF and SVD before any neural training
	cd ml-v2 && uv run --no-sync newsrec baseline --id "$(REC_ID)"

.PHONY: rec-train
rec-train: ## Train and save the small TensorFlow/Keras autoencoder
	cd ml-v2 && uv run --no-sync newsrec train --id "$(REC_ID)"

.PHONY: rec-benchmark
rec-benchmark: ## Measure retrieval and create a blind relevance sheet (never overwrites one)
	cd ml-v2 && uv run --no-sync newsrec benchmark --id "$(REC_ID)"

.PHONY: rec-serve
rec-serve: ## Serve saved representations on localhost:8001 (TensorFlow is not loaded)
	cd ml-v2 && uv run --no-sync newsrec serve --id "$(REC_ID)"

.PHONY: reader
reader: ## Serve the read-only Stories reader at http://127.0.0.1:8090
	go run ./cmd/reader

.PHONY: rec-test
rec-test: ## Check recommendation Python, Go and browser-state logic without a live DB
	cd ml-v2 && uv run --no-sync pytest tests/test_recommendations.py tests/test_evaluation_provenance.py tests/test_recommender_defaults.py
	go test ./cmd/reader ./internal/recommendation ./internal/handler ./internal/web ./internal/config ./internal/mongodb
	node --test scripts/*.test.mjs

.PHONY: ml2-compare
ml2-compare: ## Render the model comparison table from the experiment ledger
	cd ml-v2 && uv run newsmlv2 compare
