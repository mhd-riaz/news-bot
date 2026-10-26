# mhd-riaz's Development Log

Entries are in reverse chronology order.

## Mon 2026-Oct-26 12:41 (UTC+05:30)
### Copilot (Model:unknown)
#### Prompt
Display name: `mhd-riaz`

“find the plan, check whats done, whats remaining for v1 version to be finished?”

“/write-code start implementation”

“you pick the best and start working on it” (when asked which roadmap tasks to cover)

Decision: approve the design; include Medium (the owner accepts the licence risk); ignore existing sources whose `robots.txt` reserves ML or text-and-data-mining (TDM) rights, and record nothing about them.

#### Plan
Implement M1.7 (R17 sources), the next task due and unblocked, and pull forward the flaky-test half of M9.1. The owner approved the design before any edit.

#### Findings
Status review (the V1 plan is `collector/docs/roadmap.md`; the `plan.md` files are closed history):
- 64 numbered tasks: 8 done, 4 in progress, 52 not started. Only M0 and M1 had started. V1 is due 15 Nov.
- The CI and deploy path was unverified: `main` was still at the "v1 plan" commit, the work lives on `v1`, and the workflow only runs on pull requests and `main` pushes, so it had never run.
- `TestConcurrentAcquireReservesDistinctSlots` was flaky and gates every `make check` and CI run.
- D2 (no backup target) blocks M1.8, the M1 exit, M9.4 and the release checklist. D10 (reader hostname and Google OAuth client) is due 29 Oct.
- The status board was stale. A 21.5 MB `collector/backfill` binary from `ecc24cc` is in the pushed `origin/v1` history.

During implementation:
- Flaky test root cause: the test clock's `Sleep` added each concurrent caller's wait to one shared time, pushing it past later callers' reserved slots, so one caller got no wait. The production limiter is correct. The test failed 259 of 3,000 runs at `-cpu=2` (39 at `-cpu=4`, 46 at `-cpu=8`).
- V1 domain tags: `technology` (general tech news), `software`, `ai` and `data-science`. They drive the C8 professional pool rule.
- 39 candidate feeds were probed with the collector User-Agent, checking status, items, English, `robots.txt`, `Content-Signal` and RSL licence.
- The Pragmatic Engineer and MediaNama send `Content-Signal: ai-train=no` to every agent, so they were left out, by the same test that excluded Al Jazeera. DT Next (`/rss` returns 404) and Citizen Matters' per-city feeds (time out or are empty) were left out too.
- Medium's licence (`medium.com/license.xml`, RSL) permits search, ai-index and ai-input with attribution but prohibits `ai-train`. Medium is included by owner decision. Its article pages answer 403 (Cloudflare) to the collector, so Medium stories keep the feed excerpt.
- The Hugging Face and OpenAI feeds carry their whole archive (890 and 1,318 items). The existing 500-item cap keeps the newest 500, because both feeds list newest first.
- `.env` sets `NEWS_MONGO_URI` to a LAN MongoDB (likely production), so `make seed` and `make collect-source` write there by default. Verification used a scratch database on the local container with the dotenv file disabled.
- The collector command refuses to start without auth credentials (`NEWS_AUTH_API_KEYS`) even though it serves no HTTP.
- The example `NEWS_BOOTSTRAP_SOURCES_PATH` URL in the readme and compose file pointed at the old public `data-scientist-roadmap` repo. If Coolify uses it, production will not see this change.

#### Changes
- Fixed the flaky test: the test clock gained a `frozen` option, and `TestConcurrentAcquireReservesDistinctSlots` freezes it and asserts the 7 waits are exactly 1 s to 7 s.
- Made `TestShippedSourcesFileIsValid` reject any domain tag outside the four V1 domains.
- Tagged 14 existing tech sources and sections `technology`: TechCrunch, The Verge, Wired, Engadget, ZDNET, MIT Technology Review, The Register, Ars Technica, and the technology sections of The Hindu, The Indian Express, Livemint, The Guardian, BBC News and NPR.
- Added 25 sources: 20 professional (including two MIT News topics, three Medium tags, Hugging Face, OpenAI and Google DeepMind) and 5 untagged local or independent (The Hindu — Chennai, Citizen Matters, The News Minute, Newslaundry, Mongabay India).
- Added a V1 domains header note to the seed file and recorded the left-out feeds at the bottom.
- Updated the roadmap: M1 in progress, R17 done in code, M1.7 done with build notes (dotenv warning, rights test), M9.1 in progress, four §8 decision rows and two §9 work-log rows.
- Pointed the example sources URL in the readme and compose file at this repo, and added a readme sentence on the four V1 domains.
- No production code changed. No commit was made.

