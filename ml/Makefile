# Machine-learning commands. Run them from this ml/ folder.
#
# `make setup` creates ml/.venv once; every other target uses that environment as it is
# (`uv run --no-sync`), so a target never adds or removes packages behind your back.
# Commands that read the news database use the collector's settings file,
# ../deployment/env/local.env, or the file named by NEWS_ENV_FILE. Tests never read it.

COMPOSE   := docker compose -f ../deployment/compose/compose.yaml
UV_RUN    := uv run --no-sync
TEST_ENV  := NEWS_ENV_FILE=/dev/null
V4_DATA   := artifacts/v4
# The download script needs only the standard library of Python 3.11 or newer.
STDLIB_PY := uv run --no-project --python 3.12 python

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# --- Setup, tests and model files ---------------------------------------------

.PHONY: setup
setup: ## Create ml/.venv with every group: dev (tests), recommend (TensorFlow) and serve (Flask)
	uv sync --group dev --group recommend --group serve

.PHONY: test
test: ## Run every ML test (v1, v2, recommender, classifier service and V4)
	$(TEST_ENV) $(UV_RUN) pytest

.PHONY: ml-test
ml-test: ## Run the closed v1 classifier tests (tests/newsml)
	$(TEST_ENV) $(UV_RUN) pytest tests/newsml

.PHONY: ml2-test
ml2-test: ## Run the newsmlv2, recommender and classifier-service tests (tests/newsmlv2)
	$(TEST_ENV) $(UV_RUN) pytest tests/newsmlv2

.PHONY: ml4-test
ml4-test: ## Run the V4 sampler, pool, trainer and serving tests (tests/newsmlv4)
	$(TEST_ENV) $(UV_RUN) pytest tests/newsmlv4

.PHONY: classifier-test
classifier-test: ## Run the Flask classifier service tests
	$(TEST_ENV) $(UV_RUN) pytest tests/newsmlv2/test_api.py

.PHONY: rec-test
rec-test: ## Run the recommender's Python tests (the Go and browser parts: make -C ../collector rec-test)
	$(TEST_ENV) $(UV_RUN) pytest tests/newsmlv2/test_recommendations.py tests/newsmlv2/test_evaluation_provenance.py tests/newsmlv2/test_recommender_defaults.py

.PHONY: models
models: ## Download the model files listed in models.toml into models/ and check their SHA-256
	$(STDLIB_PY) scripts/download_models.py

.PHONY: models-check
models-check: ## Check the downloaded model files against models.toml without downloading
	$(STDLIB_PY) scripts/download_models.py --check

# --- Classifier service (classifier/) -----------------------------------------

.PHONY: classifier-build
classifier-build: ## Build the classifier service image
	docker build -f classifier/Dockerfile -t news-classifier:dev .

.PHONY: classifier-up
classifier-up: ## Start the internal classifier service with Docker Compose
	$(COMPOSE) up --build -d classifier

.PHONY: classifier-smoke
classifier-smoke: ## Submit an unauthenticated classifier probe; requires classifier auth disabled
	@$(COMPOSE) exec -T classifier python -c 'import json; from urllib.request import Request, urlopen; request = Request("http://127.0.0.1:8000/v1/classify", data=json.dumps({"items":[{"id":"smoke","title":"Market update","summary":"","body":""}]}).encode(), headers={"Content-Type":"application/json"}); print(urlopen(request).read().decode())'

# --- Read-only recommendation demo (src/newsrec, recommender/) ----------------
# Historical baseline ID; use a new REC_ID for builds, or demo-refresh/demo-serve.
REC_ID ?= stories-002

.PHONY: recommender-build
recommender-build: ## Build the ranker service image
	docker build -f recommender/Dockerfile -t news-recommender:dev .

.PHONY: rec-inspect
rec-inspect: ## Verify which news database the app will read, without displaying its URI
	$(UV_RUN) newsrec inspect

.PHONY: rec-prepare
rec-prepare: ## Freeze a new cohort; pass REC_ID=<new-id> CUT=<past ISO timestamp>
	@test -n "$(CUT)" || (echo "CUT must be a past ISO timestamp with timezone"; exit 1)
	$(UV_RUN) newsrec prepare --id "$(REC_ID)" --cut "$(CUT)"

.PHONY: rec-baseline
rec-baseline: ## Fit TF-IDF and SVD before any neural training
	$(UV_RUN) newsrec baseline --id "$(REC_ID)"

