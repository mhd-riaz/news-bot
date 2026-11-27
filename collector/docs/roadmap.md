# AFTERLINE roadmap — V1 web, V2 audio and iPhone

This is the single source of truth for agents: scope, contracts, milestones, status and decisions. Working rules and the delivered baseline are in [copilot-instructions.md](../../.github/copilot-instructions.md).

**Updated:** 27 Nov 2026 · **Original V1 due date:** 15 Nov 2026 (release not accepted; no revised date approved) · **Baseline:** code `c06fdf4`, edition `stories-002`

Task markers: `[ ]` todo · `[~]` in progress (agent, date) · `[x]` done (evidence) · `[!]` blocked (reason) · `[>]` moved (the task named after the arrow carries the remaining work)

## 1. Status board

Statuses distinguish code/local evidence from deployment and release acceptance. They
are not a new check of running services; the original milestone windows below have passed.

| Milestone | Lead (others' tasks) | Window | Needs | Status |
| --- | --- | --- | --- | --- |
| M0 Baseline, guardrails and deploy path | Owner, A, B | 26–27 Oct | — | in progress |
| M1 Collector hardening and sources | A (B: M1.6–M1.8) | 26–30 Oct | M0 | in progress |
| M2 Revision-aware pipeline | A (B: M2.6, M2.7) | 29 Oct–3 Nov | H1 | todo |
| M3 Accounts, settings, saved items, reader feeds | B (Owner: M3.9) | 29 Oct–4 Nov | M0, D10; H2a for the feed | todo |
| M4 Daily edition (text) | B (Owner: M4.5) | 4–9 Nov | H2a, H3 | todo |
| M5 Association rules | A (B: M5.6) | 2–7 Nov | H2b | todo |
| M6 Recommendation model and tuning | A | 5–8 Nov | H2b, H5 | todo |
| M7 MCP server | B (A: M7.2) | 6–8 Nov | H2a; H5 for rule tools | todo |
| M8 Freeze and human evaluation | Owner, A | 9–13 Nov | M3–M6 | todo |
| M9 Hardening and handover | B; A reviews | 10–15 Nov | M7, M8 | todo |
| [DOC.1 Plain-English progress checklist](recommender-client-review.md#project-progress-checklist) | Copilot | 23 Nov | —; documentation only | task done; no release acceptance |
| DOC.2 Product documentation and comment refresh | Copilot | 25 Nov | —; documentation only | task done: 61 files refreshed and statically checked; historical evidence preserved; no release acceptance |
| ML4 Classifier V4 candidate labels (separate from V1/M8) | Copilot | on demand | owner approval | ML4.6 complete: local `v4-ai-072b01a9ceaf-hybrid_svc` from 8,594 truthful AI labels, including 2,582 extra AI-sampled articles; held-out AI-label macro-F1 0.8246. Earlier human-provenance claims are withdrawn. Human validation and 200 human labels/class remain not met. D19 (27 Nov): the owner approved this model for production; ML4.7 prepared the sidecar, image and relabel job, and deployment is not confirmed |
| [DEMO Bare-minimum client demo](#demo--bare-minimum-client-demo-separate-from-release-acceptance) (D18) | Copilot | 24–25 Nov | D18 | DEMO.1–DEMO.5 done locally with evidence; DEMO.6 morning refresh and rehearsal open. No V1 requirement or release gate is closed by the demo |
| [R Repository restructure](#r--repository-restructure-d21) (D21) | Copilot | from 27 Nov | D21 | R0 done: both backups verified, `main` merged into `v4`, checks and a manual CI run passed, `v4` pushed. R1–R9 todo. Eight open tasks moved into R tasks (`[>]`). No V1 requirement or release gate changes |

Milestones overlap only through these handoffs. A dependent task starts when its handoff is marked done here.

| Handoff | From → to | Delivers | Target | Status |
| --- | --- | --- | --- | --- |
| H1 | M1 → M2 | New articles carry every C1 field | 28 Oct | implemented/tested in M1.1–M1.4; production verification pending |
| H2a | M2 → M3, M4, M7 | Ranker serves generations with C2 freshness, `source_ids` and verified date-window filters | 31 Oct | todo |
| H2b | M2 → M5, M6 | First full English index with story groups and multi-topic assignment | 1 Nov | todo |
| H3 | M3 → M4 | Sign-in, events, settings and saved-items APIs | 4 Nov | todo |
| H5 | M5 → M6, M7 | Follow-up links, topic labels and their ranker endpoints | 5 Nov | todo |

**Owners (pending D1).** Agent A handles data and ML: derived article fields, pipeline, ranker, rules, model and evaluation tooling. Agent B handles product and platform: deploy path, sources, operations, reader, auth, settings, edition, MCP and security. Every task in §4 names its agent. The agent that did not build a milestone reviews its exit. The owner takes the §7 decisions, sends invites, sets up the OAuth client, reviews editions and coordinates grading.

### 1.1 Schedule

Agents work every day; owner inputs are dated. IDs refer to §4 tasks.

The dates below are the original delivery plan, not a current forecast. As of 25 Nov, V1 acceptance is still open; the local demo does not close it. No replacement deadline has been approved. Today's documentation work is tracked as DOC.2.

| Day | Agent A | Agent B | Owner |
| --- | --- | --- | --- |
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
| --- | --- | --- | --- | --- |
| R1 | You and your brother first, then up to ~5 invited readers; not public | V1 | C8, C10 → M3 | todo |
| R2 | Fresh news first, archive available | V1 | C2 → M2, M3 | local DEMO.3–DEMO.4 available; automatic index/hosted release todo |
| R3 | Fresh = verified publish date within 30 days; unverified dates are never fresh; only the owner can relax this (D7) | V1 | C1, C2 → M1, M2 | local demo enforces C2; production verification todo |
| R4 | English only, including production | V1 | C1 → M1 | todo |
| R5 | A new article is recommendable within 1 h of collection, end to end | V1 | C5 → M2 | todo |
| R6 | Explicit like/dislike plus chosen topics and sources; no implicit signals, no muting | V1 | C7, C8 → M3 | browser-local feedback available; account/topic/source settings todo |
| R7 | Association rules: (a) unpicked topic suggestions, (b) follow-up stories, (c) topic labels | V1 | C6 → M5 | todo |
| R8 | Runs 24×7 on the home-lab laptop (12 GB RAM, i5, Coolify, Cloudflare Tunnel) | V1 | C15 → M9 | collector running |
| R9 | Self-hosted MongoDB on the same machine | V1 | C14 | running |
| R10 | Language, real publish date and boilerplate fixed in the collector | V1 | C1 → M1 | M1.1–M1.4 implemented/tested; production backfill and quality verification pending |
| R11 | Never store image files; publisher URL only, text fallback | V1 | C1 | URL stored today |
| R12 | Google sign-in restricted to invited accounts | V1 | C10 → M3 | todo |
| R13 | Read-only MCP for AI agents, authenticated with API keys | V1 | C11 → M7 | todo |
| R14 | Neural model trained for recommendation, compared with existing methods | V1 | C12 → M6 | baseline autoencoder trained/compared; planned C12 model todo |
| R15 | Human Useful P@5 ≥ 0.65 and not below TF-IDF | V1 | C13 → M8 | todo |
| R16 | All V1 scope, including hardening, by 15 Nov 2026 | V1 | §1 | original deadline passed; release not accepted; no revised date approved |
| R17 | Software, data science and AI sources, including MIT, Medium, local and independent publications | V1 | C1 → M1 | done in code (M1.7); reaches production with the next deploy |
| R18 | Save stories and topics, with notes | V1 | C8 → M3 | browser-local stories/notes available in demo; saved topics/account storage todo |
| R19 | Daily edition of yesterday's relevant stories (text) | V1 | C9 → M4 | per-request Yesterday demo available; stored per-reader C9 editions todo |
| R20 | Settings: professional news, local news (city) or both; professional domains | V1 | C8 → M3 | professional-source switch available locally; full settings todo |
| R21 | Readers add their own RSS feeds | V1 | C8 → M3 | todo |
| R22 | Useful without any paid service; optional paid integrations allowed | all | Rules | ongoing |
| R23 | Connect current news with older relevant material | V1 | C6, C7 → M5 | related reading spans fresh/archive locally; C6 rule-based follow-ups todo |
| V2-1 | Ask how much listening time the user has | V2 | §10 | backlog |
| V2-2 | One coherent briefing script from the daily edition, sized to that time | V2 | §10 | backlog |
| V2-3 | Text-to-speech narration | V2 | §10 | backlog |
| V2-4 | Spoken commands: playback, save stories, explore topics | V2 | §10 | backlog |
| V2-5 | iPhone app: edition, audio, saved items and notes | V2 | §10 | backlog |
| V2-6 | MCP access to a reader's own saved items and notes (D8) | V2 | §10 | backlog |
| L-1 | Android app | later | — | backlog |

## 3. Contracts (V1)

These are target contracts, not an inventory of implemented endpoints, commands,
collections or scheduled jobs. Read §4 and the [operating guides](../readme.md) for what
exists today. Later owner decisions in §7–§8 take precedence, including D3's deferral
of alert delivery to V2. The local demo exceptions are recorded under DEMO, not treated
as fulfillment of these contracts.

### C1. Article and source data

New `articles` fields. Existing fields keep their meaning; backfill writes only these fields.

| Field | Rule |
| --- | --- |
| `detected_language`, `language_confidence` | Detected from the text by the classifier sidecar, using the `english_text` logic in `newsrec/data.py`. `language` keeps the source-declared value. Everything downstream filters on `detected_language = "en"`. |
| `published_at_source` | `feed`, `page` (JSON-LD `datePublished` or `article:published_time`, extending [jsonld.go](../internal/extract/jsonld.go)) or `collected_fallback` |
| `date_verified` | `true` only for `feed` or `page`. Page timestamps must include a timezone; date-only and timezone-less page values are ignored. |
| `clean_title`, `clean_summary`, `clean_body` | Cleaned copies returned by the sidecar: `clean_article` with per-publisher rules in `ml-v2/configs/boilerplate.yaml`, generated by `boilerplate.discover` and reviewed. Raw `title`, `summary` and `content` are never overwritten. |
| `image_url` | Existing field. Add the page `og:image` or `twitter:image` when the feed has none. Never download images. |
| `content_rev` | 1 on insert; `$inc` on every write that changes text, clean fields, detected language, publish date or image URL, including enrichment and backfill. A classification write bumps it only when a derived field changes. |
| `updated_at` | Written in the same update as each `content_rev` change: `$currentDate` on updates; on insert, set in the repository just before `InsertOne`, never in `NewArticle`. |
| `inserted_at` | Write time of the insert. Legacy records without it use `collected_at` as an explicit historical estimate, not measured ingestion latency. `collected_at` is unchanged. |

- Indexes, declared in [indexes.go](../internal/mongodb/indexes.go): `{updated_at: 1, _id: 1}` and `{date_verified: 1, detected_language: 1, published_at: -1}`.
- The collector gets derived fields from the sidecar it already calls: inline at ingest, through the classification backlog on retry, and again after enrichment changes the text. Material enrichment changes reset classification to pending with a fresh attempt budget, which also re-scores the topic on the full body. Valid page dates and missing images are retained even when a page's body is too short; the short body is not stored. Articles without derived fields are not eligible for the index until the backlog fills them.
- Backfill for existing articles selects missing C1 fields, fills absent values only (never topics), and rejects a snapshot if its revision changed. Each run advances by `_id`; skipped concurrent changes remain eligible for a later run. Batches stay bounded, low priority and resumable. Existing date provenance is preserved; otherwise `published_at == collected_at` means `collected_fallback`, and a different date means `feed`.
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
| --- | --- |
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

- Every available invited reader grades, at minimum you and your brother. There are 50 cases, assigned as evenly as possible across graders (25 each for two or 10 each for five). Each grader gets one feed case from their actual profile; the remaining cases are opened articles for related reading.
- Rubric: useful (2) means the grader would read it now; partly useful (1) is related but weak or redundant; not useful (0) is unrelated, duplicate or stale. Useful Precision@5 counts only grade 2; pooled nDCG@5 uses every grade. Pool and shuffle each method's top 5, hiding method names and scores.
- M0 seals the rubric and acceptance sampling procedure (case allocation, counts and RNG seed, committed in `evaluate.py`). Re-point the 40 `stories-002` development cases after M2.5 produces the full index and before M6 tuning; record their hash on M0.3.
- At freeze, related-reading seeds are sampled by that procedure from story groups first seen after `T_train`. Fresh-feed candidates are articles inside the fresh window at `t_eval` from story groups first seen after `T_train`.
- M8 freezes the manifest (model, generation, rules, labels and weights) and `t_eval`. It then persists and hashes every method's top 5 for every case before grading. Graders see only those persisted lists.
- If R15 is met, the method that meets it becomes the default. If several meet it without a meaningful difference, choose the simpler method. If R15 is not met, the best method stays as a fallback and R15 is recorded as **not met**.
- Human and AI-assisted grades live in separate files. Development tuning may use AI-assisted grades only as supporting evidence.

### C14. Database permissions

R = read · W = insert/update · D = delete · — = none. Create one MongoDB user per principal. Add a row **before** a new collection is first used.

| Collection | collector | batch | ranker | reader | owner |
| --- | --- | --- | --- | --- | --- |
| `articles` | R W D | R | — | R | R |
| `sources` | R W D | — | — | R W (own `added_by` enforced by the reader application) | R W D |
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

- MongoDB roles enforce collection-level access. `sources.added_by` ownership is enforced by reader application authorization; MongoDB does not provide row-level role policies.
- `collector` means `cmd/api` plus the collector, scrape, seed and migrate commands. It alone holds DDL (create collection; create and drop index), because bootstrap migrates on start. Declare every collection and index, including Python-owned ones, in [collections.go](../internal/mongodb/collections.go) and the index plan.
- `batch` covers incremental runs, reconciliation and retraining. `reader` is `cmd/reader`, including `/api/v1/agent/*`. `mcp` has no database user. `owner` uses `newsrec admin` subcommands for the allow-list, rollback, label overrides, data deletion and lease release.
- `read_events` is legacy `cmd/api` telemetry, not a recommendation signal (R6).

### C15. Operations

- Images (D11, D20): `news-bot` (Go; every `cmd/*` binary, each service choosing its command; `news-collector` until 22 Nov), the existing `news-collector-classifier` sidecar, and `news-recommender` (new `deployments/recommender.Dockerfile`: ml-v2 with the recommend and serve groups, for the ranker, batch jobs and `newsrec admin`). This repository's GitHub Actions workflow builds them and publishes per-commit `sha-` tags to GHCR from `main`; its `release` job moves all three `latest` tags to one commit and triggers Coolify, which pulls.
- Add `reader`, `ranker`, `batch` and `mcp` to [coolify.compose.yml](../deployments/coolify.compose.yml). Schedule incremental runs every 30 min, reconciliation and rule mining nightly, and retraining weekly on Sunday 02:00–05:00 IST. Prefer Coolify scheduled tasks to a custom scheduler. Batch runs and retraining get low priority.
- Give every service a health check and restart policy. Alerts (channel D3) fire on:
  - No new articles for 2 h.
  - Two consecutive failed runs.
  - New-article SLA p95 above 60 min.
  - Ranker not ready.
- Run a daily encrypted off-machine `mongodump` (target D2). Rehearse restore in M1 and M9.
- MongoDB publishes host port 27017 on the loopback interface only (§8, 18 Nov); Compass and mongosh connect through an SSH or Cloudflare Access tunnel.
- Measure peak memory after the first full build and every retrain. Consider a vector index only if ranker memory exceeds an agreed share of 12 GB, p95 approaches 500 ms under the agreed load, or retraining overruns its window.

Memory limits for the 12 GB laptop. These are targets: measure them, and record changes in §8.

| Service | Limit |
| --- | --- |
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

- [x] **M0.1** (Owner) Confirm D1, D9 and D11; decide D2 and D3
- [~] **M0.2** (Owner, 25 Oct) C13 rubric and 10–13 Nov grading window approved; tester agreement and booking remain to be confirmed.
- [ ] **M0.3** (A, deferred to M2.5) Re-point the 40 `stories-002` development cases at the full index and record their hash before M6 tuning.
- [x] **M0.4** (A, 25 Oct) `evaluate.sample_acceptance` freezes one actual-profile feed case per grader and fills the 50-case balance with related-reading cases, sampled by distinct post-training story group using seed `20260823`. Procedure SHA-256: `aeecc565d67d1c634d421dbede20d973129063ef6d8d428db7fbb8eb7d90ff9d`; the frozen sample hash is recorded when M8 has the full index and profiles.
- [>] **M0.5** → **R6** (B, 25 Oct) Main-branch GitHub Actions tests and publishes the Go, classifier and recommender images to GHCR, then triggers Coolify; package every `cmd/*` in the Go image. Implementation and local image builds are complete. Pull requests to `main` run the checks and image builds, and `ci-passed` is the check to require. The first `main` publish was refused because the `news-collector` GHCR package belongs to `data-scientist-roadmap`. On 22 Nov the owner made this repository standalone (D20): the Go image is `news-bot`, `main` publishes `sha-` tags, and the `release` job (armed by `DEPLOY_ENABLED`, `production` environment) moves all three `latest` tags and deploys; a `main` ruleset requires `ci-passed` (§8, 22 Nov). Release and Coolify deploy evidence remain to be verified.
- [x] **M0.6** (B, 25 Oct) `deployments/mongo-users.js` creates the C14 collection-scoped users. The owner runs it as root with distinct 64-hex passwords from the environment. The script and access boundaries passed disposable-Mongo probes; the owner confirmed production provisioning on 26 Oct.
- [x] **M0.7** MongoDB `--wiredTigerCacheSizeGB 2` and the C15 memory limits for the currently deployed services are configured in the compose file and validated.

**Build notes.** `deployments/Dockerfile` uses Go 1.27 and builds every `cmd/*` binary. Go, classifier and recommender images built locally; the compose file parsed with required dummy values. MongoDB provisioning created all five users on a disposable server; each passed an allowed-operation probe and was denied an ungranted collection/operation. Collector collection and index DDL probes also passed.

**Exit:** every item is done with evidence, and CI builds all three images. Remote
CI/GHCR/Coolify publishing/deployment evidence is still pending. Production database
provisioning was owner-confirmed on 26 Oct (M0.6); it is not an outstanding provisioning task.

### M1 — Collector hardening and sources (26–30 Oct · A; B for M1.6–M1.8)

- [x] **M1.1** (A) Sidecar `/v1/classify` items accept an optional `source` and return `clean_title`, `clean_summary`, `clean_body`, `language` and `language_confidence` (C1). `langdetect==1.0.9` is pinned in `requirements-serve.txt`; the reviewed boilerplate rules ship in the image. Full ML/classifier tests pass and the classifier image builds locally.
- [x] **M1.2** (A) Go: the classifier client parses the derived fields; `domain.Article` gains the C1 fields; the processor writes them at ingest with `published_at_source` and `date_verified`; the repository sets `inserted_at` and `updated_at` at write time. `make check` and the Mongo article create/read-back integration test pass.
- [x] **M1.3** (A) The classification backlog writes derived fields and bumps `content_rev` and `updated_at` only when they change. Enrichment extracts page dates/images, preserves feed images, increments the revision on content metadata changes, and resets classification to pending. Go unit/race tests and the Mongo repository integration suite pass.
- [x] **M1.4** (A) C1 indexes in `internal/mongodb`, with tests; with M1.2 and M1.3 this completes H1. `make check` and the Mongo migration integration tests pass.
- [>] **M1.5** → **R6** (A) `cmd/backfill` and `make backfill`: sidecar-derived fields for existing articles, new fields only, resumable; the bounded, low-priority implementation is verified, but the production run remains pending.
- [x] **M1.6** Source `domains` and `added_by` through `domain.Source`, `SourceInput`, `sources.yaml`, seed, sync and the sources API. `added_by` is response-only for API clients until authenticated reader identity exists; trusted seed/internal callers may set it.
- [x] **M1.7** (B, 26 Oct) Existing technology sources and sections tagged; MIT, Medium, other software, data science and AI feeds, and local or independent publications added and verified (R17). 14 existing tech sources and sections carry `technology`; 25 sources were added: 20 professional (including two MIT News topics and three Medium tags) and 5 local or independent. All 25 collected into a scratch database (1,669 items, 97.6% detected English); `make check` and `make test-race` pass.
- [ ] **M1.8** (B) Health checks; `newsrec alerts` as a scheduled task (D3); daily encrypted `mongodump` (D2); restore rehearsed into a scratch database
- [ ] **M1.9** (A) Verified-date share per publisher reported (input to D7)

**Build notes.**

- M1.1: verified with `uv run pytest -q` in `ml-v2` and a successful local classifier image build.
- M1.2: `internal/classifier/{classifier,http}.go`, `internal/domain/article.go` (`publicationTime` also returns its provenance), `internal/processor/processor.go` and `internal/repository/mongo/article.go`.
- M1.3: `internal/service/classification.go`, `internal/repository/mongo/article_classification.go`, `internal/extract/jsonld.go` plus meta tags (test with `fixtures/articles/*.html.gz`), `internal/service/enrichment.go` and `internal/repository/mongo/article_scrape.go`.
- M1.3: validated with `make check`, `make test-race`, and `go test -tags=integration -count=1 ./internal/repository/mongo`.
- M1.4: `make check` and `go test -tags=integration -count=1 ./internal/mongodb` pass; the migration test verifies both C1 indexes.
- M1.5: `make check`, `make build`, and the Mongo backfill integration test pass. Production execution is intentionally pending until the production target is provisioned and explicitly selected.
- M1.5: the selector covers any missing or null required C1 field, not just an absent `content_rev`, so incomplete legacy records remain eligible. Batches of 50 match the sidecar batch size; revision checks protect concurrent changes. It never writes topics.
- M1.6: source domains are normalized/validated and round-trip through seed sync, API and Mongo persistence. `added_by` is UUID-validated, exposed in responses, and cannot be supplied by API clients. Focused source tests, Mongo integration tests, `make check` and `make test-race` pass.
- M1.7: verify each feed with `make collect-source SOURCE=<id>` against a local database before enabling it. Keep `.env` on a local database and select production only explicitly (`NEWS_ENV_FILE=.env.prod`, see the readme). For a throwaway check, set `NEWS_MONGO_DATABASE` to a scratch database. The collector command also needs any `NEWS_AUTH_API_KEYS` value, although it serves no HTTP.
- M1.7: a feed is added only if it answers with English items and no robots.txt group or licence that applies to every agent reserves AI-training or text and data mining rights (§8). Left-out feeds are recorded at the bottom of `configs/sources.yaml`.

**Exit:** new and backfilled articles carry every C1 field. `collection_runs` shows no collection gap. Restore has been rehearsed. `make check`, `make test-race`, `make test-integration` and `make ml2-test` pass.

### M2 — Revision-aware pipeline (29 Oct–3 Nov · A; B for M2.6 and M2.7)

- [ ] **M2.1** (A) Generation layout and manifests, compare-and-set activation, `pipeline:publish` lease and rollback (C4)
- [ ] **M2.2** (A) Vectorised MinHash/LSH vendored into ml-v2; the 43 labelled pairs used by `make ml-pairs-import` still give recall ≥ 0.90 and precision ≥ 0.80 (C3)
- [ ] **M2.3** (A) Full build: chronological split; TF-IDF, SVD and autoencoder fits; story groups; multi-topic assignment and topic-count choice (C3); peak memory recorded
- [ ] **M2.4** (A) Ranker: hot reload; `/health/ready` reports generation, model and `activated_at`; C2 freshness, `source_ids` and verified date-window filters; responses drop `text` and carry generation and model (H2a)
- [ ] **M2.5** (A) First full production index after the M1.5 backfill (H2b); incremental runs and nightly reconciliation live. Then complete deferred M0.3 before M6 tuning.
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

- [>] **M9.1** → **R5** (B) Flaky rate-limit test fixed; JavaScript line coverage raised. The flaky-test half was pulled forward and done on 26 Oct (§9); JavaScript coverage remains.
- [ ] **M9.2** (B) Security review covers C10, C11 and C14 enforcement, CSP, CSRF and the MongoDB port decision (C15)
- [ ] **M9.3** (B) Concurrent load test with testers and agents (target D5), using a small standard-library script
- [ ] **M9.4** (B) Final backup and restore rehearsal; weekly retrain schedule enabled
- [ ] **M9.5** (A, B) `recommender.md`, `recommender-results.md`, `recommender-client-review.md` and the root `README.md` updated with measured evidence
- [ ] **M9.6** (B) §4.1 release checklist run

**Exit:** p95 under the agreed load meets the target. C14 is verified, docs are updated and restore is rehearsed.

### ML4 — Classifier V4 candidate labels (separate from V1/M8)

**Provenance correction (D16, 22 Nov):** the owner confirms that all old and new label datasets are AI-generated, including round 1 previously described as human gold. Earlier human-provenance statements below and in historical work-log entries are superseded, not evidence of human review. Existing scores measure agreement with AI labels, not human-validated accuracy; existing artifacts remain intact with their provenance correction recorded separately. No AI judgement is gold, and no candidate is promoted to production by this decision.

- [x] **ML4.6** (Copilot, 22 Nov) Audited and combined usable old and new AI-generated labels into a separate, accurately attributed local V4 training corpus and candidate (D16), reusing admission, taxonomy, cleaning, dedup and the ML4.3 ladder. Original datasets and model artifacts are unchanged. [Pooled manifest](../ml-v4/data/v4-ai-pooled-20261122T000000Z/manifest.json): 8,594 AI-labelled articles, including 3,281 from the full round-2 effort and 2,582 beyond its original sheet selection; 0 historical evaluation ID/alias overlap, 456 old test IDs recovered against the recorded hash, all 13 AI-labelled classes above 200. `make ml4-train DATASET=v4-ai-pooled-20261122T000000Z` completed all eight rungs and wrote [model card](../ml-v4/data/models/v4-ai-072b01a9ceaf/model-card.md), bundle, manifest, split IDs and training log in 863.36 s with 5.23 GB peak RSS. Selected `hybrid_svc`; 6,875 development articles include 2,627 AI-sampled round-2 articles; 1,719 held-out articles, opened once. AI-label macro-F1 0.8246 [0.8056, 0.8442], accuracy 0.829. Sigmoid calibration wins log loss (0.5742 versus 0.6041); provisional cut 0.2059 reaches 0.8143 out-of-fold AI-label agreement with 100% coverage. Fresh-process offline reload and three fictional inference probes passed; source/partition/hash checks passed. `make ml4-test`: 75 sampler/verifier and 26 trainer/pool tests passed; shared admission tests passed in the 45-case targeted run. **Not met:** human validation and 200 human labels/class. No production promotion or ML4 milestone closure.

- [>] **ML4.7** → **R6** (Copilot, 27 Nov) Promote `v4-ai-072b01a9ceaf-hybrid_svc` to production on the owner's approval (D19). Done in the repository: the sidecar serves a V4 bundle through `newsmlv4.serving.SidecarModel`, which rebuilds the training input (whitespace-collapsed title plus the 400-character lede from the summary or body) and keeps the `/v1/classify` contract, warming the encoder at start-up. `ml-v2/app/api.py` still serves a v2 bundle, so rollback is a path and hash change. The image carries CPU torch, sentence-transformers and the pinned MiniLM revision, offline at run time (§8). Compose allows 1.5 GB, a 120 s gunicorn timeout and a 120 s health grace, and `.dockerignore` keeps `ml-v4/data/` out of the build context. `make backfill-reclassify` relabels articles carrying another model's topic: `ReclassificationService`, two repository methods and a `-reclassify` flag on `cmd/backfill`. It writes only topic, confidence, model version, status and classified time; a topic-only write leaves `updated_at` and `content_rev` alone, as `UpdateClassification` does. `classifier.ItemError` lets a batch with sidecar-declined articles be resubmitted without them. Evidence: `make check` and `make test-race` pass; `make classifier-test` 7 passed; `make ml4-test` second stage 31 passed (26 trainer/pool, 5 serving); 3 new Mongo integration tests passed against a disposable local MongoDB. The real bundle ran through the Dockerfile's gunicorn command in a simulated image layout (clean Python 3.13 from the pinned requirements, an empty encoder cache filled by the build-step command, `HF_HUB_OFFLINE=1`): `/v1/meta` reported `v4-ai-072b01a9ceaf-hybrid_svc` with 14 topics, a wrong API key got 401 and two probe articles were classified. Start-up with warm-up 6.6 s, a 50-article long-body batch 0.83 s, 893 MB peak. **Not done:** the Docker image was not built (no daemon running), so Linux size, memory and latency under one CPU thread against the 10 s classifier timeout are unmeasured. The model file is not on the production volume, `DEPLOY_ENABLED` is not changed and the relabel has not run; those are the owner's steps ([ml-v4 README](../ml-v4/README.md#deploy-the-v4-classifier-d19)). Human validation and 200 human labels/class remain **not met**; every score is AI-label agreement. Closure awaits the deployment, one relabel run and the other agent's review.
- [>] **ML4.1** → **R2** (Copilot, 10 Nov) Read-only, fixed-cut local export in `ml-v4/` reuses V1/V2 CSV writing, admission, dedup and taxonomy hints. `make ml4-labels-export` produced 2,287 distinct candidates in four private CSVs (2,347 sheet rows including 60 intentional overlaps); 0 old-gold ID overlap and 0 repeated content hashes or near-duplicate groups among selected rows. None of the 8,151 old-gold IDs exists in this local DB, so cross-corpus near-duplicate comparison could not be verified. The 200/class target is **not met** for conflict/war (141, short 59), crime/justice (92, short 108), disaster/accident (83, short 117) and education (171, short 29). `make ml4-labels-verify RUN=v4-20261110T120557Z`: 2,287 checked, 0 missing/changed in the DB or CSVs, 0 label conflicts. The combined classifier and V4 tests: 189 passed, 0 failed/skipped. At export on 10 Nov, no human labels had yet been created; this changed with the human labelling recorded under ML4.2 on 21 Nov. Task closure awaits a PR and automated review.
- [x] **ML4.2** (Owner) The 2,287 candidates in `v4-20261110T120557Z` were human-labelled by reviewers from 12 groups on 21 Nov and imported the same day on the export-time database check (D14). The local database had been replaced by a production copy (243,702 articles) that holds none of the exported IDs: `make ml4-labels-verify` reported 0 checked and 2,287 missing. `make ml4-labels-import-exported RUN=v4-20261110T120557Z` found the sheets identical to the export fingerprints and wrote gold: 2,347 labels over 2,287 articles, with no conflicts. Today's database still holds 1,628 of them with identical text; 659 could not be re-checked (348 technology, 84 politics). Training rights were approved on 21 Nov (D12). The 200/class target is still unmet for 10 of 13 classes (809 labels short); ML4.5 carries it. Measured on this run, the provisional strata were weak for those classes: reviewers kept 10 of 83 provisional disaster/accident candidates (12%), 48 of 200 society/lifestyle (24%) and 38 of 141 conflict/war (27%). Do not reduce the target or treat provisional topics or AI-agent judgements as gold. The original blank sheets are retained as a backup, not as the active labels.
- [>] **ML4.3** → **R2** (Copilot, 21 Nov) Stratified V4 trainer `newsmlv4.train` (`make ml4-train`). It compares eight rungs on identical repeated stratified folds: majority, Complement NB, TF-IDF logistic regression, TF-IDF LinearSVC, word+char LinearSVC, MiniLM + logistic regression, word+char+MiniLM LinearSVC, and a small Keras MLP. The simplest rung that a corrected resampled t-test cannot separate from the best one wins. The winner is calibrated over five cross-fitted folds (sigmoid or isotonic, whichever has the lower out-of-fold log loss), gets one global confidence cut at the existing 0.80 precision target, and is scored once on a sealed stratified 20% test split. The trainer refuses to run while a class is below the 200/class target unless the shortfall is explicitly accepted, and it never overwrites an earlier model for the same gold. Tree models are left out on ml-v2 Phase E evidence. It was built and tested on synthetic data before any V4 label was imported. Evidence: `make ml4-test` passed 67 sampler/verifier tests in `ml/` and 10 trainer tests in ml-v2. On the real run, `make ml4-train RUNS=v4-20261110T120557Z` passed the export, fingerprint and sheet checks, then refused at the missing `gold.jsonl` and wrote nothing. A full default run on synthetic text at the real class counts (457 down to 25; no labelled article read) completed all eight rungs in 150 s; its scores say nothing about model quality. A code review found two bugs, both fixed with regression tests: pickling the Keras rung stripped the network from the in-memory model, and a class with zero labels slipped past the per-class floor. Testing also showed that scikit-learn's frozen-model calibration refuses any class with fewer than five calibration rows, so V4 calibrates on one explicit all-rows split. On 22 Nov the trainer was changed to create the model directory before it opens the test split, so a run stopped part-way cannot open it a second time (regression test; `make ml4-test`: 75 passed in `ml/`, 14 in ml-v2). Closure awaits a PR and the other agent's review.
- [>] **ML4.4** → **R3** (Copilot, 21 Nov) Interim V4 classifier: `make ml4-train` on the round-1 human gold plus the round-2 AI-agent weak labels (ML4.5), with the human 200/class shortfall accepted for this run only (D15) and recorded as not met. Retrain when the round-2 human labels are imported. Exit: the manifest and model card record the ladder with intervals, the chosen rung, the calibration, coverage at the cut and the single test opening, and every class that misses a target is reported as not met. Evidence (22 Nov): `make ml4-train RUNS=v4-20261110T120557Z WEAK_RUNS=v4-20261121T000000Z ACCEPT_SHORTFALL=1` wrote `ml-v4/data/models/v4-62490efb025d` (`v4-62490efb025d-hybrid_svc`) in 518 s with a 4.3 GB peak resident set. It used 2,278 human-labelled articles (1,822 development, 456 sealed test; 9 `unsorted` set aside) and offered 701 weak labels. `hybrid_svc+weak` had the best mean (0.762 ± 0.025), but the corrected t-test could not separate it from human-only `hybrid_svc` (0.748 ± 0.030; difference 0.014, p = 0.17), so the shipped model does not use the weak labels. Sigmoid calibration won on log loss (0.692 against 0.868 for isotonic). The cut 0.2745 reaches 0.800 out-of-fold precision and files 98.6% of articles; the dial files 86.8% at 0.85 and 72.1% at 0.90. Sealed test, opened once: macro-F1 0.7705 [0.7075, 0.8183], accuracy 0.814, 98.7% filed at 0.820 accuracy. Per-class test F1 runs from sport 0.96 down to society_lifestyle 0.54; conflict_war (10 test articles) and disaster_accident (5) have intervals too wide to judge. The model declined none of the 9 articles humans labelled `unsorted`. **Not met:** 200/class for 10 of 13 classes (accepted for this run only, D15). Not measured: a comparison with the production classifier on the same articles, and drift. The manifest's `git_sha` names base commit `75f2bdb`; the trainer itself was uncommitted. The task stays open for the retrain on the round-2 human labels.
- [>] **ML4.5** → **R3** (Copilot, 21 Nov; reviewers label) Round 2 for the ten classes below 200, sized to the human gap (809 labels). Six AI agents select and judge candidates through the VS Code MongoDB MCP server, which is connected read-only to the local `news` database. They work from the taxonomy class descriptions, stratified by description facet and collection day over [10 Nov 12:05:58, 21 Nov 00:00) UTC. `make ml4-labels-export PROPOSALS=… START=… CUT=… REVIEWED_GOLDS=…` re-applies every eligibility and exclusion rule. It writes blind sheets for reviewers and `weak-labels.jsonl`, which is never gold. Exit: sheets with per-class quotas equal to the human gap, any shortfall reported as not met, and the reviewers' labels imported with `make ml4-labels-import`. Export evidence (22 Nov): the agents recorded 3,825 judgements. A one-off cap of two articles per event per class, using the agents' own story tags, removed 165 (70 conflict, 95 disaster), leaving 3,660 judgements over 3,382 articles; 20 articles the agents disagreed on were dropped. Run `v4-20261121T000000Z` then rejected 32 at admission, 5 as near-duplicates of earlier gold and 14 proposed as unsorted, and filled every quota with no shortfall: 809 candidates (business 38, conflict 152, crime 76, disaster 175, education 68, environment 79, health 48, science 81, society 60, sport 32). The four blind sheets hold 869 rows, with 20 articles in all four for agreement. `make ml4-labels-verify RUN=v4-20261121T000000Z` on 22 Nov: 809 checked, 0 missing, 0 changed, 0 label conflicts. `weak-labels.jsonl` has 809 rows; the 701 high- or medium-confidence rows train, the 108 low-confidence rows do not. The capped proposal files are kept with their SHA-256s in the run manifest. Remaining: reviewers label the sheets.

**Exit:** ML4.1 has candidate sheets and a measured shortfall report. ML4 closes when the round-2 human labels are imported, the 200/class target is met or explicitly recorded as not met, and ML4.4 has retrained on them; training rights were approved on 21 Nov. ML4.4 trains only through the ML4.3 trainer. No candidate or AI-agent judgement is called gold.

### LOCAL — On-demand reader demo (separate from release acceptance)

- [x] **LOCAL.1** (Copilot, 22 Nov) Started the read-only news reader for the owner (D17). The missing `stories-002` files were not reconstructed or overwritten; a separate `stories-local-20261122T105200Z` archive holds 20,000 articles from 53 publishers, fixed before 22 Nov 10:52 UTC. `NEWS_ENV_FILE=/dev/null make rec-prepare REC_ID=stories-local-20261122T105200Z CUT=2026-11-22T10:52:00+00:00`, `rec-baseline` and `rec-train` passed; baseline 73.94 s, neural fit 7.44 s. Persisted [manifest](../ml-v2/artifacts/recommender/stories-local-20261122T105200Z/manifest.json) and all three representations. The detached ranker serves loopback :8001. A reader from this repository appeared on :8090 while preparation ran; reused it without stopping another process. Both `/health/ready` endpoints returned 200, reader MongoDB check passed, and each of TF-IDF/SVD/neural returned five hydrated articles with zero unavailable IDs. The browser opened [AFTERLINE](http://127.0.0.1:8090/stories) and displayed a real story and the 20,000-article archive. V4, the collector and historical datasets are unchanged; no production promotion or human-quality claim.

### DEMO — Bare-minimum client demo (separate from release acceptance)

Owner decision D18 (24 Nov): a client demo on the morning of 25 Nov, presented from the owner's laptop, with fresh news from the collector running locally against the local database. Must-haves: a fresh-first feed with the archive, a "Yesterday" page, a professional-focus switch, and saved stories with notes kept in the browser. Demo shortcuts, recorded here rather than as contract changes: the snapshot is rebuilt by hand instead of the M2 pipeline (C3–C5), editions are computed per request and not stored, with no topic cap (C9), and saved items and settings live in browser storage (C8). Everything else in V1 stays open and is reported as not done.

- [x] **DEMO.1** (Copilot, 24 Nov) Collector running on this Mac against the local database only. `make rec-inspect` showed the default environment targets the local `news` database (246,922 articles, newest collected 22 Nov 10:47 UTC) before the run. Started `cmd/api` with `configs/config.yaml` (classifier disabled, so topics wait as designed). Migrations and source sync passed, with 124 sources, 34 of them domain-tagged. 1,090 new articles in the first two minutes, all with `date_verified`; no warnings or errors in the log. Production was not touched.
- [x] **DEMO.2** (Copilot, 24 Nov) Recency-first snapshot: `newsrec prepare --recent-days N` keeps every article collected in the last N days (newest first within the candidate budget), then fills the limit with the existing seeded reservoir sample of older articles. With `--recent-days 0` the selection is unchanged. Rows now carry `source_id`, the source's `domains`, `date_source` and `date_verified`, with stored C1 provenance first and the C1 legacy rule otherwise. First real build, `demo-20261124T082508Z`: 30,000 articles; 16,335 from the last 7 days; 29,947 date-verified; 3,412 from domain-tagged sources. Prepare took 177 s at 0.70 GB peak RSS, baseline 147 s at 1.34 GB, train 17 s at 1.10 GB. Tests in `tests/test_recommendations.py` cover the recent window, the newest-first budget and date provenance.
- [x] **DEMO.3** (Copilot, 24 Nov) Ranker and reader API. Requests take `window` (`fresh` = C2: verified date, 0–30 days old; `yesterday` = the C9 day in Asia/Kolkata, available from 06:00; `archive` = everything not fresh) and `domains`. With no likes, news windows read newest first; an edition ranks every eligible story; related reading ignores the window, so older material can surface (C7, R23). Items carry `date_verified` and `fresh`, and metadata carries window counts, the edition date and domain counts. The Go reader passes these through and validates tags with the shared `domain.ValidDomainTag`. Real-data probe: fresh 18,765, archive 11,235, yesterday 929 (edition 23 Nov). `make rec-test` scope: 71 Python tests passed; `go test` passed for `./internal/recommendation`, `./internal/handler`, `./internal/domain` and `./cmd/reader`.
- [x] **DEMO.4** (Copilot, 24 Nov) Reader UI. Additions: a Fresh / Yesterday / Archive switch; a Professional focus switch (ai, data-science, software, technology); the edition as one fixed page of up to 10; dates shown in India time; "date unverified" labels; a fresh or archive stamp; and Save with a note, plus a Saved list kept in browser storage across snapshots. Third-party text and notes render only through `textContent`. Browser walkthrough on the real snapshot covered Fresh newest-first, Professional focus, choosing two of today's stories as interests, "Fresh · for you", and related reading reaching February and May 2026 archive articles. It also covered save, a note auto-saved on blur, the Saved list, and Yesterday (Monday 23 Nov, 10 stories). An independent code review found two browser bugs. A note typed just before a touch swipe or reload could be lost. A like or not-interested choice inside Yesterday could grow the edition past 10. Both are fixed: notes are saved as you type and before any story change, swipes no longer start on the note box, and the edition stays one fixed page. Each fix has a regression test that fails without it, and both were rechecked in the browser. `node --test scripts/stories.test.mjs`: 23 passed. Owner request, same day: the story now fills the screen. On screens at least 900 px wide, the picture sits beside the text, every control is in one bar above, the topic circles are a compact row of buttons, and the introduction and collection numbers sit below the story. This is template and CSS only, and every element ID is unchanged. Checked in the browser at 1440×800 (story and navigation on one screen), at the owner's 1056×674 window (whole story card visible, navigation just below), and at phone width (stacked, no sideways scrolling). Owner request, same day: a light/dark switch. Every colour is now a CSS variable with a dark charcoal value. With no saved choice, the reader follows the computer's setting through CSS alone. The "Dark theme" toggle in the masthead saves an explicit choice in the browser's settings, and a regression test covers the system default, both toggles, the saved choice and bad stored values. Checked in the browser by simulating a dark and then a light computer setting: dark by default, a light choice kept after reload in dark mode, a dark choice kept in light mode, and every screen readable in dark (interests picker, text cover, saved note, Saved list, end of edition). `make rec-test`: 71 Python, reader Go packages and 27 JavaScript tests passed. Owner request, same day: a premium layout in the style of Apple, Airbnb and Medium, with a grid wherever a story has little text. `/stories` is now a grid: a full-width lead story, then three, two or one columns by screen width, with borderless picture tiles (or a coloured panel with the source name), source, date, headline, up to three lines of stored text and a ☆ save button. Opening a tile opens a full-screen reading view: a 720-pixel serif column, the original link, like, not interested, save with a note, and six related stories as a grid with "See all related stories". The first page holds 25 stories and "More stories" adds 24, leaving out stories already shown without marking them viewed; only opening a story marks it viewed. Likes no longer reshuffle the page while reading: "Update for your new choices" re-ranks it, and not-interested stories leave when the story closes. Esc, "All stories" and the browser Back button close the reader at the same scroll position and return focus to the tile. The Saved list and the interests picker are grids, with picture thumbnails in the picker. Still template, CSS and plain JavaScript: no new dependency, and the page's security policy is unchanged. Checked in the browser on the real snapshot at 1440×800 in light and dark, at 1056×674 and at a 390-pixel phone: grid and lead story, More stories (49 tiles, no repeats), reading view, → / Esc / Back, related grid (six on-topic stories), See all related, saving from a tile and from the reader with a typed note, the Saved grid, a like followed by the update button and a re-ranked "For you" page, Yesterday (10 stories and its end note), Professional focus (technology sources only) and picker thumbnails, with no console errors. The related stories checked were all fresh, so archive background in the grid was not re-demonstrated on this snapshot. An independent code review of the redesign then found three problems, all fixed. First, marking every story on a page not interested left a blank page; it now says "Nothing left on this page." and offers the update or "Show all stories". Second, after "See all related stories" the browser's Back restored the old scroll position, so the new page opened mid-way (y ≈ 5,200–5,700 instead of its top, 3 of 3 runs); scroll restoration is now manual, and 6 of 6 runs (instant and smooth scrolling) open at the top. Third, after a not-interested choice, focus jumped to the top of the page; it now returns to the opener's story, or the next story kept after it. The first and third have regression tests that fail without the fix (with the fixes reverted, 2 failed and 27 passed); the second was reproduced and rechecked in the browser, together with Esc and Back keeping the reader's place. `make rec-test`: 71 Python, reader Go packages and 32 JavaScript tests passed, including five new ones (tile safety and badges, related reading and its trail, Back and focus, the emptied page, focus after not-interested).
- [x] **DEMO.5** (Copilot, 24 Nov) `make demo-refresh` shows the target database through `newsrec inspect`, then freezes, fits and trains a fresh-first snapshot and records it in `LATEST_DEMO`; `make demo-serve` serves it. Run: local `news` database (249,047 articles, newest collected 08:36 UTC); `demo-20261124T084052Z` has 30,000 articles, 16,330 recent, 29,954 date-verified and 3,432 domain-tagged. It took 341.5 s. `make demo-serve` switched the ranker; both ready checks returned 200. After a browser reload, the new snapshot started with empty likes, while Professional focus and the saved story with its note carried over.
- [ ] **DEMO.6** (Owner, Copilot, 25 Nov) Morning: `make demo-refresh`, restart the ranker with `make demo-serve`, restart `make reader`, rehearse the script in [the client briefing](recommender-client-review.md#the-25-november-demo).

**Not delivered by the demo (V1 stays open):** sign-in and hosting (M3.1, M3.3), server-side likes, settings and saved items (M3.2, M3.5, M3.7), stored editions and topic caps (M4), the incremental pipeline and 1-hour freshness target (M2, R5), topic suggestions and follow-ups (M5), the two-tower model (M6), MCP (M7), reader-added feeds (M3.6), human evaluation (M8, R15), and hardening (M9).

### DOC — Reader-friendly progress documentation

- [x] **DOC.1** (Copilot, 23 Nov) Added the [plain-English progress checklist](recommender-client-review.md#project-progress-checklist): completed work, work in progress, remaining V1 work, later versions and existing acceptance targets. Distinguished local/code completion from production acceptance and applied D16's label-provenance correction. Standard-library checks passed for 6 tables, 38 checklist rows and 57 local file/heading links; the historical technical-review body matches `HEAD` unchanged. `git diff --check -- collector/docs/recommender-client-review.md collector/docs/roadmap.md` passed. Documentation only; no application tests or live-service checks rerun, and no M9.5, milestone or release acceptance claimed.

- [x] **DOC.2** (Copilot, 25 Nov) Refreshed 61 files covering product/operations guides, current status, historical-plan notices, diagrams, source comments and classifier explanatory copy. Collector, local AFTERLINE and model-tooling claims now distinguish implementation, local evidence, deployment and acceptance. Historical measurements/artifacts and thresholds are preserved; D16's AI-label provenance is explicit. Evidence: `git diff --check` and `make -C collector help` passed; the offline checker passed 14 Markdown files, 210 local file/heading links and 282 documented make references, with matching overview diagrams and unchanged Makefile executable content. Both changed Mermaid flowcharts validated. Static source checks preserved non-documentation structure/numbers and Go directives across 15 Go, 22 Python and one JavaScript file; syntax/format checks passed, and all 24 notebook code cells, outputs and metadata are unchanged. No application suites, database operations, services, retraining or production checks ran; no milestone, requirement or release gate is closed by this task.

### R — Repository restructure (D21)

Owner decision D21 (27 Nov): split the repository into one top-level folder per part, in this repository on the `v4` branch. The parts are `collector/` (Go), `server/` (Python: `core/`, `web/` and a separate read-only `mcp/` program), `frontend/` (React, checked by Biome), `ml/` (one package; model files are ignored by git and downloaded by `run.sh`), `data/labels/`, `deployment/` (a Helm chart, plus Docker Compose for laptops), `docs/`, a short `README.md`, `run.sh` and `.github/`. Documentation is written so an 8th-grade student can follow it. Every phase ends with the app still working, so collection never stops (rule 1). V1 contracts and thresholds are unchanged; a phase that needs to change one adds a §8 row first.

- [x] **R0** (Copilot, 27 Nov) Safety first: back up, merge and push before anything moves. Evidence: a laptop copy at `~/repos/personal/Backups/news-bot-2026-11-27`, leaving out `.venv` folders, caches and `.env` files (rule 6): 1,595 of 1,595 files match by SHA-256 and `git fsck --full` passes. A private repository, `mhd-riaz/news-bot-archive`, with GitHub Actions turned off: its 7 branches match commit for commit (GitHub's 6 plus the laptop-only `v4` at `3bc5b8e`). Its release `laptop-files-2026-11-27` holds the 105 git-ignored files that existed only on the laptop (`ml-v2/artifacts` and `ml-v4/data`; 336 MB and 85 MB packed). Downloaded again, both packed files and all 105 unpacked files match their SHA-256s. Before `3bc5b8e` went public, a scan of its 1,566 added lines found 0 possible secrets. `main`'s `8bbd4af` was merged into `v4` as `2848018`; both branches had used D18, so `main`'s standalone-deployment decision is now D20. Checks on the merge: CI's Go gates (`make fmt-check vet test-race test-integration`, 37 packages), ml-v2 pytest (198 passed, 14 private-data skips), `make ml4-test` (75 + 31 passed) and Node (32 passed). `v4` pushed; manual CI run [45983035576](https://github.com/mhd-riaz/news-bot/actions/runs/45983035576) passed `test`, all three image builds and `ci-passed`. `release` was skipped because the run was not on `main`, so nothing was published or deployed. It is the first build of the classifier image with ML4.7's V4 changes; its size, memory and latency are still unmeasured. None of the 9 open tasks met its own closing condition, so none was closed: 8 are marked `[>]` with the R task that now carries their remaining work, and M0.2 stays with the owner. The recommender's `stories-002` judgement files are on neither this laptop nor GitHub, so the results recorded in [recommender-results.md](recommender-results.md) cannot be re-checked from files.
- [ ] **R1** (Copilot) The big move. Create the top-level folders and `git mv` today's files into them unchanged. Fix the paths in the Makefile, Dockerfiles, CI and Copilot instructions; rename the Go module to match the repository; turn `fixtures/` into `testdata/`; delete the empty `.gitkeep` files. Exit: every existing test passes from its new place, and the local demo still runs.
- [ ] **R2** (Copilot) One ML package on Python 3.12 (the version CI tests) built from `ml`, `ml-v2` and `ml-v4`, with duplicate files collapsed into one copy. The classifier service lives in `ml/classifier/`. Model files go to the private archive and are listed with their SHA-256s in `ml/models.yaml`, with a download script. The historical Streamlit app and the unused recommender image are removed. Carries the pull request and review that ML4.1 and ML4.3 wait for. Exit: tests pass, the collector's classifier check passes, and downloaded models match their fingerprints.
- [ ] **R3** (Copilot) `data/labels/`: one dataset built from the ML4.6 pooled set, with only article ID, topic, training-or-test and topic-list version. It has no article text (rule 11) and no per-row origin tags; `data/labels/README.md` says once how the labels were made (D16). The old label folders and the committed article snapshots are deleted from the files; they stay in git history (D21). Carries ML4.4's retrain and ML4.5's reviewer labelling, if the owner still wants them; any human labels go in a separate file (rule 4). Exit: a check confirms the row count against the pooled manifest, no article text, and no article in both training and test.
- [ ] **R4** (Copilot) Python `server/` with `core/`, `web/` (Google sign-in, sessions and CSRF protection) and `mcp/` (a separate program with a read-only database login and API keys). It replaces the Python ranker; the Go reader keeps serving until R5. Exit: tests pass, sign-in works end to end, and the database refuses a write from the MCP program.
- [ ] **R5** (Copilot) React `frontend/`, checked by Biome, rebuilds every reader screen; then the Go reader is deleted. Rule 7 is reworded for React: third-party text is rendered as text, never through `dangerouslySetInnerHTML`. Carries M9.1's JavaScript coverage. Exit: Biome and the tests pass, and every screen is checked in a browser.
- [ ] **R6** (Copilot; owner for the home lab) A Helm chart with settings for each environment, Docker Compose for laptops, and one `.env.example` per environment. k3s runs at home, the database is copied across, and CI switches from Coolify to Helm. Carries M0.5's release evidence, M1.5's production backfill run and ML4.7's production deployment and relabel; the owner may still do those through Coolify first. Exit: collection never stops during the switch, and article counts match before and after.
- [ ] **R7** (Copilot) `run.sh` works on Linux and macOS, downloads the models and starts everything against a local database by default; a short root `README.md`. Exit: a fresh clone on a clean machine runs with one command.
- [ ] **R8** (Copilot) Rewrite the documentation in `docs/` at an 8th-grade reading level, checking each claim against the code. Exit: every link and command in the docs works.
- [ ] **R9** (Copilot) One CI workflow per service, Copilot instructions for the new layout, instruction files per language, skills, and MCP settings wherever each tool reads them. Exit: CI is green for every service, and the instructions name only paths that exist.

**Exit:** R0–R9 are done with evidence, and the other agent has reviewed them (working protocol, step 7).

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
| --- | --- | --- | --- |
| V1 scope, now including R17–R21, does not fit 21 days for two agents | High | High | R17–R21 stay off the ML critical path. A milestone more than a day late goes to §7 the same day; no silent cuts. |
| GHCR publication or Coolify deployment fails | High | High | M0.5 workflow gates deployment on checks and image publication; verify with configured secrets before closing M0 |
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
| --- | --- | --- | --- |
| D1 | Confirm the agent split in §1 | M0 | As proposed |
| D2 | Off-machine backup target | M1 | Decided 26 Oct: a LAN disk or NAS (§8) |
| D3 | Alert channel | V2 | Deferred; no V1 alert delivery |
| D4 | Retention period for `reader_events` | M3 | Keep until the reader deletes them |
| D5 | Load target (requests/s, p95) for M9 | M9 | 5 readers + 2 agents, p95 ≤ 500 ms |
| D6 | Content and image rights for invited readers | M9 | Summary or excerpt plus link; images hotlinked |
| D7 | Relax R3 if few dates are verified | M1 report | No |
| D8 | Should MCP expose a reader's own saved items and notes? | M7 | Not in V1 (V2-6) |
| D9 | Accept the simplifications marked "Proposed" in §8 | M0 | Accept |
| D10 | Public hostname for the reader (Cloudflare Tunnel) and the Google OAuth client | 29 Oct | Hostname decided 26 Oct: `news.mxdio.com` (§8). The OAuth client is pending and still blocks M3.3 |
| D11 | Publish V1 images and automatically deploy on main pushes | M0 | GitHub Actions → GHCR → authenticated Coolify webhook |
| D12 | How to source and human-label enough V4 examples for the classes below 200, and which shipped publishers permit classifier training? | Before ML4.2/training | Resolved 21 Nov. Rights: every labelled V4 article may be used for training (Medium was excluded at export), and the owner accepts the rights risk for a private, self-hosted model. Sourcing: AI agents select round-2 candidates through the MongoDB MCP server from the taxonomy class descriptions, and reviewers label the blind sheets (ML4.5). Never reuse old labels or lower 200/class |
| D13 | Whether the V4 labels may be treated as human labels and imported as gold | Before `ml4-labels-import` | Superseded 22 Nov by D16: the 21 Nov human-review attribution is withdrawn. All existing classifier labels are AI-generated; preserve the original sheets/import records, but do not treat them as human validation. |
| D14 | How to import round 1 now that the database it was exported from is gone | Before the ML4.2 import | Resolved 21 Nov: import on the export-time database check (`make ml4-labels-import-exported`), and record the 659 articles today's database cannot re-check |
| D15 | Whether to train before the round-2 human labels arrive | Before ML4.4 | Interim training approved 21 Nov; its assumed human round-1 provenance was withdrawn by D16 on 22 Nov. Interpret the recorded scores as AI-label agreement. Human validation remains not met; ML4.6 records the later pooled local candidate, not production promotion. |
| D16 | Correct label origins and permit a larger pooled V4 candidate without falsely calling AI labels human | Before ML4.6 | Resolved 22 Nov: owner confirms all old and new labels are AI-generated and approves combining usable records with truthful origins, duplicate/test-leakage exclusions and local candidate training. This supersedes earlier human-provenance assertions and the no-old-label sourcing restriction for this separate candidate only. Existing rights/admission rules and human-validation targets remain unchanged; no production promotion |
| D17 | How to start the local news reader when its saved recommendation archive is missing | Before LOCAL.1 | Resolved 22 Nov: owner chose the news reader and approved a new local 20,000-article archive from the current database. Use a separate fixed-cut snapshot and the existing recommender workflow; no production changes or implication that the reader uses the V4 topic classifier |
| D18 | What is the bare-minimum client demo, and how is it shown? | 24 Nov | Resolved 24 Nov: demo on the morning of 25 Nov from the owner's laptop. Fresh news comes from the collector running locally against the local database. Must-haves: fresh-first feed with archive, "Yesterday" page, professional focus, and saved stories with notes in the browser. Hosting, sign-in and the rest of V1 stay open; no V1 scope, deadline or threshold changes |
| D19 | Promote the pooled V4 classifier `v4-ai-072b01a9ceaf-hybrid_svc` to production, and relabel existing articles with it | Before ML4.7 | Resolved 27 Nov: owner approved both. The approval rests on AI-label agreement alone (macro-F1 0.8246, accuracy 0.829 on the once-opened test split): human validation and 200 human labels/class stay **not met** and no threshold changes. Production stays gated by `DEPLOY_ENABLED`; the owner puts the bundle on the volume and runs the relabel. Supersedes the "no production promotion" lines in D15 and D16 for this model only |
| D20 | Whether this repository publishes and deploys on its own, independent of `data-scientist-roadmap` | M0.5 | Resolved 22 Nov: standalone. The owner confirmed that Coolify deploys this repository's compose file, chose `news-bot` as the Go image name, and kept automatic deploys from `main` once armed (D11 as written). Numbered D18 on `main` until the 27 Nov merge with `v4`, which had already used D18 |
| D21 | How to reorganise the repository, and what to do about the article text already in its public history | Before R1 | Resolved 27 Nov: the phases in §4 R, in this repository on `v4`. No history rewrite: R3 removes the committed article snapshots from the files, but they stay in old commits. Backups go to a private `news-bot-archive` and to the owner's laptop. A Python `server/` replaces the Go reader and the ranker, with MCP as its own read-only program; React with Biome; Helm on k3s plus Docker Compose for laptops; one label dataset without per-row origin tags; Python 3.12 everywhere. Open V1 contracts and thresholds are unchanged |

## 8. Decision log

Newest first. Never lower a threshold or change a contract without a row here.

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-11-27 | **D21: restructure in phases R0–R9 (§4 R).** Same repository and `v4` branch, with history kept. Backups come before any change: a private `mhd-riaz/news-bot-archive` (every branch, plus a release holding the laptop-only data and model files) and a copy on the owner's laptop. Eight open tasks move into R tasks under a new `[>]` marker; none is closed. One Python version, 3.12, everywhere | Owner decision. The repository is public, and four committed snapshot files hold publishers' article text (against rule 11). GitHub's documentation says old commits stay reachable through pull requests and cached views even after a history rewrite, so the owner chose to stop adding text rather than rewrite history. 3.12 is what CI tests today; the classifier image's 3.13 is untested. No threshold or contract changes |
| 2026-11-27 | **D21 server and frontend (rule 9).** A Python `server/` (`core/`, `web/`, `mcp/`) replaces the Go reader and the separate Python ranker. The MCP server is a second program built from the same code, with a read-only database login and API keys. A React `frontend/`, checked by Biome, replaces the Go templates. This adds Node.js and a build step, replacing rule 9's "the web reader has no JavaScript build step". The exact packages and versions get their own rows in R4 and R5 | Owner decision. One codebase serves people and AI agents. Running MCP as its own program lets the database itself enforce read-only, keeps Google sign-in and API keys apart, and stops a busy agent from slowing the reader. Rule 7 still applies, reworded for React in R5 |
| 2026-11-27 | **D21 deployment (rule 9).** A Helm chart deploys the app to k3s (a small Kubernetes) on the home lab, with settings for each environment; Docker Compose runs the stack on laptops for `run.sh`. Coolify stays until the R6 switch | Owner decision: one chart deploys the app on any Kubernetes. Rule 1 means the switch must not stop collection, so R6's exit requires matching article counts before and after |
| 2026-11-27 | **D21 labels.** `data/labels/` holds one dataset built from the ML4.6 pooled set: article ID, topic, training-or-test and topic-list version. It has no article text and no per-row origin tags; its README says once how the labels were made. Human labels, if reviewers ever label the round-2 sheets, go in a separate file | Owner decision. Every existing label was made the same way (D16), so a tag on each row adds nothing. Rule 3 keeps the one sentence, because a score against AI-made labels measures agreement, not correctness. Rule 4 keeps any future human labels apart, and rule 11 keeps article text out of git |
| 2026-11-27 | **D19: V4 serves production; the sidecar accepts either bundle.** `newsmlv4.serving.SidecarModel` wraps a V4 bundle so `/v1/classify` and `/v1/meta` keep their shape; `model_version` becomes `v4-ai-072b01a9ceaf-hybrid_svc` for new articles and for articles relabelled by `make backfill-reclassify`, while older articles keep `v2-001` until relabelled. Rollback is `NEWSML_MODEL_DIR` plus the hash. `classifier.ItemError` makes a sidecar-declined item identifiable instead of failing a batch opaquely (it still matches `ErrBadResponse`) | Owner approved promotion and relabelling on 27 Nov. No threshold or Go response contract changes, and the cut stays the model's own 0.2059. Topic-only relabels leave `updated_at` and `content_rev` unchanged, so an incremental indexer keyed on them will not see relabelled articles: revisit that if the recommender ever uses topics |
| 2026-11-27 | **Classifier image dependencies (rule 9):** `pymongo`, `sentence-transformers`, `torch` (CPU build), `transformers`, `huggingface-hub`, `tokenizers` and `safetensors`, all pinned in `ml-v2/requirements-serve.txt`; classifier memory limit 768 MB to 1.5 GB; gunicorn timeout 120 s | V4 files an article through a MiniLM encoder, so the image needs sentence-transformers and torch; the CPU wheel avoids multi-GB CUDA libraries. `pymongo` is only imported because the bundle's classes live in `newsmlv4.train`; the sidecar never opens a database connection and has no MongoDB credential. The encoder revision is pinned by the trainer, fetched at build time and used offline. Measured locally: 702 MB after warm-up, 893 MB peak, against the old 768 MB limit |
| 2026-11-24 | **D18: bare-minimum client demo on 25 Nov.** Shown locally from the owner's laptop; the collector runs locally against the local database. Demo shortcuts: hand-rebuilt recency-first snapshots (`make demo-refresh`) instead of the M2 pipeline, editions computed per request without storage or topic caps, and browser-only saved items, notes and settings | Owner decision with the demo due the next morning. No contract, threshold or deadline changes: C2 freshness and the C9 day boundary are implemented as written, and the C1 legacy date rule is applied at freeze time without writing to MongoDB. No new dependency: `zoneinfo` is in the standard library, and `uv sync --inexact` installed only groups already declared in `pyproject.toml` |
| 2026-11-22 | **D11 amended for D20 (standalone):** the Go image is `news-bot`. Every `main` run publishes per-commit `sha-` tags for all three images. One `release` job, armed by `DEPLOY_ENABLED` and limited to `main` by the `production` environment, checks the deploy secrets, moves all three `latest` tags to the same commit and calls Coolify. A `main` ruleset requires a pull request and `ci-passed`, with branches up to date. This replaces the 18 Nov publish gate | `news-collector` belongs to `data-scientist-roadmap`, so this repository's `GITHUB_TOKEN` could not push it: all five `main` runs from 26 Oct to 22 Nov failed with `permission_denied: write_package`. A separate name ends the shared `latest` tag. Per-image `latest` tags had moved on every failed run, leaving mixed sets. `ci-passed` was documented as required, but `main` had no rules. No dependency is added; the environment and ruleset are GitHub settings |
| 2026-11-22 | **D16: truthful pooled AI-label V4 candidate.** All old and new labels are AI-generated by owner confirmation; earlier human-provenance claims are withdrawn. Reuse usable historical labels in a separate local candidate, with source hashes, conflict/dedup checks and historical evaluation exclusions | Owner explicitly approved accurate attribution and local training rather than relabelling AI work as human. Development and held-out scores on this corpus are AI-label agreement only, not human acceptance, and any calibration/cut is provisional on AI labels. Original data and model artifacts remain intact. Human validation and 200 human labels/class remain not met; no new dependency, infrastructure or production promotion |
| 2026-11-22 | **D17: rebuild a separate local reader archive.** Existing `stories-002` files are missing, so use a new fixed-cut local snapshot through the existing prepare/baseline/train commands | Owner approved the local 20,000-article rebuild to start the news reader. This is a development archive, not a release acceptance or V4 classifier integration. No dependency, infrastructure, schema migration or production deployment is added |
| 2026-11-21 | **D15: interim V4 model on round-1 human gold plus round-2 AI-agent weak labels.** The human 200/class shortfall is accepted for this run only and recorded as not met; the target is unchanged | Owner decision. Weak labels never score, calibrate or cut a model and never touch the sealed test split. A `+weak` rung ships only if a corrected resampled t-test separates it from every human-only rung |
| 2026-11-21 | **D12 sourcing: round 2 is selected by AI agents through the VS Code MongoDB MCP server** from the taxonomy class descriptions, stratified by description facet and collection day | Owner decision. Articles have no `description` field, so the agents use the class descriptions in the labelling guide. Round 1 sent no article text to a generative AI service; round 2 sends titles and summaries of the local corpus to the agents, under the D12 rights acceptance. The MCP server is an editor tool, not project infrastructure, and adds no dependency |
| 2026-11-21 | **D14: round 1 imported on the export-time database check** | The local database had been replaced by a production copy (243,702 articles) holding none of the 2,287 exported IDs. All 2,287 passed the database check at export on 10 Nov, and the sheets still match those fingerprints; today's database holds 1,628 with identical text and cannot re-check 659. Owner decision |
| 2026-11-21 | **V4 trainer protocol (ML4.3):** a sealed stratified 20% test split and repeated stratified 5×3 cross-validation replace the temporal `newsml snapshot`/`newsml train` path named in the V4 README. The model reads the title and summary the reviewers saw, taken from the verified sheets | All 2,287 V4 article IDs are UUIDv7s whose embedded timestamps fall between 06:18 and 10:37 UTC on 10 Nov, so they carry no publication order. A 70/15/15 temporal split would leave about four disaster/accident articles to validate on. ml-v2 Phase H3 measured no difference between random and temporal splits. The existing ml-v2 environment provides every library, so no dependency is added |
| 2026-11-21 | **D12 rights:** every labelled V4 article may be used for classifier training. **Class balance:** label more examples for the short classes before training; the 200/class target is unchanged | Owner decision. Medium was already excluded at export, and the owner accepts the rights risk for a private, self-hosted model. 10 of 13 classes are below 200 on human labels |
| 2026-11-21 | **ML4.2 human labels confirmed:** run `v4-20261110T120557Z` was labelled by human reviewers from 12 groups | The owner confirms these are human judgements and directs that contradictory AI-label statements be removed. The 200/class target is unchanged; database verification and rights review remain pending. |
| 2026-11-10 | V4 provisional strata use fresh-only local TF-IDF against the 13 taxonomy descriptions plus existing feed/category/publisher hints; the 200/class target is unchanged | The local database had 7,494 articles but zero `topic` predictions, and no fitted classifier bundle was available. Owner approved the alternative; it needs no new dependency and does not train on old gold |
| 2026-11-10 | Owner approved a separate `ml-v4/` classifier sampling project: local MongoDB read-only, up to 200 fresh candidates per class, AI-assisted sampling and human-validated gold | Existing `ml/data/labels/v3` is an earlier annotation round; keep it and all V1/V2 datasets intact. No old labels are copied into V4 |
| 2026-11-18 | **D11 amended:** pull requests to `main` run the checks and image builds, and the `ci-passed` job is the one required check. Main publishes to GHCR and deploys only while the repository variable `DEPLOY_ENABLED` is `true`. The deploy request sends Cloudflare Access service-token headers when set and must return a 2xx | Production still deploys from `data-scientist-roadmap` and pulls `news-collector:latest` on every redeploy, so publishing that tag from here before the Coolify cutover would run this image under the old compose file. Access answers a rejected request with a 302 that `curl --fail` accepts |
| 2026-11-18 | **C15:** MongoDB is pinned to `mongo:7.0.48` and publishes 27017 on the host loopback only | Matches production. Docker publishes ports ahead of the host firewall, so a `ufw` rule cannot restrict an all-interfaces mapping; a floating tag stays on whichever image the host cached first |
| 2026-10-26 | **D2: backups go to a LAN disk or NAS**, not off-site | Owner decision. A NAS keeps backups off the laptop; neither option covers a site-level loss such as theft or fire |
| 2026-10-26 | **D10 hostname: `news.mxdio.com`**, through Cloudflare Tunnel. The OAuth redirect is `https://news.mxdio.com/auth/callback` | Owner decision; the Google OAuth client is still to be created |
| 2026-10-26 | Production reads the sources file baked into the image; Coolify leaves `NEWS_BOOTSTRAP_SOURCES_PATH` unset | Every main merge rebuilds and redeploys (D11), so a remote copy adds a runtime dependency for no gain |
| 2026-10-26 | Merge `v1` into `main` with a squash merge | Keeps the 21.5 MB binary added in `ecc24cc` and removed in `ddf4a15` out of `main` without rewriting pushed history |
| 2026-10-26 | **V1 domain tags:** `technology` (general tech news), `software`, `ai` and `data-science`. `TestShippedSourcesFileIsValid` rejects any other tag in `configs/sources.yaml`; the API still accepts any valid tag. | The C8 pool rule matches source and reader domains, so a misspelt tag would silently drop a source from every professional pool |
| 2026-10-26 | **New sources pass the Al Jazeera test:** no robots.txt group or licence that applies to every agent may reserve AI-training or text and data mining rights. The Pragmatic Engineer and MediaNama were left out (`Content-Signal: ai-train=no`). Blocks aimed only at named AI crawlers do not count. | Applies the existing Al Jazeera exclusion consistently to R17 additions |
| 2026-10-26 | **Medium included by owner decision**, although its licence (`medium.com/license.xml`) prohibits `ai-train`; it permits search and indexing with attribution. Three tag feeds sample `ai`, `data-science` and `software`. | R17 names Medium; the owner accepted the licence risk |
| 2026-10-26 | The M9.1 flaky rate-limit test fix was pulled forward from 10 Nov | It failed 259 of 3,000 runs at `-cpu=2` and gates every `make check` and CI run |
| 2026-10-26 | **C1 legacy insertion estimate:** use `collected_at` when `inserted_at` is absent; never replace a known insertion time | Owner approved the explicit estimate while resolving review `ecc24cc`; original insertion timestamps are unavailable |
| 2026-10-26 | Track synthetic feed/extraction checks; keep captured publisher HTML and gold labels private with explicit optional-data skips | Owner chose synthetic fixtures rather than redistributing publisher content; clean-checkout CI must remain self-contained |
| 2026-10-26 | CI runs Mongo integration tests against a health-checked MongoDB 7 service | Repository races and update-pipeline invariants require the real database engine; reuse the existing integration suite without a new dependency |
| 2026-10-25 | **C13 sampling refined:** one feed case from each grader's actual profile; fill the remainder of 50 with related-reading cases; use seed `20260823` | Owner replaced the initial 25/25 case-type split |
| 2026-10-25 | **D1 accepted; D2 no backup target for now; D3 deferred to V2** | Owner decision |
| 2026-10-25 | **D9 accepted:** per-request reader profiles, environment-backed MCP key hashes and the existing publication lease | Owner accepted the three proposed simplifications |
| 2026-10-25 | **D11:** main pushes build and publish all V1 images to GHCR, then call Coolify's authenticated deploy webhook | Deploy only after successful checks and image publication |
| 2026-10-25 | **C13 sampling (initial proposal, superseded above):** 50 cases, split 25 feed / 25 related-reading, using RNG seed `20260823` | Owner later chose one actual-profile feed case per grader |
| 2026-10-25 | `sources.added_by` is application-enforced, not a MongoDB row-level role | MongoDB RBAC grants collection-level actions only |
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
| --- | --- | --- | --- |
| 2026-10-25 | — | Roadmap created | Built from the client expectations, the v4 review draft and the review of that draft |
| 2026-10-25 | — | V1 execution plan added | §1.1 schedule, numbered tasks with build notes, §4.1 release checklist |
| 2026-10-25 | B | M0.5–M0.7 | Built all three images locally; Compose validation passed; the Mongo user script and allow/deny plus collector DDL probes passed on a disposable instance. Remote CI/deployment and production provisioning are not yet verified. |
| 2026-10-25 | Owner | M0.2–M0.4 | Approved the C13 rubric and 10–13 Nov grading window, chose to wait for M2's full index for development cases, and set acceptance sampling to 25 feed + 25 related-reading cases with RNG seed `20260823`. |
| 2026-10-25 | Owner | M0.4 | Refined the case allocation to one actual-profile feed case per grader and the remaining cases as related reading. |
| 2026-10-25 | A | M0.4 | Added and tested deterministic acceptance sampling, including post-training group and fresh-feed eligibility, balanced grader assignment, sample hashing and overwrite protection. Procedure SHA-256 is recorded on the M0.4 task; the sample hash awaits M8's full index and profiles. |
| 2026-10-26 | Copilot | Review `ecc24cc` claimed | Owner approved all validated fixes, the legacy insertion estimate and synthetic fixtures; confirmed production provisioning is already complete. No production operations or history rewrite authorized. |
| 2026-10-26 | Copilot | Review `ecc24cc` source fixes validated | Full Go race suite: 776 passed; full Go integration-tagged suite: 877 passed; ML suite: 203 passed; Node: 21 passed. Tracked-source-only Go CI gates passed; ML: 189 passed, 14 explicit private-data skips; Node: 21 passed. Owner chose to leave changes uncommitted and handle binary history before pushing. |
| 2026-10-26 | Copilot | M9.1 flaky test (pulled forward) | `TestConcurrentAcquireReservesDistinctSlots` failed because the test clock added each concurrent sleep to one shared time, moving it past later reservations. A frozen test clock now makes the expected waits exactly 1–7 s: 0 failures in 12,000 runs at `-cpu` 1–8 (previously 259 of 3,000 at `-cpu=2`), and a deliberately broken reservation fails it. The limiter itself is unchanged. |
| 2026-10-26 | Copilot | M1.7 done | Owner approved the design, included Medium and chose no action on existing sources. The 25 new feeds were probed for status, items, language, robots and licence, then seeded and collected into a scratch database on the local container (dropped afterwards). Production was not touched. If Coolify sets `NEWS_BOOTSTRAP_SOURCES_PATH` to the old `data-scientist-roadmap` URL, production will not see this change. |
| 2026-10-26 | Owner | Review and decisions | Approved M1.7 and the M9.1 flaky-test fix. D2: a LAN disk or NAS. D10 hostname: `news.mxdio.com`. Production uses the baked sources file; the owner unsets `NEWS_BOOTSTRAP_SOURCES_PATH` in Coolify. M0.6 closed on the owner's confirmation. The local `.env` now targets localhost, and production credentials moved to a gitignored `.env.prod`. `v1` reaches `main` through a reviewed PR with a squash merge; the M1.5 production backfill runs in the api container after that deploy is healthy. Next: M2.1. |
| 2026-11-10 | Copilot | ML4.1 claimed | Owner approved an independent classifier V4 sampling effort, distinct from M8 recommender evaluation. Existing label rounds and their gold files remain untouched. |
| 2026-11-10 | Copilot | ML4.1 candidate export complete; ML4.2 blocked | Fixed-cut rerun reproduced all 2,287 candidate IDs and class counts. Local verification found 0 changed/missing articles or sheets; 189 combined tests passed. Four classes were short by 313 candidates total, and on 10 Nov no labels were yet gold because human labelling had not begun. D12 records the owner decision needed for more eligible material and rights. |
| 2026-11-10 | Copilot | ML4.1 closure correction | The preceding "complete" describes the candidate export, not task closure: no PR or automated review was requested, so ML4.1 stays `[~]`. Standard-library trace coverage: sampler 89%, export CLI 84%, verifier 82%; below the 90% backend and 95% critical-logic targets because no isolated Mongo test instance is available. The read-only local export and verifier exercised the database paths separately. |
| 2026-11-21 | Copilot | ML4.2 human labels (12 reviewer groups) | All 2,287 candidates were labelled by human reviewers from 12 groups using title and summary, following the V4 guide, in the four original sheets (2,347 rows; each of the 20 articles repeated in every sheet has one label). 1,055 rows have notes; 9 are `unsorted`. Only `label` and `notes` changed against the blank backup. Offline `compare_sheets`: 2,287 checked, 0 missing/changed/conflicts; `read_sheet`: 0 problems; 0 cross-sheet disagreements. Distribution: technology 457, politics 409, entertainment/arts 221, sport 168, business/economy 162, health 152, society/lifestyle 140, education 132, crime/justice 124, environment/climate 121, science/space 119, conflict/war 48, disaster/accident 25; 10 of 13 classes are below 200. Database verification was not run at that time. The labels are not imported; ML4.2 remains `[!]` pending database verification, the D12 rights decision and the class-balance decision. Provenance: `labels-provenance.json` in the run directory. |
| 2026-11-21 | Owner | D12 and class balance | Approved training on every labelled V4 article and accepted the rights risk. Chose to label more examples for the short classes before training. Will restart VS Code with `NEWS_ML_MONGO_URI` set so the agent can run the database verification and import. |
| 2026-11-21 | Copilot | ML4.3 claimed | Stratified V4 trainer. Code and synthetic-data tests only until ML4.2 clears. |
| 2026-11-21 | Copilot | ML4.3 trainer built; ML4.4 blocked | Added `newsmlv4.train`, `make ml4-train` and 10 tests. `make ml4-test`: 67 passed in `ml/` and 10 passed in ml-v2. The real run passes the trainer's export and sheet checks and stops at the missing `gold.jsonl`. A synthetic run at the real class counts took 150 s for all eight rungs. No V4 label was trained on; ML4.4 waits for ML4.2. |
| 2026-11-21 | Owner | D14, D15 and round-2 sourcing | Chose to import round 1 on the export-time check, to have AI agents select round 2 through the MongoDB MCP server, and to train an interim model now on human plus weak labels while reviewers label round 2. Connected the VS Code MongoDB MCP server to `localhost:27017`. |
| 2026-11-21 | Copilot | ML4.2 imported (D14); ML4.5 started | Import: 2,347 labels over 2,287 articles; 1,628 identical in today's database, 659 not re-checked. MCP and pymongo agree on the local database (243,702 articles; 27,215 in the round-2 window). No article `description` field exists, so six AI agents work from the taxonomy class descriptions. Added the export-verified importer, proposal-driven export and weak-label training; `make ml4-test`: 73 passed in `ml/` and 12 in ml-v2. |
| 2026-11-22 | Copilot | ML4.5 exported; ML4.4 interim model trained | Since the last entry, a second code review found three issues, all fixed with regression tests. Round-2 export `v4-20261121T000000Z`: 809 candidates, every quota met, verified 809/0/0. The first interim training run was stopped during calibration, before the test split was opened and before anything was written; the rerun reproduced its ladder exactly. The trainer now creates the model directory before it opens the test split. Interim model `v4-62490efb025d-hybrid_svc`: test macro-F1 0.7705 [0.7075, 0.8183]; it does not use the weak labels. `make ml4-test`: 75 passed in `ml/` and 14 in ml-v2. |
| 2026-11-22 | Copilot | ML4.6 claimed; D16 provenance correction | Owner confirms all old and new label datasets are AI-generated and approves truthful pooled local candidate training. Earlier human-review claims and human-validation interpretations of existing classifier scores are withdrawn. Auditing source schemas, usable text, duplicate/conflict records and protected historical evaluation IDs before combining data. Original datasets and model artifacts will not be overwritten. |
| 2026-11-22 | Copilot | ML4.6 corpus built; final training running | Private, read-only MCP title/summary snapshots recovered the unselected AI proposals. Pooled corpus: 8,594 records, 2,582 extra AI-sampled articles, 0 historical ID/alias overlap; the old model's 456 test IDs were reproduced exactly. All labels are attributed to AI, including legacy labels with contradicted human-origin fields; originals remain intact. `make ml4-test`: 75 + 26 passed. The first training attempt was stopped before the model directory/test-opening marker existed to correct CLI pickle namespaces; a subprocess regression now verifies canonical save/load. The final eight-rung run is in progress; no human-validation claim or production promotion. |
| 2026-11-22 | Copilot | ML4.6 local candidate verified | `make ml4-train DATASET=v4-ai-pooled-20261122T000000Z` completed in 863.36 s; all eight rungs ran, including Keras. Model `v4-ai-072b01a9ceaf-hybrid_svc`: AI-label macro-F1 0.8246 [0.8056, 0.8442], accuracy 0.829 on 1,719 once-opened held-out articles; human validation not met. Fresh-process offline load verified importable estimator classes, five calibrated folds, finite normalized probabilities, valid routing on three fictional probes, and dataset/source/split hashes. The 6,875 development articles include 2,627 AI-sampled round-2 articles. Model and training evidence remain private; no original corpus or old model was rewritten, and nothing was promoted to production. |
| 2026-11-22 | Copilot | LOCAL.1 claimed | Owner chose the AFTERLINE news reader, not a classifier demo, and approved rebuilding its missing recommendation archive. Safe local inspection found 246,922 articles in `news`; reader/ranker ports 8090/8001 are free. Rebuild and startup use process environment only, with dotenv file reads disabled. V4 and the collector remain unchanged. |
| 2026-11-22 | Copilot | LOCAL.1 reader verified | New private archive `stories-local-20261122T105200Z`: 20,000 articles, 53 publishers; lexical/SVD/neural artifacts saved. Ranker started detached at 127.0.0.1:8001. Another reader appeared during preparation at 127.0.0.1:8090 (PID 50765, repository `collector` working directory); the additional launch failed with address-in-use, so the existing reader was reused rather than killed. Reader/ranker ready endpoints passed; all three methods returned five real hydrated articles with no missing IDs, and the browser rendered the archive. No database write, collector start or V4 integration occurred. |
| 2026-11-22 | Copilot | M0.5 taken over (owner, D20) | Owner made the repository standalone and directed the CI fix. Root cause: all five `main` runs since 26 Oct failed only at the `news-collector` push (`permission_denied: write_package`; the package is linked to `data-scientist-roadmap`), while `DEPLOY_ENABLED` was already `true`. Set `DEPLOY_ENABLED=false` until the first green `main` run; renamed the Go image to `news-bot`; `main` publishes `sha-` tags; added the `release` job, the `production` environment (deploys from `main` only) and the `main` ruleset (pull request, strict `ci-passed`, no force-push or deletion, no bypass). `actionlint` passes; the compose file resolves the API image to `ghcr.io/mhd-riaz/news-bot:latest`. `COOLIFY_WEBHOOK` is not yet a repository secret. |
| 2026-11-23 | Copilot | DOC.1 claimed | Preparing an eighth-grade-friendly progress checklist in the existing client briefing, using detailed task records and the latest provenance/deployment decisions. No production operation, scope change or milestone acceptance. |
| 2026-11-23 | Copilot | DOC.1 done | Added the reader-friendly status tables and remaining-work explanations to the existing briefing, with source links, pass targets, scope limits and the older technical review folded separately. Table/status/link checks and historical-body preservation passed; `git diff --check` passed. The original V1 deadline is reported without rescheduling it; no application, infrastructure or release status changed. |
| 2026-11-24 | Owner | D18 | Asked for a bare-minimum client demo, due the morning of 25 Nov. Chose to present it locally, with the collector running on this Mac against the local database. |
| 2026-11-24 | Copilot | DEMO.1–DEMO.5 claimed | Local database copy had stopped on 22 Nov, and the 22 Nov archive was a random 2012–2026 sample, so nothing could show today's news. Started the local collector first because it needs the most time; then built the recency-first snapshot, ranker windows, reader pass-through and UI. |
| 2026-11-24 | Copilot | DEMO.1–DEMO.4 done | Evidence on each task line. Real snapshot `demo-20261124T082508Z` served locally; the browser walkthrough of Fresh, Professional focus, interests, related reading, Save with a note and Yesterday passed. Python 71, JavaScript 22 and the targeted Go packages passed. |
| 2026-11-24 | Copilot | DEMO.5 done; DEMO.6 open | `make demo-refresh` and `make demo-serve` verified on `demo-20261124T084052Z`. Full checks on the working tree: `make check`, `make test-race` and `make rec-test` (71 Python, reader Go packages, 25 JavaScript) passed. Collector, ranker and reader left running locally for rehearsal. Nothing was committed or deployed. |
| 2026-11-24 | Copilot | DEMO review fixes | Code review of the working tree: no findings in the Python, Go or Makefile changes. Two browser findings were fixed with failing-first regression tests (see DEMO.4). The reader embeds its static files, so it was restarted to serve the fix. `make rec-test`: 71 Python, reader Go packages and 26 JavaScript tests passed; `git diff --check` clean. |
| 2026-11-24 | Owner, Copilot | DEMO.4 full-screen layout | Owner asked whether the site is one page and said stories would read better using the whole screen. `/archive` and `/articles/{id}` are the older plain pages, and neither uses the full screen. The owner chose a full-screen reader on `/stories`; evidence is on DEMO.4. `make rec-test` passed again (71 Python, reader Go packages, 26 JavaScript); `git diff --check` clean. The reader was restarted to serve it. |
| 2026-11-24 | Owner, Copilot | DEMO.4 light/dark switch | Owner asked for a dark version as a switchable theme and chose to start from the computer's setting. CSS variables and a masthead toggle; no new dependency, and the page's security policy is unchanged (no inline script or style). Evidence is on DEMO.4; `git diff --check` clean. The reader was restarted to serve it. |
| 2026-11-24 | Owner, Copilot | DEMO.4 premium grid redesign | Owner asked for a premium reading space like Apple, Airbnb and Medium, and a grid wherever a story has little text. `/stories` became a grid front page with a full-screen reading view and a related-stories grid; evidence is on DEMO.4. An independent code review found three problems (a blank page after marking every story not interested, the scroll position after "See all related stories", and focus after a not-interested choice); all are fixed and rechecked. `make rec-test` (71 Python, reader Go packages, 32 JavaScript) passed and `git diff --check` is clean. The reader was restarted to serve it. Nothing committed. |
| 2026-11-25 | Copilot | DOC.2 claimed | Auditing documentation and comments against current source. Collector operations and reader/model documentation are separate, non-overlapping work areas; shared product summaries and the roadmap stay with the coordinating agent. No application behavior, production operation, release gate, contract or deadline change. |
| 2026-11-25 | Copilot | DOC.2 done | Updated current collector/reader/classifier documentation and misleading comments/help copy across 61 files. Source-backed corrections include C1 backfill eligibility, local versus production MongoDB setup, manual snapshots, browser-storage lifetimes, the 06:00 India-time day boundary and AI-label provenance. Offline documentation, syntax/format, source-preservation and whitespace checks passed (evidence on DOC.2). Historical artifacts/measurements and notebook code/outputs remain intact; no collection/ranking logic, configuration values, acceptance threshold, deadline or deployment changed. |
| 2026-11-27 | Owner, Copilot | ML4.7 claimed | Owner approved promoting the pooled V4 classifier and relabelling existing articles (D19). Claimed the sidecar adapter, image and compose changes, the relabel job, and the documents that called V4 unpromoted. The model file, `DEPLOY_ENABLED` and the production relabel run stay with the owner. |
| 2026-11-27 | Copilot | ML4.7 repository work done; deployment open | Sidecar, image, compose, relabel job and documents updated; evidence on ML4.7. The Docker image was not built and the bundle is not on the production volume, so nothing is deployed. Human validation stays not met. |
| 2026-11-27 | Owner | D21 restructure | Chose the R plan in this repository on `v4`, keeping history. Backups go to a private `news-bot-archive` and to the laptop. A Python `server/` with a separate read-only MCP program; React with Biome; Helm on k3s plus Docker Compose; one label dataset with no per-row origin tags and one README sentence on how the labels were made; Python 3.12; open tasks folded into R. |
| 2026-11-27 | Copilot | R0 claimed | Backups first, then the `main` merge, the checks and the `v4` push. Evidence on R0. |
| 2026-11-27 | Copilot | R0 done | Both backups verified; `main` merged into `v4`; local checks and manual CI run 45983035576 passed; `v4` pushed. Nothing was published or deployed. Next: R1, on the owner's go-ahead. |

## 10. V2 backlog (not designed)

Requirements V2-1 to V2-6 are listed in §2. Known constraints:

- V2 builds on the stored V1 daily edition (C9) and saved items (C8). Do not fork the selection logic.
- English only. No paid service may be required; evaluate on-device iOS speech recognition and synthesis first.
- Listening times are examples, not fixed limits: about 5 min in the bath and 15–30 min while driving. How to estimate and meet the requested duration is still open.
- Spoken commands cover playback, saving stories and exploring topics. Their feedback becomes R6 signals.
- Course-informed candidates for a future recommender/classifier iteration are documented in [recommender.md](recommender.md). They are research ideas, not approved scope; create owner-approved roadmap tasks with measurable criteria before implementation.
