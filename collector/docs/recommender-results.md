# AFTERLINE — verified delivery results

## Delivered

A working content-based news archive recommender with a read-only Go application, a private Flask vector service, a trained TensorFlow/Keras autoencoder, TF-IDF and SVD comparisons, and a responsive Stories-inspired reader.

Local reader: **http://127.0.0.1:8090/stories**

See [setup, training, evaluation and viva instructions](recommender.md).

### Final data and trained edition

| Measure | Verified result |
| --- | --- |
| Edition | `stories-002` |
| Database | Original `news`, through the user-configured endpoint matching the larger MCP corpus |
| Records scanned before cutoff | 165,624 |
| Collection cutoff | 2026-10-22 18:00 UTC |
| Reservoir candidates | 30,000 |
| Indexed articles | **20,000**, across **40 publishers** |
| Input coverage | 19,391 body-backed; 494 summary-backed; 115 headline-only |
| Stored images | 12,237; the remainder use the text-first design |
| Publication range | 25 October 2007–22 October 2026; clearly an archive |
| Conservative duplicate groups | 19,967 |
| Articles without usable TF-IDF features | 0 |
| Train / validation | 16,000 / 4,000; chronological group boundary |
| Network | 256 → 128 → 64 → 128 → 256, denoising input, nonlinear hidden layers |
| Network size | **82,496 parameters** |
| Training | TensorFlow 2.21.0, Keras 3.15.1, Python 3.12.15, 30 epochs |
| Recorded baseline preparation | 80.37 seconds |
| Recorded neural training/clustering stage | 7.85 seconds |
| Final validation reconstruction MSE | 0.4165 — **not a recommendation-quality score** |

All derived documents, preprocessing, models, matrices, clusters, hashes, versions and evaluation records persist under the ignored `ml-v2/artifacts/recommender/stories-002/` directory. Seeds and manifests are saved. Raw article text and secrets were not added to git.

The initial Python default pointed to a different, smaller August-only local database. That discrepancy was detected before final delivery; the user supplied the correct connection, its count was checked, and the final edition was exported/trained against the larger corpus. It is not a fixture or a claim to index the entire live database.

## Measured performance

Same frozen cases and corpus across methods. Python-only results used 140 requests/method. End-to-end results used three warm-ups plus 100 measured requests/method, including two viewed candidates per case.

| Method | Python retrieval p95 | Go + Python + Mongo p50 | End-to-end p95 | Mean publishers in top 5 |
| --- | ---: | ---: | ---: | ---: |
| TF-IDF | 6.10 ms | 12.47 ms | **14.22 ms** | 3.77 |
| SVD | 4.68 ms | 11.03 ms | **12.45 ms** | 3.62 |
| Neural | 4.34 ms | 10.68 ms | **11.69 ms** | 3.83 |

All three beat the proposed **500 ms warm local p95** target on this cohort. Exclusion checks passed on all 309 end-to-end requests: no current article, selected interest, supplied viewed item or repeated known duplicate group was returned.

These are local single-reader measurements on the inspected M1 Pro/32 GB machine and configured database connection—not load-test or full-corpus guarantees. Image downloads are outside API latency.

An idle Mongo connection later produced one logged broken-pipe readiness failure, correctly surfaced as 503. The driver reconnected; native and MCP database checks and the reader readiness check then succeeded again. Warm latency above does not certify cold/idle recovery or the availability of the existing database/network connection.

## Relevance: independent user-judged pilot

The user independently rated **20 blinded candidate pairs** from **two fixed cases**:

- `article-01`: a headline-only article about state investment friendliness.
- `article-05`: an article about a new state of matter.

Each method was scored on the same pooled judgements. Grade 2 counts as useful for Precision@5; grades 0/1/2 contribute to graded pooled nDCG.

| Method | Useful Precision@5 | Pooled nDCG@5 | Cases judged |
| --- | ---: | ---: | ---: |
| **TF-IDF** | **0.80** | **0.9349** | 2 of 40 |
| SVD | 0.70 | 0.6596 | 2 of 40 |
| Neural | 0.60 | 0.5755 | 2 of 40 |

