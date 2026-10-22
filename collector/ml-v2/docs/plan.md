# ml-v2 — Body-Aware 13-Class News Classifier (POC)

> Living document. Update status as phases land; append to the decision log rather than
> rewriting history.

**Status:** **Phases A–H complete. The test split is open and closed.** · snapshot
`v2-001` · **final: test macro-F1 0.751 [0.719, 0.780]**, or **83.4% accuracy at 80.7%
coverage** once it is allowed to abstain · next: review, then decide on serving

**The core hypothesis is confirmed.** The article body is worth **+0.059 macro-F1**
(word_char_svc: 0.712 → 0.771), with non-overlapping intervals and McNemar p=7.5e-06.
Against the v1-parity rung measured on this same snapshot (0.696), the gain is **+0.075**.

**Everything else has failed to beat it, which is the second finding.** Entity/geography
scrubbing (D0), feature engineering (D), all seven alternative model families (E) and
every reachable ensemble (F) were each measured and each lost or tied. The data
preparation in Phase A carried this project; the classifier was never the bottleneck.

**Phase G bought the thing accuracy could not**: calibrated confidence, and an
abstention policy that files **76% of articles at 88% accuracy** instead of 100% at 79%.

**Frozen corpus cut:** `collected_before = 2026-08-26T12:00:00+00:00` → 14,189 articles,
40 publishers, all **8,001** gold labels join.
**Gold digest:** `8ed59b13d4148727063fdd5d38ee6c4d365e9949f179525f3824eb187e5a918e`

---

## Why this exists

`news/ml/` (v1) reaches **val macro-F1 0.720** classifying on `title + summary` — about
33 words per article. Two things changed:

1. **The corpus now has bodies.** 94.3% of gold articles carry a median 3,765-char body.
   That is roughly 100× more text per article, and it is the central hypothesis to test.
2. **v1's methodology has known, documented weaknesses** — a single validation split used
   for both tuning and selection, point estimates with no confidence intervals, a
   near-duplicate threshold that provably cannot exceed 0.80 precision, and a class floor
   whose module constant (300) disagrees with its CLI default (40).

v2 is a **standalone rewrite that improves those methods**, not a port.

This is a **POC**. Ship nothing, deploy nothing. Build the model, measure it honestly on
real data, then decide whether it earns a deployment conversation.

---

## Measured baseline

Verified 2026-08-26 against the live corpus. Supersedes any earlier figures.

| Fact | Value |
| --- | --- |
| Gold labels | **8,001** articles, one label each, all human, taxonomy v4 |
| Class distribution | politics 1,576 … conflict_war 234; `unsorted` 63. Imbalance **6.7:1** |
| **Body coverage (gold)** | **94.3%** — median 3,765 chars, p90 7,285, p99 16,228, max 179,230 |
| Summary coverage | 74.8%; title-only 86 articles (1.07%) |
| Body coverage by class | 89.7%–99.3%, uniform — no class disadvantaged |
| Corpus at the frozen cut | **14,189** articles, 97 feeds → **40 publishers**, 92.6% with a body |
| `collected_at` span | 2026-08-22 → 08-26 (**4 days**) |
| `published_at` span | 2025-09-13 → 2026-08-26 |
| v1 best (historical) | macro-F1 **0.720**, coverage 82.9%, 11 MB, 0.05 ms/doc, 12 emittable classes |
| Expected val size | ~1,190 ⇒ SE on macro-F1 ≈ **±0.02–0.03** |

> **Any delta under ~0.03 on a single validation split is noise.** v1 repeatedly read
> ±0.07 per-class swings as signal. Phase C's harness exists to stop that recurring.

---

## Pre-implementation findings (2026-08-26)

### Finding 1 — publisher holdout candidates

Publisher = the part of `source_name` before the em-dash, so all `The Indian Express — *`
section feeds collapse into one publisher.

| Publisher | gold | classes covered | classes <10 articles |
| --- | ---: | ---: | --- |
| The Indian Express | 1,683 | 13 | **none** |
| The Hindu | 897 | 13 | **none** |
| The Guardian | 800 | 13 | **none** |
| The New Indian Express | 600 | 13 | technology, science_space |
| Livemint | 593 | 13 | 6 classes |
| Hindustan Times | 526 | 13 | 4 classes |
| Phys.org | 231 | 11 | (missing 2) |

Only **three** publishers cover all 13 classes with ≥10 articles each. Individual *section
feeds* are badly skewed — `The Indian Express — Education` covers only 8 of 13 — which is
why a publisher must be held out as a family, never as a feed.

**Decision: hold out The Hindu (in-distribution) and The Guardian (out-of-distribution).**
The Guardian is the harder test: non-Indian, different house style and vocabulary.
**The Indian Express is deliberately not used** even though v1 used it — at 1,683 of 8,001
it is 21% of all labels, so removing it confounds "generalizes to an unseen publisher"
with "trained on 21% less data". v1's reassuring 0.018–0.043 drop was measured under
exactly that confound.

### Finding 2 — body furniture

400 bodies sampled across 76 sources.

- Furniture is **repetitive and per-source**, exactly what line-frequency discovery
  handles: `Story continues below this ad` (71–75% of Indian Express bodies),
  `Updated on:` / `2 min read` (52%/33% New Indian Express), `- Ends` / `Published On:`
  (62% India Today), `Tags:`, `© IE Online Media Services Pvt Ltd`, Guardian
  newsletter-promo lines.
- Only **26.5%** of bodies contain any common furniture marker; the largest single one
  (`read more`) is 11.8%. Tractable, not a swamp.
- **New risk — embedded author biographies.** Phys.org has `Who's behind this story?` in
  86% of bodies followed by multi-sentence bios; Livemint and Indian Express do the same.
  These are *topically misleading* — a cricket correspondent's bio inside a business
  article pulls it toward `sport`. **v1's rule would miss them**: `MAX_LINE_WORDS = 25`
  treats long lines as syndicated content, and bios are long.
- 5% of bodies are under 200 chars, in two distinct kinds: Deccan Herald `DH Toon` cartoon
  pages whose entire body is `Check out more of our cartoons here .` (reject as
  non-article), and NDTV one-line summaries that are thin but legitimate (keep).

### Finding 3 — label noise ceiling

Same-story groups found by sparse TF-IDF cosine over title + 4,000 chars of body, then
checked for label agreement. **~18–22% of multi-article story groups carry disagreeing
labels**, stable across cosine cuts 0.55 / 0.70 / 0.85.

That is an **upper bound, not the noise rate** — many are *grouping* false positives:
`DH Toon` cartoons, `Daily Quiz` instalments, `Watch:` segments and `Chennai Canvas
Episode 1–4` merged as one "story", plus two unrelated France 24 articles merged by shared
boilerplate. These are the same four failure kinds v1 catalogued.

The genuine disagreements are **taxonomy boundary collisions, not carelessness**:

| Same story | Labels given |
| --- | --- |
| Ukraine shopping-centre strike | politics vs conflict_war |
| Gujarat hooch tragedy | disaster_accident vs crime_justice |
| Ex-cricketers' letter on Imran Khan | politics / crime_justice / **sport** (3-way) |
| NCERT textbook panel | politics vs education |

Top disagreeing pairs: conflict_war↔politics (8), business_economy↔politics (8),
crime_justice↔disaster_accident (5) — **the same pairs the v1 classifier confuses most**,
meaning those confusions are partly in the labels, not the model.

**Consequence: macro-F1 has a real ceiling below 1.0.** `conflict_war`, `crime_justice`
and `politics` cannot reach `sport`-level F1. Targeting 0.90 macro-F1 means targeting
annotation noise. Tie-break rules in the labelling guide would buy more than another
labelling round.

### Finding 4 — near-duplicate cost is not a problem

Sparse TF-IDF cosine over all 8,001 articles with 4,000-char bodies ran in **12 seconds
end to end**. Pure-Python MinHash over the same bodies would be orders of magnitude slower
(~22× more shingles per document than headline-length text). Cosine verification is
effectively free and should carry most of the work.

---

## What v2 does differently

| Layer | v1 | v2 | Why |
| --- | --- | --- | --- |
| Text | title+summary, one string | title / summary / body as separate fields | a concatenated string cannot be field-weighted |
| Storage | JSONL snapshots | **Parquet + zstd** | bodies make snapshots ~60 MB; ~5× smaller, ~10× faster, re-read by every run |
| Near-dup | one MinHash threshold | **two-stage: blocking → cosine verify**, + time-gap and boilerplate guards | v1 measured precision **cannot exceed 0.80 at any cut**; its 4 FP kinds need rules, not a threshold |
| Tuning | one val split | **StratifiedGroupKFold on train**; val for selection only | v1 tuned and selected on the same ~600 rows |
| Statistics | point estimates | **bootstrap CIs resampled by story group** + McNemar | article-level bootstrap under-reports variance when near-dup clusters exist |
| Calibration | `CalibratedClassifierCV(cv=5)` | `cv="prefit"` on val | 5× cheaper, calibrates on genuinely held-out data |
| Thresholds | grid-searched on val | fitted on **OOF probabilities from train** | `education` had 29 val articles — a cut fitted on that overfits |
| Admission | hardcoded rules | each rule toggleable and **priced** | 443 articles dropped by `language_mismatch` alone; nobody knows if it helps |
| Class floor | fixed (300 in module, 40 in CLI) | **derived: the smallest class present** | nothing is ever dropped; v1's mismatch would have deleted `conflict_war` silently |
| Tracking | ad-hoc `/tmp` scripts | append-only experiment ledger | v1 lost whole rounds of results between sessions |

