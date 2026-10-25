# AFTERLINE roadmap — V1 web, V2 audio and iPhone

This is the single source of truth for agents: scope, contracts, milestones, status and decisions. Working rules and the delivered baseline are in [copilot-instructions.md](../../.github/copilot-instructions.md).

**Updated:** 25 Oct 2026 · **V1 due:** 15 Nov 2026 · **Baseline:** code `c06fdf4`, edition `stories-002`

Task markers: `[ ]` todo · `[~]` in progress (agent, date) · `[x]` done (evidence) · `[!]` blocked (reason)

## 1. Status board

| Milestone | Owner | Window | Needs | Status |
|---|---|---|---|---|
| M0 Baseline and guardrails | Owner, A, B | 26–27 Oct | — | todo |
| M1 Collector hardening and sources | A | 26–30 Oct | M0 roles | todo |
| M2 Revision-aware pipeline | A | 28 Oct–3 Nov | H1 | todo |
| M3 Accounts, settings, saved items, reader feeds | B | 29 Oct–6 Nov | M0; H2a for the feed | todo |
| M4 Daily edition (text) | B | 5–8 Nov | H2a, H3 | todo |
| M5 Association rules | A | 1–7 Nov | H2b | todo |
| M6 Recommendation model and tuning | A | 4–9 Nov | H2b, H5 | todo |
| M7 MCP server | B | 6–9 Nov | H2a; H5 for rule tools | todo |
| M8 Freeze and human evaluation | Owner, A | 10–13 Nov | M3–M6 | todo |
| M9 Hardening and handover | B; A reviews | 13–15 Nov | M7, M8 | todo |

Milestones overlap only through these handoffs. A dependent task starts when its handoff is marked done here.

| Handoff | From → to | Delivers | Target | Status |
|---|---|---|---|---|
| H1 | M1 → M2 | New articles carry every C1 field | 28 Oct | todo |
| H2a | M2 → M3, M4, M7 | Ranker serves generations with C2 freshness, `source_ids` and date-window filters | 31 Oct | todo |
| H2b | M2 → M5, M6 | First full English index with story groups and multi-topic assignment | 1 Nov | todo |
| H3 | M3 → M4 | Sign-in, events, settings and saved-items APIs | 5 Nov | todo |
| H5 | M5 → M6, M7 | Follow-up links and topic labels | 5 Nov | todo |

**Owners (pending D1).** Agent A handles data and ML: collector changes, pipeline, rules, model and evaluation tooling. Agent B handles product and platform: reader, auth, settings, edition, MCP, deployment and security. The agent that did not build a milestone reviews its exit. The owner takes the §7 decisions, sends invites, sets up the OAuth client and coordinates grading.

## 2. Requirements

V1 is the web product, due 15 Nov. V2 is the audio briefing and iPhone app. Android follows V2.

| ID | Requirement | Ver | Contract → milestone | Status |
|---|---|---|---|---|
| R1 | You and your brother first, then up to ~5 invited readers; not public | V1 | C8, C10 → M3 | todo |
| R2 | Fresh news first, archive available | V1 | C2 → M2, M3 | todo |
| R3 | Fresh = verified publish date within 30 days; unverified dates are never fresh; only the owner can relax this (D7) | V1 | C1, C2 → M1, M2 | todo |
| R4 | English only, including production | V1 | C1 → M1 | todo |
| R5 | A new article is recommendable within 1 h of collection, end to end | V1 | C5 → M2 | todo |
| R6 | Explicit like/dislike plus chosen topics and sources; no implicit signals, no muting | V1 | C7, C8 → M3 | todo |
| R7 | Association rules: (a) unpicked topic suggestions, (b) follow-up stories, (c) topic labels | V1 | C6 → M5 | todo |
| R8 | Runs 24×7 on the home-lab laptop (12 GB RAM, i5, Coolify, Cloudflare Tunnel) | V1 | C15 → M9 | collector running |
| R9 | Self-hosted MongoDB on the same machine | V1 | C14 | running |
| R10 | Language, real publish date and boilerplate fixed in the collector | V1 | C1 → M1 | todo |
| R11 | Never store image files; publisher URL only, text fallback | V1 | C1 | URL stored today |
| R12 | Google sign-in restricted to invited accounts | V1 | C10 → M3 | todo |
| R13 | Read-only MCP for AI agents, authenticated with API keys | V1 | C11 → M7 | todo |
| R14 | Neural model trained for recommendation, compared with existing methods | V1 | C12 → M6 | todo |
| R15 | Human Useful P@5 ≥ 0.65 and not below TF-IDF | V1 | C13 → M8 | todo |
| R16 | All V1 scope, including hardening, by 15 Nov 2026 | V1 | §1 | todo |
| R17 | Software, data science and AI sources, including MIT, Medium, local and independent publications | V1 | C1 → M1 | todo |
| R18 | Save stories and topics, with notes | V1 | C8 → M3 | todo |
| R19 | Daily edition of yesterday's relevant stories (text) | V1 | C9 → M4 | todo |
| R20 | Settings: professional news, local news (city) or both; professional domains | V1 | C8 → M3 | todo |
| R21 | Readers add their own RSS feeds | V1 | C8 → M3 | todo |
| R22 | Useful without any paid service; optional paid integrations allowed | all | Rules | ongoing |
| R23 | Connect current news with older relevant material | V1 | C6, C7 → M5 | todo |
| V2-1 | Ask how much listening time the user has | V2 | §10 | backlog |
| V2-2 | One coherent briefing script from the daily edition, sized to that time | V2 | §10 | backlog |
| V2-3 | Text-to-speech narration | V2 | §10 | backlog |
| V2-4 | Spoken commands: playback, save stories, explore topics | V2 | §10 | backlog |
| V2-5 | iPhone app: edition, audio, saved items and notes | V2 | §10 | backlog |
| V2-6 | MCP access to a reader's own saved items and notes (D8) | V2 | §10 | backlog |
| L-1 | Android app | later | — | backlog |

