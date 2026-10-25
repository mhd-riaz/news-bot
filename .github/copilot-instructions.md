# news-bot — agent instructions

## Product

A personal news briefing for a small invited group: you and your brother first, then up to about 5 readers. English only, self-hosted on the owner's home lab, and useful without any paid service.

The client wants to keep up with their professional field, initially software development, data science and AI. They also want to discover relevant topics they did not know to look for, connect current news with older material, and save items for deeper study.

- **V1 — web, due 15 Nov 2026:**
  - 24×7 collector and a revision-aware batch pipeline that makes new articles recommendable within 1 h.
  - AFTERLINE web reader with Google sign-in, a fresh-first feed and archive, and a daily "yesterday" edition.
  - Likes and dislikes; topic, source and local/professional settings; reader-added RSS feeds; saved stories and topics with notes.
  - Association-rule suggestions and follow-ups, and a neural recommender compared against TF-IDF.
  - A read-only MCP server for AI agents.
- **V2 — audio and iPhone:** ask for the user's listening time, narrate a briefing sized to it from the daily edition, accept spoken commands, and ship an iPhone app. Android follows V2.

**The plan, contracts and status live in [collector/docs/roadmap.md](../collector/docs/roadmap.md).** `collector/docs/plan.md` and `collector/ml-v2/docs/plan.md` are closed classifier plans: use them as history only, never as a task source.

## Delivered in phase 1 (baseline `c06fdf4`)

- **Collector** (Go 1.27, `cmd/api`): 99 RSS/Atom sources, full-text enrichment, a 13-class topic-classifier sidecar and MongoDB `news` (~172,667 articles, ~2,661/day on 25 Oct). It runs 24×7 on the home-lab laptop via Coolify and Cloudflare Tunnel.
- **AFTERLINE MVP:** frozen edition `stories-002` (20,000 articles from 40 publishers, cut on 22 Oct). TF-IDF is the default; SVD-256 and a Keras denoising autoencoder (64-d, 82,496 parameters) are selectable. It has eight MiniBatchKMeans content groups and conservative, quadratic story grouping.
- **Serving:** a read-only Go reader (`cmd/reader`, `/stories`) calls a private Flask ranker and hydrates results with one bounded MongoDB query. Local single-reader p95 is ≤ 15.12 ms.
- **Reader:** Stories-style UI with onboarding, like/dislike, related reading and method switching. Preferences live in browser storage per snapshot.
- **Evidence:** a human pilot covered 20 pairs (TF-IDF P@5 0.80). A separate AI-assisted run covered 40 cases (TF-IDF 0.565 > SVD 0.480 > Neural 0.380). The 0.65 target is unverified. Details are in [recommender-results.md](../collector/docs/recommender-results.md).
- **Not delivered:**
  - Incremental indexing and freshness.
  - Reader sign-in; the demo runs on loopback with auth off.
  - Server-side preferences.
  - Rules and MCP.
  - Deployment of the reader and ranker.

## Architecture

| Path (under `collector/`) | Role |
|---|---|
| `cmd/api`, plus the `collector`, `scrape`, `seed` and `migrate` commands | Collector: scheduling, enrichment, classification, source sync and MongoDB migration on start. The only writer of `articles`. |
| `cmd/reader` | AFTERLINE reader and API; read-only today |
| `internal/mongodb` | The only schema owner: collection names and the index plan |
| `internal/domain`, `internal/repository/mongo`, `internal/service`, `internal/handler`, `internal/web` | Domain model, persistence, services, HTTP handlers, templates and static UI |
| `ml-v2/src/newsrec` | Recommender: `data.py` prepares data, `model.py` trains, `index.py` ranks, `api.py` serves the Flask ranker, plus `evaluate.py` and `cli.py` |
| `ml-v2/src/newsmlv2` | Shared cleaning, admission, boilerplate and dedup |
| `ml/` | Closed v1 classifier; `ml/src/newsml/neardup.py` holds the calibrated MinHash/LSH |
| `deployments/coolify.compose.yml` | Production stack: MongoDB, classifier and API |
| `configs/` | `config.yaml`, `reader.yaml` and `sources.yaml` |