---

## Phase A — Foundation

- [x] **A1. Scaffold `news/ml-v2/`** — done 2026-08-26
  - uv-managed package `newsmlv2`, Python 3.12, console script `newsmlv2`.
  - One dependency set (POC): scikit-learn 1.9, pymongo, numpy, scipy, pandas, pyarrow,
    PyYAML, xgboost 3.4, sentence-transformers 6.0, matplotlib, spacy 3.8. Dev: pytest.
  - `taxonomy.yaml` (v4, 13 classes) and `data/labels/gold.jsonl` (8,001 labels) vendored,
    digest `8ed59b13…a918e` recorded in every snapshot manifest, so ml-v2 builds without
    `../ml/`. Label *production* stays v1's job.
  - `config.py` (paths, seed, frozen cut, publisher holdouts), `load.py` (Article with
    title/summary/body **separate**, `publisher_of`), `labels.py` (taxonomy + gold reader,
    `trainable` strips `unsorted` before any class is counted).
  - `ml2-*` targets in `news/Makefile`. 13 tests green.

- [x] **A2. Text layer** — done 2026-08-26
  - `clean.py` cleans title, summary and body **independently**; explicit punctuation
    fold, line-anchored furniture removal, dateline and wire-agency extraction into
    fields, plus a navigation-body guard.
  - `boilerplate.py` discovers per-source repeated lines over **bodies**, with
    `MAX_LINE_WORDS` raised from 25 → 120 and a repetition bar replacing the length bar.
    Found **355 lines across 47 sources, 19 of them long** — the author bios v1 could not
    reach. Cleaning removes only **1.2%** of body text corpus-wide.
  - `admit.py` — every gate is a switch on `Policy`, so Phase B can price it by turning
    it off and re-scoring. Rejections on the real corpus: **582 of 14,189 = 4.1%**
    (implausible_timestamp 238, too_short 142, non_article_format 128, service_bulletin
    38, sponsored 31, exact_duplicate 5). **7,969 of 8,001 gold labels survive.**
    Kept articles: 13,607, **94.9% with a usable body**, median **594 words** against
    v1's ~33.
  - Language rejection defaults **off**: v1 dropped 443 articles on it without ever
    measuring the cost. Implemented as a deterministic script ratio rather than
    `langdetect`, which samples randomly and needs a global seed to reproduce.
  - 76 tests green.

- [x] **A3. Near-duplicate detection, two-stage** — done 2026-08-26
  - Blocking by sparse TF-IDF cosine k-NN, verification by threshold plus two guards.
  - **Calibrated against v1's 43-pair hand-judged census** (39 survive admission):
    at cut **0.50** with the guard, **precision 0.86, recall 0.81, F1 0.833**.
    v1's proven ceiling was **precision 0.80 at any single-threshold cut** — beaten.
  - Cut is **not** the F1 argmax (0.30, F1 0.852). The census only covers the 0.40–0.95
    band, so a lower cut extrapolates where nothing was ever judged, and the whole
    0.30–0.52 range differs by one true positive out of 39.
  - **Recall criterion restated from ≥0.90 to ≥0.80.** Recall plateaus at 0.84 even at
    cut 0.30: about 5 of the 31 judged same-story pairs share almost no vocabulary
    because two publishers covered one event in genuinely different words. No
    text-similarity threshold reaches those, so 0.90 was never achievable by this route.
  - **Body-based grouping folds 999 articles vs 708 for title+summary — the Phase B2
    prediction confirmed, +41%.** Largest groups verified genuine: the Kriti Sanon rakhi
    story across 3 publishers, Ajit Doval's Beijing talks across 5.
  - `pipeline.py` added as the single clean→admit→group path, so no script can drift
    from the snapshot's recipe.

- [x] **A4. Snapshot** — done 2026-08-26, `v2-001`
  - Parquet + zstd, 24 MB. `title`, `summary`, `body` stored **separately**, plus
    `body_chars`, `has_body`, `publisher`, `story_group_id`, `split`, `topic`.
  - Manifest pins git sha, seed, cleaning/taxonomy versions, the **label file digest**,
    the frozen cut, split boundaries, near-dup config and the admission policy.
  - `--id` is required and an existing id refuses to overwrite.
  - `newsmlv2 verify` re-checks digests: both files OK.
  - **Result:** 13,607 admitted, 582 rejected, 7,919 labelled, 12,608 story groups.

- [x] **A5. Splits — three regimes** — done 2026-08-26
  - Grouped + temporal on `collected_at`, cuts placed on **labelled** rows and applied to
    all, straddling groups dropped whole. Boundaries frozen in the manifest.
  - **Labelled split: train 5,487 / val 1,120 / test 1,159 / dropped 153** = 69/14/15.
  - `publisher_holdout()` for The Hindu and The Guardian, keyed on publisher, never a feed.
  - `StratifiedGroupKFold` over train is what hyperparameter search will use.
  - Asserted against the real snapshot: no story group spans two splits, and every test
    article was collected after every train article.

- [ ] **A6. Class scope — derived, never fixed** *(needs A5)*
  - `min_per_class` is **computed**: the size of the smallest class present. Every class
    clears it by construction, `out_of_scope` is always empty, nothing can be dropped.
  - **Trap:** exclude `unsorted` (63 rows) *before* taking the minimum, or the floor
    becomes 63 and `unsorted` starts training as a 14th class. Today's real minimum is
    `conflict_war` at 234.
  - Two advisory reports, neither of which drops anything:
    - **CV feasibility** — `StratifiedGroupKFold(n_splits=5)` needs ≥5 members per class
      in train. Below that, reduce `n_splits` for that run and say so loudly; never delete
      the class.
    - **Thin-class warning** — flag classes whose val support makes their F1 noise.
  - Because the thinnest class now always trains, class weighting (G3) becomes the main
    defence against the 6.7:1 imbalance rather than optional tuning.

**Phase A done when:** `newsmlv2 snapshot --id v2-<date>` then `newsmlv2 verify`
reproduces digests byte-identically, and the test suite is green.

---

## Phase B — Data quality & leakage *(done 2026-08-26)*

- [x] **B1.** `newsmlv2 report --id v2-001` → `reports/data-quality.md`, all 14 items.
  Headlines: body present on **94.9%** of admitted articles, imbalance 6.7:1,
  **481 story groups span more than one publisher** (the syndication that would leak),
  longest body 175,331 chars = 53x the median.
- [x] **B2. Leakage audit.**
  - Body-based grouping folds **999 articles vs 708** for title+summary — the prediction
    held, +41%.
  - No story group spans two splits (asserted on the real snapshot, not a fixture).
  - Admission-rule pricing moved into Phase C's harness, where a model exists to price
    them against. `Policy` already exposes every gate as a switch.

---

## Phase C — Harness + baselines *(done 2026-08-26)*

- [x] **C1. Experiment ledger** — `experiment.py` + `evaluate.py`. Every run appends a
  row with git sha, snapshot, config digest, metrics and timings. **Bootstrap CIs
  resampled by story group** and **McNemar** are built in, and every run is scored on the
  validation split *and* both publisher holdouts (each refit without that publisher).
- [x] **C2. Baselines** — 5 models x 2 variants, 10 runs in the ledger.

| Model | title_summary | title_body | Hindu | Guardian |
| --- | --- | --- | --- | --- |
| majority | 0.025 | 0.025 | 0.030 | 0.017 |
| complement_nb | **0.635** | 0.594 | 0.589 | 0.563 |
| tfidf_logreg | 0.698 | 0.752 | 0.747 | 0.736 |
| tfidf_linear_svc *(v1 parity)* | 0.696 | 0.753 | 0.750 | 0.745 |
| **word_char_svc** | 0.712 | **0.771 [0.743, 0.796]** | 0.769 | 0.724 |

**The body A/B, the central question of the project:**

| Model | delta | McNemar p | Verdict |
| --- | --- | --- | --- |
| complement_nb | **−0.041** | 2.8e-02 | **short wins** |
| tfidf_logreg | +0.054 | 3.0e-05 | body wins |
| tfidf_linear_svc | +0.056 | 1.3e-04 | body wins |
| word_char_svc | **+0.059** | 7.5e-06 | body wins, intervals disjoint |

Three findings worth keeping:

