# Project status

**Short answer (27 Nov 2026):** V1 is not finished. The collector is recorded as
running in production. The reader has been shown working on a laptop. Hosting, real
Google sign-in, automatic updates, topic suggestions and the final human reading
test are not done.

The original V1 date was 15 Nov 2026. It has passed, and no new date has been
approved. Nothing on this page closes a V1 requirement or a release check.

This page is a plain summary. The full records are:

- the [roadmap](roadmap.md): the plan, the status board and every decision;
- [recommender-results.md](recommender-results.md): the measured evidence for the
  recommender, in full;
- [recommender-client-review.md](recommender-client-review.md): the client briefing
  of 25 Nov 2026 and the older technical review.

Hard words are explained in the [glossary](../glossary.md).

## What works

"Works" here means there is a recorded check. Read the "where" column: working on one
laptop is not the same as working in production.

| What | Where | Record |
| --- | --- | --- |
| The collector reads news feeds, saves stories and fetches full text | Recorded as running in production (requirements R8, R9). The shipped list has 124 feeds; the 25 added in M1.7 reach production with the next deploy (R17) | [roadmap §2](roadmap.md#2-requirements) |
| Date checks, revisions, cleaned text and detected language for new stories | In code, with tests. Not yet checked on production data | M1.1–M1.4 |
| A backfill for old stories, and a relabel command for a new model | In code, with tests. Not yet run on production | M1.5, ML4.7 |
| The V4 topic classifier | Approved for production by the owner (D19). Code ready; not yet deployed | ML4.7, RS2 |
| The ranker with three methods: TF-IDF, SVD and Neural | On a laptop, with snapshots built by hand | DEMO.2, DEMO.5 |
| The reader: Fresh, Yesterday and Archive views, Professional focus, a story grid, a full-screen reading view, related stories, saved stories with notes, light and dark | Shown on a laptop with the old Go reader, and again with the new React app against the real server (27 Nov, sign-in off). Choices stay in one browser | DEMO.4, RS5 |
| The Python web server and the React app, replacing the Go reader | In code, with tests, and checked in a browser against the real server on a laptop. Not deployed | RS4, RS5 |
| Google sign-in for invited readers | In code, tested with a fake Google. Not tried with a real Google client | RS4 |
| The read-only MCP program, with 5 tools | On a laptop, over HTTP and stdio. Not deployed | RS4 |
| One CI workflow, with one job per part | In the repository; every part passed on draft PR #11 | RS9 |

## What is not done

These V1 parts have no recorded completion:

- **Hosting the reader** with sign-in on, at `news.mxdio.com` (M3.3). The Google OAuth
  client does not exist yet (D10).
- **Automatic updates.** A pipeline that adds new and changed stories to the ranker,
  so a new story is recommendable within 1 hour (M2, requirement R5). Today a person
  rebuilds the snapshot by hand.
- **Reader data on the server:** likes, settings, saved stories, saved topics and
  notes that follow the reader to another device (M3).
- **Reader-added feeds** (M3.6).
- **Stored daily editions** for each reader (M4). Today "Yesterday" is worked out on
  each request.
- **Topic suggestions and follow-up stories** from association rules (M5). The MCP
  tools `get_story_group` and `get_rules` wait for this.
- **The two-tower recommendation model** (M6).
- **The final human reading test** (M8, requirement R15).
- **Hardening:** load tests, backups with a rehearsed restore, and the release
  checklist (M1.8, M9).
- **Production checks:** which publishers give trustworthy dates (M1.9), and running
  the backfill and the relabel on production (RS6).
- **The repository move (RS):** RS4 waits for the Google OAuth client. RS6 (Helm)
  waits for the owner's home-lab steps. RS7 (`run.sh`) worked in a fresh copy on a
  Mac, but is not yet tried on a clean machine or on Linux. The move is in draft
  [PR #11](https://github.com/mhd-riaz/news-bot/pull/11) and is not yet in `main`.

## Key measured numbers

Every number below is copied from its record. None was measured again for this page.

### Recommender: the `stories-002` edition (cut 22 Oct 2026)

20,000 articles from 40 publishers. The neural network has 82,496 parameters.

| Method | Human pilot: Useful P@5 | Human pilot: nDCG@5 | AI-assisted: Useful P@5 | AI-assisted: nDCG@5 | End-to-end p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **TF-IDF** | **0.80** | **0.9349** | **0.565** | **0.8526** | 15.12 ms |
| SVD | 0.70 | 0.6596 | 0.480 | 0.7375 | 12.92 ms |
| Neural | 0.60 | 0.5755 | 0.380 | 0.6435 | 14.07 ms |

- The **human pilot** is 2 cases (20 graded pairs) out of 40. That is too few for a
  general claim.
- The **AI-assisted** pass graded all 437 pairs in the 40 cases. It agreed exactly with
  only 8 of the 20 grades the person gave, so it does not replace people. It is kept
  separate from the human grades.
- The speeds are single-reader tests on one laptop, not a load test.
- **The V1 target is not yet measured:** human Useful P@5 of at least 0.65, and not
  below TF-IDF, over 50 frozen cases (roadmap C13). Neither result above counts toward
  it.

Full details: [recommender-results.md](recommender-results.md). Its "reproduce"
commands were written for the old folder layout; run them from `ml/` now.

### Classifier: `v4-ai-072b01a9ceaf-hybrid_svc`

On its test set of 1,719 articles, opened once: macro-F1 0.8246 [0.8056, 0.8442] and
accuracy 0.829. [`data/labels/README.md`](../../data/labels/README.md) says how the
labels were made, and so what these scores mean. Human validation and 200 labels by
people for each topic are **not met**. Details: [classifier guide](../services/classifier.md#how-the-model-was-made).

### The latest laptop snapshot

`demo-20261124T084052Z` (24 Nov 2026): 30,000 articles, 16,330 of them recent, 29,954
with a verified date and 3,432 from sources with topic tags. The build took 341.5 s.

### The repository move (27 Nov 2026)

- ML tests (`make -C ml test`): 505 passed, 14 skipped because they need private data.
- Server tests: 232 passed, 2 skipped (they need a MongoDB with passwords, and passed
  in a Docker run).
- 30 local recommendation requests through the Python server: p95 10.8 ms. This was
  not a formal benchmark.
- Reader app (`npm run ci`): 60 Vitest tests passed; the build is 290 kB of JavaScript
  (88 kB compressed).
- Images: the ranker image is 608 MB (it was 12.0 GB), and the classifier image is
  2.11 GB.