## 3. Contracts (V1)

### C1. Article and source data

New `articles` fields. Existing fields keep their meaning; backfill writes only these fields.

| Field | Rule |
|---|---|
| `detected_language`, `language_confidence` | Detected from the text. `language` keeps the source-declared value. Everything downstream filters on `detected_language = "en"`. |
| `published_at_source` | `feed`, `page` (JSON-LD `datePublished` or `article:published_time`, extending [jsonld.go](../internal/extract/jsonld.go)) or `collected_fallback` |
| `date_verified` | `true` only for `feed` or `page` |
| `clean_title`, `clean_summary`, `clean_body` | Cleaned copies; raw `title`, `summary` and `content` are never overwritten. Publisher boilerplate rules come from the Python discovery, are reviewed, and are committed as `configs/boilerplate.yaml`. |
| `image_url` | Existing field. Add the page `og:image` or `twitter:image` when the feed has none. Never download images. |
| `content_rev` | 1 on insert; `$inc` on every write that changes text, clean fields, detected language, publish date or image URL, including enrichment and backfill. Classification writes do not bump it. |
| `updated_at` | Written in the same update as each `content_rev` change: `$currentDate` on updates; on insert, set in the repository just before `InsertOne`, never in `NewArticle`. |
| `inserted_at` | Write time of the insert. `collected_at` is unchanged. |

- Indexes, declared in [indexes.go](../internal/mongodb/indexes.go): `{updated_at: 1, _id: 1}` and `{date_verified: 1, detected_language: 1, published_at: -1}`.
- Backfill for existing articles writes new fields only, in batches, at low priority, and is resumable. Old dates: `published_at == collected_at` means `collected_fallback`; otherwise `feed`.
- Golden fixtures in `fixtures/cleaning/` are asserted by both suites: Go cleaning and English decisions must equal Python `clean_article` and `english_text` on the same inputs.
- Sources gain optional `domains` (tags such as `ai`, `software`, `data-science`) and `added_by` (reader ID for reader feeds). `city` already exists.
- Tag existing technology sources and sections. Add MIT, Medium and other software, data science and AI feeds, plus local and independent publications. Enable each only after it collects English articles within robots rules.

### C2. Freshness

- Fresh means `detected_language = "en"`, `date_verified`, and `0 ≤ now − published_at ≤ 30 days`. The ranker applies this at request time; `now` is the request time, or the frozen `t_eval` in M8.
- Unverified dates are never fresh. Those articles stay in the archive and related reading, labelled "date unverified".
- Archive means every other indexed English article.

### C3. Pipeline checkpoint

- The active generation's manifest holds the watermark `(updated_at, _id)`. `pipeline_runs` is only a log.
- A run reads the active manifest (base generation `B`, `model_version`, watermark `W`), selects `updated_at ≥ W − 10 min`, and skips `(article_id, content_rev)` pairs already in `B`. It prepares text from `clean_*` fields with the existing input recipe, builds story groups, vectorises with pinned models and assigns topics. It refreshes rules and labels (M5), writes generation `B+1`, then activates it (C4).
- Story groups: vendor the calibrated MinHash/LSH from [neardup.py](../ml/src/newsml/neardup.py) (32 bands × 4 rows, threshold 0.44) into ml-v2. Compare only within 72 h and keep the `is_recurring_template` guard. The pipeline does not use the quadratic `story_groups` in [model.py](../ml-v2/src/newsrec/model.py).
- Topics: each article gets a primary topic (nearest centroid) and up to two secondary topics within a similarity margin. Articles far from every centroid stay `unassigned` until the next retrain. Retrain chooses the topic count by silhouette or coherence plus human review; 8 is too few.
- A changed article replaces its row. An article that stops qualifying is removed.
- Nightly reconciliation compares every eligible article's `content_rev` with the active generation. It re-queues stale or missing rows, removes ineligible rows, and reports counts.
- Any failure before activation leaves the active generation and watermark unchanged.