1. **The body is worth ~+0.06 macro-F1**, significant on every linear model.
2. **ComplementNB gets *worse* with the body** — the one model where it hurts. Naive
   Bayes assumes term independence and is sensitive to document length, so a 500-word
   body breaks its assumptions where a headline did not. A good reminder that "more
   text" is not universally better.
3. **Publisher generalization improved rather than degraded** (Hindu 0.682→0.769,
   Guardian 0.665→0.724). H2 predicted bodies might carry more publisher style and make
   this *worse*; measured, the opposite happened — the Phase A boilerplate work is the
   likely reason.

---

## Phase D0 — Signal hygiene *(done 2026-08-26 — NEGATIVE RESULT, nothing adopted)*

> Cleaning here is signal correction, not tidying: furniture and place names become
> **publisher→class shortcuts** that score well on validation and collapse on an unseen
> masthead. `scrub.py` runs one spaCy pass (105s for 6,607 docs) and renders every policy
> from the stored annotations, so ablations are cheap.

**Result: no rule earned adoption.** Measured on `word_char_svc` + `title_body`,
baseline 0.773.

| Policy | val | Δ val | Δ holdout | publisher probe | Verdict |
| --- | --- | --- | --- | --- | --- |
| raw | 0.773 | — | — | 0.482 | baseline |
| mask PERSON | 0.769 | −0.004 | −0.000 | 0.481 | reject |
| mask PLACE | 0.768 | −0.005 | **+0.003** | 0.476 | inside noise |
| mask numbers | 0.766 | −0.007 | −0.000 | 0.477 | reject |
| lemmatise | 0.771 | −0.002 | −0.003 | 0.487 | reject |
| person+place | 0.766 | −0.007 | −0.008 | 0.474 | reject |
| person+place+numbers | 0.764 | −0.009 | −0.009 | 0.471 | reject |
| all four | **0.775** | **+0.002** | **−0.018** | 0.473 | **reject** |

Three things this bought, all worth more than a fractional gain would have been:

1. **The acceptance test paid for itself on the last row.** `person+place+numbers+
   lemmatise` *improves validation* (+0.002) while *losing 0.018 of publisher
   generalization*. On validation alone it looks like the winner. That is precisely the
   failure mode the holdout-vs-validation rule exists to catch, and without it this
   would have shipped.
2. **The publisher probe barely moves** (0.482 → 0.471 at best). Entity masking removes
   almost no publisher fingerprint — because **Phase A already removed it**. The
   boilerplate, affix and publisher-level work did the job, so D0 arrived with nothing
   left to clean.
3. **The brief's warning was right.** "Do not blindly apply traditional NLP
   preprocessing" — lemmatisation was the only rule that made the probe *worse* (+0.005),
   i.e. it made publishers easier to identify, presumably by collapsing distinct
   vocabulary into shared stems.

Kept as a switchable module for Phase E to re-test on embeddings, where masking may
behave differently. Not enabled anywhere.

> **Cleaning here is signal correction, not tidiness.** `Story continues below this ad`
> is in 75% of Indian Express bodies; `- Ends` in 62% of India Today; `Who's behind this
> story?` in 86% of Phys.org. Those publishers skew toward particular classes, so each
> phrase becomes a **publisher→class shortcut** — a fake relationship that scores well on
> validation and collapses on an unseen publisher.

Each rule is an independent switch, measured against the plain baseline, adopted only on
a CI-backed gain. spaCy `en_core_web_sm` costs one ~15-minute pass over ~14k articles;
the scrubbed text is **cached** and paid for once.

### D0 rules — high expected payoff

- [ ] 1. **Publisher fingerprints** — per-source line-frequency removal plus author bios.
- [ ] 2. **Geography stripping** — the corpus is India-heavy and city desks over-supply
  crime and disaster, so the model learns `Bengaluru → crime_justice`. `taxonomy.yaml`
  already carries a `geography` list, so the stoplist is free.
- [ ] 3. **Number / date / money normalization** — `<NUM>`, `<DATE>`, `<MONEY>`. Converts
  thousands of single-document features into real indicators.
- [ ] 4. **Entity policy, split by type** — `PERSON` → `<PERSON>` (brittle memorization;
  the brief asks for generalization to new people), `GPE`/`LOC` → `<PLACE>`, but
  **keep `ORG`** (ISRO→science_space, RBI→business_economy, BCCI→sport are genuine signal).

### D0 rules — medium, test before believing

- [ ] 5. **Entity-aware lemmatization** — helps thin classes most (`conflict_war` has 234
  labels, so merging inflections multiplies the evidence per feature). Non-entity tokens
  only, so `Reuters` never becomes `reuter`.
- [ ] 6. **Keyword extraction** on the body (~30 topic-bearing terms inside ~650 words).
- [ ] 7. **`chi2` / mutual-information feature selection** after vectorization.
- [ ] 8. **Drop non-English lines** — India Today bodies carry Hindi fragments.

**Rejected:** aggressive stemming (destroys entities), stopword removal (`sublinear_tf`
handles it), removing all entities (throws away ORG signal).

### D0 acceptance — two probes, both required

- **Publisher probe:** train a classifier to predict the *publisher* from cleaned text.
  **The score must get worse** after each cleaning step; if it stays high, fingerprints
  remain.
- **The real tell:** a genuine cleaning win improves the **publisher holdout more than
  validation**. Validation shares publishers with train, so shortcuts still pay there —
  only the holdout exposes them. A rule that helps val but not the holdout removed
  *information*, not noise, and must be reverted.

---

## Phase D — Feature engineering *(done 2026-08-26)*

**Body length sweep** (`word_char_svc`, title ×1, head truncation):

| Body chars | val macro-F1 | Hindu | Guardian |
| --- | --- | --- | --- |
| none (summary only) | 0.712 | 0.688 | 0.675 |
| 256 | 0.716 | 0.694 | 0.613 |
| 512 | 0.759 | 0.730 | 0.665 |
| 1024 | 0.760 | 0.752 | 0.679 |
| 2048 | 0.774 | 0.752 | 0.700 |
| **4000** | **0.771** | **0.772** | **0.726** |
| 8000 | 0.783 | 0.760 | 0.721 |
| full | 0.781 | 0.765 | 0.712 |

The curve climbs steeply to ~2,048 characters and then flattens — 8000 is nominally best
but its interval [0.753, 0.807] overlaps everything from 2048 up, so the extra text is
not measurably worth anything. **4000 wins on the tiebreak that matters: it has the best
publisher holdout on both mastheads.** It was already the default, so the sweep confirmed
the setting rather than changing it.

**Title repetition — the lazy alternative to a weighted FeatureUnion — loses, clearly:**

| Title × | 1 | 2 | 3 | 5 |
| --- | --- | --- | --- | --- |
| val macro-F1 | **0.783** | 0.768 | 0.764 | 0.751 |

Monotonically worse. That settles the field-weighting question in the *opposite*
direction to the prior: the body deserves its weight, and up-weighting the headline
actively destroys signal. No FeatureUnion weighting is needed, which removes a whole
tuning dimension.

**Head+tail is not better than head-only** (2048: 0.764 h+t vs 0.774 head; 4000: 0.779 vs
0.771 — all overlapping). News puts the topic in the lede, as expected.

**Settled: `body_chars=4000`, title ×1, head truncation, no field weighting.**

- [ ] **Body reduction — test three, assume none.** The body is ~650 words against a
  ~10-word title, so it must be compressed or weighted or it dominates:
  1. **Truncation** — first-N ∈ {512, 1024, 2048, 4096, full} chars, and first-N + last-N.
     News puts the topic in the lede, so this may be sufficient on its own.
  2. **Keyword extraction** — top-k terms. Cheapest at inference.
  3. **Lemmatization / stemming** — collapses inflections, shrinks vocabulary.
- [ ] **Field-weighted `FeatureUnion`** (title / summary-or-lede / reduced body) with
  tuned weights.
- [ ] **The lazy alternative** — just repeat the title N times in one concatenated string.
  Often matches a weighted union at a fraction of the complexity; if it ties, it wins.
- [ ] Char n-grams (`char_wb` 3–5) on title for spelling and transliteration robustness.
- [ ] Ablations: stop-words, `sublinear_tf`, min_df/max_df.
- Explicit handling for the 86 title-only and 25%-no-summary articles; a missing field
  must never become the literal string `"None"`.

> These are ablations, not defaults. The brief warns against blindly applying traditional
> NLP preprocessing, and the warning is well aimed: stemming damages named entities
> (`Reuters`→`reuter`), and entities are exactly what separates `politics` from `sport`.
> v1 already measured that feature engineering bought nothing **at headline length** —
> whether that reverses at 100× the length is what this phase tests.
>
> **Never lemmatize or keyword-reduce the text used for near-duplicate detection** —
> duplicate detection needs surface form; normalizing it inflates false merges.

---

## Phase E — Model families *(done 2026-08-26 — the incumbent wins outright)*