Files changed:
- `collector/internal/ratelimit/ratelimit_test.go`
- `collector/internal/bootstrap/bootstrap_test.go`
- `collector/configs/sources.yaml`
- `collector/deployments/coolify.compose.yml`
- `collector/readme.md`
- `collector/docs/roadmap.md`

#### Verification
All passed:
- `make check`
- `make test-race`
- `go clean -testcache && go test ./... -parallel 8 -cover`
- `go test -race -count=50 ./internal/ratelimit`
- `make seed-check`: 124 sources valid (99 + 25)
- Node tests: 21/21
- ML taxonomy source-name tests (`collector/ml/tests/test_labels.py`, 3 selected), run with the `ml-v2` interpreter because `collector/ml/.venv` is stale

Flaky test and guard checks:
- After the fix: 0 failures in 3,000 runs at each of `-cpu` 1, 2, 4, 8.
- A deliberately broken reservation (`st.next = now.Add(...)`) fails the new assertion; the old "positive gap" check would have passed it.
- A misspelt tag (`datascience`) fails `TestShippedSourcesFileIsValid`.

Scratch database `news_m17_verify` on the local Mongo container, dropped afterwards (production was not touched):
- Migrated and seeded: 124 sources created; 34 sources tagged, with tag counts ai 14, technology 14, software 7, data-science 4.
- Ran `cmd/collector -source <id>` for each of the 25 new sources: all succeeded, with Hugging Face and OpenAI `partial` at the 500 cap. 1,669 items stored.
- langdetect 1.0.9: 97.6% detected as English. The misses are short English titles, plus one Tamil story from Citizen Matters, which the C1 detected-language filter drops.
- The declared rss/atom type matches every feed.

Coverage of the changed packages:
- Ratelimit: 92.5% (only the real-timer sleep is uncovered)
- Bootstrap: 64.6% (pre-existing gaps: `Run`, `Migrate` and the `LoadSources` error branches)

Full Go suite: 776 passed, 0 failed, 0 skipped.

#### Bug Notes
- Local `.env` defaults Make targets to the LAN (likely production) MongoDB. The roadmap's M1.7 build notes now say how to point them at a scratch database.
- `collector/ml/.venv` is stale: its pytest shim points at the repo's old path.
- Hugging Face and OpenAI collection runs will show `partial` on every run because of truncation, though the source is still recorded as a success.

#### Suggested Optimization
- Move the V1 domain list into the `domain` package when the M3.7 settings screen needs it.
- Add tests for the uncovered ratelimit `sleep` and the `LoadSources`/`openSources` error branches.
- If Medium's 403s waste too many scrape attempts, add a per-host scrape skip; until then the host circuit breaker bounds them.

## Mon 2026-Oct-26 09:25 (UTC+05:30)
### Copilot (Model:unknown)
#### Prompt
Display name: `mhd-riaz`

“go proceed with v1 implementation of our plan, stop if you need any help or if you need my decision on”

Decision: keep `added_by` server-owned and defer reader ownership to authentication.

#### Plan
Implement the spec-driven M1.6 changes for domain tags and optional UUID `added_by`, including seed parsing/sync, Mongo persistence, API behavior, tests, and documentation.

#### Findings
- Domains are normalized and validated.
- `added_by` is an optional UUID.
- API requests cannot set `added_by`; it remains server-owned.
- Reader ownership is deferred to authentication.
- No migrations or indexes are required.

#### Changes
- Added domain tags and optional `added_by` across the domain, bootstrap, service, handler, and Mongo integration layers.
- Exposed both fields in API responses.
- Allowed API create/patch requests to manage domains.
- Updated seed configuration, tests, readme, and roadmap.
- Marked M1.6 complete.

Files changed:
- `collector/internal/domain/source.go`
- `collector/internal/domain/source_test.go`
- `collector/internal/bootstrap/bootstrap.go`
- `collector/internal/bootstrap/bootstrap_test.go`
- `collector/internal/service/source.go`
- `collector/internal/service/source_test.go`
- `collector/internal/handler/source.go`
- `collector/internal/handler/source_test.go`
- `collector/internal/repository/mongo/source_integration_test.go`
- `collector/configs/sources.yaml`
- `collector/readme.md`
- `collector/docs/roadmap.md`

#### Verification
All passed:
- `go test ./internal/domain ./internal/bootstrap ./internal/service ./internal/handler`
- `go test -tags=integration -count=1 ./internal/repository/mongo`
- `go test ./... -parallel 8 -cover`
- `make check`
- `make test-race`
- `git diff --check`

Full-suite coverage:
- Domain: 92.3%
- Handler: 96.5%
- Bootstrap: 64.6%
- Service: 88.6%
- Command packages with no tests: 0%
- Mongo repository: 0% in regular coverage because it is integration-tagged

No test failures.

#### Bug Notes
None reported.

#### Suggested Optimization
None.