### C4. Publication and activation

- `index_generations` stores one manifest per generation: `index_generation`, `base_generation`, `model_version`, `watermark`, `rules_version`, `labels_version`, artifact hashes, counts, `created_at` and `status`. One pointer document, `{_id: "active", index_generation, model_version}`, marks the active generation.
- **Activation is a compare-and-set** on the pointer from the expected `(B, model_version)`. No match means the build is stale: discard it and rebuild from the new active generation. Never overwrite the pointer blindly.
- The lease reuses `application_locks` with resource `pipeline:publish` and the protocol in [lock.go](../internal/repository/mongo/lock.go). It only prevents wasted work; the compare-and-set decides.
- Retrain promotion:
  1. Fit on cut `W_r` and transform every eligible article up to it.
  2. Pass the gates on development cases.
  3. Read active `B`, then catch up by transforming `updated_at ≥ W_r − 10 min` with the new models.
  4. Build rules and labels for the new model.
  5. Compare-and-set from `B`. If that fails, redo catch-up from the new active generation.
- Rollback is a compare-and-set to a retained generation. Keep the last 3 generations and the last 2 model versions. The retained watermark becomes the cursor, so later changes replay.
- The ranker polls the pointer at least every 30 s, verifies hashes and model, then switches. It reports `index_generation`, `model_version` and `activated_at` on `/health/ready` and in every response.
- Clients accept generation and model changes without resetting likes or viewed history. This replaces the snapshot rejection in [stories.js](../internal/web/static/stories.js).

### C5. Freshness SLA (R5)

- New-article latency = the `activated_at` of the first generation containing the article − `collected_at`.
- Revision latency = the `activated_at` of the first generation containing that `content_rev` − `updated_at`. The design target is ≤ 60 min; R5 does not cover revisions.
- `activated_at` is the ranker-reported switch time. Each run records it in `pipeline_runs` after confirming the ranker serves the new generation.
- The measured population is every article admitted to the index. Count rejections by reason. Apply no other exclusions; report `inserted_at − collected_at` separately for diagnosis.
- Budget: 30-min cadence + ≤ 10 min build and activation + ≤ 30 s reload.

### C6. Association rules (R7, R23)

- Items: `topic:<id>` (primary and secondary), `ent:<entity>` from spaCy `en_core_web_sm` (already a dependency; normalise case and aliases), and `kw:<term>` (top TF-IDF terms). Drop items above a maximum-support cutoff. Use FP-Growth via `mlxtend` and log the dependency in §8.
- (a) Topic suggestions use these sources in trust order:
  - Reader-day baskets (liked plus chosen topics), only after 100 reader-days.
  - Multi-topic article baskets.
  - Topic–entity–topic bridges scored `conf(A⇒X) × conf(X⇒B)`, kept only when both lifts are > 1.

  Each reader gets up to three unpicked topics, each showing the rule behind it.
- (b) Follow-ups:
  - For story group `S` first seen on day `t`, the basket holds `t0:` entities and keywords from `S`. It adds `t1:` items from other groups on days `t+1…t+7` that share an entity.
  - Keep only rules with `t0:` antecedents and `t1:` consequents.
  - Link `S → S2` when a kept rule matches and content similarity passes a threshold.
  - Store links in `story_links`; links point forward in time only.
- (c) Labels: the top 2–3 items by support × lift among a topic's primary articles. Regenerate them at retrain; the owner can override them in `topic_labels.override`.
- Acceptance:
  - (a) At least 70% of suggestions across 20 development profiles are judged sensible. Every suggestion shows its rule, and every source with enough data contributes.
  - (b) At least 70% of follow-ups across 30 sampled articles are judged genuine later developments, and all links point forward.
  - (c) At least 80% of a 30-label sample are judged sensible, and every topic has a label.
  - Ablation on development cases shows P@5 with `rule_boost` ≥ without it.

### C7. Ranking

`score(c) = w1·sim(c, liked) − w2·sim(c, disliked) + w3·rule_boost(c) + w4·pref(c) + w5·freshness(c)`