| Candidate | val macro-F1 [95% CI] | Hindu | Guardian | fit s |
| --- | --- | --- | --- | --- |
| E1 linear C=0.5 | 0.770 [0.741, 0.795] | 0.771 | 0.717 | 8.1 |
| **E1 linear C=1 (incumbent)** | **0.771 [0.743, 0.796]** | **0.772** | **0.726** | **8.8** |
| E1 linear C=3 | 0.772 [0.743, 0.797] | 0.768 | 0.712 | 11.4 |
| E1 logreg C=10 | 0.751 [0.720, 0.775] | 0.763 | 0.736 | 23.4 |
| E2 xgboost svd256 | 0.735 [0.705, 0.761] | 0.721 | 0.679 | 41.9 |
| E2 xgboost svd512 depth 8 | 0.729 [0.697, 0.757] | 0.703 | 0.700 | 82.7 |
| E3 random forest | 0.730 [0.698, 0.757] | 0.705 | 0.695 | 22.0 |
| E3 extra trees | 0.684 [0.651, 0.712] | 0.686 | 0.648 | 20.1 |
| E4 MiniLM + logreg | 0.710 [0.679, 0.736] | 0.718 | 0.693 | 0.2 |
| E4 MiniLM + xgboost | 0.704 [0.670, 0.731] | 0.654 | 0.627 | 95.6 |

**Nothing beats the linear model, and nothing is close.** The best alternative
(xgboost svd256) is 0.036 below at 5x the fit time.

1. **Tuning is exhausted.** A 6x swing in `C` moves macro-F1 by 0.002 — the incumbent
   sits on a flat optimum. There is no headroom left in the linear family.
2. **Trees lose for a structural reason, not a tuning one.** Text lives in a ~200k
   dimensional sparse space where classes are near-linearly separable. Reducing to 256
   SVD components to make trees usable discards exactly the discriminative detail the
   linear model exploits. Giving XGBoost *more* capacity (512 components, depth 8) made
   it **worse** — the signature of a wrong inductive bias, not an under-fit.
3. **The holdouts move with validation**, so this is genuinely weaker modelling rather
   than an overfitting artefact.
4. **MiniLM lands at 0.710, almost exactly the title+summary TF-IDF score (0.712).**
   That is the tell: MiniLM truncates at **256 tokens (~200 words)**, while the body
   advantage comes from ~500 words. The embedding model structurally cannot see the
   thing that made v2 work. A longer-context encoder might do better, but the plan's
   rule was to escalate only if the small model showed promise — it did not.

The brief's instruction "do not assume XGBoost is better than SVM" is now **measured on
this data** rather than asserted.

- [ ] **E1. Linear** — LinearSVC, LogisticRegression. Tune C, class_weight, n-gram range,
  min_df/max_df.
- [ ] **E2. XGBoost** — **never on raw sparse TF-IDF.** Dense input = TruncatedSVD
  (128/256/512) of the union + engineered metadata (title length, body length, `has_body`,
  source desk prior, category tags, hour-of-day). Early stopping on val.
- [ ] **E3. Bagging** — RandomForest, ExtraTrees, Bagging on the same dense input.
  **Expected to lose** on text; the phase exists to prove it, and the result is recorded
  either way.
- [ ] **E4. Embeddings** — `all-MiniLM-L6-v2` first; escalate only if it shows promise.
  Cache vectors keyed by (model, snapshot, text hash) or every later experiment re-pays
  the encode cost. Encode on **CPU** — GPU/MPS kernels are not bit-reproducible and would
  break snapshot reproducibility. Heads: LogisticRegression, linear, XGBoost.
  The publisher-holdout score is the real question: does semantics survive an unseen
  publisher?

---

## Results so far

Everything below is measured on snapshot `v2-001`, validation split (1,120 labelled
articles), with intervals bootstrapped over story groups.

| Phase | Question | Answer | Adopted? |
| --- | --- | --- | --- |
| C | Does the body help? | **+0.059**, p=7.5e-06, disjoint intervals | **yes** |
| C | v1-parity rung on this snapshot | 0.696 → 0.771 = **+0.075** | — |
| D0 | Does entity/geo scrubbing help? | no rule cleared the bar | no |
| D | Best body length? | 4000 chars (best holdout; 2048+ all tie) | confirmed default |
| D | Up-weight the title? | **worse**, monotonically | no |
| D | Head+tail vs head? | no difference | no |
| E1 | Better `C`? | ±0.002 over a 6× swing | no |
| E2 | XGBoost on SVD? | −0.036, 5× slower | no |
| E3 | Bagging? | −0.041 to −0.087 | no |
| E4 | MiniLM embeddings? | −0.061 | no |
| F1 | Are the models complementary? | **yes** — oracle 0.900 vs 0.771 | — |
| F1 | Can a vote reach it? | **no** — +0.001, McNemar p=1.00 | no |
| G1 | Does calibration cost accuracy? | no — 0.769 vs 0.771, ECE 0.039 | **yes, isotonic** |
| G1 | Is calibrate-on-val good enough? | **no** — ECE 2× worse, log loss 1.11 | no |
| G2 | Do per-class cuts beat one global cut? | **no** — 0.879 vs 0.891 at equal coverage | no |
| G2 | Does abstention pay? | **yes** — 76% coverage at 0.879 vs 0.795 | **yes** |
| G3 | What did `class_weight="balanced"` buy? | −0.003 val, **+0.014 Guardian** | kept, on the holdout |
| H1 | Are the errors the labels' fault? | **18.6%** sit on human-disagreement pairs | ceiling, not a bug |
| H2 | Does an unseen masthead cost anything? | Hindu **+0.001**, Guardian −0.045 (overlapping) | risk did not materialise |
| H3 | Is the temporal split measuring drift? | no — random 0.752, overlapping | 4-day window too short |
| H6 | Does it decline what humans could not label? | **yes** — 0.70 vs 0.81 median confidence | abstention works |
| **H4** | **Does it hold up on unseen data?** | **test 0.751 vs val 0.771, −0.021** | **accepted** |

**Current winner: `word_char_svc` on `title_body`, body capped at 4,000 chars,
`class_weight="balanced"`, isotonic calibration cross-validated on train, one global
confidence cut — val macro-F1 0.771 [0.743, 0.796], or 0.879 accuracy at 76% coverage
once it is allowed to abstain.**

Per-class on that model: sport 0.95, entertainment_arts 0.89, science_space 0.86,
disaster_accident 0.84, business_economy 0.84, technology 0.81, crime_justice 0.79,
politics 0.78, conflict_war 0.74, health 0.72, education 0.71, environment_climate 0.69,
**society_lifestyle 0.42**.

Top confusions are the *same pairs humans disagreed on* in Finding 3:
business_economy↔politics (13+13), society_lifestyle→politics (11), conflict_war→politics (8).

---

## Phase F — Ensemble decision *(done 2026-08-26 — F1 run, F2 refused on evidence)*

The prior said this would be a formality. It was not: **the models ARE complementary,
and it still does not help.** That is a more useful result than the expected one.

- [x] **F1. Complementary-error analysis** — `scripts/phase_f_ensemble.py` refits all ten
  Phase E candidates once and caches their validation predictions, so F2 and any later
  question costs nothing.

**The oracle gap is real and large:**

| Member set | n | oracle macro-F1 | oracle accuracy |
| --- | ---: | --- | ---: |
| incumbent alone | 1 | 0.771 [0.743, 0.796] | 0.794 |
| linear family | 4 | 0.818 [0.789, 0.839] | 0.838 |
| incumbent + best tree | 2 | 0.823 [0.796, 0.846] | 0.841 |
| incumbent + best embedding | 2 | 0.839 [0.813, 0.860] | 0.856 |
| one per family | 3 | 0.867 [0.842, 0.888] | 0.881 |
| **everything** | 10 | **0.900 [0.878, 0.919]** | 0.912 |

A perfect selector would score **0.900** — +0.129 over the incumbent, with disjoint
intervals. The families genuinely disagree; MiniLM alone rescues 70 of the incumbent's
231 errors. **So the "uniformly weaker, not differently-wrong" prior was wrong.**

**And every reachable ensemble lands exactly on the incumbent:**

| Member set | n | val macro-F1 | vs incumbent |
| --- | ---: | --- | ---: |
| one per family | 3 | 0.772 [0.742, 0.796] | +0.001 |
| linear family | 4 | 0.771 [0.743, 0.796] | +0.000 |
| top 5 by macro-F1 | 5 | 0.772 [0.741, 0.796] | +0.000 |
| everything | 10 | 0.770 [0.741, 0.795] | −0.002 |

Best vote 0.772 vs incumbent 0.771, **McNemar p=1.0000** (24 vs 25 exclusive wins). Four
different member sets, four ties. That is not a marginal result, it is a flat line.

**Why the gap is unreachable — the pairwise table is the whole explanation:**

