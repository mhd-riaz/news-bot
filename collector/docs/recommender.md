# AFTERLINE — content-based news archive recommendations

[Verified delivery results, measurements and remaining limitations](recommender-results.md).

[Client and architecture review briefing, including the demonstration walkthrough](recommender-client-review.md).

AFTERLINE recommends archived articles using their content and the articles a reader explicitly selects. It does **not** predict preferences learned from historical users: the original `read_events` collection was empty and had no user identifiers.

The reading default is **TF-IDF**, selected after the separate relevance comparisons. SVD and the trained Neural lens remain available. The model service advertises `default_method`; a request that explicitly selects a lens is never overridden.

## Quick start

Requirements: Go **1.27+**, Python **3.12**, `uv`, and access to the existing MongoDB `news` database. Node is needed only for the optional JavaScript unit checks, not for serving the UI.

From `collector/`:

```bash
make rec-setup
# Copy .env-example to .env, then configure the SAME Mongo endpoint as MongoDB MCP.
# .env is ignored by git. Do not print or commit credentials.
make rec-inspect
```

Check the count and collection dates before exporting. A local Mongo instance and an SSH-forwarded or remote instance may contain different copies of `news`; a successful connection is not proof that it is the correct corpus. Both Python and Go read `NEWS_MONGO_URI` and `NEWS_MONGO_DATABASE` from `collector/.env`, with process environment taking precedence. `NEWS_ENV_FILE` can select another dotenv file.

If the trained local `stories-002` artifacts are present, start these in **two terminals**:

```bash
make rec-serve REC_ID=stories-002     # http://127.0.0.1:8001, private vector service
```

```bash
make reader                        # http://127.0.0.1:8090/stories
```

The development reader binds loopback and has authentication disabled in `configs/reader.yaml`. Do not expose it publicly in this configuration. Existing authentication is available through the usual `NEWS_AUTH_*` settings; production configuration rejects disabled authentication. The Python ranking service is loopback-only when started with `newsrec serve`. For managed serving, use the existing Gunicorn dependency, one worker initially, and set `NEWSREC_MODEL_DIR` to the artifact directory:

```bash
cd ml-v2
NEWSREC_MODEL_DIR="$PWD/artifacts/recommender/stories-002" \
  uv run --no-sync gunicorn --bind 127.0.0.1:8001 --workers 1 --threads 4 \
  'newsrec.api:create_app()'
```

An optional `NEWS_RECOMMENDER_API_KEY`, read from the environment or the shared dotenv file, protects the private model endpoints. Go sends it as `X-Recommender-Key`. Never put this key into browser code. `NEWS_RECOMMENDER_ENDPOINT` changes the Go client's destination; it is operator configuration, never request input.

`cmd/reader` is a separate, read-only entry point: **no migration, seeding, scheduler, scraping, classification, retention deletion or telemetry writes**. Do not substitute `make run` or `make up`: the original collector intentionally writes on startup.

The reader caps idle Mongo data connections at **60 seconds**, retiring them before the observed network idle disconnects instead of adding silent retries. Configure `mongo.max_connection_idle_time` or `NEWS_MONGO_MAX_CONNECTION_IDLE_TIME` for a different network. Zero preserves an existing URI `maxIdleTimeMS` or the driver's default; the collector's default remains zero. This bounds stale pooled sockets, not database/network availability. Monitor readiness failures and reconnect latency after long pauses.

## Freeze and train a new edition

Use a new ID; preparation refuses to overwrite a snapshot:

```bash
make rec-prepare REC_ID=stories-003 CUT=2026-10-22T18:00:00+00:00
make rec-baseline REC_ID=stories-003
make rec-train REC_ID=stories-003
make rec-benchmark REC_ID=stories-003
make rec-serve REC_ID=stories-003
```

Choose a cutoff in the past, including its timezone. The explicit example above reproduces the initial edition's collection boundary; use a different past timestamp for a newer edition. The corpus must still exist at the configured endpoint.

Preparation scans a stable `_id`-ordered cursor, uses a seeded reservoir of at most 30,000 candidates, and keeps up to 20,000 admitted articles. It never loads an unbounded full corpus into memory. Mongo projects capped text and needed metadata only; category labels are deliberately absent from the query. The frozen file, not a changing live query, is the reproducibility boundary. Previously enriched article content can change on the live collector, so re-exporting later is not promised to produce the same bytes.