- Weights start at `w1 = 1`, `w2 = 0.2` (origin unknown, untuned) and `w3 = w4 = w5 = 0`. Tune all five on development cases only (M6), and log the values and reasons in §8.
- `rule_boost(c)` is the highest confidence × lift, or bridge score, of an active topic rule whose antecedent matches the reader and whose consequent matches `c`'s topics. `pref(c)` measures the match with chosen topics and sources. `freshness(c) = exp(−age/τ)` inside the fresh window, and 0 in the archive.
- Each request computes the profile from the reader's latest 50 liked and 50 disliked article IDs, with time-decay weights, plus chosen topics. Profile vectors are not stored (D9), so a model change needs no profile rebuild.
- The reader resolves settings into allowed `source_ids` (C8) and sends them. The ranker filters on `source_id`.
- Related reading searches the fresh and archive partitions, so older relevant material can surface (R23).
- [index.py](../ml-v2/src/newsrec/index.py) keeps its existing behaviour:
  - Exclusions: current, liked, disliked and viewed articles, plus their whole story groups.
  - Publisher cap, relaxed only to fill a page.
  - Request bounds: ≤ 30 results, ≤ 50 liked and 50 disliked IDs, ≤ 2,000 viewed IDs and 128 KiB.

### C8. Readers, settings, saved items and reader feeds

| Collection | Contents |
|---|---|
| `readers` | `reader_id`, `google_sub`, email, name, `invited`, `created_at`, `last_login_at`. The owner inserts invited emails; first sign-in binds `google_sub`. |
| `reader_sessions` | Hashed session ID, `reader_id`, created, last seen, `expires_at` (TTL index) |
| `reader_events` | `reader_id`, `article_id`, `action` (`like`/`dislike`), `index_generation`, `at`. The latest action per article wins; undo deletes it. |
| `reader_settings` | `reader_id`, topics (ID, label, `model_version`), source IDs, `mix` (`professional`, `local` or `both`; default `both`), `city`, `domains` |
| `saved_items` | `reader_id`, `kind` (`article`/`topic`), `ref` (article ID, or topic ID with label and `model_version`), `note` (plain text ≤ 2,000 chars), `created_at`, `updated_at`. Unique on `reader_id`, `kind`, `ref`. |
| `editions` | See C9 |

- **Pool rule (R20):** an article is in a reader's pool when any of these hold:
  - Its source is one of the reader's chosen sources.
  - `mix` includes professional, and `source.domains ∩ reader.domains ≠ ∅`.
  - `mix` includes local, and `source.city = reader.city`.

  Empty settings mean all sources.
- **Topic IDs change at retrain.** Map chosen and saved topics to the closest new topic and show the new label.
- **Reader feeds (R21):**
  - The reader submits an http(s) URL and a name. The reader process validates the input, caps feeds at 20 per reader, and rate-limits adds.
  - It then inserts a `sources` document with `added_by` and adds it to that reader's chosen sources. Required source fields (`type`, `language: en`, `country`) come from the reader's input, with owner defaults.
  - **Only the collector fetches the URL**, through the existing SSRF guard ([guard.go](../internal/httpclient/guard.go)), robots rules and politeness. The reader sees status from the existing `health_status` and `last_error`.
  - The owner can disable any feed. Bootstrap `SyncSources` must leave reader feeds alone; it reconciles and never prunes, and a test keeps it that way.
- **Settings screen:** topics by label; sources grouped by publisher and section; mix; city; domains; my feeds; saved items with notes; reset profile; download my data (JSON); delete my data.
- Browser storage becomes only a cache. The viewed list stays browser-local as a no-repeat aid, not a preference signal.

### C9. Daily edition (R19)

- The edition for reader `R` and date `D` contains English, `date_verified` articles from `R`'s pool, published within `D` in Asia/Kolkata (configurable). C7 ranks them. Each story group contributes one article, preferring the most complete text. Publisher and topic caps apply, with 10 stories by default.
- The edition for `D` becomes available at `D+1 06:00` local time (configurable). Until then, the reader sees the latest available edition.
- The edition is built on first open and stored in `editions`. It records `reader_id`, `date`, items (`article_id`, `story_group`, `rank` and `reason`), `index_generation`, `model_version` and `created_at`, with a unique key on `reader_id` + `date`. Later opens show the stored edition; an explicit rebuild replaces it.
- Page: stories are grouped by topic label, using current term labels until H5. Each story shows:
  - Headline, source and verified date.
  - Stored summary or labelled excerpt; never generated text.
  - "N sources covered this", counting distinct publishers in the story group.
  - Original link and like, dislike, save and note actions.
- If fewer than 10 stories are eligible, show what exists and explain why. If none are eligible, point to the fresh feed.
- V2 narrates this stored edition, so keep its order and reasons stable.

### C10. Authentication (R12)