| Model | disagrees | rescuable | would lose | net |
| --- | ---: | ---: | ---: | ---: |
| E1 linear C=0.5 | 28 | 10 | 8 | **+2** |
| E1 linear C=3 | 18 | 8 | 6 | **+2** |
| E1 logreg C=10 | 135 | 40 | 59 | −19 |
| E2 xgboost svd256 | 181 | 53 | 89 | −36 |
| E3 random forest | 192 | 59 | 94 | −35 |
| E4 minilm + logreg | 271 | **70** | **148** | −78 |
| E3 extra trees | 226 | 39 | 120 | −81 |

**Every diverse model is net negative, and the more diverse it is, the worse the trade.**
MiniLM rescues the most articles (70) and also destroys the most (148) — better than
2:1 against. The only net-positive members are the two C-sweep rungs, which differ from
the incumbent on 18–28 articles and are the same model. So the disagreement is real but
**asymmetric**: a weaker model is far more often wrong where the incumbent is right than
right where the incumbent is wrong. Voting cannot exploit that, because a vote has no
way to know which side of the trade it is on.

- [x] **F2. Refused.** The bar was "only if F1 justifies it". F1 measured the reachable
  gain at +0.001 with p=1.00, so soft voting and stacking are not run. Soft voting would
  face the identical asymmetry with the added cost of calibrating every member (Phase G1
  exists precisely because `LinearSVC` has no probabilities), and stacking a meta-learner
  on 5,487 OOF rows to arbitrate a 2:1-against trade is exactly the kind of complexity
  the plan's tie-breaks are written to reject.

> **The 0.129 oracle gap is the useful artefact, and it belongs to Phase G, not F.** It
> says a *selector* would pay where an *average* does not — and the closest reachable
> thing to a selector is per-class thresholds and abstention. The gap is now the measured
> upper bound on what confidence routing could ever buy.

---

## Phase G — Calibration, confidence, imbalance *(done 2026-08-26)*

This is where the remaining value was, and it delivered — while refuting two of its own
premises. It does not raise macro-F1; it converts a 0.771 classifier into a system that
knows when it is unsure.

> **Toolchain correction:** the plan specified `cv="prefit"`. That was **removed in
> scikit-learn 1.8**; this project runs 1.9. The replacement is
> `CalibratedClassifierCV(FrozenEstimator(fitted), ...)`, which does the same job.

### G1. Calibration — adopted (isotonic, cross-validated on train)

All four rows are scored out-of-sample: the cheap recipe is cross-fitted **within**
validation by story group, because calibrating on validation and then reporting
calibration on that same validation flatters itself.

| Recipe | Method | val macro-F1 | Brier | log loss | ECE | cost |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| — (raw margin) | none | 0.771 [0.743, 0.796] | — | — | — | 11s |
| train 5-fold CV | sigmoid | 0.770 [0.739, 0.795] | 0.2970 | 0.6550 | 0.0641 | 48s |
| **train 5-fold CV** | **isotonic** | **0.769 [0.738, 0.794]** | 0.2981 | **0.6379** | **0.0389** | 47s |
| prefit on val | sigmoid | 0.784 [0.757, 0.808] | 0.2970 | 0.6626 | 0.0820 | 4s |
| prefit on val | isotonic | 0.774 [0.745, 0.798] | 0.3064 | **1.1054** | 0.0429 | 4s |

1. **Calibration is free, again.** 0.769 against a raw 0.771, intervals almost identical.
   v1 measured the same thing (0.720 calibrated vs 0.718 raw). Since `LinearSVC` has no
   `predict_proba` at all, this was never optional — a margin is a signed distance from a
   hyperplane and must never be rendered as a confidence.
2. **The cheap recipe is not good enough, so the plan's shortcut is rejected.** Prefit on
   validation is 10× faster and costs **2× the calibration error** on sigmoid. Isotonic
   is worse still: fitting a step function on ~560 rows produces hard 0s and 1s, and log
   loss blows out to **1.11** against 0.64. `prefit + sigmoid` also shows the highest
   macro-F1 in the table (0.784) *and* the worst ECE — a good reminder that argmax
   accuracy says nothing about whether the number attached to it is honest.
3. **The model is under-confident, not over-confident** — the unusual direction.

| Confidence band | n | claimed | actual | gap |
| --- | ---: | ---: | ---: | ---: |
| 0.2–0.3 | 5 | 0.267 | 0.400 | +0.133 |
| 0.3–0.4 | 29 | 0.361 | 0.448 | +0.087 |
| 0.4–0.5 | 94 | 0.461 | 0.426 | −0.036 |
| 0.5–0.6 | 133 | 0.549 | 0.541 | −0.007 |
| 0.6–0.7 | 148 | 0.651 | 0.689 | +0.038 |
| 0.7–0.8 | 139 | 0.753 | **0.878** | **+0.125** |
| 0.8–0.9 | 191 | 0.852 | 0.853 | +0.002 |
| 0.9–1.0 | 381 | 0.954 | 0.987 | +0.033 |

Most classifiers overclaim. This one underclaims, worst in the 0.7–0.8 band where it is
right 88% of the time while saying 75%. Erring toward caution is the safe direction for
an abstention system, but it means a naive 0.80 cut throws away good work.

### G2. Thresholds — abstention adopted, **per-class cuts rejected**

Cuts fitted on genuinely nested out-of-fold probabilities from train (5 outer × 3 inner
folds, grouped and stratified), so neither the base model nor the calibrator ever saw
the rows a cut is fitted on.

| Class | OOF n | auto cut | auto P | review cut | review P |
| --- | ---: | ---: | ---: | ---: | ---: |
| business_economy | 565 | 0.547 | 0.901 | 0.303 | 0.842 |
| conflict_war | 83 | 0.712 | 0.905 | 0.282 | 0.707 |
| crime_justice | 496 | 0.627 | 0.902 | 0.356 | 0.788 |
| disaster_accident | 258 | 0.411 | 0.902 | 0.312 | 0.872 |
| education | 362 | 0.571 | 0.902 | 0.273 | 0.845 |
| entertainment_arts | 538 | 0.489 | 0.901 | 0.289 | 0.864 |
| environment_climate | 181 | 0.676 | 0.905 | 0.389 | 0.700 |
| health | 382 | 0.598 | 0.902 | 0.278 | 0.830 |
| politics | 1163 | 0.677 | 0.901 | 0.251 | 0.782 |
| science_space | 224 | 0.504 | 0.902 | 0.296 | 0.871 |
| **society_lifestyle** | 211 | **0.677** | **0.909** | 0.465 | 0.702 |
| sport | 542 | **0.345** | **0.952** | 0.345 | 0.952 |
| technology | 482 | 0.617 | 0.902 | 0.321 | 0.811 |

**Every class reaches 90% precision. There are no forced abstainers.**

| Policy on validation | coverage | accuracy on kept |
| --- | ---: | ---: |
| everything, no abstention | 1.000 | 0.795 |
| auto + review | 0.985 | 0.801 |
| **auto only** | **0.761** | **0.879** |

At three precision targets: 80% → coverage 0.922 / accuracy 0.824; 85% → 0.854 / 0.848;
90% → 0.761 / 0.879. A clean, well-behaved dial.

**`society_lifestyle` is not a forced abstainer, and that overturns a v1 decision.** v1
retired it permanently: at headline length its best available cut reached only 0.64
precision, below every other class's *target*. With 500 words of body and honest
calibration it reaches **0.909 at cut 0.677** — a high bar, as expected for a class
scoring F1 0.42, but a reachable one. The class is weak at *ranking*, not at *knowing*:
its confidence carries real signal even though its argmax often does not. **It ships as
a normal class with a high cut, not as a permanent abstainer.**

**The per-class machinery earns nothing, which was not the expected answer:**

| At coverage 0.761 | accuracy on kept |
| --- | ---: |
| per-class cuts | 0.879 |
| one global cut at 0.605 | **0.891** |

About 13 articles in 852 — inside noise, so the honest claim is *"per-class cuts buy
nothing"*, not *"a global cut is better"*. Either way the plan's premise ("never a single
global cut") is refuted, and for a satisfying reason: **G1 already solved the problem G2
was built to solve.** Per-class cuts exist because raw scores are not comparable across
classes. Once isotonic calibration makes them comparable, 0.6 means the same thing
whether the class is `sport` or `society_lifestyle`, and slicing per class is redundant
machinery on top of a fix that already landed. The per-class table is kept as a
**diagnostic** — it is how we learned `society_lifestyle` is usable and that `sport`
bottoms out at 0.345 — but the shipping policy is one global cut.

### G3. Imbalance — `balanced` kept, on the holdout's evidence only

| Weighting | val macro-F1 | Hindu | Guardian |
| --- | --- | ---: | ---: |
| none (plain) | 0.774 [0.745, 0.798] | 0.773 | 0.712 |
| **balanced (incumbent)** | 0.771 [0.743, 0.796] | 0.772 | **0.726** |
| oversampled to 375 (median class) | 0.774 [0.744, 0.798] | 0.773 | 0.712 |

