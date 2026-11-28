# news-bot — agent instructions

## How to talk to the owner

Follow this in every chat reply:

- Keep replies short. Say only what is needed and what is important.
- Use simple English that an 8th-grade student in India can follow.
- If you must use a technical word, explain it in a few simple words the first time.
- Make the words simple, not the facts. The owner knows the subject well, so keep exact names, numbers, commands and file paths.
- Give the answer first. Add more detail only when the owner asks for it.

Write the docs in this repository the same way.

## Product

A personal news briefing for a small invited group: you and your brother first, then up to about 5 readers. English only, self-hosted on the owner's home lab, and useful without any paid service.

The client wants to keep up with their professional field, initially software development, data science and AI. They also want to discover relevant topics they did not know to look for, connect current news with older material, and save items for deeper study.

- **V1 — web, original target 15 Nov 2026 (not accepted; no revised date approved):**
  - 24×7 collector and a revision-aware batch pipeline that makes new articles recommendable within 1 h.
  - AFTERLINE web reader with Google sign-in, a fresh-first feed and archive, and a daily "yesterday" edition.
  - Likes and dislikes; topic, source and local/professional settings; reader-added RSS feeds; saved stories and topics with notes.
  - Association-rule suggestions and follow-ups, and a neural recommender compared against TF-IDF.
  - A read-only MCP server for AI agents.
- **V2 — audio and iPhone:** ask for the user's listening time, narrate a briefing sized to it from the daily edition, accept spoken commands, and ship an iPhone app. Android follows V2.

**The plan, contracts and status live in [docs/project/roadmap.md](../docs/project/roadmap.md).** The closed plans in `docs/history/` are history only, never a task source.

## Where things are

| Folder | What it is |
|---|---|
| `collector/` | Go 1.27. Reads 124 RSS/Atom feeds day and night, cleans and enriches articles, and asks the classifier for topics. The only program that writes `articles`. `collector/internal/mongodb` owns the database layout for the whole app. |
| `ml/` | Python 3.12, one uv project: the classifier service (`ml/classifier`), the ranker service (`ml/recommender`), training code (`ml/src`: `newsml`, `newsmlv2`, `newsrec`, `newsmlv4`) and the list of model files (`ml/models.toml`). Model files are downloaded into `ml/models/` and never committed. |
| `server/` | Python 3.12. The web server: the reader API, Google sign-in, sessions, and the built React app. The same code also runs `newsbot-mcp`, the separate read-only MCP program for AI agents. |
| `frontend/` | React + TypeScript with Vite: the AFTERLINE reader, checked by Biome. |
| `data/labels/` | The one topic-label dataset: article IDs, topics and the train/test split. No article text. |
| `deployment/` | The Helm chart (`helm/news-bot`), Docker Compose files (`compose/`), environment templates (`env/`) and database users (`mongo/`). |
| `docs/` | Plain-English docs. `docs/project/roadmap.md` is the plan; `docs/history/` keeps closed work. |
| `run.sh` | Starts the whole app on this computer. |
| `.github/` | CI (`workflows/ci.yml`), these instructions, path-specific instructions (`instructions/`) and skills (`skills/`). Shared MCP settings live in `/.mcp.json`, because the tools do not read MCP settings from `.github/`. |

How a story reaches a reader: collector → MongoDB → ranker snapshot (built with `make -C ml demo-refresh`) → ranker service → server → React app. The collector calls the classifier to give each article a topic.

## Current state (27 Nov 2026)

These are code and local checks. They do not close V1 acceptance or prove today's service health.

- **Restructure:** the repository was reorganised on 27 Nov (roadmap milestone RS, decision D21). Old study code is at git tag `before-restructure`, and a full private copy is `mhd-riaz/news-bot-archive`.
- **Collector:** C1 date provenance, revisions, write timestamps, cleaning and language results, reclassification and resumable backfill are built. The production backfill and deployment checks are still open. Collection does not reject non-English articles by itself.
- **Reader:** the Python server and React app replace the Go reader: Fresh, Yesterday and Archive views, professional focus, a grid front page and full-screen reading view, related stories, saved stories with notes in browser storage, and a light/dark switch. Google sign-in is built but not yet tested with a real OAuth client (roadmap D10). There are no server-side likes, settings or saved items, saved topics or reader-added feeds yet (M3).
- **Limits:** ranker snapshots are rebuilt by hand. There is no automatic revision-aware index, no measured one-hour freshness, no stored per-reader editions and no association rules yet (M2 to M5).
- **MCP:** five read-only tools. `get_story_group` and `get_rules` wait for association rules and story links (M5).
- **Classifier:** the production model is `v4-ai-072b01a9ceaf-hybrid_svc` (D19), trained on the labels in `data/labels/`; that folder's README says how the labels were made. Human validation and 200 human labels per class are not met.
- **Deployment:** production runs on Coolify from `deployment/compose/coolify.compose.yml` (Coolify read an older copy in `data-scientist-roadmap` until 28 Nov), and publishing is gated by `DEPLOY_ENABLED`. Production MongoDB requires TLS. A local image build is not a deployment.

