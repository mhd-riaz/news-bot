# Model card — news topic classifier

**Snapshot** `v2-001` · fitted 2026-08-27T00:02:44+05:30 · cleaning
v2.0.0 · label digest `8ed59b13d414…`

## What it does

Files an English-language news article into one of 13 topics, and
**declines to answer when it is not confident enough**. Confidence is a calibrated
probability, never a raw SVM margin.

## Recipe

| | |
| --- | --- |
| Estimator | `word_char_svc` — word 1–2 grams + char\_wb 3–5 grams on the first 600 chars → LinearSVC (C=1, `class_weight="balanced"`) |
| Input | `title_body`, body capped at 4000 characters |
| Calibration | isotonic, 5 grouped folds of train, averaged |
| Abstention | one global cut at **0.584**, fitted on train out-of-fold probabilities for 90% precision |
| Trained on | 5,487 articles (train split only) |
| Bundle | 148.3 MB · 3.74 ms/article |

## How good it is

| | macro-F1 | accuracy |
| --- | --- | --- |
| validation | 0.769 [0.738, 0.794] | 0.795 |
| **test** (opened once, 2026-08-26) | **0.751 [0.719, 0.780]** | 0.778 |

With abstention on test: **80.7% of articles filed at
83.4% accuracy**, against 77.7%
if it is forced to answer everything.

Calibration error (ECE): validation 0.039, test 0.021.

**The central result:** reading the article body instead of the headline and summary is
worth **+0.059 macro-F1** (0.712 → 0.771,
McNemar p=7.5e-06).

## Per class

| Class | val F1 | 95% interval | val support | test F1 |
| --- | ---: | --- | ---: | ---: |
| sport | 0.95 | [0.92, 0.98] | 91 | 0.95 |
| entertainment_arts | 0.89 | [0.84, 0.93] | 116 | 0.85 |
| business_economy | 0.85 | [0.81, 0.89] | 168 | 0.78 |
| science_space | 0.83 | [0.74, 0.90] | 57 | 0.81 |
| disaster_accident | 0.82 | [0.73, 0.88] | 63 | 0.87 |
| technology | 0.81 | [0.74, 0.88] | 66 | 0.81 |
| crime_justice | 0.79 | [0.72, 0.85] | 92 | 0.82 |
| politics | 0.79 | [0.75, 0.83] | 213 | 0.76 |
| health | 0.73 | [0.61, 0.82] | 50 | 0.69 |
| conflict_war | 0.72 | [0.60, 0.83] | 55 | 0.60 |
| education | 0.72 | [0.58, 0.83] | 29 | 0.65 |
| environment_climate | 0.67 | [0.55, 0.76] | 54 | 0.71 |
| society_lifestyle | 0.43 | [0.32, 0.54] | 66 | 0.44 |

## Known limits

- `society_lifestyle` is a definitional grab-bag (community + labour + lifestyle) and
  scores F1 ~0.42. It still calibrates honestly, so abstention protects it.
- `education` has 29
  validation articles; read its F1 as noise, not as a measurement.
- ~18.6% of errors sit on class pairs where human annotators themselves disagreed, so
  macro-F1 has a real ceiling well below 1.0.
- Trained on a 4-day collection window, so nothing here measures drift over weeks.
- English only, and India-heavy: 40 publishers, mostly Indian mastheads plus The
  Guardian, BBC and France 24.