At 6.7:1 the imbalance barely matters. **`class_weight="balanced"` is nominally *worse*
on validation** (−0.003, well inside noise) and its only real effect is **+0.014 on The
Guardian**, the out-of-distribution holdout. Oversampling to the median class size is
indistinguishable from doing nothing — unsurprising, since duplicating rows and
re-weighting them are the same operation with different arithmetic.

Kept, because the project's stated tiebreak is the publisher holdout rather than
validation, and every Phase C–F number was measured with it on. But the honest summary
is that it bought **almost nothing**, and the 6.7:1 imbalance never needed defending.

---

## Phase H — Error analysis, holdouts, selection *(done 2026-08-26 · test split closed)*

The model is chosen: **`word_char_svc`, `title_body` at 4,000 chars,
`class_weight="balanced"`, isotonic calibration cross-validated on train, one global
confidence cut.** Nothing in this phase tunes anything — `scripts/phase_h_analysis.py`
only characterises what was already selected.

### H1. Where the errors are — and how many are the labels' fault

**43 of 231 validation errors (18.6%) sit on the three class pairs Finding 3 measured
human annotators disagreeing on.** Finding 3 put label disagreement at 18–22% of
multi-article story groups. Two independent measurements landing on the same number is
strong evidence that this share of the error budget is **annotation noise, not model
error** — and that chasing it would mean fitting the disagreement.

Top confusions († = a pair humans also disagreed on):

| Actual | Called | n |
| --- | --- | ---: |
| business_economy | politics | 13 † |
| politics | business_economy | 13 † |
| **society_lifestyle** | **politics** | **11** |
| conflict_war | politics | 8 † |
| politics | crime_justice | 8 |
| politics | education | 8 |
| conflict_war | politics *(reverse)* | 6 † |
| society_lifestyle | entertainment_arts | 6 |

The one large confusion **not** covered by human disagreement is
`society_lifestyle → politics`, which is the class's own definition problem showing up
again rather than a boundary two reasonable people would argue over.

**Only 5 of 230 errors are made at confidence ≥ 0.90** — the calibration is doing its
job, and the dangerous failure mode (confidently wrong, invisible to a reviewer) is
rare. The ten worst are genuine boundary cases, not nonsense: *"Amazon hikes hardware
prices by 60 percent, blaming memory"* called `technology` when it was labelled
`business_economy`; *"The UK will help Ukraine make long-range missiles"* called
`politics` when labelled `conflict_war`. A human would hesitate on most of them.

*(231 errors raw vs 230 calibrated: isotonic calibration flips one argmax.)*

### H2. Publisher holdouts — the final read

| Publisher | n held | macro-F1 | vs validation |
| --- | ---: | --- | ---: |
| The Hindu | 738 | 0.772 [0.727, 0.805] | **+0.001** |
| The Guardian | 665 | 0.726 [0.681, 0.765] | −0.045 |

**The main new risk the body introduced did not materialise.** Bodies carry far more
house style than headlines, so this was the place v2 could legitimately have got worse
than v1. In-distribution (The Hindu) the drop is **zero**. Out-of-distribution (The
Guardian — non-Indian, different house style and vocabulary) it is −0.045, and the
interval **overlaps validation**, so even that is not statistically separable. The Phase
A boilerplate and affix work is the likely reason.

### H3. Temporal split vs random split

| Split | macro-F1 |
| --- | --- |
| temporal (shipping) | 0.771 [0.743, 0.796] |
| random, grouped | 0.752 [0.722, 0.777] |

Delta −0.019, intervals overlap. **The temporal split is not costing anything**, which
means no drift is detectable — as expected across four days. Stated plainly: *neither
number says anything about drift over weeks.* The publisher holdouts carry the whole
generalisation argument until the collector has run longer.

### H5. Class support — which scores mean anything

| Class | train | val | F1 | 95% interval | width |
| --- | ---: | ---: | ---: | --- | ---: |
| sport | 532 | 91 | 0.95 | [0.92, 0.98] | 0.06 |
| entertainment_arts | 523 | 116 | 0.89 | [0.84, 0.93] | 0.09 |
| science_space | 233 | 57 | 0.86 | [0.78, 0.92] | 0.15 |
| disaster_accident | 268 | 63 | 0.84 | [0.76, 0.91] | 0.15 |
| business_economy | 580 | 168 | 0.83 | [0.79, 0.87] | 0.08 |
| technology | 452 | 66 | 0.81 | [0.73, 0.88] | 0.14 |
| crime_justice | 495 | 92 | 0.79 | [0.72, 0.85] | 0.13 |
| politics | 1075 | 213 | 0.78 | [0.73, 0.82] | 0.09 |
| conflict_war | 120 | 55 | 0.74 | [0.62, 0.83] | 0.22 |
| health | 375 | 50 | 0.72 | [0.61, 0.81] | 0.21 |
| **education** | 349 | **29** | 0.71 | [0.56, 0.82] | **0.25** — thin, read as noise |
| environment_climate | 178 | 54 | 0.69 | [0.57, 0.78] | 0.20 |
| society_lifestyle | 307 | 66 | 0.42 | [0.31, 0.53] | 0.22 |

All 13 classes train and are reported — `out_of_scope` is empty, as designed.
**`education`'s 29 validation articles make its 0.71 a quarter of an F1 point wide**;
this is exactly the situation v1 read as signal. Only `sport`, `entertainment_arts`,
`business_economy` and `politics` have intervals tight enough (≤0.09) to compare
between runs. `society_lifestyle`'s ceiling of 0.53 is below every other class's floor.

### H6. Behaviour on news nobody labelled

1,260 unlabelled articles from the validation window. Confidence looks healthy: median
**0.79**, 32.5% above 0.90, 13.3% below 0.50 — a sane spread, not a model that is sure
of everything or nothing.

**The predicted mix leans toward the big classes:** `politics` 30.4% predicted against a
19.5% share of the gold labels, `crime_justice` 13.5% vs 8.9%; while `conflict_war`
(0.3% vs 2.6%), `science_space` (0.8% vs 4.4%) and `health` (2.6% vs 6.4%) are
under-called.

> **This comparison is confounded and must not be read as majority-class collapse.** The
> gold label distribution is **not** the corpus prevalence: v1's round-2 and round-3
> samplers deliberately over-retrieved rare classes to raise the class floor, so
> `conflict_war` is far better represented in the gold set than in real news. The
> divergence is a hypothesis worth testing against a random sample, not a measured
> defect. **Deferred to a labelled random slice**, which does not exist yet.

**The abstention design works.** Of the 63 `unsorted` gold rows — decision #8's
abstention evaluation set — the 40 outside the test split score a median confidence of
**0.70 against 0.81** on labelled validation, and **75% fall below the labelled median**.
The model is measurably less sure about articles humans could not classify either.

### H4. The test split — opened once, 2026-08-26, and now closed

`scripts/phase_h4_open_test.py`, the single greppable door
(`open_the_test_split_once`), refuses to run without `--yes`. Fitted on train only, so
it scores the same model every earlier decision was made against.

| | macro-F1 | accuracy |
| --- | --- | ---: |
| validation | 0.771 [0.743, 0.796] | 0.794 |
| **test** | **0.751 [0.719, 0.780]** | 0.778 |

**Delta −0.021 against a ±0.05 guard, intervals overlapping. The validation number held
up on data the model had never seen.** No investigation triggered, and nothing was
changed in response.

Per class, test against validation:

| Class | test F1 | support | val F1 | delta |
| --- | ---: | ---: | ---: | ---: |
| sport | 0.95 | 86 | 0.95 | +0.00 |
| disaster_accident | 0.87 | 62 | 0.84 | +0.03 |
| entertainment_arts | 0.85 | 82 | 0.89 | −0.04 |
| crime_justice | 0.82 | 113 | 0.79 | +0.03 |
| technology | 0.81 | 106 | 0.81 | −0.00 |
| science_space | 0.81 | 81 | 0.86 | −0.05 |
| business_economy | 0.78 | 152 | 0.83 | −0.05 |
| politics | 0.76 | 238 | 0.78 | −0.01 |
| environment_climate | 0.71 | 62 | 0.69 | +0.02 |
| health | 0.69 | 53 | 0.72 | −0.03 |
| education | 0.65 | 15 | 0.71 | −0.06 |
| **conflict_war** | **0.60** | 51 | 0.74 | **−0.14** |
| society_lifestyle | 0.44 | 58 | 0.42 | +0.02 |

**`conflict_war` is the only class that moved more than the guard**, and it is the
thinnest class in the corpus (120 train articles). Its validation interval was
[0.62, 0.83], so 0.60 sits just below the floor — a thin class behaving like a thin
class, which is precisely what H5 flagged in advance. Its dominant test confusion,
`conflict_war → politics` (21), is a Finding 3 human-disagreement pair.

**The shipping policy on test**, with the cut taken from train out-of-fold probabilities
and never fitted on anything scored here:

| | value |
| --- | ---: |
| global cut | 0.584 (90% precision on train OOF) |
| coverage | 0.807 |
| **accuracy on filed articles** | **0.834** |
| accuracy if it never abstained | 0.777 |
| **ECE on test** | **0.0211** |