.PHONY: rec-train
rec-train: ## Train and save the small TensorFlow/Keras autoencoder
	$(UV_RUN) newsrec train --id "$(REC_ID)"

.PHONY: rec-benchmark
rec-benchmark: ## Measure retrieval and create a blind relevance sheet (never overwrites one)
	$(UV_RUN) newsrec benchmark --id "$(REC_ID)"

.PHONY: rec-serve
rec-serve: ## Serve saved representations on localhost:8001 (TensorFlow is not loaded)
	$(UV_RUN) newsrec serve --id "$(REC_ID)"

DEMO_RECENT_DAYS ?= 7
DEMO_LIMIT       ?= 30000
DEMO_CANDIDATES  ?= 40000
DEMO_POINTER     := artifacts/recommender/LATEST_DEMO

.PHONY: demo-refresh
demo-refresh: ## Build a recent-first snapshot within the configured candidate/article budgets, plus an older sample
	@$(UV_RUN) newsrec inspect
	@id=demo-$$(date -u +%Y%m%dT%H%M%SZ); \
	cut=$$(python3 -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(timespec="seconds"))'); \
	$(UV_RUN) newsrec prepare --id "$$id" --cut "$$cut" --limit $(DEMO_LIMIT) \
		--candidates $(DEMO_CANDIDATES) --recent-days $(DEMO_RECENT_DAYS) \
	&& $(UV_RUN) newsrec baseline --id "$$id" && $(UV_RUN) newsrec train --id "$$id" \
	&& echo "$$id" > $(DEMO_POINTER) && echo "Built $$id. Restart the ranker with: make demo-serve"

.PHONY: demo-serve
demo-serve: ## Serve the latest demo-refresh snapshot on localhost:8001
	@test -s $(DEMO_POINTER) || (echo "No demo snapshot yet: run make demo-refresh"; exit 1)
	$(MAKE) rec-serve REC_ID=$$(cat $(DEMO_POINTER))

# --- V4 classifier: candidates, labels and training (src/newsmlv4) ------------
# Private runs, pools and proposals live in artifacts/v4/; trained models go to
# models/classifier/. Roadmap D16: every existing classifier label is AI-generated.

.PHONY: ml4-labels-export
ml4-labels-export: ## Export fresh, balanced classifier candidates: make ml4-labels-export CUT=2026-11-10T00:00:00+00:00
	@test -n "$$NEWS_ML_MONGO_URI" || { echo "Set NEWS_ML_MONGO_URI to a local read-only MongoDB URI (do not print it)" >&2; exit 1; }
	$(UV_RUN) python -m newsmlv4.cli \
		$(if $(CUT),--cut $(CUT),) $(if $(OUT),--out $(V4_DATA)/$(OUT),) \
		$(if $(SEED),--seed $(SEED),) $(if $(PER_CLASS),--per-class $(PER_CLASS),) \
		$(if $(SCAN_LIMIT),--scan-limit $(SCAN_LIMIT),) \
		$(if $(PROPOSALS),--proposals $(V4_DATA)/proposals/$(PROPOSALS),) \
		$(if $(START),--start $(START),) \
		$(foreach path,$(REVIEWED_GOLDS),--reviewed-gold $(V4_DATA)/$(path))

.PHONY: ml4-train
ml4-train: ## Choose and save a local V4 classifier: DATASET=<AI pool> or RUNS="<genuine human runs>"
	@test -n "$(RUNS)$(DATASET)" || { echo "Set DATASET to an AI pool or RUNS to genuine human-reviewed runs" >&2; exit 1; }
	@if test -n "$(DATASET)" -a -n "$(RUNS)"; then echo "DATASET and RUNS are mutually exclusive" >&2; exit 1; fi
	$(UV_RUN) python -m newsmlv4.train \
		$(if $(DATASET),--dataset $(V4_DATA)/$(DATASET),$(foreach run,$(RUNS),--run $(run))) $(if $(MODELS),--models $(MODELS),) \
		$(foreach run,$(WEAK_RUNS),--weak-run $(run)) \
		$(if $(ACCEPT_SHORTFALL),--accept-shortfall,)