- The Go reader uses Google OpenID Connect (authorization code with PKCE). Only `readers` with `invited = true` can sign in.
- Sessions use a secure, `HttpOnly`, `SameSite=Lax` cookie and server-side storage, with idle and absolute timeouts.
- Every state-changing request is CSRF-protected. Reject cross-site writes using `Sec-Fetch-Site`, then `Origin`.
- Every reader route is scoped to the signed-in `reader_id`; no route accepts a `reader_id` from the client.
- Reader routes accept only sessions. The existing API-key `handler.Authenticator` protects only `/api/v1/agent/*`.
- OAuth client ID and secret come from the environment. TLS terminates at Cloudflare, and origin services listen on localhost.

### C11. MCP server (R13)

- New Go `cmd/mcp` uses the official MCP Go SDK; log that dependency. Its read-only tools are `search_articles`, `get_article`, `get_related`, `get_recommendations` (stateless, with seed IDs or topics in the request), `list_topics`, `get_story_group` (with follow-ups) and `get_rules`.
- Agents authenticate to MCP with per-agent keys:
  - Keys are configured in the environment as `name:sha256(key)` pairs (D9) and checked in constant time.
  - Revoke a key by removing its entry and restarting.
  - Each key has its own rate limit and an access log of tool, time and result size, without article bodies.
  - Request and response limits match the reader API.
- MCP calls the reader with one service key on `/api/v1/agent/*`. Reader routes reject that key, and agent routes reject cookies. No agent route touches `readers` or `reader_*` data.
- There are no write tools; agents cannot trigger runs or retraining.

### C12. Recommendation model (R14)

- Use a two-tower TensorFlow/Keras model:
  - The article tower maps TF-IDF/SVD features, optionally with the autoencoder vector, to a normalised 64-d embedding.
  - The query tower uses time-decayed liked-article features plus chosen-topic embeddings.
  - Train with InfoNCE and in-batch negatives; dislikes are hard negatives.
- Serving excludes the query's whole story group, so positives must be distinct stories:
  - Follow-up links (C6).
  - Same topic plus a shared entity across different story groups.
  - Reader co-likes across different story groups.

  Same-story pairs are only down-weighted auxiliary examples. Never use them as in-batch negatives for their own group.
- Leave-one-out: remove a target like from that reader's query profile.
- Train up to `T_train` and validate on later articles. `T_train` falls before the acceptance fresh window starts.
- Exclude every M0-reserved acceptance seed's story group, and every related-reading candidate's story group, from training and validation.
- Compare TF-IDF, SVD, autoencoder and two-tower, each with and without boosts, using the same pool, exclusions and freshness filter.

### C13. Evaluation (R15)

- Every available invited reader grades, at minimum you and your brother. There are 50 cases, split evenly: 25 each for two graders or 10 each for five. A case is the grader's own profile (feed) or an opened article (related reading).
- Rubric: useful (2) means the grader would read it now; partly useful (1) is related but weak or redundant; not useful (0) is unrelated, duplicate or stale. Useful Precision@5 counts only grade 2; pooled nDCG@5 uses every grade. Pool and shuffle each method's top 5, hiding method names and scores.
- M0 seals the rubric, development cases, acceptance seeds and related-reading candidate story groups. Their hashes go on the M0 task line.
- Fresh-feed acceptance candidates are articles inside the fresh window at `t_eval`, all collected after `T_train`.
- M8 freezes the manifest (model, generation, rules, labels and weights) and `t_eval`. It then persists and hashes every method's top 5 for every case before grading. Graders see only those persisted lists.
- If R15 is met, the method that meets it becomes the default. If several meet it without a meaningful difference, choose the simpler method. If R15 is not met, the best method stays as a fallback and R15 is recorded as **not met**.
- Human and AI-assisted grades live in separate files. Development tuning may use AI-assisted grades only as supporting evidence.

### C14. Database permissions

R = read · W = insert/update · D = delete · — = none. Create one MongoDB user per principal. Add a row **before** a new collection is first used.

| Collection | collector | batch | ranker | reader | owner |
|---|---|---|---|---|---|
| `articles` | R W D | R | — | R | R |
| `sources` | R W D | — | — | R W (own `added_by` only) | R W D |
| `collection_runs` | R W | — | — | — | R |
| `feed_cache_metadata` | R W | — | — | — | R |
| `application_locks` | R W D | R W D | — | — | R W D |
| `read_events` | R W | — | — | — | R D |
| `index_generations` | — | R W | R | — | R W |
| `pipeline_runs` | — | R W | — | — | R |
| `association_rules` | — | R W D | R | — | R |
| `story_links` | — | R W D | R | — | R |
| `topic_labels` | — | R W | R | — | R W |
| `readers` | — | — | — | R W | R W D |
| `reader_sessions` | — | — | — | R W D | R D |
| `reader_events` | — | R | — | R W D | R D |
| `reader_settings` | — | R | — | R W D | R D |
| `saved_items` | — | — | — | R W D | R D |
| `editions` | — | — | — | R W D | R D |