**Calibration generalised better than it validated** — test ECE 0.021 against validation's
0.039. The confidence number is trustworthy on unseen data, which is the whole point of
Phase G.

| Cost | |
| --- | ---: |
| predict | 0.784 ms/article |
| bundle | 46.2 MB (joblib, uncalibrated estimator) |

Against v1's 0.05 ms and 11 MB: ~15× slower and ~4× larger, which is the price of
4,000 characters of body plus character n-grams. Still trivial in absolute terms.

### Still open

- [ ] **H7. Results notebook** driving the charts (notebooks call `src/`, never define
  logic). The comparison table itself is now the *Results so far* section plus H2/H4/H5.

**Then stop and review.** Serving, stress testing and packaging are decided after these
numbers exist.

---

## Deferred — planned, not in scope yet

- Robustness / stress tests: short, long, malformed, missing title, missing body, unseen
  publishers, syndicated, paraphrased, breaking-news, multi-topic articles.
- FastAPI `/predict` service with the agreed JSON contract, plus latency and memory
  benchmarks.
- Artifact versioning strategy and README.
- **Fine-tuned transformer** (DeBERTa-v3-small / DistilRoBERTa). Likely the single biggest
  accuracy lever left, but deliberately sequenced *after* the body A/B: running both at
  once makes it impossible to attribute the gain, and if bodies alone suffice, a 250 MB
  model is not worth it. Also sits outside the course's classical-ML syllabus.

---

## Verification

1. `make ml2-test` green, including regression tests for the three known text traps
   (curly-quote fold, title-only service bulletins, no `travel` in the pattern).
2. `newsmlv2 snapshot --id v2-<date>` → `verify` reproduces digests byte-identically.
3. Near-dup scores **precision 0.86 at recall 0.81** on v1's 43-pair census, clearing the
   0.80 precision ceiling v1 proved a single threshold had. (Recall bar restated from
   0.90 — see A3 and the decision log for why it is unreachable by text similarity.)
4. No story group spans splits, in any of the three regimes.
5. `reports/data-quality.md` answers all 14 data-quality items.
6. Ledger has one row per run with config hash and git sha; the comparison table renders
   with group-resampled CIs and a publisher-holdout column from Phase C onward.
7. The body-vs-no-body A/B is reported as one number with a CI. **DONE: +0.059
   [disjoint intervals], McNemar p=7.5e-06.**
8. **Publisher probe run before and after D0** — publisher-prediction accuracy must fall,
   and each retained D0 rule shows a larger gain on the publisher holdout than on
   validation.
9. Both baselines reported: v1-parity rung on the v2 snapshot, and the historical 0.720
   clearly labelled as cross-snapshot context.
10. Every complexity decision cites a McNemar p-value or an overlapping CI. **DONE for
    D0, D, E, F and G — every rejected option has a measured interval against the
    incumbent; the ensemble refusal cites McNemar p=1.0000, and per-class thresholds
    were rejected against a global cut at matched coverage.**
11. `out_of_scope` is **empty in every run**, asserted in tests. The class-support report
    lists all 13 classes with train/val support. **DONE — H5, all 13 with per-class CIs.**
12. Test split touched exactly once. **DONE 2026-08-26 — `phase_h4_open_test.py`,
    `open_the_test_split_once`, `--yes` required. Now closed for good.**
13. Latency and bundle size benchmarked. **DONE — 0.784 ms/article, 46.2 MB.**
14. **Confidence is a calibrated probability, never a raw margin**, and its reliability
    is reported out-of-sample. **DONE: ECE 0.039, log loss 0.638, macro-F1 unchanged.**

---

## Decisions

| # | Decision | Rationale |
| --- | --- | --- |
| 1 | **Improve, don't port** | v1's *measurements* are inherited as constraints and test cases; its *implementations* are not |
| 2 | **Body text is the hypothesis, not a given** | no CI-backed gain ⇒ stay on short text and record the negative result; that is a valid outcome |
| 3 | Gold labels **vendored + digest-pinned, not committed** | user keeps an external backup. Known gap: no git commit contains the 8,001-label file, so the manifest sha256 is the only integrity anchor |
| 4 | **Snapshot cut `collected_before` = 2026-08-26T12:00:00Z, frozen** | a mid-project re-cut makes every earlier number incomparable. The timestamp is pinned by two constraints: it must fall **after** the last gold label (09:49:39Z) or labelled articles are dropped, and **in the past** or the collector keeps adding rows inside the window and the snapshot stops being reproducible |
| 5 | Near-dup on **body**, two-stage, cosine-verified | bodies are a far stronger duplicate signal than a reworded headline |
| 6 | Time split on `collected_at` only | a 2019 article can arrive tomorrow; `published_at` would leak |
| 7 | **Two publisher holdouts** (The Hindu, The Guardian), scored every run | The Indian Express excluded — 21% of labels would confound the result |
| 8 | The 63 `unsorted` rows are the **abstention evaluation set** | a good model should decline to classify them |
| 9 | **No class is ever dropped** | floor derived as the smallest class; `unsorted` excluded before the minimum; all 13 train by construction |
| 10 | D0 cleaning is **signal correction** | furniture creates publisher→class shortcuts; a rule is kept only if it helps the holdout more than val |
| 11 | Body NLP is an **ablation set** | adopted only on a CI-backed gain, and never applied to near-dup text |
| 12 | **Macro-F1 has a ceiling below 1.0** | measured label disagreement on conflict_war↔politics, business_economy↔politics, crime_justice↔disaster_accident |
| 13 | Randomized search, fixed iteration cap | the space multiplies out and each fit is now ~100× longer; budget is better spent on more model families than a finer grid |
| 14 | Embeddings encoded on **CPU** | GPU/MPS is not bit-reproducible and would break snapshot reproducibility |
| 15 | POC — one dependency set | no packaging ceremony. If it doesn't beat v1, the transformer gets ditched |
| 16 | Test split closed until H4 | one door, greppable, opened once |
| 17 | **Confidence is an isotonic-calibrated probability from train CV, not a margin and not calibrated on val** | a `LinearSVC` margin has no scale; calibrating on val costs 2× ECE and blows log loss to 1.11 on ~560 rows |
| 18 | **One global confidence cut, not per-class** | calibration already made scores comparable across classes, so per-class cuts scored 0.879 against a global 0.891 at matched coverage. The per-class table survives as a diagnostic |

---

## Open considerations

1. **The classifier was never the bottleneck; the data preparation was.** Phase A bought
   +0.075 over v1-parity. Phases D0, D, E and F added **nothing** between them. If more
   accuracy is wanted, the evidence points at labels and taxonomy, not at models.
   Phase F puts a number on the remaining modelling headroom: **0.129 to a perfect
   selector**, and no averaging method can collect any of it.
2. **`society_lifestyle` is a ranking problem, not a knowledge problem — revised after
   G2.** Its F1 is 0.42 at headline length (v1) and 0.42 at 500 words (v2), so the class
   definition really is muddled, and Finding 3 shows humans disagree on it too. **But its
   calibrated confidence reaches 90% precision at cut 0.677**, where v1 could not clear
   0.64 at any cut. So it knows when it is right even though it is often wrong — which is
   why it ships with a high cut rather than as v1's permanent forced abstainer. Splitting
   or narrowing the class would still buy more than any modelling change.
3. **A longer-context encoder is the one untested modelling idea with a real rationale.**
   MiniLM's 256-token window provably cannot see the body advantage. That is a specific,
   falsifiable reason to expect better from a long-context model — unlike the tree
   families, which failed for structural reasons that more capacity would not fix.
   Still gated behind the same rule: only if it clears the incumbent's interval.
4. **Body length is no longer a risk.** Measured: the curve flattens after ~2,048 chars,
   so the 175k-char outlier is irrelevant once truncation is in place.
5. **The 3-day `collected_at` window remains a weak drift test** and no modelling fixes
   it. The two publisher holdouts carry the generalization argument; a real drift test
   needs the collector running several more weeks.
6. **Upstream: fix the BBC scraping technique** (user TODO, 2026-08-26). 25 BBC bodies are
   scraped navigation menus rather than article text. ml-v2 works around it by dropping
   the body and falling back to title+summary, but the real fix is in the Go collector's
   extractor. Low urgency at 0.19% of the corpus.

---

## Decision log

Append newest at the top. One line of rationale each.