Reuse existing code before writing new code:

- Lease protocol: `internal/repository/mongo/lock.go` and `application_locks`.
- SSRF guard: `internal/httpclient`.
- Robots and rate limiting: `internal/robots` and `internal/ratelimit`.
- JSON-LD extraction: `internal/extract`.
- API-key auth: `handler.Authenticator`.
- Cleaning, admission and dedup: `newsmlv2`.
- Clean text and detected language for articles: the existing classifier-sidecar call (`internal/classifier`, `ml-v2/app/api.py`).

## Hard rules

1. Collection never stops because of pipeline, model or reader failures.
2. Never delete or rewrite original `articles` fields outside the collector's own logic. Derived data goes into new fields; raw text stays.
3. Evidence comes before claims: no metric, capability or `[x]` without a recorded measurement or demonstration. A fallback is not a pass; record unmet criteria as **not met**.
4. Keep human and AI-assisted judgements in separate records. Never tune or train on sealed acceptance cases.
5. Escalate owner decisions in roadmap §7; never take them. These include scope, deadlines, R3, thresholds, content rights and retention.
6. Secrets live only in the environment or Coolify secrets — never in `configs/`, code, logs or archives. Never print the MongoDB URI; `make rec-inspect` checks the target safely.
7. Render third-party text only through `html/template` or `textContent`. State-changing browser requests need a session and CSRF protection.
8. Declare every new collection or index in `internal/mongodb`, and add a roadmap C14 row before first use.
9. Add no dependency or infrastructure without a one-line reason in roadmap §8. This includes vector databases, brokers, caches, LLMs or paid APIs, and JavaScript toolchains. Prefer the standard library, then an existing dependency, then a small package. The web reader has no JavaScript build step.
10. English only. No V1 feature may require a paid service.
11. Do not redistribute the raw corpus; publish only derived metrics and figures.
12. Pin, seed and make Python work reproducible. Notebooks call `src/` and never define logic.
13. Do not create per-change markdown files. Update the roadmap and existing docs instead.

## Working protocol (two agents)

1. Read the roadmap status board and today's row in §1.1, then your task, its milestone's build notes and the contracts it cites.
2. Claim one task by its ID: change `[ ]` to `[~] <agent> <date>` and add a work-log line. Take only tasks whose dependencies or handoffs are done.
3. Do not touch files under a task the other agent has claimed. Coordinate in the work log.
4. To finish a task, add the code, tests and exit evidence (a command and its result, or a link) to the task line, then mark it `[x]`. Update the status board and requirement status.
5. If blocked, mark the task `[!] <reason>` and add the question to §7.
6. Every contract or threshold change needs a §8 row with the reason. Never lower a threshold to make a check pass.
7. Close a milestone only after the other agent reviews its exit criteria.
8. Keep roadmap edits small: your task lines, the status board and the append-only logs.

## Build and test (from `collector/`)

- Go: run `make check` (format check, vet and unit tests) and `make test-race`. `make test-integration` needs MongoDB on `localhost:27017`.
- Recommender: run `make rec-setup` once, then `make rec-test` for pytest, Go and `node --test`. Use `make ml2-test` for `newsmlv2`.
- Local run: `make rec-serve REC_ID=stories-002` and `make reader`, then open http://127.0.0.1:8090/stories.
- Never run `make run` or `make up` against the production database — they migrate and collect.
- One scheduling-dependent Go rate-limit test is known to be flaky; M9 fixes it.

## Docs

- [roadmap.md](../collector/docs/roadmap.md) — V1/V2 plan, contracts, status and decisions.
- [recommender.md](../collector/docs/recommender.md) — recommender setup and operation.
- [recommender-results.md](../collector/docs/recommender-results.md) — measured phase-1 evidence and limits.
- [recommender-client-review.md](../collector/docs/recommender-client-review.md) — client briefing; update it with evidence at milestone exits.
- [collector/readme.md](../collector/readme.md) — collector operations.
