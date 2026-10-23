# AFTERLINE: client and architecture review briefing

**Review date:** 23 October 2026  
**Audience:** client stakeholders, solution architect and engineering reviewers  
**Delivered edition:** `stories-002`  
**Current application-code checkpoint inspected:** `c06fdf4`  
**Maturity:** working, integrated MVP for pilot review; not production acceptance

## 1. Executive summary

We extended an existing news-collection and topic-classification project into a **content-based news archive recommendation system** with a focused, Stories-inspired reading interface.

The system works with real MongoDB articles, not a demonstration fixture. It recommends related articles and adapts to articles a reader explicitly selects. It includes three comparable retrieval methods: TF-IDF, SVD and a locally trained TensorFlow/Keras autoencoder.

**TF-IDF is the current reading default because it led the available relevance comparisons.** The neural model remains trained, integrated and selectable; its learned representations also support the content clusters used for exploration.

The main engineering outcomes are:

- An end-to-end path from existing MongoDB data to trained representations, recommendation APIs and the reader.
- A versioned, reproducible 20,000-article edition with original records preserved.
- A genuinely trained unsupervised neural representation model, alongside simpler controls.
- Explicit feedback, cold start, duplicate/history exclusions and honest archive presentation.
- Measured local retrieval performance, automated tests, browser checks and a verified private backup.

The main qualification is equally important: **technical integration is demonstrated, but full human-validated recommendation quality is not yet signed off.** The broader relevance assessment is AI-assisted and is kept separate from the small human pilot.

## 2. Business problem and intended value

The previous project answered: "Which topic does this article belong to?"

The new project answers:

1. "What should I read next after this article?"
2. "What articles match the interests I have selected?"
3. "Where can a new reader start without an existing profile?"

The intended value is easier discovery and reuse of an existing archive through a calmer, focused reading experience. Improvements in engagement, retention or business conversion have **not** been measured and are not claimed.

### What this is not

It is not a live breaking-news service, social network, generative news writer, fact-checking system or collaborative recommender trained on historical reader behavior.

## 3. What was reused, changed and built

| Area | Existing foundation reused | New or modified work |
| --- | --- | --- |
| News acquisition | Go RSS/Atom collector and article enrichment | Collection logic preserved; not started by the new reader |
| Data | Existing MongoDB `news` corpus and stable article IDs | Read-only export, language checks and frozen recommendation edition |
| Preparation | Existing text cleaning, boilerplate discovery and admission patterns | Consistent recommendation input and bounded cohort preparation |
| Duplicate handling | Existing identity/hash concepts and recurring-template guard | Conservative story grouping and result exclusions |
| ML tooling | Python, scikit-learn, NumPy, SciPy, PyArrow and existing project packaging | TF-IDF retrieval, SVD control, TensorFlow autoencoder and learned content clusters |
| API infrastructure | Go HTTP/service/repository patterns and Flask serving conventions | Recommendation service, metadata contract and one-query article hydration |
| Reader | Go templates, native CSS and plain JavaScript | AFTERLINE story interface, onboarding, feedback, local profile and navigation |
| Reliability | Existing health, logging, authentication and configuration patterns | Read-only entry point, dependency readiness and native idle-connection retirement |
| Delivery | Existing test runners and build tools | Recommendation tests, evaluation artifacts, review documentation and verified backup |

The original supervised topic classifier is preserved. Its classification scores are not reused as evidence of recommendation quality, and its category labels do not train the new unsupervised model.

## 4. Dataset actually used

The live database can grow independently of the delivered index. The edition, rather than today's changing database count, is the reproducibility boundary.

| Measure | Delivered edition |
| --- | ---: |
| Original records scanned before cutoff | 165,624 |
| Collection cutoff | 22 October 2026, 18:00 UTC |
| Seeded reservoir candidates | 30,000 |
| Prepared/indexed articles | 20,000 |
| Publishers represented | 40 |
| Body-backed model inputs | 19,391 |
| Summary-backed model inputs | 494 |
| Headline-only model inputs | 115 |
| Stored images available | 12,237 |
| Conservative story groups | 19,967 |
| Representation training / validation | 16,000 / 4,000 |