| Date | Decision |
| --- | --- |
| 2026-08-26 | **H4: the test split was opened once, and the result held.** Test macro-F1 **0.751 [0.719, 0.780]** against validation's 0.771 — delta −0.021 on a ±0.05 guard, intervals overlapping. Nothing was changed in response, and the split is now closed for good. The shipping policy files **80.7% of articles at 83.4% accuracy** against 77.7% with no abstention, and **test ECE (0.021) is better than validation's (0.039)** — the calibration generalised. Only `conflict_war` moved more than the guard (0.74 → 0.60), and it is the thinnest class at 120 train articles, sitting just below the validation interval H5 had already flagged as unreliable. Cost: 0.784 ms/article, 46.2 MB — ~15× slower and ~4× larger than v1, which is what 4,000 characters of body plus char n-grams costs. |
| 2026-08-26 | **Phase H6: the live-news prediction mix leans to the big classes, but the obvious reading of that is wrong.** `politics` is called on 30.4% of unlabelled articles against a 19.5% gold share, `conflict_war` on 0.3% against 2.6%. That looks like majority-class collapse — except **the gold distribution is not the corpus prevalence**: v1's round-2/3 samplers deliberately over-retrieved rare classes to raise the class floor. The comparison is confounded and is recorded as a hypothesis needing a labelled random slice, not as a defect. Confidence itself is healthy (median 0.79). Separately, the abstention design is confirmed: on the 63 `unsorted` gold rows the model's median confidence is **0.70 against 0.81**, with 75% below the labelled median. |
| 2026-08-26 | **Phase H1–H5: the error budget is ~19% annotation noise, and the body's main risk did not materialise.** 43 of 231 validation errors fall on the three pairs Finding 3 measured humans disagreeing on — independently reproducing that finding's 18–22% estimate, and marking that share as a ceiling rather than a bug. Only **5 of 230 errors are made above 0.90 confidence**, so the invisible-failure mode is rare. The publisher holdout, the main new risk of using bodies, came in at **+0.001 on The Hindu** and −0.045 on The Guardian with overlapping intervals. The temporal split costs nothing against a random one (0.771 vs 0.752, overlapping), which means four days is too short to see drift, not that there is none. **`education` has 29 validation articles and an interval 0.25 wide** — only four classes are precise enough to compare between runs. |
| 2026-08-26 | **Phase G3: `class_weight="balanced"` bought almost nothing, and is kept on the holdout's evidence alone.** Plain 0.774 / balanced 0.771 / oversampled-to-median 0.774 on validation — balanced is nominally *worse*. Its only real effect is **+0.014 on The Guardian**, the out-of-distribution holdout, which is the project's stated tiebreak. Oversampling is indistinguishable from plain, as expected: duplicating rows and re-weighting them are the same operation. At 6.7:1 the imbalance never needed defending. |
| 2026-08-26 | **Phase G2: abstention adopted, per-class cuts rejected — because G1 already fixed what they were for.** Filing only the confident 76% lifts accuracy 0.795 → **0.879**, a clean dial (80% target → 92% coverage, 90% → 76%). But per-class cuts score **0.879 against a single global cut's 0.891** at matched coverage, i.e. nothing, because isotonic calibration already made scores comparable across classes and that comparability was the entire reason to slice per class. **`society_lifestyle` reaches 90% precision at cut 0.677 and is no longer a forced abstainer**, overturning v1's permanent retirement of it: it is weak at ranking, not at knowing. Every one of the 13 classes clears 90%. |
| 2026-08-26 | **Phase G1: calibration is free again, and the plan's cheap recipe is rejected.** Isotonic cross-validated on train gives ECE **0.039** / log loss **0.638** at macro-F1 0.769 vs a raw 0.771. Calibrating on validation instead — the plan's `cv="prefit"` shortcut — doubles ECE on sigmoid and blows isotonic's log loss out to **1.11**, because a step function fitted on ~560 rows emits hard 0s and 1s. That row also posts the table's *highest* macro-F1 (0.784) alongside its *worst* ECE, a reminder that argmax accuracy says nothing about whether the attached number is honest. The model is **under**-confident: in the 0.7–0.8 band it is right 88% of the time while claiming 75%. **Toolchain note: `cv="prefit"` was removed in scikit-learn 1.8; `FrozenEstimator` is the replacement.** |
| 2026-08-26 | **Phase F: the models ARE complementary and an ensemble still does not help — the prior was wrong for an interesting reason.** A perfect selector would score **0.900 [0.878, 0.919]** against the incumbent's 0.771, intervals disjoint, so the diversity is real. But four different majority votes all land on 0.770–0.772 with **McNemar p=1.0000**. The pairwise table explains it: every diverse member is **net negative** because the disagreement is asymmetric — MiniLM rescues 70 of the incumbent's errors and destroys 148 of its correct answers, better than 2:1 against. A vote has no way to tell which side of that trade it is on; only a selector could, and that is Phase G's per-class thresholds, not an average. **F2 refused on this evidence rather than run.** |
| 2026-08-26 | **Phase E: the linear model wins outright; nothing else is close.** XGBoost −0.036, Random Forest −0.041, Extra Trees −0.087, MiniLM −0.061, all at higher cost and lower on *both* publisher holdouts. Giving XGBoost more capacity (512 components, depth 8) made it **worse**, which is a wrong-inductive-bias signature rather than under-fitting. MiniLM's 0.710 is almost exactly the title+summary TF-IDF score, because its **256-token window** cannot reach the body text that produced v2's gain — so E4 is a limitation of that encoder, not a verdict on semantics. |
| 2026-08-26 | **Phase D: body length settled at 4,000 chars; title up-weighting refuted.** The length curve flattens after ~2,048 (all intervals overlap), and 4,000 wins the tiebreak on publisher holdout. Repeating the title degrades monotonically (×1 0.783 → ×5 0.751), which settles field weighting in the *opposite* direction to the prior and removes a whole tuning dimension. |
| 2026-08-26 | **Phase D0: no scrubbing rule adopted, and the acceptance test earned its keep.** `person+place+numbers+lemmatise` *improves validation* (+0.002) while *losing 0.018 of publisher generalization* — on validation alone it looks like the winner. The publisher probe barely moves (0.482 → 0.471) because **Phase A already removed the fingerprints**. Lemmatisation was the only rule to make the probe *worse*, vindicating the brief's warning against blind NLP preprocessing. |
| 2026-08-26 | **Two toolchain traps recorded.** XGBoost needs `brew install libomp` on macOS and refuses string class labels (wrapped in `_StringLabels` so the registry stays interchangeable). sentence-transformers crashes under `nohup` — its forked workers cannot reinitialise closed stdin — so it must run in the foreground. |
| 2026-08-26 | **`bool(nan)` is `True`, and it silently reintroduced v1's worst split bug.** An unlabelled row's `topic` is `NaN` in pandas, so `bool(r.topic)` marked every row as labelled, the cuts fell back to corpus-wide quantiles, and the labelled split came out **79/12/9** instead of 70/15/15. The unit test written to catch exactly this passed, because its fixture used a real `bool`. Fixed with `isinstance(r.topic, str)`; the snapshot test now asserts split proportions on the **real** frozen data, which is the only place the bug was visible. |
| 2026-08-26 | **Boilerplate must be keyed on publisher, not section feed, and found at three levels.** Line-level discovery alone missed two whole classes: scrapers that emit a body as a *single line* (The Economic Times' `Listen to this article in summarized format`) needed **sentence-level** splitting, and chrome concatenated without punctuation (the BBC's `Related topics MoneyUpdates from your News topics...`) needed **common prefix/suffix** detection. Keying on `source_name` also put each of the BBC's six feeds under the discovery floor. Together these merged **38, 21 and 20 unrelated articles** into single story groups at 0.99 similarity. After the fix the largest groups are genuine syndication. |
| 2026-08-26 | **Near-dup recall bar restated 0.90 → 0.80.** Precision now reaches 0.86 (v1 proved 0.80 was its ceiling), but recall plateaus at 0.84 even at a cut of 0.30, because ~5 of 31 judged same-story pairs share almost no vocabulary. Same shape as v1's own restatement, in the opposite direction. |
| 2026-08-26 | **Boilerplate discovery validated on the real corpus.** 355 lines across 47 sources, **19 of them longer than 25 words** — exactly the author bios v1's cap made unreachable, including a 112-word Livemint cricket-correspondent bio in 36% of its Sports bodies. Cleaning removes only **1.2%** of body text corpus-wide, so it is not eating reporting. 7 bodies clean to nothing, all Deccan Herald `DH Toon` cartoons, which admission will reject. |
| 2026-08-26 | **Navigation bodies found and handled.** 25 of 13,133 bodies (0.19%, almost all BBC) are scraped menus or video carousels rather than prose; 8 carry gold labels. Per-source boilerplate cannot catch them because every carousel lists different titles. Handled with a one-line share-of-short-lines guard that **drops the body and falls back to title+summary**, rather than rejecting an article whose headline is perfectly good. |
| 2026-08-26 | **Corpus cut corrected to 12:00:00Z.** A midnight cut silently dropped **477 of 8,001** gold labels — articles collected this morning carry labels. The cut must sit after the last gold label *and* in the past. Caught by the Phase A smoke test, not by inspection. |
| 2026-08-26 | Plan created. Publisher holdouts fixed as The Hindu + The Guardian; class floor made data-derived; Phase D0 added after measuring publisher fingerprints in bodies; transformer deferred behind the body A/B. |