- `collector` means `cmd/api` plus the collector, scrape, seed and migrate commands. It alone holds DDL (create collection; create and drop index), because bootstrap migrates on start. Declare every collection and index, including Python-owned ones, in [collections.go](../internal/mongodb/collections.go) and the index plan.
- `batch` covers incremental runs, reconciliation and retraining. `reader` is `cmd/reader`, including `/api/v1/agent/*`. `mcp` has no database user. `owner` uses `newsrec admin` subcommands for the allow-list, rollback, label overrides, data deletion and lease release.
- `read_events` is legacy `cmd/api` telemetry, not a recommendation signal (R6).

### C15. Operations

- Add `reader`, `ranker`, `batch` and `mcp` to [coolify.compose.yml](../deployments/coolify.compose.yml). Schedule incremental runs every 30 min, reconciliation nightly, and retraining weekly on Sunday 02:00–05:00 IST. Prefer Coolify scheduled tasks to a custom scheduler. Batch runs and retraining get CPU and memory limits and low priority.
- Give every service a health check and restart policy. Alerts (channel D3) fire on:
  - No new articles for 2 h.
  - Two consecutive failed runs.
  - New-article SLA p95 above 60 min.
  - Ranker not ready.
- Run a daily encrypted off-machine `mongodump` (target D2). Rehearse restore in M1 and M9.
- MongoDB currently publishes host port 27017 for LAN access. M9 records whether to bind it to localhost or firewall it.
- Measure peak memory after the first full build and every retrain. Consider a vector index only if ranker memory exceeds an agreed share of 12 GB, p95 approaches 500 ms under the agreed load, or retraining overruns its window.

## 4. Milestones

### M0 — Baseline and guardrails (26–27 Oct · Owner, A, B)

- [ ] Owner confirms the agent split (D1) and the simplifications (D9)
- [ ] Testers agree on the C13 rubric
- [ ] Development cases created, separate from acceptance cases
- [ ] Acceptance seeds and related-reading candidate story groups reserved; hashes recorded here
- [ ] MongoDB users created per C14, with credentials in Coolify secrets; a probe shows each user is denied outside its row
- [ ] Owner books grading time for 10–13 Nov

**Exit:** every item is done with evidence.

### M1 — Collector hardening and sources (26–30 Oct · A)

- [ ] C1 article fields written on insert and enrichment (H1)
- [ ] Golden fixtures show Go cleaning and English decisions equal Python on the same inputs, asserted in both suites
- [ ] C1 indexes added to `internal/mongodb`
- [ ] Backfill command for existing articles: new fields only, batched, low priority and resumable
- [ ] Verified-date share per publisher reported (input to D7)
- [ ] Source `domains` and `added_by` fields carried through the domain model, `sources.yaml`, seed and sync
- [ ] Existing technology sources and sections tagged. MIT, Medium, other software, data science and AI feeds, and local or independent publications added and verified (R17)
- [ ] Health checks and alerts (D3)
- [ ] Encrypted off-machine backup, with restore rehearsed (D2)

**Exit:** new and backfilled articles carry every C1 field. `collection_runs` shows no collection gap. Restore has been rehearsed. `make check`, `make test-race` and `make test-integration` pass.

### M2 — Revision-aware pipeline (28 Oct–3 Nov · A)

- [ ] Incremental run per C3 on a 30-min schedule
- [ ] Calibrated MinHash/LSH story grouping vendored into ml-v2 (C3)
- [ ] Multi-topic assignment and topic-count selection (C3)
- [ ] First full English index, fresh and archive, built after the M1 backfill (H2b); peak memory recorded
- [ ] Generation manifests, compare-and-set activation, `pipeline:publish` lease and rollback (C4)
- [ ] Ranker hot reload. `/health/ready` reports generation, model and `activated_at`. C2 freshness, `source_ids` and date-window filters (H2a)
- [ ] Reader client accepts generation changes without losing likes or history; `scripts/stories.test.mjs` updated
- [ ] Nightly reconciliation
- [ ] Tests cover:
  - [ ] Delayed insert
  - [ ] Enrichment after indexing
  - [ ] Backfill update
  - [ ] Failure before activation
  - [ ] Restart mid-run
  - [ ] Reconciliation restoring a removed row
  - [ ] Stale build rejected after another activation
  - [ ] Rollback, then replay
  - [ ] Open tab across an incremental activation and a model change
- [ ] C5 SLA report running

**Exit:** all tests pass. New-article latency has p95 ≤ 60 min and max ≤ 60 min over 48 consecutive hours. Revision latency is reported. No step is quadratic. Peak memory is recorded.

### M3 — Accounts, settings, saved items and reader feeds (29 Oct–6 Nov · B)

