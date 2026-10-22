# Model card — `calibrated_linear_svc-20260825-121`

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
| Trained at | 2026-08-25T12:56:43+00:00 |
| Git SHA | `7acabdbf200e3616661ede3e011ddc6e527ea133` |
| Dataset snapshot | `20260825-121` |
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
| Macro-F1 | 0.671 |
| Accuracy | 0.757 |
| Coverage after abstention | 87.9% |
| Accuracy on the articles it files | 0.812 |
| Inference | 0.049 ms/article |
| Bundle size | 11.7 MB |
| Training articles | 3,002 |

Macro-F1 is the headline, not accuracy: with this many classes a model that
ignores every small class still posts a respectable accuracy.

## Per class

| Class | Train | Val | F1 | Cut | Precision at the cut | Reached target |
| --- | --- | --- | --- | --- | --- | --- |
| `sport` | 229 | 83 | 0.90 | 0.00 | 0.90 | yes |
| `business_economy` | 314 | 71 | 0.86 | 0.00 | 0.80 | yes |
| `disaster_accident` | 90 | 43 | 0.83 | 0.00 | 0.82 | yes |
| `politics` | 504 | 178 | 0.82 | 0.21 | 0.80 | yes |
| `education` | 232 | 14 | 0.79 | 0.44 | 0.83 | yes |
| `crime_justice` | 221 | 51 | 0.75 | 0.33 | 0.80 | yes |
| `technology` | 346 | 41 | 0.74 | 0.00 | 0.80 | yes |
| `entertainment_arts` | 315 | 33 | 0.69 | 0.47 | 0.81 | yes |
| `science_space` | 156 | 23 | 0.61 | 0.48 | 0.82 | yes |
| `health` | 256 | 23 | 0.55 | 0.49 | 0.85 | yes |
| `conflict_war` | 61 | 21 | 0.47 | 0.39 | 0.60 | **no** |
| `environment_climate` | 93 | 16 | 0.43 | 0.45 | 0.50 | **no** |
| `society_lifestyle` | 185 | 40 | 0.30 | — | — | **forced abstain** |

Target precision was 80%. Classes that never reach it at
any cut: `conflict_war`, `environment_climate`. Those are not thresholds that need tuning — they are
classes the model cannot yet separate, and the cut simply cannot rescue them.
Classes barred from ever being emitted, by decision rather than measurement: `society_lifestyle`.

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