Stored publication dates span October 2007 to October 2026. The UI therefore presents the collection as an archive, with absolute dates, not as today's news.

### Data issues addressed

- Some records marked `language=en` actually contained Hindi or other non-English text. Preparation checks the text instead of trusting that metadata.
- Articles have different amounts of available content. All methods use the same fallback recipe.
- Publisher furniture, repeated leads and encoding problems can pollute text features. Existing cleaning is reused, but it is not assumed to solve every extraction problem.
- A non-empty body does not certify a complete publisher article.
- Some publication dates were substituted from collection time by the original collector. Equality is conservatively labelled "Collected"; publisher-date provenance is not uniformly verified.
- Identical titles are not automatically duplicates: recurring features can reuse a headline.

A connection mismatch was also detected: the initial local endpoint contained a smaller August-only archive. The correct larger database was configured and verified before building the final edition.

## 5. Architecture

### C4 level 1: system context

```text
[Reader / browser] ----> [AFTERLINE recommendation system]
                               |
                               +---- reads ----> [Existing news MongoDB]

[Reader / browser] ---- images / original links ----> [Publisher sites and CDNs]
```

The original collector remains an independent producer of the MongoDB corpus. The recommendation reader is a consumer, not a replacement collector.

### C4 level 2: runtime containers and data stores

```text
OFFLINE
[Existing MongoDB]
       |
       v
[Python preparation and training CLI]
       |
       v
[Versioned local artifacts: snapshot, models, matrices, clusters, hashes]

ONLINE
[Browser: Go-rendered HTML + CSS + JavaScript]
       |
       v
[Go read-only reader / API :8090] ---- batch article reads ----> [Existing MongoDB]
       |
       +---- private HTTP ----> [Python Flask/Gunicorn ranker :8001]
                                      |
                                      +---- reads ----> [Versioned artifacts]
```

These are separate processes and responsibilities. A browser request does not initiate training, scraping or a migration.

### Why this separation

- Go retains the existing application boundary and ownership of MongoDB access.
- Python retains the scientific/ML ecosystem and numerical retrieval.
- Heavy preparation happens offline.
- The online service reuses saved representations; it does not import TensorFlow to serve each recommendation.
- Same-origin browser APIs avoid an additional public ML API and cross-origin configuration.

There is no added vector database, cache cluster, message broker, frontend framework or external LLM dependency in the recommendation path.

## 6. Technology choices and rationale

| Technology | Role | Why it was selected |
| --- | --- | --- |
| Go 1.27+ | Reader, public API and MongoDB hydration | Reuses the existing backend and operational patterns |
| MongoDB | Original article source of truth | Reuses the existing dataset and article identifiers |
| Python 3.12 | Preparation, training and numerical retrieval | Fits the existing ML project |
| scikit-learn | TF-IDF, SVD, normalization and MiniBatchKMeans | Existing, focused implementations rather than custom algorithms |
| TensorFlow 2.21 / Keras 3.15.1 | Denoising autoencoder training | Delivers meaningful local neural learning within the project constraints |
| NumPy / SciPy | Dense/sparse representations and on-demand similarity | Adequate for the bounded cohort without another retrieval service |
| Flask / Gunicorn | Private representation service | Reuses the project's Python serving approach |
| Go templates / native CSS / JavaScript | Stories-inspired frontend | No new bundler, Node runtime or framework migration |
| pytest / Go tests / native Node tests | Verification | Extends existing tooling; Node is not needed to run the reader |

Training was demonstrated on the inspected Apple M1 Pro/32 GB machine using CPU. GPU acceleration is not a runtime requirement for this edition.

## 7. Offline preparation and training

The offline sequence is:

1. Select a past collection cutoff.
2. Scan MongoDB in stable ID order with bounded field projections and cursor batches.
3. Reservoir-sample candidate records with a fixed seed.
4. Clean title, summary and body separately.
5. Apply language and article-admission checks.
6. Assemble the consistent model input.
7. Freeze article IDs, prepared text, metadata and provenance.
8. Group known/exact and conservative near-duplicate stories.
9. Establish a chronological, story-group-aware training boundary.
10. Fit TF-IDF, SVD and scaling using training data only.
11. Train the autoencoder, produce centered/normalized vectors and build content clusters.
12. Persist all artifacts and verify their ID alignment and hashes.

### Input recipe

```text
Headline + first 250 cleaned body words
             |
             +-- no usable body: use cleaned stored summary
             |
             +-- neither available: headline only
```

The same recipe is used for all three comparison methods. Names, places and numbers remain useful article content. Category labels, source IDs, publisher names, URLs and image data are not model features.

The display recipe is separate: prefer a stored summary, otherwise show a clearly labelled excerpt or headline-only state. No generative summarization is used.

## 8. The three recommendation representations

| Method | Representation | Purpose |
| --- | --- | --- |
| TF-IDF | Sparse word unigrams/bigrams; vocabulary capped at 25,000 | Transparent non-neural baseline and current reading default |
| SVD | 256-dimensional latent semantic representation | Control for the benefit of dimensionality reduction alone |
| Neural | 64-dimensional autoencoder bottleneck | Locally learned nonlinear article representation |

### What the neural model actually learns

```text
256 standardized SVD features
  -> Gaussian noise, standard deviation 0.05
  -> Dense 128, GELU
  -> Dense 64, bottleneck
  -> Dense 128, GELU
  -> Dense 256, linear reconstruction
```

The network contains **82,496 parameters** and uses Adam with mean squared reconstruction error. Training includes batching, fixed seeds, deterministic CPU settings and validation-based early stopping. The delivered run used 30 epochs.

The input is its own clean reconstruction target. This is unsupervised learning, not classification or click prediction.

Recorded baseline preparation took 80.37 seconds; the recorded neural training/clustering stage took 7.85 seconds. The latter is not total export/preparation time.

Final validation reconstruction MSE was 0.4165. That value is an optimization diagnostic, not recommendation accuracy.

Eight MiniBatchKMeans groups over learned vectors support the topic circles and representative cold-start articles. Their labels are derived from real top terms and are not a verified editorial taxonomy.

## 9. How recommendation behavior works

### Related reading

The opened article is the positive query. Unrelated saved interests do not dilute that query.

### Interest-based reading

The selected positive article vectors are averaged and normalized into a content profile. Explicit negative choices adjust ranking:

```text
score(candidate)
  = cosine(candidate, positive profile)
    - 0.2 * cosine(candidate, negative profile)
```

The second term applies only when negative choices exist. This is a simple content adjustment, not a calibrated model of user preference.

### Cold start

Readers without interests can explore representative articles from learned content groups. The starting experience does not pretend to know their preferences or popularity trends.

### Exclusions and diversity

The retriever excludes the current article, selected interests, explicit negative items, supplied viewed history and their known duplicate groups. At most one item from a known duplicate group enters a result page.

A publisher cap encourages variety where candidates permit it. Only that cap is relaxed to fill a page; duplicate/history exclusions are not relaxed.

Duplicate detection is conservative, not a guarantee that all paraphrased copies are recognized. The current scoring also contains no freshness or breaking-news boost.

## 10. What happens during one online request

1. The browser sends a selected method, optional seed/interests, viewed IDs and result limit.
2. Go validates the bounded request and calls the private ranker.
3. Python validates IDs against the named edition.
4. The selected matrix produces on-demand similarity scores.
5. Exclusion, topic-group and publisher-diversity rules select article IDs.
6. Go hydrates those IDs in **one bounded MongoDB query**, avoiding per-result database requests.
7. Go preserves ranking order and returns original article metadata plus the labelled snapshot snippet and matching reason.
8. The browser renders fetched text as text, not executable HTML.

