# Data quality report — snapshot `v2-001`

Frozen corpus cut `2026-08-26T12:00:00+00:00`. Cleaning version 2.0.0, taxonomy v4, seed 20260823.

> Generated from the snapshot, not from a live query, so every number here is reproducible from the manifest digests.

## 1. Shape

| Measure | Value |
| --- | --- |
| Articles read | 14,189 |
| Admitted | 13,607 |
| Rejected | 582 (4.1%) |
| Labelled | 7,919 of 8,001 offered |
| `unsorted` (abstention set) | 50 |
| Story groups | 12,608 |
| Publishers | 38 |
| Section feeds | 95 |

## 2. Fields available

| Field | Non-empty |
| --- | --- |
| title | 100.0% |
| summary | 79.2% |
| body | 94.9% |
| published_at | 100.0% |
| collected_at | 100.0% |
| categories | 64.6% |
| dateline_city | 2.7% |
| wire_agency | 0.9% |

**Body is present for 94.9% of admitted articles.** That is the whole premise of v2: v1 classified on title+summary alone.

## 3-4. Classes and distribution

| Class | Labelled | Share |
| --- | --- | --- |
| politics | 1,571 | 19.8% |
| business_economy | 916 | 11.6% |
| entertainment_arts | 734 | 9.3% |
| crime_justice | 723 | 9.1% |
| sport | 716 | 9.0% |
| technology | 630 | 8.0% |
| health | 486 | 6.1% |
| society_lifestyle | 439 | 5.5% |
| disaster_accident | 401 | 5.1% |
| education | 398 | 5.0% |
| science_space | 373 | 4.7% |
| environment_climate | 298 | 3.8% |
| conflict_war | 234 | 3.0% |

Imbalance **6.7:1** (politics 1,571 vs conflict_war 234). Handled by class weighting, not resampling.

## 5. Missing values

| Gap | Articles |
| --- | --- |
| No body | 688 |
| No summary | 2,834 |
| Neither body nor summary (title only) | 150 |
| No published_at | 0 |

## 6, 11. Exact duplicates

5 articles rejected on a repeated content hash. Distinct URLs among admitted: 13,607 of 13,607.

## 7, 12, 14. Near-duplicates and syndication

| Group size | Groups |
| --- | --- |
| 1 article | 11,946 |
| 2 articles | 472 |
| 3 articles | 121 |
| 4 articles | 43 |
| 5 articles | 9 |
| 6 articles | 9 |
| 7 articles | 1 |
| 8 articles | 2 |
| 9 articles | 1 |
| 11 articles | 1 |
| 13 articles | 2 |
| 14 articles | 1 |

**999 articles (7.3%) fold into a larger story group** — 1,349 pairs merged, 378 rejected as recurring templates by the time-gap guard.

Story groups spanning more than one publisher: **481** — these are the syndicated copies that would leak across a split if left ungrouped.

## 8-9. Article length

| Measure | Value |
| --- | --- |
| Words (p10/p50/p90/p99) | 68 / 587 / 1,172 / 2,304 |
| Body chars (p10/p50/p90/p99) | 862 / 3,313 / 6,646 / 13,668 |
| Shorter than 60 words | 1,130 |
| Body longer than 20,000 chars | 56 |
| Longest body | 175,331 chars |

The longest body is 53x the median. Body reduction is a Phase D decision, not a detail.

## 10. Publishers

| Publisher | Articles | Labelled | Classes covered |
| --- | --- | --- | --- |
| The Indian Express | 2,116 | 1,681 | 13 |
| The Hindu | 1,693 | 894 | 13 |
| India Today | 1,354 | 195 | 13 |
| Hindustan Times | 1,218 | 524 | 13 |
| NDTV | 1,051 | 373 | 13 |
| The New Indian Express | 1,014 | 600 | 13 |
| Livemint | 933 | 591 | 13 |
| The Guardian | 900 | 795 | 13 |
| Deccan Herald | 759 | 332 | 13 |
| BBC News | 453 | 343 | 13 |
| Phys.org | 236 | 231 | 11 |
| Deutsche Welle | 208 | 132 | 11 |

Holdouts: The Hindu, The Guardian — chosen because they cover all 13 classes. A section feed cannot be held out: it carries one or two classes, so macro-F1 over it is arithmetic noise.

## 13. Timestamps and the split

| Measure | Value |
| --- | --- |
| collected_at range | 2026-08-22 17:27 → 2026-08-26 11:57 |
| published_at range | 2025-09-06 → 2026-08-26 |
| train until | 2026-08-24T14:58:42.877000+00:00 |
| val until | 2026-08-25T12:31:39.883000+00:00 |
| Labelled by split | {'train': 5487, 'val': 1120, 'test': 1159, 'dropped': 153} |

The split is on `collected_at`, never `published_at` — a 2019 article can arrive in the feed tomorrow. **The window is only 3 days**, so this is a weak drift test; the publisher holdouts carry the generalization argument.

## Rejections

| Reason | Articles |
| --- | --- |
| implausible_timestamp | 238 |
| too_short | 142 |
| non_article_format | 128 |
| service_bulletin | 38 |
| sponsored | 31 |
| exact_duplicate | 5 |

Every gate is a switch on `admit.Policy`, so Phase C can price each one by disabling it and re-scoring.