.PHONY: ml4-labels-verify
ml4-labels-verify: ## Verify exported V4 text has not changed: make ml4-labels-verify RUN=v4-20261110T120557Z
	@test -n "$$NEWS_ML_MONGO_URI" || { echo "Set NEWS_ML_MONGO_URI to a local read-only MongoDB URI (do not print it)" >&2; exit 1; }
	@test -n "$(RUN)" || { echo "Set RUN to the name of a directory inside $(V4_DATA)/" >&2; exit 1; }
	$(UV_RUN) python -m newsmlv4.verify --run $(V4_DATA)/$(RUN)

.PHONY: ml4-labels-import
ml4-labels-import: ## Validate V4 sheets and write legacy gold.jsonl; provenance must be recorded separately
	@test -n "$(RUN)" || { echo "Set RUN to the name of a directory inside $(V4_DATA)/" >&2; exit 1; }
	@test ! -e "$(V4_DATA)/$(RUN)/gold.jsonl" || { echo "Refusing to overwrite V4 gold" >&2; exit 1; }
	$(MAKE) ml4-labels-verify RUN=$(RUN)
	$(UV_RUN) newsml import-labels --sheets $(V4_DATA)/$(RUN)/*.csv --out $(V4_DATA)/$(RUN)/gold.jsonl

# Only for a run whose export database is gone (roadmap D14): checks the sheets against
# the export fingerprints, records a re-check against today's database, then writes
# legacy gold.jsonl. Existing classifier labels are AI-generated (roadmap D16).
.PHONY: ml4-labels-import-exported
ml4-labels-import-exported: ## Import V4 labels on the export-time DB check (D14); not proof of human review
	@test -n "$$NEWS_ML_MONGO_URI" || { echo "Set NEWS_ML_MONGO_URI to a local read-only MongoDB URI (do not print it)" >&2; exit 1; }
	@test -n "$(RUN)" || { echo "Set RUN to the name of a directory inside $(V4_DATA)/" >&2; exit 1; }
	$(UV_RUN) python -m newsmlv4.importer --run $(V4_DATA)/$(RUN)

# --- Closed classifier studies: v1 (src/newsml) and v2 (src/newsmlv2) ---------
# Kept for reference; neither is the production model. Their history is in
# ../docs/history/ml/. Rebuilding the old v1 snapshots needs the label rounds and
# snapshots at git tag before-restructure.

.PHONY: ml-profile
ml-profile: ## Write the corpus profile report and figures to reports/
	$(UV_RUN) newsml profile

.PHONY: ml-boilerplate
ml-boilerplate: ## Discover per-source template lines for review
	$(UV_RUN) newsml boilerplate

.PHONY: ml-train
ml-train: ## Fit the legacy classifier from a snapshot: make ml-train SNAPSHOT=data/snapshots/<id>
	$(UV_RUN) newsml train --snapshot $(SNAPSHOT)

.PHONY: ml-labels-export
ml-labels-export: ## Write blind labelling sheets: make ml-labels-export SIZE=150 SHARDS=4 CUT=2026-08-25T00:00:00+00:00
	$(UV_RUN) newsml export-labels $(if $(SIZE),--size $(SIZE),) $(if $(SHARDS),--shards $(SHARDS),) $(if $(OVERLAP),--overlap $(OVERLAP),) $(if $(CUT),--collected-before $(CUT),)

.PHONY: ml-labels-import
ml-labels-import: ## Validate sheets and write legacy gold.jsonl; the filename does not establish human provenance
	$(UV_RUN) newsml import-labels --sheets $(SHEETS)

.PHONY: ml-pairs-export
ml-pairs-export: ## Write the blind near-duplicate sheet: make ml-pairs-export SNAPSHOT=data/snapshots/<id>
	$(UV_RUN) newsml export-pairs --snapshot $(SNAPSHOT)

.PHONY: ml-pairs-import
ml-pairs-import: ## Calibrate the near-duplicate threshold from the labelled sheet
	$(UV_RUN) newsml import-pairs

.PHONY: ml2-snapshot
ml2-snapshot: ## Freeze a dataset: make ml2-snapshot ID=v2-001 (--id is mandatory, ids must never collide)
	$(UV_RUN) newsmlv2 snapshot --id $(ID)

.PHONY: ml2-verify
ml2-verify: ## Rebuild a snapshot and confirm byte-identical digests: make ml2-verify ID=v2-001
	$(UV_RUN) newsmlv2 verify --id $(ID)

.PHONY: ml2-report
ml2-report: ## Write a snapshot's data-quality report to reports/: make ml2-report ID=v2-001
	$(UV_RUN) newsmlv2 report --id $(ID)