- [ ] Google sign-in, allow-list, sessions and CSRF (C10)
- [ ] `reader_events` (like, dislike, undo) and `reader_settings` (C8)
- [ ] Ranker requests built server-side from stored events and settings (C7); browser storage becomes a cache
- [ ] Fresh-first feed and archive view (after H2a)
- [ ] Saved stories and topics with notes (R18)
- [ ] Reader feeds: add, list with collector status, disable (R21)
- [ ] Settings screen with mix, city, domains, reset, download and delete (R20)
- [ ] Security tests for every new route: auth, scope, CSRF and size limits (H3)
- [ ] Testers start liking articles (owner)

**Exit:** only allow-listed accounts can sign in. Preferences, saved items and notes survive a browser reset, a device change and a generation change. The fresh feed shows only C2-fresh articles. A reader-added feed is collected and shown to that reader. Delete-my-data removes every `reader_*`, `saved_items` and `editions` row for that reader.

### M4 — Daily edition (5–8 Nov · B)

- [ ] Ranker edition request with date window, pool, caps and one article per story group
- [ ] Build on first open, store, and support explicit rebuild (C9)
- [ ] Edition page with actions and short or empty states
- [ ] Tests cover Asia/Kolkata day boundaries; English `date_verified` articles only; the pool rule; story-group dedupe; caps; availability time; and a stored edition remaining unchanged across generations
- [ ] Testers review 3 consecutive editions; useful share reported, with no pass mark until the owner sets one

**Exit:** each tester gets editions on consecutive days. Tests pass, and the review is reported.

### M5 — Association rules (1–7 Nov · A)

- [ ] Item extraction with the maximum-support cutoff (C6)
- [ ] (a) Article and bridge rules, with reader baskets gated at 100 reader-days; per-reader suggestions with their rule
- [ ] (b) Follow-up rules, `story_links` and a "Follow-ups" endpoint, with B adding the reader section (H5)
- [ ] (c) Labels with owner override (H5)
- [ ] `rule_boost` in ranking
- [ ] C6 acceptance checks recorded

**Exit:** each C6 check passes or is recorded as not met.

### M6 — Recommendation model and tuning (4–9 Nov · A)

- [ ] Training pairs, leave-one-out profiles and holdouts (C12)
- [ ] Two-tower model trained and served as a method
- [ ] Weekly retrain with catch-up promotion; one promotion done (C4)
- [ ] `w1`–`w5` tuned on development cases; values and reasons logged in §8
- [ ] Offline comparison of all methods, with and without boosts

**Exit:** the model is served, one promotion with catch-up is done, and the comparison is recorded.

### M7 — MCP server (6–9 Nov · B)

- [ ] `cmd/mcp` with the C11 tools
- [ ] Agent keys, rate limits, size limits and access log
- [ ] `/api/v1/agent/*` protected by the service key
- [ ] Service added to the compose file

**Exit:** every tool works with a valid key. Unknown and removed keys are rejected. Reader routes reject the service key, and agent routes reject cookies. No reader data is reachable.

### M8 — Freeze and human evaluation (freeze 10 Nov; grading 10–13 Nov · Owner, A)

- [ ] Manifest, weights and `t_eval` frozen; every method's top 5 for every case persisted and hashed (C13)
- [ ] Blind pooled sheets created; all 50 cases graded
- [ ] Scores calculated; R15 recorded as met or not met; default method set

**Exit:** all 50 cases are graded against the frozen lists. Human grades are stored separately from AI grades, and R15 status is recorded.

### M9 — Hardening and handover (13–15 Nov · B; A reviews)

- [ ] Concurrent load test with testers and agents (target D5)
- [ ] Security review covers C10, C11 and C14 enforcement, CSP, CSRF and the MongoDB port decision (C15)
- [ ] JavaScript line coverage raised; flaky rate-limit test fixed
- [ ] Final backup and restore rehearsal
- [ ] `recommender.md`, `recommender-results.md`, `recommender-client-review.md` and the root `README.md` updated with measured evidence

**Exit:** p95 under the agreed load meets the target. C14 is verified, docs are updated and restore is rehearsed.

## 5. Checks in every milestone

