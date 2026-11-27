# History

This folder keeps finished and closed work. It is a record of what was done and what
was measured at the time.

**It is not a task list.** Do not take work from these files. Current work, status
and decisions are in the [roadmap](../project/roadmap.md), and a plain summary is on
the [status page](../project/status.md).

The files are kept as they were. Some name old folders, such as `collector/ml-v2/`,
or old commands. Some links inside them point to files that no longer exist. Two
examples are the old workflow `news-collector.yml` (now
[`ci.yml`](../../.github/workflows/ci.yml)) and report figures that were never
committed. The code they describe is at git tag `before-restructure`.

Several of these files say that the classifier labels were made by people. That was
corrected on 22 Nov 2026 (roadmap D16). [`data/labels/README.md`](../../data/labels/README.md)
says how the labels were really made.

## What each file is

| File | What it is | Came from |
| --- | --- | --- |
| [`classifier-plan.md`](classifier-plan.md) | The closed phase plan and results of the first topic-classifier study (August 2026) | `collector/docs/plan.md` |
| [`project-report.md`](project-report.md) | "A Dynamic E-Newspaper Built on Classical Machine Learning": the Semester 1 mini-project report about that study | `collector/docs/project-report.md` |
| [`submission/README.md`](submission/README.md) | The checklist, demo script and expected questions for the August 2026 classifier submission | `collector/submission/README.md` |
| [`submission/slides/build_deck.py`](submission/slides/build_deck.py) | The script that built that submission's slide deck | `collector/submission/slides/build_deck.py` |
| [`ml/v1/README.md`](ml/v1/README.md) | The guide to the first (v1) classifier study and its tools | `collector/ml/README.md` |
| `ml/v1/boilerplate.yaml` | The v1 list of repeated lines removed from stories | `collector/ml/artifacts/boilerplate.yaml` |
| `ml/v1/models/*/` | Four v1 model records: `manifest.json` and `model-card.md` for each. The models themselves are not here | `collector/ml/artifacts/models/` |
| [`ml/v1/reports/corpus-profile.md`](ml/v1/reports/corpus-profile.md), `profile.json` | A profile of the August 2026 story collection (1,350 articles from 20 sources) | `collector/ml/reports/` |
| [`ml/v2/plan.md`](ml/v2/plan.md) | The closed plan and results of the v2 study: a classifier that also reads the story body | `collector/ml-v2/docs/plan.md` |
| `ml/v2/boilerplate.yaml` | The v2 list of repeated lines removed from stories | `collector/ml-v2/artifacts/boilerplate.yaml` |
| `ml/v2/experiments/ledger.jsonl` | One line per v2 experiment (10 lines) | `collector/ml-v2/artifacts/experiments/ledger.jsonl` |
| [`ml/v2/models/v2-001/model-card.md`](ml/v2/models/v2-001/model-card.md), `metadata.json`, `metrics.json` | The record of model `v2-001`, the production classifier before V4 | `collector/ml-v2/artifacts/models/v2-001/` |
| [`ml/v2/reports/data-quality.md`](ml/v2/reports/data-quality.md), `clean-impact.yaml` | The data-quality report for snapshot `v2-001`, and the effect of cleaning | `collector/ml-v2/reports/` |
| [`ml/near-duplicate-pairs/labelling-guide.md`](ml/near-duplicate-pairs/labelling-guide.md) | The guide for labelling pairs of near-copy stories | `collector/ml/data/pairs/labelling-guide.md` |
| `ml/near-duplicate-pairs/pairs-key.jsonl` | The 43 labelled pairs used to set the near-copy threshold. Roadmap task M2.2 plans to check against them again | `collector/ml-v2/data/pairs/pairs-key.jsonl` |
| [`devlog/2026-oct.md`](devlog/2026-oct.md) | A development log of chat sessions with Copilot in October 2026 | `docs/devlog/` |
| `devlog/README.md` | The author's name and contact for that log | `docs/devlog/` |

## Old pictures

Two pictures in [`../assets/`](../assets/) are also history:

- [`news-classifier-lifecycle.svg`](../assets/news-classifier-lifecycle.svg) shows the
  first classifier's life: the label worksheet, training by hand, where the model
  lives, and using it live.
- [`afterline-training.svg`](../assets/afterline-training.svg) shows the training
  curve of the neural method for the `stories-002` edition. Its measure is
  reconstruction error, not recommendation quality.

## Older code and data

- Git tag `before-restructure` marks the last commit before the folders were moved on
  27 Nov 2026. It has the old Go reader, the study scripts, the notebook and the old
  label rounds.
- The private repository `mhd-riaz/news-bot-archive` holds every branch and the files
  that existed only on the owner's laptop (roadmap RS0).