**The neural model did not outperform the baseline on this pilot.** Two cases are too few for a broad quality claim, a statistical superiority claim, or certification of the full relevance target. The remaining **38 cases / 417 pairs remain unjudged**. No assistant-generated grades filled those gaps.

The separate 100-query old-training-label proxy, over a common restricted pool of 692 labelled articles, measured same-category top-five agreement of TF-IDF 0.580, SVD 0.656 and neural 0.624. That measures coarse category agreement, not reading preference or human relevance; it does not replace the manual benchmark.

The benchmark is an in-catalog related-reading experiment. It does not establish prediction of unseen users' clicks, long-term satisfaction or recommendation quality for future unindexed articles.

### Reproduce the limited manual pilot

From `collector/ml-v2/`:

```bash
uv run --no-sync newsrec score --id stories-002 \
  --judgements artifacts/recommender/stories-002/judgements.jsonl \
  --case article-01 --case article-05
```

The original user ratings also persist in `manual-pilot-grades.json`. The selected-case result is `relevance-selected.json`; it does not overwrite a full evaluation. Complete the other cases independently, then score without `--case` for the full result.

## Verification

| Surface | Verified |
| --- | --- |
| Go | Full unit suite passed; focused race detector and `go vet` passed |
| Python | 138 existing tests passed in the full run; all **49** final recommendation tests passed in subsequent focused runs |
| JavaScript | **16** persistent stdlib Node tests passed; no runtime frontend dependencies |
| Recommendation coverage | Python **94%** overall with branches; ranking **99%**, Flask API **100%**, CLI **100%** |
| Go coverage | Recommendation service **96.5%**, handler package **95.9%**, web package **90.1%** |
| Startup / driver coverage | Reader command **33.8%** in unit coverage; Mongo driver repository not unit-instrumented. Actual startup and batch hydration were exercised through the live services |
| Browser-state unit coverage | JavaScript **58.1% lines / 89.37% branches**; below the proposed 80% line target. Layout/event wiring also received live-browser verification, not counted as instrumented unit coverage |
| Existing classifier | Original saved bundle still loads and predicts; its closed test split was not reopened |
| Read-only behavior | No mutation routes in the new command; MongoDB `read_events` remained **0** after browser and API checks |

Browser verification covered:

- Real Mongo data and trained representations through the running API and reader.
- Desktop presentation, onboarding with three real selected articles, stored interests, related mode, model lenses and the legacy archive.
- Interest updates followed by new recommendations; previous/next and native keyboard navigation.
- A 390-pixel viewport with no page-level horizontal overflow and a synthetic touch-pointer swipe.
- Actual missing-image text-first rendering with real articles.
- Headline-only, empty/end-of-feed and 503/retry states using **explicit temporary browser-response fixtures**, then recovery to real data. These fixtures were not stored, trained on or left in the running integration.

A shared related-mode bug was caught with a failing regression test: unrelated saved interests could dilute the opened article. It was fixed in the common retrieval function. All 120 pre-existing method/case rankings were rechecked unchanged before the user's blinded judging; the judgement pool itself was preserved.

Keras/joblib emit upstream NumPy deprecation warnings during some tests; checks pass. No library source or unrelated tests were rewritten to hide them.

## Boundaries

- Original Mongo articles were not modified. The reader starts no collector, scraper, migration, classifier scheduler or telemetry writer.
- New articles need a new explicit edition/index build. This delivery indexes 20,000, not every live Mongo record.
- Language checks and conservative duplicate detection are imperfect. Near-duplicate grouping remains quadratic offline work on the bounded subset; scale it only after adding candidate blocking.
- Preferences are browser-local: 50 positive, 50 negative and the last 2,000 viewed IDs. There are no accounts or cross-device profiles.
- Publication timestamps are stored collector values; some fall back to collection time. Publisher images, original links, rights, paywalls and hotlink policies are not guaranteed.
- The default neural lens demonstrates the trained model; it is **not** a claim that it is the best method. TF-IDF remains selectable and won the two-case manual pilot.
- Finish the remaining independent judgements before presenting a full relevance acceptance claim.
