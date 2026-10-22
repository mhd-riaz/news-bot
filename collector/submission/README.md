# Submission checklist

**Supervised Machine Learning — Classification · Mini Project · due 29 August 2026**
Mohamed Riaz · PES1PGE25DS037

## What to hand in

| Marks | Component | Artifact | Status |
| ---: | --- | --- | --- |
| 4 | User interface | `ml-v2/app/streamlit_app.py` — run it live | ready |
| 4 | Validation / testing | UI *Validation* tab · `ml-v2/docs/plan.md` · model card · 133 tests | ready |
| 4 | Novelty / innovation | calibrated confidence + abstention + the body A/B | ready |
| 4 | PPT presentation | `slides/news-topic-classifier.pptx` (17 slides) | **read it through once** |
| 4 | 2-page IEEE report | `report/ieee-report.pdf` — compiled, 2 pages | ready |

## Building each artifact

```bash
cd ../ml-v2

uv sync --group dev --group demo
uv run pytest                                   # 133 tests
uv run newsmlv2 train --id v2-001               # bundle + metrics.json + model-card.md
uv run python scripts/build_figures.py          # ../submission/report/figures/*.png

cd ../submission
uv run --with python-pptx python slides/build_deck.py
```

Both the deck and the figures read `ml-v2/artifacts/models/v2-001/metrics.json`, so
neither can quote a number the shipped model does not produce. Retrain and they update.

### The report

`report/ieee-report.pdf` is the submission copy: **2 pages**, IEEEtran conference format.
Rebuild it with Tectonic, which needs no TeX Live install and fetches packages on demand:

```bash
brew install tectonic          # once
cd report && tectonic -X compile ieee-report.tex
```

Overleaf also works (*New Project → Upload Project →* the `report/` folder). Two things
keep the page count stable across toolchains and should not be removed: `newtxtext`,
which pins Times so the engine cannot fall back to the wider Computer Modern, and the
float-spacing block in the preamble. It fits two pages with about four lines to spare, so
any added sentence needs one removed.

The file `Reading_the_Body__A_Calibrated__AbstainingClassifier_...pdf` is the earlier
3-page Overleaf build and is **stale** — delete it before submitting.

## Demo script — about six minutes

Start the app before the session; the first model load takes ~30 seconds and is then
cached.

```bash
uv run --directory ml-v2 streamlit run app/streamlit_app.py
```

1. **Frame it in one sentence.** "A news article goes in, one of 13 topics comes out,
   and it is allowed to say it doesn't know." Point at the sidebar: test macro-F1
   0.751, 83.4% accuracy on what it files.
2. **Classify → Sport.** It comes back `Sport` at 0.97. Scroll to *Why* and read two of
   the terms out. Say the line that earns the mark: *"this is a linear model over
   TF-IDF, so the decision is literally a sum of weight × term-frequency — these terms
   are the reasons, not an approximation of them."*
3. **Classify → A near tie.** `politics` 0.60 with `business_economy` at 0.40, just
   above the cut. Now drag the sidebar **Abstention dial** up to ~0.65 and re-classify:
   the same article flips to *Held for review*. That single interaction demonstrates
   calibration, abstention and the coverage/accuracy trade in one move.
4. **Press "a real one it is unsure about."** It pulls the lowest-confidence article out
   of real collected news nobody labelled — usually one with a truncated body — and
   holds it for review at ~0.3. Say: *"it is not confidently wrong, it is correctly
   unsure."*
5. **Validation tab.** Show the per-class table and point at `education`: F1 0.71 with
   29 validation articles and an interval a quarter of an F1 point wide. *"I report that
   as noise rather than as a result."* Then the reliability diagram — the points sit
   above the diagonal, so the model is under-confident, which is the safe direction.
6. **Run it on the corpus tab.** Classify 60 real unlabelled articles; show the split
   between filed and held.
7. **How it was built tab.** The table of everything that lost. Close on the ensemble
   paradox: oracle 0.900, every reachable vote 0.771, McNemar *p* = 1.00.

## Questions to expect, and the answers

**"Why not BERT / an LLM?"**
Deliberate. The body-vs-headline A/B is the question the project asks; running a
transformer at the same time makes the gain impossible to attribute. It is also outside
the classical-ML syllabus, and MiniLM embeddings were measured — they scored 0.710,
almost exactly the headline-only TF-IDF number, because MiniLM truncates at 256 tokens
and structurally cannot see the text that made v2 work.

**"0.751 isn't very high."**
Macro-F1 over 13 classes with a `sport`-to-`conflict_war` imbalance of 6.7:1, against a
majority-class floor of 0.025. And ~18.6% of the errors sit on class pairs where the
human annotators disagreed with each other, so there is a real ceiling below 1.0.
The number that matters operationally is 83.4% accuracy on the 80.7% it chooses to file.

**"How do you know it isn't overfitting?"**
Grouped, temporal splits; no story group spans two splits; intervals bootstrapped over
story groups; two publisher holdouts refit without that publisher; and a test split
opened exactly once, after the model was frozen, through a function that refuses to run
without an explicit flag. The validation-to-test gap is −0.021 against a guard of ±0.05.

**"What's actually novel here?"**
Three things: (1) the body-vs-headline A/B is measured, not assumed, with a paired test;
(2) the classifier abstains under a calibrated probability rather than a raw SVM margin,
which is what makes 0.6 mean the same thing for `sport` and `society_lifestyle`; (3) the
project's most useful output is the list of things that did *not* work, each with a
p-value attached.

**"Why is the model 148 MB?"**
Because the shipped bundle is the exact recipe that was measured — five grouped folds,
each with its own base estimator and isotonic calibrator, averaged. A single
`CalibratedClassifierCV(ensemble=False)` would be a fifth of the size and a slightly
different model to the one every reported number describes.

## Before you submit

- [ ] Delete the stale 3-page `Reading_the_Body__...pdf` from `report/`.
- [ ] Open the `.pptx` and read every slide — check nothing overflows its box.
- [ ] Run the demo end to end once on the machine you will present from.
- [ ] `uv run pytest` in `ml-v2/` — all green.
- [ ] Do **not** run `scripts/phase_h4_open_test.py`. That door is closed.
