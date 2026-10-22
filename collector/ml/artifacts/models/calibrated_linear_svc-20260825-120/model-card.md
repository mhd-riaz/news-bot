# Model card — `calibrated_linear_svc-20260825-120`

Written by `newsml train`. Do not edit by hand; retrain instead.

## What it does

Reads a news headline and its opening sentence (`title_summary`) and files
it under one of 13 topics, or declines and returns `unsorted`.
It is a linear model over word n-grams. It does not read the article body:
body availability tracks the publisher rather than the topic, so training on
it would teach the model to recognise the newspaper.

## Provenance

| Field | Value |
| --- | --- |
| Model | `calibrated_linear_svc` |
| Trained at | 2026-08-25T10:43:22+00:00 |
| Git SHA | `7acabdbf200e3616661ede3e011ddc6e527ea133` |
| Dataset snapshot | `20260825-120` |
| Corpus cut | 2026-08-25T00:00:00+00:00 |
| Cleaning version | `1.2.0` |
| Taxonomy version | `4` |
| Seed | `20260823` |
| scikit-learn | 1.9.0 |
| Serving | python-sidecar |

Every label it was trained on is human. Weak labels derived from RSS section
names agree with a person only about 74% of the time and cannot express
`crime_justice`, `conflict_war` or `disaster_accident` at all, because no
publisher runs those sections.

## How it scored

On the validation split. **The test split has not been opened.**

| Metric | Value |
| --- | --- |
| Macro-F1 | 0.678 |
| Accuracy | 0.760 |
| Coverage after abstention | 89.8% |
| Accuracy on the articles it files | 0.813 |
| Inference | 0.052 ms/article |
| Bundle size | 11.0 MB |
| Training articles | 2,818 |

Macro-F1 is the headline, not accuracy: with this many classes a model that
ignores every small class still posts a respectable accuracy.

## Per class

| Class | Train | Val | F1 | Cut | Precision at the cut | Reached target |
| --- | --- | --- | --- | --- | --- | --- |
| `sport` | 216 | 88 | 0.91 | 0.00 | 0.93 | yes |
| `business_economy` | 292 | 54 | 0.83 | 0.31 | 0.81 | yes |
| `politics` | 453 | 174 | 0.83 | 0.18 | 0.80 | yes |
| `technology` | 344 | 40 | 0.81 | 0.00 | 0.84 | yes |
| `disaster_accident` | 74 | 32 | 0.77 | 0.00 | 0.80 | yes |
| `crime_justice` | 191 | 53 | 0.77 | 0.00 | 0.81 | yes |
| `education` | 230 | 14 | 0.77 | 0.00 | 0.83 | yes |
| `science_space` | 154 | 24 | 0.67 | 0.37 | 0.82 | yes |
| `entertainment_arts` | 302 | 33 | 0.66 | 0.48 | 0.81 | yes |
| `health` | 247 | 22 | 0.57 | 0.56 | 0.80 | yes |
| `environment_climate` | 89 | 14 | 0.46 | 0.42 | 0.60 | **no** |
| `conflict_war` | 48 | 15 | 0.44 | 0.38 | 0.50 | **no** |
| `society_lifestyle` | 178 | 37 | 0.33 | 0.35 | 0.50 | **no** |

Target precision was 80%. Classes that never reach it at
any cut: `conflict_war`, `environment_climate`, `society_lifestyle`. Those are not thresholds that need tuning — they are
classes the model cannot yet separate, and the cut simply cannot rescue them.

## Known weaknesses

- **Short text.** A headline and one sentence is 20-60 words. Some articles are
  genuinely ambiguous at that length, and no threshold fixes that.
- **Small classes are measured noisily.** The split is temporal, which
  concentrates rare classes into very few validation articles. A per-class score
  with single-digit support is not a result; the Val column above is there so
  that is visible rather than implied.
- **Drift is unmeasured.** The corpus spans days, not months, so nothing here
  says how the model ages. Decide a retraining trigger before relying on it.
- **One annotator.** The labels come from a single person, so annotator bias and
  the model's bias are not independent.
- **English only.** Every configured source is an English feed; language is
  assumed from configuration rather than detected.

## What it must not be used for

- Deciding anything about a person. It classifies subject matter, nothing else.
- Any claim about how much coverage a topic receives: the class mix reflects
  which feeds were configured, not what was published in the world.
- Redistribution of the training corpus, which is third-party copyrighted text
  collected for study.