If records have disappeared from MongoDB, unavailable IDs are explicit. If all ranked articles are missing, the request fails rather than returning a fabricated successful feed.

Features and snippets are frozen to an edition; original metadata is read live. That distinction matters if an existing article changes after export.

## 11. Delivered reader experience

- Horizontal content-group circles and immediate archive exploration.
- Selection of a few real articles to initialize interests; onboarding can be skipped.
- Focused story cards with headline, short text, source, absolute date and original-source link.
- Real publisher imagery where available and an intentional text-first design otherwise.
- Interested and not-interested actions affecting subsequent retrieval.
- Previous/next controls, keyboard navigation and touch-pointer handling.
- Position/progress indicators without a countdown or forced advancement.
- Explicit loading, error/retry, unavailable-content, empty and exhausted-feed states.
- Method switching between TF-IDF, SVD and Neural.
- Local profile reset and visible storage-failure handling.
- A legacy archive reader retained as an alternative.

The viewer is not claimed to hold every complete original article. It presents the available summary/excerpt/headline honestly, with the original reporting one click away.

Profiles are browser-local and edition-specific: up to 50 positive choices, 50 negative choices and the last 2,000 viewed IDs. Previous navigation can revisit the loaded trail even though new retrieval excludes supplied history.

## 12. API contract and boundaries

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/recommendations/meta` | Edition, coverage, methods, default method and content groups |
| `POST /api/v1/recommendations` | Related, interest-based or exploratory recommendations |
| `GET /api/v1/articles` | Existing article listing |
| `GET /api/v1/articles/{id}` | Original stored article detail |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | MongoDB and ranking dependency readiness |
| `GET /stories` | AFTERLINE reader |
| `GET /archive` | Legacy reader |

Recommendation requests are limited to 30 results, 50 positive IDs, 50 negative IDs and 2,000 viewed IDs within a 128 KiB payload bound.

Responses identify the method and snapshot, matching reason, labelled text, exhaustion state and unavailable IDs. Invalid input returns 400; an unindexed seed/interest returns 404; service/database failures are surfaced as 503.

Similarity scores are not probabilities of liking, editorial confidence or factual reliability.

## 13. Evaluation: what the evidence says

Evaluation compared the same fixed 40 cases and indexed corpus across all methods: 30 related-article queries and ten explicit multi-interest profiles.

### Human pilot: two cases

The user graded 20 blinded candidate pairs:

| Method | Useful Precision@5 | Pooled nDCG@5 |
| --- | ---: | ---: |
| TF-IDF | 0.80 | 0.9349 |
| SVD | 0.70 | 0.6596 |
| Neural | 0.60 | 0.5755 |

This is a small pilot, not broad human validation.

### Separate AI-assisted assessment: all 40 cases

A user-approved blinded AI pass rated 437 candidate pairs without seeing methods, ranks, scores or prior human grades:

| Method | Useful Precision@5 | Pooled nDCG@5 |
| --- | ---: | ---: |
| TF-IDF | 0.565 | 0.8526 |
| SVD | 0.480 | 0.7375 |
| Neural | 0.380 | 0.6435 |

The AI exactly agreed with only eight of 20 overlapping user grades. Its assessment is a useful proxy, not validated human ground truth. It must not be merged into a human benchmark.

Precision@5 counts grade-2 useful recommendations among the first five. Pooled nDCG measures ordering against the best ordering inside the judged candidate pool; it is not exhaustive corpus relevance.

The neural model did not outperform the baseline. TF-IDF therefore became the conservative default rather than choosing a more complex method solely because it is neural.

**The original full human-quality acceptance target is still unverified.** The AI-assisted TF-IDF P@5 is itself below 0.60. No passing quality claim is made.

The 16,000/4,000 temporal split validates representation reconstruction, not reader satisfaction. The recommendation comparison is in-catalog; it does not establish out-of-time article quality, unseen-user preference prediction or online business outcomes.

## 14. Performance and scale

Three warm-ups and 100 measured requests per method exercised the Go/Python/Mongo path:

| Method | End-to-end p50 | End-to-end p95 |
| --- | ---: | ---: |
| TF-IDF | 12.55 ms | 15.12 ms |
| SVD | 11.37 ms | 12.92 ms |
| Neural | 11.13 ms | 14.07 ms |

All 309 requests passed the edition, hydration and exclusion checks. These measurements comfortably beat the proposed 500 ms warm local p95 target.

They are single-reader measurements on the inspected machine and configured database connection, not concurrent-load results, internet/mobile rendering times or a production SLA. Image downloads are excluded.

Twenty thousand 64-dimensional float32 vectors occupy roughly 5.1 MB. That is not total process memory: metadata, sparse features, SVD representations, runtime libraries and duplicated workers add overhead.

No complete article-by-article similarity matrix is saved. Runtime retrieval calculates one score per candidate and orders the bounded corpus. Offline duplicate comparison remains quadratic despite its bounded batches; full-corpus scaling is not certified.

## 15. Verification and operational resilience

Recorded delivery checks include:

- **199 Python tests passed**; recommender coverage 94%, ranking 99%, Flask API and CLI 100%.
- **18 native Node checks passed**; JavaScript coverage 58.19% lines and 90.23% branches.
- All 142 top-level tests in the changed Go surfaces passed; focused race and vet checks passed.
- Browser journeys covered real-data onboarding, feedback, related reading, method changes, keyboard navigation, mobile-width layout and text-first cards.
- Explicit temporary browser fixtures covered otherwise hard-to-reach missing-content, empty and outage states; those fixtures were not left in the integration.
- The final browser reload verified TF-IDF by default, continued Neural selection, no page errors and no horizontal overflow at 390 pixels.

The full-repository Go run also exposed an unchanged, scheduling-dependent rate-limit test failure. It is documented rather than hidden behind a blanket "all tests pass" statement.

Startup and Mongo wrapper unit coverage remain low; actual startup/hydration checks supplement but do not replace those coverage numbers. JavaScript line coverage is below the proposed 80% target.

### Connection and restart checks

The reader now retires idle Mongo data sockets after 60 seconds through the native driver policy. The setting is configurable; existing collector defaults remain unchanged.

A fresh reader, a real article join, the first read after 70 seconds idle, an intentional model-service stop and subsequent recovery were verified. A stopped ranker correctly produced 503 instead of a successful-looking substitute feed.

This mitigates the observed stale-connection condition. It does not guarantee availability through arbitrary database or network failures.

## 16. Security and data handling

Implemented controls include:

- A separate reader command with no migration, source-management, retention-delete, collection, enrichment, classification-worker or telemetry-write path.
- Bounded requests, typed IDs, parameter validation, explicit errors and bounded downstream calls.
- Escaped Go templates, text-only DOM assignment, a restrictive content policy and safe URL schemes.
- No server-side arbitrary-URL image proxy.
- Existing authentication integration and an optional private recommender API key.
- Environment-based secrets excluded from source and the submission archive.
- Trusted-local-artifact loading, with edition hashes and ID/matrix alignment checked at startup.

Important limits:

- The demonstrated configuration is loopback development with reader authentication disabled. It is not a publicly deployable security configuration.
- Read-only behavior is an application property; a dedicated read-only MongoDB role still needs to be enforced operationally for production.
- Browser-local preferences are sent to the recommendation endpoint but are not persisted as server-side user histories. Local storage is not an encrypted user vault.
- External images and original links contact publisher infrastructure. Referrer suppression does not anonymize the reader's IP address.
- There is no delivered tenant isolation, account-based article authorization or production identity integration.
- No independent penetration test, security certification or production threat-model sign-off is claimed.

## 17. Operations, reproducibility and backup

Preparation writes derived artifacts separately from MongoDB. The edition saves prepared text/IDs, cleaning settings, seed, split, vocabulary, preprocessing, both Keras models, representations, clusters, training history and hashes.

At briefing preparation, the saved corpus/model/retrieval hashes matched, live readiness returned HTTP 200, and the shared browser showed the 20,000-article edition using TF-IDF.

Local startup is:

```bash
# Terminal 1, from collector/
make rec-serve REC_ID=stories-002

