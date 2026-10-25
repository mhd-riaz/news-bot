# AFTERLINE roadmap — V1 web, V2 audio and iPhone

This is the single source of truth for agents: scope, contracts, milestones, status and decisions. Working rules and the delivered baseline are in [copilot-instructions.md](../../.github/copilot-instructions.md).

**Updated:** 25 Oct 2026 · **V1 due:** 15 Nov 2026 · **Baseline:** code `c06fdf4`, edition `stories-002`

Task markers: `[ ]` todo · `[~]` in progress (agent, date) · `[x]` done (evidence) · `[!]` blocked (reason)

## 1. Status board

| Milestone | Lead (others' tasks) | Window | Needs | Status |
|---|---|---|---|---|
| M0 Baseline, guardrails and deploy path | Owner, A, B | 26–27 Oct | — | todo |
| M1 Collector hardening and sources | A (B: M1.6–M1.8) | 26–30 Oct | M0 | todo |
| M2 Revision-aware pipeline | A (B: M2.6, M2.7) | 29 Oct–3 Nov | H1 | todo |
| M3 Accounts, settings, saved items, reader feeds | B (Owner: M3.9) | 29 Oct–4 Nov | M0, D10; H2a for the feed | todo |
| M4 Daily edition (text) | B (Owner: M4.5) | 4–9 Nov | H2a, H3 | todo |
| M5 Association rules | A (B: M5.6) | 2–7 Nov | H2b | todo |
| M6 Recommendation model and tuning | A | 5–8 Nov | H2b, H5 | todo |
| M7 MCP server | B (A: M7.2) | 6–8 Nov | H2a; H5 for rule tools | todo |
| M8 Freeze and human evaluation | Owner, A | 9–13 Nov | M3–M6 | todo |
| M9 Hardening and handover | B; A reviews | 10–15 Nov | M7, M8 | todo |

Milestones overlap only through these handoffs. A dependent task starts when its handoff is marked done here.

| Handoff | From → to | Delivers | Target | Status |
|---|---|---|---|---|
| H1 | M1 → M2 | New articles carry every C1 field | 28 Oct | todo |
| H2a | M2 → M3, M4, M7 | Ranker serves generations with C2 freshness, `source_ids` and verified date-window filters | 31 Oct | todo |
| H2b | M2 → M5, M6 | First full English index with story groups and multi-topic assignment | 1 Nov | todo |
| H3 | M3 → M4 | Sign-in, events, settings and saved-items APIs | 4 Nov | todo |
| H5 | M5 → M6, M7 | Follow-up links, topic labels and their ranker endpoints | 5 Nov | todo |

**Owners (pending D1).** Agent A handles data and ML: derived article fields, pipeline, ranker, rules, model and evaluation tooling. Agent B handles product and platform: deploy path, sources, operations, reader, auth, settings, edition, MCP and security. Every task in §4 names its agent. The agent that did not build a milestone reviews its exit. The owner takes the §7 decisions, sends invites, sets up the OAuth client, reviews editions and coordinates grading.

### 1.1 Schedule

Agents work every day; owner inputs are dated. IDs refer to §4 tasks.

| Day | Agent A | Agent B | Owner |
|---|---|---|---|
| Mon 26 Oct | M0.3, M0.4, M1.1 | M0.5 | M0.1, M0.2 |
| Tue 27 Oct | M1.2 | M0.6, M0.7, M1.6 | Run the M0.6 script |
| Wed 28 Oct | M1.3, M1.4 → **H1** | M1.7; deploy the collector with H1 | Invite list |
| Thu 29 Oct | M1.5 (start the production backfill); M2.1 | M3.1 | D10 |
| Fri 30 Oct | M1.9; M2.2, M2.3 | M1.8 | D7 from the M1.9 report |
| Sat 31 Oct | M2.4 → **H2a** | M2.6, M2.7; review M1 | — |
| Sun 1 Nov | M2.5 → **H2b**; SLA window opens | M3.2, M3.3 | M3.9: sign in and start liking |
| Mon 2 Nov | M2.8; M5.1 | M3.4, M3.5 | Like articles daily until the freeze |
| Tue 3 Nov | M2.9 → **M2 exit**; M5.2 | M3.6, M3.7; review M2 | — |
| Wed 4 Nov | M5.3, M5.4 | M3.8 → **H3**, **M3 exit**; M4.1 | — |
| Thu 5 Nov | M5.5 → **H5**; M6.1; review M3 | M4.2, M4.3, M4.4 | — |
| Fri 6 Nov | M6.2, M6.3 (first promotion overnight) | M5.6, M7.1 | M4.5 day 1; M5.7 judging |
| Sat 7 Nov | M5.7 → **M5 exit**; M6.4, M7.2 | M7.3 | M4.5 day 2 |
| Sun 8 Nov | M6.5 → **M6 exit** | M7.4 → **M7 exit**; review M6 | M4.5 day 3 |
| Mon 9 Nov | M8.1; review M4 and M7; buffer | M4.5 report → **M4 exit**; review M5; buffer | — |
| Tue 10 Nov | M8.2: freeze, sample, persist, send sheets | M9.1 | Grading starts |
| Wed 11 Nov | Grading support; frozen artifacts untouched | M9.2 | Grade |
| Thu 12 Nov | Grading support | M9.3 | Grade |
| Fri 13 Nov | M8.3 → **M8 exit** | M9.4; review M8 | Grading closes in the morning |
| Sat 14 Nov | M9.5 (results docs); review M9 | M9.5 (other docs), M9.6 | — |
| Sun 15 Nov | Release checklist review | Tag `v1.0.0` | V1 acceptance |

**Critical path.** Agent A's chain M1.1 → M1.2 → M1.3 → M1.5 → M2.3 → M2.5 (H2b) → M5 → H5 → M6 → M8.2 has about half a day of slack, on 9 Nov. Owner inputs on that path: D1, D9 and D11 on 26 Oct; D10 by 29 Oct; invites by 1 Nov; edition reviews 6–8 Nov; grading 10–13 Nov.

**Slip rule.** A critical-path task one day late goes to §7 the same day, with options such as turning secondary topics off or deferring reader baskets. The owner decides; nothing is cut silently. The 48 h SLA window is passive and can slide to any 48 h before 9 Nov.

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
| `detected_language`, `language_confidence` | Detected from the text by the classifier sidecar, using the `english_text` logic in `newsrec/data.py`. `language` keeps the source-declared value. Everything downstream filters on `detected_language = "en"`. |
| `published_at_source` | `feed`, `page` (JSON-LD `datePublished` or `article:published_time`, extending [jsonld.go](../internal/extract/jsonld.go)) or `collected_fallback` |
| `date_verified` | `true` only for `feed` or `page` |
| `clean_title`, `clean_summary`, `clean_body` | Cleaned copies returned by the sidecar: `clean_article` with per-publisher rules in `ml-v2/configs/boilerplate.yaml`, generated by `boilerplate.discover` and reviewed. Raw `title`, `summary` and `content` are never overwritten. |
| `image_url` | Existing field. Add the page `og:image` or `twitter:image` when the feed has none. Never download images. |
| `content_rev` | 1 on insert; `$inc` on every write that changes text, clean fields, detected language, publish date or image URL, including enrichment and backfill. A classification write bumps it only when a derived field changes. |
| `updated_at` | Written in the same update as each `content_rev` change: `$currentDate` on updates; on insert, set in the repository just before `InsertOne`, never in `NewArticle`. |
| `inserted_at` | Write time of the insert. `collected_at` is unchanged. |

- Indexes, declared in [indexes.go](../internal/mongodb/indexes.go): `{updated_at: 1, _id: 1}` and `{date_verified: 1, detected_language: 1, published_at: -1}`.
- The collector gets derived fields from the sidecar it already calls: inline at ingest, through the classification backlog on retry, and again after enrichment changes the text. Enrichment resets `classification_status` to pending, which also re-scores the topic on the full body. Articles without derived fields are not eligible for the index until the backlog fills them.
- Backfill for existing articles uses the same sidecar call and writes new fields only (never topics), in batches, at low priority, and is resumable. Old dates: `published_at == collected_at` means `collected_fallback`; otherwise `feed`.
- Sources gain optional `domains` (tags such as `ai`, `software`, `data-science`) and `added_by` (reader ID for reader feeds). `city` already exists.
- Tag existing technology sources and sections. Add MIT, Medium and other software, data science and AI feeds, plus local and independent publications. Enable each only after it collects English articles within robots rules.

### C2. Freshness

- Fresh means `detected_language = "en"`, `date_verified`, and `0 ≤ now − published_at ≤ 30 days`. The ranker applies this at request time; `now` is the request time, or the frozen `t_eval` in M8.
- Unverified dates are never fresh. Those articles stay in the archive and related reading, labelled "date unverified".
- Archive means every other indexed English article.

### C3. Pipeline checkpoint

- The active generation's manifest holds the watermark `(updated_at, _id)`. `pipeline_runs` is only a log.
- Eligible articles have `detected_language = "en"` and derived fields, and pass the existing admission rules.
- A run reads the active manifest (base generation `B`, `model_version`, watermark `W`), selects `updated_at ≥ W − 10 min`, and skips `(article_id, content_rev)` pairs already in `B`. It prepares text from `clean_*` fields with the existing input recipe, builds story groups, vectorises with pinned models, assigns topics and applies the current rules (follow-up links for new story groups). It writes generation `B+1`, then activates it (C4). Rules and labels are mined nightly and at retrain, not in every run.
- Story groups: vendor the calibrated MinHash/LSH from [neardup.py](../ml/src/newsml/neardup.py) (32 bands × 4 rows, threshold 0.44) into ml-v2, with a vectorised signature (M2.2). Compare only within 72 h and keep the `is_recurring_template` guard. The pipeline does not use the quadratic `story_groups` in [model.py](../ml-v2/src/newsrec/model.py).
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

- Items: `topic:<id>` (primary and secondary), `ent:<entity>` from spaCy `en_core_web_sm` (already a dependency; normalise case and aliases), and `kw:<term>` (top TF-IDF terms). Drop items above a maximum-support cutoff. Use FP-Growth via `mlxtend` and log the dependency in §8. Mine nightly and at retrain; every 30-min run only applies the current rules.
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
- Train up to `T_train`, the cut of the promoted retrain, and validate on later articles. Acceptance seeds and fresh candidates come only from story groups first seen after `T_train` (C13), so no acceptance pair can be a training pair.
- Compare TF-IDF, SVD, autoencoder and two-tower, each with and without boosts, using the same pool, exclusions and freshness filter.

### C13. Evaluation (R15)

- Every available invited reader grades, at minimum you and your brother. There are 50 cases, split evenly: 25 each for two graders or 10 each for five. A case is the grader's own profile (feed) or an opened article (related reading).
- Rubric: useful (2) means the grader would read it now; partly useful (1) is related but weak or redundant; not useful (0) is unrelated, duplicate or stale. Useful Precision@5 counts only grade 2; pooled nDCG@5 uses every grade. Pool and shuffle each method's top 5, hiding method names and scores.
- M0 seals the rubric, the development cases (the 40 `stories-002` cases) and the acceptance sampling procedure (strata, counts and RNG seed, committed in `evaluate.py`). Their hashes go on the M0 task lines.
- At freeze, related-reading seeds are sampled by that procedure from story groups first seen after `T_train`. Fresh-feed candidates are articles inside the fresh window at `t_eval` from story groups first seen after `T_train`.
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

- Images (D11): `news-collector` (Go; every `cmd/*` binary, each service choosing its command), the existing `news-collector-classifier` sidecar, and `news-recommender` (new `deployments/recommender.Dockerfile`: ml-v2 with the recommend and serve groups, for the ranker, batch jobs and `newsrec admin`). A GitHub Actions workflow in this repo builds them and pushes them to GHCR; Coolify pulls.
- Add `reader`, `ranker`, `batch` and `mcp` to [coolify.compose.yml](../deployments/coolify.compose.yml). Schedule incremental runs every 30 min, reconciliation and rule mining nightly, and retraining weekly on Sunday 02:00–05:00 IST. Prefer Coolify scheduled tasks to a custom scheduler. Batch runs and retraining get low priority.
- Give every service a health check and restart policy. Alerts (channel D3) fire on:
  - No new articles for 2 h.
  - Two consecutive failed runs.
  - New-article SLA p95 above 60 min.
  - Ranker not ready.
- Run a daily encrypted off-machine `mongodump` (target D2). Rehearse restore in M1 and M9.
- MongoDB currently publishes host port 27017 for LAN access. M9 records whether to bind it to localhost or firewall it.
- Measure peak memory after the first full build and every retrain. Consider a vector index only if ranker memory exceeds an agreed share of 12 GB, p95 approaches 500 ms under the agreed load, or retraining overruns its window.

Memory limits for the 12 GB laptop. These are targets: measure them, and record changes in §8.

| Service | Limit |
|---|---|
| MongoDB, with a 2 GB WiredTiger cache | 3 GB |
| Collector API | 0.5 GB |
| Classifier sidecar | 0.75 GB |
| Ranker | 1.5 GB |
| Reader and MCP | 0.25 GB |
| Incremental batch | 1.5 GB |
| Weekly retrain, fitting on samples | 3 GB |

That leaves about 1.5 GB for the OS, Docker, Coolify and Cloudflare Tunnel.

## 4. Milestones

### M0 — Baseline, guardrails and deploy path (26–27 Oct · Owner, A, B)

- [ ] **M0.1** (Owner) Confirm D1, D9 and D11; decide D2 and D3
- [ ] **M0.2** (Owner) Testers agree on the C13 rubric; grading booked for 10–13 Nov
- [ ] **M0.3** (A) Development cases: the 40 `stories-002` cases re-pointed at the full index
- [ ] **M0.4** (A) Acceptance sampling procedure committed in `evaluate.py`; hashes recorded here (C13)
- [ ] **M0.5** (B) Deploy path (C15, D11): port `news-collector.yml` from `mhd-riaz/data-scientist-roadmap`; move `deployments/Dockerfile` to `golang:1.27-alpine` and build every `cmd/*`; add `deployments/recommender.Dockerfile`
- [ ] **M0.6** (B) `deployments/mongo-users.js` creates the C14 users. The owner runs it once as root, with passwords from the environment. A probe shows each user is denied outside its row; credentials go in Coolify secrets.
- [ ] **M0.7** (B) MongoDB `--wiredTigerCacheSizeGB 2` and the C15 memory limits in the compose file

**Build notes.** `deployments/Dockerfile` uses `golang:1.26-alpine` while `go.mod` requires Go 1.27, and official Go images default to `GOTOOLCHAIN=local`, so expect the image build to fail until M0.5. The image also builds no reader binary today.

**Exit:** every item is done with evidence, and CI builds all three images.

### M1 — Collector hardening and sources (26–30 Oct · A; B for M1.6–M1.8)

- [ ] **M1.1** (A) Sidecar `/v1/classify` items accept an optional `source` and return `clean_title`, `clean_summary`, `clean_body`, `language` and `language_confidence` (C1). Add `langdetect` to `requirements-serve.txt`, and ship the reviewed boilerplate rules in the image.
- [ ] **M1.2** (A) Go: the classifier client parses the derived fields; `domain.Article` gains the C1 fields; the processor writes them at ingest with `published_at_source` and `date_verified`; the repository sets `inserted_at` and `updated_at` at write time
- [ ] **M1.3** (A) The classification backlog writes derived fields and bumps `content_rev` and `updated_at` when they change. Enrichment stores the page date and image, bumps on change, and resets classification to pending.
- [ ] **M1.4** (A) C1 indexes in `internal/mongodb`, with tests; with M1.2 and M1.3 this completes H1
- [ ] **M1.5** (A) `cmd/backfill` and `make backfill`: sidecar-derived fields for existing articles, new fields only, resumable; run in production at low priority
- [ ] **M1.6** (B) Source `domains` and `added_by` through `domain.Source`, `SourceInput`, `sources.yaml`, seed, sync and the sources API
- [ ] **M1.7** (B) Existing technology sources and sections tagged; MIT, Medium, other software, data science and AI feeds, and local or independent publications added and verified (R17)
- [ ] **M1.8** (B) Health checks; `newsrec alerts` as a scheduled task (D3); daily encrypted `mongodump` (D2); restore rehearsed into a scratch database
- [ ] **M1.9** (A) Verified-date share per publisher reported (input to D7)

**Build notes.**

- M1.1: `ml-v2/app/api.py` already cleans every item with `serve.prepare` → `clean_article`, then discards the result. Return it instead, passing `source` so per-publisher rules apply. Refactor `english_text` in `newsrec/data.py` to also return its confidence.
- M1.2: `internal/classifier/{classifier,http}.go`, `internal/domain/article.go` (`publicationTime` also returns its provenance), `internal/processor/processor.go` and `internal/repository/mongo/article.go`.
- M1.3: `internal/service/classification.go`, `internal/repository/mongo/article_classification.go`, `internal/extract/jsonld.go` plus meta tags (test with `fixtures/articles/*.html.gz`), `internal/service/enrichment.go` and `internal/repository/mongo/article_scrape.go`.
- M1.5: the filter `{content_rev: {$exists: false}}` makes it resumable, and batches of 50 match the sidecar batch size. It never writes topics.
- M1.7: verify each feed with `make collect-source SOURCE=<id>` against a local database before enabling it.

**Exit:** new and backfilled articles carry every C1 field. `collection_runs` shows no collection gap. Restore has been rehearsed. `make check`, `make test-race`, `make test-integration` and `make ml2-test` pass.

### M2 — Revision-aware pipeline (29 Oct–3 Nov · A; B for M2.6 and M2.7)

- [ ] **M2.1** (A) Generation layout and manifests, compare-and-set activation, `pipeline:publish` lease and rollback (C4)
- [ ] **M2.2** (A) Vectorised MinHash/LSH vendored into ml-v2; the 43 labelled pairs used by `make ml-pairs-import` still give recall ≥ 0.90 and precision ≥ 0.80 (C3)
- [ ] **M2.3** (A) Full build: chronological split; TF-IDF, SVD and autoencoder fits; story groups; multi-topic assignment and topic-count choice (C3); peak memory recorded
- [ ] **M2.4** (A) Ranker: hot reload; `/health/ready` reports generation, model and `activated_at`; C2 freshness, `source_ids` and verified date-window filters; responses drop `text` and carry generation and model (H2a)
- [ ] **M2.5** (A) First full production index after the M1.5 backfill (H2b); incremental runs and nightly reconciliation live
- [ ] **M2.6** (B) Reader: Go request and metadata fields; display text built from `clean_summary` or `clean_body` with the existing display recipe; `stories.js` drops the snapshot check and per-snapshot storage key; `scripts/stories.test.mjs` updated
- [ ] **M2.7** (B) `ranker` and `batch` deployed: `newsrec run` every 30 min and `newsrec reconcile` nightly, with C15 limits
- [ ] **M2.8** (A) Integration tests against the local `make mongo-up` database cover:
  - [ ] Delayed insert
  - [ ] Enrichment after indexing
  - [ ] Backfill update
  - [ ] Failure before activation
  - [ ] Restart mid-run
  - [ ] Reconciliation restoring a removed row
  - [ ] Stale build rejected after another activation
  - [ ] Rollback, then replay
  - [ ] Open tab across an incremental activation and a model change (with B)
- [ ] **M2.9** (A) `newsrec sla` report (C5); 48 consecutive hours measured

**Build notes.**

- New `ml-v2/src/newsrec/pipeline.py`, with `build`, `run`, `reconcile`, `rollback` and `sla` commands in `cli.py`. Reuse the fitting code in `model.py` and the input recipe in `data.py`.
- A generation directory holds `tfidf.npz`, `svd.npy`, `neural.npy`, `rows.parquet` (ID, source ID, publisher, dates, `date_verified`, `content_rev`, story group, topics and, from M5, entities), `minhash.npy` (72 h window) and `manifest.json`. Text stays in MongoDB.
- Simplification with a known ceiling: each generation is a full copy, about 0.6 GB at 170k articles. Switch to base + delta segments only if a run exceeds 5 min.
- MinHash: hash each shingle once with blake2b, then apply 128 `(a·x + b) mod p` permutations in numpy. The current pure-Python signature computes 128 blake2b hashes per shingle and is too slow for the full corpus. Both schemes estimate Jaccard, so the calibrated banding and threshold still apply; the labelled-pairs check confirms it.
- Fit TF-IDF and SVD on a sample of up to 60k articles, then transform the rest. Export the autoencoder encoder to numpy, so only retrain imports TensorFlow.

**Exit:** all tests pass. New-article latency has p95 ≤ 60 min and max ≤ 60 min over 48 consecutive hours. Revision latency is reported. No step is quadratic. Peak memory is recorded.

### M3 — Accounts, settings, saved items and reader feeds (29 Oct–4 Nov · B; owner for M3.9)

- [ ] **M3.1** (B) Google sign-in with PKCE, allow-list, sessions and CSRF (C10)
- [ ] **M3.2** (B) `reader_events` (like, dislike, undo) and `reader_settings`; ranker requests built server-side from them (C7, C8); browser storage becomes a cache
- [ ] **M3.3** (B) Reader deployed behind the D10 hostname with auth on
- [ ] **M3.4** (B) Fresh-first feed and archive view (after H2a)
- [ ] **M3.5** (B) Saved stories and topics with notes (R18)
- [ ] **M3.6** (B) Reader feeds: add, list with collector status, disable (R21)
- [ ] **M3.7** (B) Settings screen with mix, city, domains, reset, download and delete (R20)
- [ ] **M3.8** (B) Security tests for every new route: auth, scope, CSRF and size limits (H3)
- [ ] **M3.9** (Owner) Testers invited; they sign in and like articles daily from 1 Nov

**Build notes.**

- Add `golang.org/x/oauth2` (PKCE helpers) and `github.com/coreos/go-oidc/v3` (ID-token verification), and log both in §8. A new config section holds the OAuth client, cookie and timeouts; secrets come from the environment.
- Reuse `sameOrigin` from `internal/web/web.go` for state-changing routes; move it where both packages can use it.
- Add repositories in `internal/repository/mongo/` and collections in `internal/mongodb`. Indexes: unique reader email and `google_sub`, a TTL on session expiry, and unique keys for events, saved items and editions.
- Add routes to `readerRoutes` in `cmd/reader/main.go`: `/auth/login`, `/auth/callback`, `/auth/logout` and `/api/v1/me/…` for events, settings, saved items, feeds, export and delete.
- Pages: `settings.html` and `saved.html` templates with small vanilla JavaScript; no build step.
- Reader feeds go through the existing `SourceInput` validation with `added_by`; the collector does every fetch.

**Exit:** only allow-listed accounts can sign in. Preferences, saved items and notes survive a browser reset, a device change and a generation change. The fresh feed shows only C2-fresh articles. A reader-added feed is collected and shown to that reader. Delete-my-data removes every `reader_*`, `saved_items` and `editions` row for that reader.

### M4 — Daily edition (4–9 Nov · B; owner for M4.5)

- [ ] **M4.1** (B) Edition service: the pool becomes `source_ids`; ranker request with the verified date window, caps and one article per story group; editions stored per C9
- [ ] **M4.2** (B) Edition page with actions, short and empty states, and explicit rebuild
- [ ] **M4.3** (B) Tests cover Asia/Kolkata day boundaries; English `date_verified` articles only; the pool rule; story-group dedupe; caps; availability time; and a stored edition remaining unchanged across generations
- [ ] **M4.4** (B) Deployed by 6 Nov 06:00, so editions for 5–7 Nov can be reviewed
- [ ] **M4.5** (Owner) Testers review 3 consecutive editions; useful share reported, with no pass mark until the owner sets one

**Build notes.** `internal/service/edition.go`, `internal/repository/mongo/edition.go`, `internal/web/templates/edition.html` and a `/edition/{date}` route. Config keys cover the edition timezone, availability time and size.

**Exit:** each tester gets editions on consecutive days. Tests pass, and the review is reported.

### M5 — Association rules (2–7 Nov · A; B for M5.6)

- [ ] **M5.1** (A) Entities for every indexed article, from a one-off spaCy pass (`n_process=2`) and then each run, stored in `rows.parquet`; item extraction with the maximum-support cutoff (C6)
- [ ] **M5.2** (A) Nightly and retrain mining with `mlxtend` FP-Growth on a sparse basket matrix into `association_rules`; article and bridge rules, with reader baskets gated at 100 reader-days; per-reader suggestions with their rule (R7a)
- [ ] **M5.3** (A) Follow-up rules and `story_links`, applied to new story groups in every run (R7b)
- [ ] **M5.4** (A) Labels with owner override in `topic_labels` (R7c)
- [ ] **M5.5** (A) `rule_boost` in scoring; ranker endpoints for suggestions, follow-ups and rules (H5)
- [ ] **M5.6** (B) "Follow-ups" section and topic-suggestion row in the reader
- [ ] **M5.7** (Owner, A) C6 acceptance judged and recorded

**Build notes.** New `ml-v2/src/newsrec/rules.py`. `make ml2-setup` already installs spaCy `en_core_web_sm`; log `mlxtend` in §8. Mining runs nightly and at retrain only.

**Exit:** each C6 check passes or is recorded as not met.

### M6 — Recommendation model and tuning (5–8 Nov · A)

- [ ] **M6.1** (A) Training pairs, leave-one-out profiles and the temporal split (C12)
- [ ] **M6.2** (A) Two-tower model trained; towers exported to `.npz` and run in numpy inside the ranker, with no TensorFlow at serve time; served as method `twotower`
- [ ] **M6.3** (A) `newsrec retrain` with catch-up promotion (C4); one promotion done. The weekly schedule starts only after M8 (M9.4), so the evaluated model stays fixed.
- [ ] **M6.4** (A) `w1`–`w5` tuned on development cases with AI-assisted grades in separate files; values and reasons logged in §8
- [ ] **M6.5** (A) Offline comparison of all methods, with and without boosts

**Build notes.** New `ml-v2/src/newsrec/twotower.py`. Reuse the Keras setup in `model.train`: seeds, determinism and CPU thread limits.

**Exit:** the model is served, one promotion with catch-up is done, and the comparison is recorded.

### M7 — MCP server (6–8 Nov · B; A for M7.2)

- [ ] **M7.1** (B) `/api/v1/agent/*` in the reader behind `handler.Authenticator` with the service key; reader routes reject that key, and agent routes reject cookies
- [ ] **M7.2** (A) Ranker `/v1/search` scores a TF-IDF query vector against the active generation, for `search_articles`
- [ ] **M7.3** (B) `cmd/mcp` with the C11 tools, environment keys, per-key rate limit, size limits and access log
- [ ] **M7.4** (B) MCP deployed from the compose file; cross-rejection tests pass

**Build notes.** Add `github.com/modelcontextprotocol/go-sdk` with streamable HTTP, and log it in §8. Tools call only the reader; `cmd/mcp` has no database user.

**Exit:** every tool works with a valid key. Unknown and removed keys are rejected. Reader routes reject the service key, and agent routes reject cookies. No reader data is reachable.

### M8 — Freeze and human evaluation (9–13 Nov; freeze 10 Nov · Owner, A)

- [ ] **M8.1** (A) Freeze command in `evaluate.py`: pin the manifest, weights and `t_eval`; sample acceptance seeds by the sealed procedure; persist every method's top 5 per case. Reuse the existing blind-sheet export and `score()`.
- [ ] **M8.2** (A, Owner) Freeze on 10 Nov; hashes recorded here; blind pooled sheets sent; all 50 cases graded
- [ ] **M8.3** (A) Scores calculated; R15 recorded as met or not met; default method set

**Exit:** all 50 cases are graded against the frozen lists. Human grades are stored separately from AI grades, and R15 status is recorded.

### M9 — Hardening and handover (10–15 Nov · B; A reviews)

- [ ] **M9.1** (B) Flaky rate-limit test fixed; JavaScript line coverage raised
- [ ] **M9.2** (B) Security review covers C10, C11 and C14 enforcement, CSP, CSRF and the MongoDB port decision (C15)
- [ ] **M9.3** (B) Concurrent load test with testers and agents (target D5), using a small standard-library script
- [ ] **M9.4** (B) Final backup and restore rehearsal; weekly retrain schedule enabled
- [ ] **M9.5** (A, B) `recommender.md`, `recommender-results.md`, `recommender-client-review.md` and the root `README.md` updated with measured evidence
- [ ] **M9.6** (B) §4.1 release checklist run

**Exit:** p95 under the agreed load meets the target. C14 is verified, docs are updated and restore is rehearsed.

### 4.1 V1 release checklist

- [ ] Every V1 requirement in §2 is done or recorded as not met, with evidence
- [ ] Collector, sidecar, reader (auth on), ranker, batch and MCP run in production, with health checks green for 24 h
- [ ] The C5 report shows p95 ≤ 60 min and max ≤ 60 min over 48 consecutive hours
- [ ] R15 is recorded as met or not met from the frozen human evaluation
- [ ] Security review done; database users enforced; no secrets in the repository
- [ ] Backup and restore rehearsed within the last 48 h
- [ ] `make check`, `make test-race`, `make test-integration`, `make rec-test`, `make ml2-test` and the JavaScript tests pass on the release commit
- [ ] Docs updated, and the deployed commit tagged `v1.0.0`

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
| No deploy path for this repo, or the Go image build fails | High | High | M0.5 on day 1: port the workflow and bump the Go image |
| Owner inputs arrive late (D10, invites, reviews, grading) | Medium | High | Dates in §1.1; escalate the same day |
| Sidecar outage delays derived fields | Low | Medium | Articles wait in the classification backlog and enter the index later; the SLA counts the delay |
| Few articles have verified dates | Medium | High | Measure in M1; owner decides D7 early |
| Only two graders by 10 Nov | Medium | High | 25 cases each; book time in M0 |
| 12 GB memory pressure during a full build or retrain | Medium | High | C15 limits; fits on samples; only retrain imports TensorFlow; measured on every build |
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
| D10 | Public hostname for the reader (Cloudflare Tunnel) and the Google OAuth client | 29 Oct | None; blocks M3.3 |
| D11 | Port the old repo's GitHub Actions workflow and publish this repo's images to GHCR | 26 Oct | Yes |

## 8. Decision log

Newest first. Never lower a threshold or change a contract without a row here.

| Date | Decision | Reason |
|---|---|---|
| 2026-10-25 | V1 execution plan: numbered tasks with agents, the §1.1 schedule and the §4.1 release checklist; B takes deployment, sources and operations | Agent A's chain is the critical path |
| 2026-10-25 | **Proposed (D9):** clean text and detected language come from the existing classifier-sidecar call, not a Go port. Enrichment resets classification, so text is re-derived and the topic re-scored on the full body. | Same code as preparation, no parity fixtures, and the existing retry path |
| 2026-10-25 | Rules and labels are mined nightly and at retrain; runs only apply them | Mining the corpus does not fit a 30-min run |
| 2026-10-25 | Generations are full copies, MinHash is vectorised, fits use samples, and only retrain imports TensorFlow | Keeps runs within 10 min and memory within the C15 limits |
| 2026-10-25 | The Go reader builds display text from `clean_*` fields; generations store no text | Text stays in MongoDB, and generations stay small |
| 2026-10-25 | The weekly retrain schedule starts after M8 | The evaluated model must not change before grading |
| 2026-10-25 | Voice, audio briefing and iPhone app move to V2; Android follows V2 | Owner |
| 2026-10-25 | V1 adds R17–R21; the audience starts with you and your brother, then grows to ~5 readers | Owner |
| 2026-10-25 | Activation is a compare-and-set on the active pointer; the watermark lives in the manifest | A stale build could undo a retrain, and rollback could skip updates |
| 2026-10-25 | The SLA has no exclusions and is measured at ranker activation; revision latency is separate | R5 has no exceptions; revisions are not collections |
| 2026-10-25 | Acceptance seeds and fresh candidates are sampled at freeze from story groups first seen after `T_train`, by a procedure sealed in M0; rankings are persisted at freeze | Candidates cannot be reserved in M0, and the temporal split already prevents leakage; persisted rankings prevent drift during grading |
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
| 2026-10-25 | — | V1 execution plan added | §1.1 schedule, numbered tasks with build notes, §4.1 release checklist |

## 10. V2 backlog (not designed)

Requirements V2-1 to V2-6 are listed in §2. Known constraints:

- V2 builds on the stored V1 daily edition (C9) and saved items (C8). Do not fork the selection logic.
- English only. No paid service may be required; evaluate on-device iOS speech recognition and synthesis first.
- Listening times are examples, not fixed limits: about 5 min in the bath and 15–30 min while driving. How to estimate and meet the requested duration is still open.
- Spoken commands cover playback, saving stories and exploring topics. Their feedback becomes R6 signals.