Phase-1 history and the measured recommender results are in [recommender-results.md](../docs/project/recommender-results.md).

## Reuse before writing new code

- Leases: `collector/internal/repository/mongo/lock.go` and `application_locks`.
- SSRF guard: `collector/internal/httpclient`. Robots and rate limits: `collector/internal/robots` and `collector/internal/ratelimit`.
- JSON-LD extraction: `collector/internal/extract`. API keys for the collector API: `handler.Authenticator`.
- Cleaning, admission and dedup: `newsmlv2` in `ml/src`. Clean text and detected language for an article: the classifier call (`collector/internal/classifier`, `ml/classifier/app/api.py`).
- Reading articles, ranking calls and settings for the web app and MCP: `server/src/newsbot_server/core`.

## Hard rules

1. Collection never stops because of pipeline, model, ranker or server failures.
2. Never delete or rewrite original `articles` fields outside the collector's own logic. Derived data goes into new fields; raw text stays.
3. Evidence comes before claims: no metric, capability or `[x]` without a recorded measurement or demonstration. A fallback is not a pass; record unmet criteria as **not met**.
4. Keep human and AI-assisted judgements in separate records. Never tune or train on sealed acceptance cases.
5. Escalate owner decisions in roadmap §7; never take them. These include scope, deadlines, R3, thresholds, content rights and retention.
6. Secrets live only in the environment, in `deployment/env/<environment>.env` (ignored by git) or in platform secrets — never in configs, code, logs or archives. Never print the MongoDB URI; `make -C ml rec-inspect` checks the target safely.
7. Show third-party text only as text (React text, `textContent`). Never use `dangerouslySetInnerHTML`. State-changing browser requests need a signed-in session and the cross-site check.
8. Declare every new collection or index in `collector/internal/mongodb`, and add a roadmap C14 row before first use.
9. Add no dependency or infrastructure without a one-line reason in roadmap §8. This includes vector databases, brokers, caches, LLMs, paid APIs and JavaScript packages. Prefer the standard library, then an existing dependency, then a small package. The React app uses Vite, TypeScript, Biome and Vitest (D21); keep its dependency list short.
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

## Build and test

- Whole app on this computer: `./run.sh` (`./run.sh help` lists every command).
- `collector/`: `make check`, `make test-race`, and `make test-integration` (needs MongoDB on localhost:27017).
- `ml/`: `make setup` once, then `make test`.
- `server/`: `uv sync --frozen`, then `uv run pytest`.
- `frontend/`: `npm ci`, then `npm run ci` (Biome, type check, tests, build).
- `deployment/`: `helm lint` and `helm template` with each values file in `deployment/helm/news-bot`, `docker compose -f deployment/compose/compose.yaml config`, and `node --test deployment/mongo/mongo-users.test.mjs`.
- CI (`.github/workflows/ci.yml`) runs all of these. `ci-passed` is the check `main` requires.
- Never run collector commands that write (`make run`, `make migrate`, `make seed`, `make collect*`, `make scrape*`, `make backfill*`) against the production database.

## Docs

- [roadmap.md](../docs/project/roadmap.md): the V1/V2 plan, contracts, status and decisions.
- [recommender-results.md](../docs/project/recommender-results.md): measured phase-1 evidence and limits.
- [recommender-client-review.md](../docs/project/recommender-client-review.md): the client briefing; update it with evidence at milestone exits.
- Each part has its own README: [collector](../collector/README.md), [ml](../ml/README.md), [server](../server/README.md), [frontend](../frontend/README.md) and [data/labels](../data/labels/README.md).