- Go: run `make check` and `make test-race`, plus `make test-integration` for repository or migration changes.
- Python: run `make rec-test`, plus `make ml2-test` when `newsmlv2` changes.
- JavaScript: run `node --test scripts/stories.test.mjs`.
- New collection or route: add its C14 row and security tests before first use.
- After each build or retrain, record peak memory, CPU and collector throughput, and confirm collection is unaffected.
- Verify the daily backup.

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V1 scope, now including R17–R21, does not fit 21 days for two agents | High | High | R17–R21 stay off the ML critical path. A milestone more than a day late goes to §7 the same day; no silent cuts. |
| Go and Python cleaning drift apart | Medium | High | Golden fixtures in both suites (M1) |
| Few articles have verified dates | Medium | High | Measure in M1; owner decides D7 early |
| Only two graders by 10 Nov | Medium | High | 25 cases each; book time in M0 |
| 12 GB memory pressure during a full build or retrain | Medium | High | Limits, quiet hours, measurements on every build |
| Too few likes for reader baskets and reader pairs | High | Medium | Content-based positives (C12); article and bridge rules carry R7(a); report the gap |
| Backfill of ~173k articles is slow | Medium | Medium | Low-priority batches; pipeline starts with new articles |
| 0.65 is not reached | Medium | Medium | Record R15 as not met; the best method stays default |
| Medium or MIT feeds block access or change | Medium | Low | Verify before enabling; feed text is enough; disable on failure |
| A reader-added feed is used for SSRF or abuse | Low | High | Only the collector fetches, through the existing guard; caps; owner disable |
| Laptop failure | Low | High | Off-machine backup and rehearsed restore from M1 |

## 7. Open decisions (owner)

| # | Decision | Needed by | Default until decided |
|---|---|---|---|
| D1 | Confirm the agent split in §1 | M0 | As proposed |
| D2 | Off-machine backup target | M1 | None; blocks the M1 backup task |
| D3 | Alert channel | M1 | None; blocks alerts |
| D4 | Retention period for `reader_events` | M3 | Keep until the reader deletes them |
| D5 | Load target (requests/s, p95) for M9 | M9 | 5 readers + 2 agents, p95 ≤ 500 ms |
| D6 | Content and image rights for invited readers | M9 | Summary or excerpt plus link; images hotlinked |
| D7 | Relax R3 if few dates are verified | M1 report | No |
| D8 | Should MCP expose a reader's own saved items and notes? | M7 | Not in V1 (V2-6) |
| D9 | Accept the simplifications marked "Proposed" in §8 | M0 | Accept |

## 8. Decision log

Newest first. Never lower a threshold or change a contract without a row here.

| Date | Decision | Reason |
|---|---|---|
| 2026-10-25 | Voice, audio briefing and iPhone app move to V2; Android follows V2 | Owner |
| 2026-10-25 | V1 adds R17–R21; the audience starts with you and your brother, then grows to ~5 readers | Owner |
| 2026-10-25 | Activation is a compare-and-set on the active pointer; the watermark lives in the manifest | A stale build could undo a retrain, and rollback could skip updates |
| 2026-10-25 | The SLA has no exclusions and is measured at ranker activation; revision latency is separate | R5 has no exceptions; revisions are not collections |
| 2026-10-25 | Acceptance seeds and related candidates are reserved in M0; fresh candidates come after `T_train`; rankings are persisted at freeze | Fresh candidates do not exist in M0; this prevents leakage and drift during grading |
| 2026-10-25 | The permission matrix covers existing collector collections; only the collector holds DDL | The collector needs them today, and bootstrap migrates on start |
| 2026-10-25 | The fresh window has a lower bound | Future-dated items would stay pinned to the top |
| 2026-10-25 | Detected language goes in `detected_language`; `language` keeps the source value | Original fields are never rewritten |
| 2026-10-25 | `updated_at` is set at write time, in the repository for inserts | Timestamps set before slow work can land behind the watermark |
| 2026-10-25 | Weekly retraining runs on the home-lab laptop under limits | This supersedes the old classifier rule "never train on the homelab", which assumed a 2 GB host; R8 |
| 2026-10-25 | **Proposed (D9):** no `reader_profiles`; profiles are computed per request from stored like/dislike IDs | Promotion needs no rebuild, and the ranker never reads reader data |
| 2026-10-25 | **Proposed (D9):** MCP agent keys are hashed environment entries, not an `api_keys` collection | There are only a few agents, and revocation is a restart |
| 2026-10-25 | **Proposed (D9):** the publish lease reuses `application_locks` | It reuses the existing lease protocol |
| 2026-10-25 | `collector/docs/plan.md` and `ml-v2/docs/plan.md` are history | This roadmap replaces them |

## 9. Work log

Append only. Add one line for each claim, handoff, block or finish.

| Date | Agent | Item | Note |
|---|---|---|---|
| 2026-10-25 | — | Roadmap created | Built from the client expectations, the v4 review draft and the review of that draft |

## 10. V2 backlog (not designed)

Requirements V2-1 to V2-6 are listed in §2. Known constraints:

- V2 builds on the stored V1 daily edition (C9) and saved items (C8). Do not fork the selection logic.
- English only. No paid service may be required; evaluate on-device iOS speech recognition and synthesis first.
- Listening times are examples, not fixed limits: about 5 min in the bath and 15–30 min while driving. How to estimate and meet the requested duration is still open.
- Spoken commands cover playback, saving stories and exploring topics. Their feedback becomes R6 signals.