`--recent-days N` makes a fresh-first snapshot: every article collected in the last N days is a candidate (the newest first if the window exceeds the candidate budget) and is kept ahead of the older reservoir sample. `make demo-refresh` builds one from the configured database with N = 7, 40,000 candidates and a 30,000 limit (about 7 minutes and 1.4 GB peak memory on the owner's laptop), records its ID in `artifacts/recommender/LATEST_DEMO`, and `make demo-serve` serves it. Each row records `source_id`, the source's `domains`, and `date_source`/`date_verified`: stored C1 provenance when present, otherwise a publish date that differs from the collection time counts as feed-provided.

Cleaning reuses the existing project cleaner, boilerplate discovery, admission rules and recurring-template guard. An actual script/language check rejects clearly non-English content; the source's `language=en` is not trusted. Language detection and article-format rules are imperfect and their rejections are recorded.

Input is **headline + first 250 cleaned body words**, falling back to summary, then headline. It removes a repeated leading headline rather than adding it twice. Real headline-only items survive. Names, places and numbers are not deliberately scrubbed from recommendation features. Display text is a stored summary, a labelled excerpt, or a headline-only state—never a generated summary.

### Methods

1. **TF-IDF baseline:** word unigrams/bigrams, at most 25,000 terms, normalized cosine similarity.
2. **SVD control:** 256-dimensional latent semantic features, normalized cosine similarity.
3. **Neural:** standardized SVD features → Gaussian input noise → Dense 128 GELU → **64-dimensional bottleneck** → Dense 128 GELU → linear reconstruction. Keras/Adam learns to reconstruct clean inputs using MSE and early stopping. The nonlinear network has approximately **82,500 parameters** at 256 input dimensions.

The neural encoder is trained locally with TensorFlow, not downloaded as an already-trained recommender. It is an unsupervised representation model, not a collaborative recommender. Categories, topic-classifier outputs, URLs, publisher names and article IDs never enter the training features or loss.

Conservative duplicate grouping combines normalized URL/content-hash matches with high-cosine candidates and the existing recurring-template time guard. Near-duplicate search uses 64-row batches, never an all-article similarity matrix. It is still quadratic offline work on this bounded cohort; introduce time-window/candidate blocking before scaling it to the full corpus. It can miss paraphrased duplicates; identical titles alone are not sufficient evidence.

The chronological 80% collection-time boundary selects training groups wholly before it. Groups crossing the boundary stay in validation. TF-IDF, SVD and scaling fit on training only; validation is for reconstruction stopping, not category supervision. The existing classifier's closed test labels are never used.

Eight MiniBatchKMeans groups over latent representations provide keyword-labelled topic circles and representative cold-start articles. These are unsupervised content groups, not verified editorial categories. Their labels are top words from real text, not generated topic claims.

## Artifacts and serving

All edition outputs stay under the ignored `ml-v2/artifacts/recommender/<id>/`:

| File | Purpose |
| --- | --- |
| `documents.jsonl`, `manifest.json`, `boilerplate.json` | Immutable prepared cohort, IDs, date coverage, input policy and content digest |
| `groups.json`, `train.npy`, `baseline.json` | Duplicate groups, split assignment and baseline settings |
| `preprocessing.joblib`, `tfidf.npz`, `svd.npy` | Fitted preprocessing and non-neural representations |
| `autoencoder.keras`, `encoder.keras`, `latent_center.npy` | Reusable trained network and centering |
| `neural.npy`, `assignments.npy`, `topics.json`, `clusters.joblib` | Latent vectors, content groups and cold-start representatives |
| `training.json` | Versions, seeds, architecture, losses, timings, code/artifact hashes |
| `benchmark.json`, `evaluation-cases.json`, `judgements.jsonl` | Measured retrieval comparison and frozen blind judgement pool |
| `api-latency.json` | Actual Go/Python/Mongo end-to-end latency and exclusion checks |
| `relevance.json` | Independent relevance results, only after completed judgements |
| `ai-grades.json`, `ai-judgements.jsonl`, `relevance-ai-assisted.json` | Separate, explicitly AI-assisted assessment; never human ground truth |
| `rehearsal.json` | Recorded clean restart, dependency outage/recovery and bounded idle-pool checks |

Only load trusted local artifacts; joblib/pickle is not an interchange format for untrusted uploads. There is no artifact-upload or user-supplied-path API.

The vector service verifies hashes and ID/matrix alignment at startup. It performs one on-demand cosine query against precomputed vectors; it does not import TensorFlow for serving. The Go service hydrates a ranked page in **one bounded Mongo query**, preserving score order and explicitly reporting records that have disappeared. It never fabricates a successful feed if the database or model is unavailable.

New Mongo articles become recommendable only after a new explicit export/index build. A snapshot of 20,000 is not presented as the full live Mongo corpus. Go hydrates current original metadata, while snippets/features remain from the named snapshot.

At 64 dimensions, 20,000 float32 neural vectors need about **5.1 MB**; even 165,000 would be approximately 42 MB before metadata. Full-corpus preparation and latency are not certified by this MVP.

## APIs

```text
GET  /health/live
GET  /health/ready                         Mongo + recommender readiness
GET  /api/v1/recommendations/meta
POST /api/v1/recommendations
GET  /api/v1/articles
GET  /api/v1/articles/{id}
GET  /stories
GET  /archive                              legacy read-only feed
```

Example request:

```bash
curl -sS http://127.0.0.1:8090/api/v1/recommendations \
  -H 'Content-Type: application/json' \
  -d '{"method":"neural","limit":5}'
```

Use a real returned ID as `seed_id` for related articles. Personalized requests accept `liked`, `disliked` and `viewed` arrays; `topic` is an optional content-group ID and `method` is `neural`, `tfidf` or `svd`. `window` is optional: `fresh` (verified publication date, 0–30 days old at request time), `yesterday` (verified and published on the latest edition day in Asia/Kolkata, which opens at 06:00) or `archive` (everything not fresh). `domains` keeps only sources carrying one of up to eight tags. The maximum is 30 results, 50 positive/50 negative IDs and 2,000 viewed IDs per request, within a 128 KiB request bound. Unknown seed/interests produce an explicit 404, malformed input a 400, and downstream outages a 503.

Responses include article metadata, labelled snapshot text, cosine score, a factual matching reason, method, snapshot ID, exhaustion state, unavailable IDs, the window, and per item `date_verified` and `fresh`; a `yesterday` response also names its `edition_date`. Metadata adds window counts, the edition date and time zone, and domain counts. Similarity scores are **not probabilities of liking or factual confidence**.

The positive profile combines explicit selected-article vectors; negative choices penalize similar content. Related mode instead anchors on the opened article alone, so unrelated saved interests cannot dilute what “related” means; selected interests are still excluded from results. Self, selected items, known duplicate groups and newly requested viewed items are excluded. Publisher diversity is applied without relaxing duplicate/history exclusions. With no likes, a `fresh` or `yesterday` window reads newest first; a `yesterday` edition ranks every eligible story rather than only positively related ones. This is a simple content profile, not retraining a preference model.

## Reader journeys and boundaries

- The front page is a grid: a full-width lead story, then three columns on wide screens, two on medium screens and one on phones. Each tile shows the picture (or a coloured panel with the source name), the source, date, headline and up to three lines of stored text, plus a ☆ to save it. The first page holds 25 stories; **More stories** adds 24 at a time, leaving out stories already on the page without marking them viewed. The view switch, saved stories and theme sit in a sticky top bar; on wide screens the thread buttons, Professional focus and lens sit in a second sticky bar. The introduction and snapshot numbers follow below the stories.
- Opening a tile opens a full-screen reading view: a 720-pixel serif column with the headline, picture, stored text, the link to the original, **More like this**, **Not interested** and **Save** with a note, and then six related stories as a grid with **See all related stories**. ← and →, a swipe or the arrow buttons move between stories; Esc, **All stories** or the browser Back button return to the grid at the same place. Only opening a story marks it viewed. A like or not-interested choice does not reshuffle the grid while you read: closing the story removes not-interested stories (if none are left, the page says so), and **Update for your new choices** re-ranks the page.
- Light and dark themes. The reader starts in the computer's setting, using CSS `prefers-color-scheme`, so no script is needed for that. The **Dark theme** toggle in the masthead overrides it, and the choice is kept in this browser with the other settings.
- Fresh, Yesterday and Archive views; Fresh is the default. Related reading ignores the view, so older background can surface beside today's news.
- Professional focus limits every view to sources tagged ai, data-science, software or technology; the setting is kept in this browser.
- Yesterday is one fixed page of up to 10 stories: viewing a story does not remove it from the edition.
- Save keeps a story with an optional note (up to 2,000 characters) in this browser across snapshots; it is not an account feature yet.
- Explore content circles immediately, or select 3–5 real articles to initialize interests; fewer/skip also work.
- Read one story comfortably; no autoplay or countdown. Buttons, arrows and horizontal touch gestures support navigation.
- “More like this” and “Not interested” change subsequent retrieval. Next records a view, not a dislike.
- Related uses the opened article as a seed. A direct `?article=<indexed-id>` link is supported.
- Previous navigates the currently loaded trail even though newly fetched feeds exclude viewed items.
- Change the lens to compare methods on the same content corpus.
- Reset clears only this browser's snapshot-local profile. No accounts or server-side user history are created.
- Storage failures, missing text/images, stale IDs, empty/exhausted feeds and service errors are visible.

Browser-local limits are deliberate: 50 positive, 50 negative and the last 2,000 viewed items. Very old views can reappear after that ceiling. Server-side history and cross-device accounts are future work, not hidden features.

Publication timestamps are collector-stored values. Some were substituted from collection time; equality is conservatively labelled “Collected,” and a date counts as verified only when the feed or page supplied it. Unverified dates are labelled and never count as fresh. Dates are absolute and shown in the edition time zone (Asia/Kolkata). HTTP(S) original links and HTTPS images are allowed; publisher availability, paywalls, hotlink policies and usage rights are not guaranteed. Every image has a text-first fallback.

Scraped values are escaped by Go templates or assigned with `textContent`, never used as HTML. JavaScript/styles are same-origin under CSP; only story images allow external HTTPS. Original links use `noopener noreferrer`, images suppress referrers, and there is no server-side arbitrary-URL image proxy. Profile requests are read-only, bounded and same-origin; no permissive CORS is enabled.

## Evaluation

```bash
make rec-benchmark REC_ID=stories-003
# Independently grade every candidate in:
# ml-v2/artifacts/recommender/stories-003/judgements.jsonl
#
# grade 0 = unrelated, 1 = loosely related, 2 = useful recommendation
cd ml-v2
uv run --no-sync newsrec score --id stories-003 \
  --judgements artifacts/recommender/stories-003/judgements.jsonl
```

The default 40 fixed cases include 30 article queries (with a headline-only slice when available) and 10 synthetic multi-interest profiles. All three methods use the **same cases and candidate corpus**. The blinded sheet pools top-five candidates without method names. It never substitutes assistant judgements for independent human ground truth. Keep the model/retrieval frozen while judging; scoring refuses mismatched snapshots or changed model/retrieval artifacts. The benchmark refuses to overwrite an existing sheet.

For an explicitly limited manual pilot, repeat `--case <case-id>` when scoring. Only those complete cases are scored, their IDs and the total evaluation size are reported, and results go to `relevance-selected.json` rather than replacing the full report. This is not a claim that the remaining cases passed.

### Separate AI-assisted assessment

The user also approved a method-blinded AI assessment. Its labels are **not human ground truth**, are not copied into `judgements.jsonl`, and carry `label_source: "ai-assisted"` in a separate sheet. Scoring requires the matching source explicitly:

```bash
cd ml-v2
uv run --no-sync newsrec score --id stories-002 \
  --judgements artifacts/recommender/stories-002/ai-judgements.jsonl \
  --label-source ai-assisted
```

Those results go to `relevance-ai-assisted.json`; the human pilot keeps its own result file. The scorer rejects mixed or mismatched label sources. All results record the sheet digest and per-case scores. An AI-assisted completion does not certify the original human-relevance acceptance target.

Report useful Precision@5 and graded **pooled** nDCG@5. Pooled judgements are not exhaustive corpus relevance, so do not report Recall@K. The target from the approved plan is held-out mean Precision@5 ≥ 0.60, not an achievement until independently measured. Reconstruction loss does not establish recommendation quality.

Automated results include warm retrieval p50/p95 over at least 100 queries/method and publisher diversity. Go/Mongo/network latency is measured separately. The optional old-training-label category-agreement proxy uses only overlapping **old train** labels and a common restricted labelled candidate pool; it is explicitly **not** human recommendation quality and is not a historical-click metric. Do not tune against the closed classifier test split.

With both services running, measure the real API on the same frozen cases:

```bash
cd ml-v2
uv run --no-sync newsrec measure --id stories-002
```

This performs three warm-up and 100 measured requests per method, including the same two viewed candidates for each frozen case across methods. It verifies edition/method consistency and self/duplicate/selected/viewed exclusions and writes `api-latency.json`. The acceptance target is warm end-to-end p95 under 500 ms on the selected cohort—not just a fast in-memory dot product.

## Course-informed next-model candidates

These are research candidates for a future recommender or classifier iteration, not approved scope. Do not start implementation or change acceptance thresholds from this list alone. Add approved work to the roadmap with an owner, dependencies and measurable exit criteria.

### High-fit experiments

1. **Validate content groups.** Compare the existing eight-group MiniBatchKMeans result with a small range of cluster counts using WCSS and silhouette score, then review representative articles and topic coherence. Keep distant articles unassigned. DBSCAN is an optional comparison if it can be evaluated on the same features and corpus; agglomerative clustering is a later option if hierarchical topics become a product need.
2. **Add simple recommendation baselines.** Measure a popularity baseline and the existing TF-IDF content baseline on identical temporal splits and candidate exclusions. Keep collaborative signals such as co-likes as an additional feature, not the sole recommender: the invited-reader group is small and interaction history is sparse.
3. **Evaluate association rules.** The roadmap already plans FP-Growth for article and reader baskets in M5.2. Report support, confidence and lift, and measure whether rule boosts improve held-out recommendation quality; do not treat rules as a replacement for the existing baselines.
4. **Compare neural models fairly.** The planned two-tower model and current autoencoder already use neural-network methods. Any tuning of architecture, dropout, batch normalization, initialization or optimization must use development data only, compare against TF-IDF/SVD, and preserve the sealed human test cases. For the V4 classifier, the trainer in [`ml-v4`](../ml-v4/README.md) (`make ml4-train`, roadmap ML4.3/ML4.6) compares a small Keras MLP, LinearSVC and sentence-embedding models on identical stratified folds. The owner confirmed on 22 Nov that all old and new classifier labels are AI-generated (D16); the pooled local candidate reports AI-label agreement only, not human-validated accuracy. Historical evaluation articles remain excluded, human validation is not met, and no production promotion is approved.

### Supporting and lower-priority topics

- **SVD and other dimensionality reduction:** SVD is already a ranking method. Use PCA only as a measured alternative; use t-SNE for visual analysis, never as the production representation.
- **Distance metrics:** cosine similarity remains the baseline. Compare another metric only as a controlled experiment with the same normalized vectors and evaluation cases.
- **Exploration:** a small, bounded exploration allocation (for example, an epsilon-greedy policy) could help readers discover unfamiliar topics. Treat it as a product experiment with explicit limits and feedback measurement, not an automatic model change.
- **Sequence models:** LSTM/GRU models or time-series forecasting may be revisited if we collect enough reliable sequential reader feedback or have a specific trend-forecasting need. Current reader volume is too small to justify them as the next recommender.
- **General reinforcement learning:** MDP, Q-learning, DQN and policy-gradient systems are not a fit for the current data volume. Do not prioritize them over offline baselines and evaluation.

For every comparison, freeze the corpus and model inputs, use a chronological split, and report the existing human relevance metrics separately from AI-assisted assessments. Reconstruction loss, clustering scores and category agreement are diagnostics, not substitutes for recommendation-quality evidence. Follow the dependency and reproducibility rules in the roadmap.

## Checks

```bash
make rec-test
go test ./...
go vet ./cmd/reader ./internal/recommendation ./internal/handler ./internal/web
cd ml-v2
uv run --no-sync pytest --cov=newsrec --cov-branch
```

Unit tests use isolated synthetic artifacts, fake repositories and mocked HTTP/database inputs. The one-epoch Keras round-trip check saves/reloads a tiny synthetic encoder and verifies its vectors. It is a test—not the real trained edition. Browser verification must use the running reader, real Mongo data and real trained representations, including mobile, keyboard, missing-content and outage cases.

## Viva explanation

“We have article content but no usable user interaction history, so we use content-based recommendation. TF-IDF cosine is our transparent baseline. SVD makes its sparse features manageable, and an unsupervised TensorFlow denoising autoencoder learns a nonlinear 64-dimensional representation. K-means exposes content groups for exploration. A reader's selected articles form an interest profile; cosine retrieval finds similar unseen articles while filtering duplicate groups. The Go app joins ranked IDs back to MongoDB and serves a Stories-style archive reader. We compare methods on the same cases, measure latency and diversity, and require independent relevance judgements rather than treating reconstruction loss as recommendation success.”