# Terminal 2, from collector/
make reader
```

The existing Docker/Compose assets for the collector/classifier were preserved. A production deployment pipeline, scheduled index publication, rolling edition promotion and production observability stack for the new reader/ranker have not been delivered.

A private submission archive contains 246 files, approximately 121 MB, including source, the trained edition and separate evaluation records. Every member hash was checked. A restored copy loaded the copied model artifacts, passed model-service requests and compiled the Go reader.

That restoration reused installed dependencies; it was not a new-machine or new-OS installation certification. The archive excludes secrets, virtual environments and executables and still requires the original MongoDB connection. Copying it off the laptop and checking dataset redistribution rights remain operational responsibilities.

## 18. Decisions requested from the client and architect

| Decision / gate | Why it matters |
| --- | --- |
| Confirm archive discovery versus live-news requirements | A freshness policy and update pipeline are different scope |
| Approve the relevance rubric and independent human assessment | The current human pilot is too small; AI assessment is not acceptance |
| Confirm pilot audience, languages, topics and expected traffic | Determines data admission, editorial labelling and capacity needs |
| Approve hosting, authentication, TLS and database permissions | The current loopback demo is not public production deployment |
| Approve privacy, profile retention and content/image rights | Browser-local profiles and publisher assets have policy implications |
| Set edition update, rollback and recovery requirements | New articles are not automatically indexed |
| Define load, memory and availability acceptance tests | Warm single-reader latency is not a production SLA |
| Agree the quality-improvement evaluation protocol | Future tuning needs a development set and fresh held-out assessment |

## 19. Recommended review demonstration

1. Show edition coverage and archive dates.
2. Explore a content circle without an existing profile.
3. Select a few actual articles as interests.
4. Demonstrate interested/not-interested behavior and related reading.
5. Switch TF-IDF, SVD and Neural without changing the underlying cohort.
6. Show the text-first fallback, original-source link, keyboard navigation and profile reset.
7. Explain the offline/online separation and the absence of Mongo writes.
8. Present human and AI evaluation tables separately, followed by latency and known limitations.

### Suggested closing statement

> We have delivered a working, evidence-backed recommendation MVP on the existing news infrastructure. It includes a genuinely trained neural representation model, but the simpler TF-IDF method is the current reading default because it performed better in the available comparisons. The system is ready for a controlled pilot and architectural review. Production deployment and full human relevance acceptance remain explicit next gates rather than assumptions.

## 20. Supporting evidence and code entry points

- [Measured results and verification caveats](recommender-results.md)
- [Setup, training, evaluation and API instructions](recommender.md)
- [Submission explanation and viva questions](recommender-submission.md)
- [Read-only Go entry point](../cmd/reader/main.go)
- [Go recommendation orchestration](../internal/recommendation/recommendation.go)
- [Public recommendation handlers](../internal/handler/recommendation.go)
- [Dataset preparation](../ml-v2/src/newsrec/data.py)
- [Baseline and neural training](../ml-v2/src/newsrec/model.py)
- [Ranking and exclusions](../ml-v2/src/newsrec/index.py)
- [Private model API](../ml-v2/src/newsrec/api.py)
- [Evaluation and provenance enforcement](../ml-v2/src/newsrec/evaluate.py)
- [Story markup](../internal/web/templates/stories.html), [styling](../internal/web/static/stories.css) and [browser behavior](../internal/web/static/stories.js)
- [JavaScript regression checks](../scripts/stories.test.mjs)
