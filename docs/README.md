# news-bot documentation

news-bot is a private news app for a small group of invited readers. It reads 124
English-language news feeds, sorts each story into a topic, and suggests what to read
in a reader app called **AFTERLINE**. It runs on the owner's own computers and needs
no paid service.

These docs are written in plain English. Hard words are explained in the
[glossary](glossary.md).

## Where to start

- **New here?** Read [Getting started](getting-started/README.md). It tells you what
  to install and how to start the app on a laptop.
- **Want to understand how it works?** Read [How news-bot fits together](architecture/README.md).
- **Want to know what is done?** Read the [status page](project/status.md).
- **Running it for real?** Read [Operations](operations/README.md).

## What is in each folder

| Folder or file | What it holds |
| --- | --- |
| [`getting-started/`](getting-started/README.md) | What to install, and how to start the app on a laptop |
| [`architecture/`](architecture/README.md) | The parts, a picture of how they connect, the path of a story from feed to reader, the database and who may use it, and how sign-in and AI-agent access work |
| [`services/`](services/) | One page for each part of the app (see below) |
| [`operations/`](operations/README.md) | Production today, how new versions get there, secrets, models, backups, and the owner's jobs |
| [`project/`](project/) | The plan and the status (see below) |
| [`history/`](history/README.md) | Closed work and old records. Not a task list |
| [`assets/`](assets/) | Pictures. [`system-overview.mmd`](assets/system-overview.mmd) is the source of the architecture picture |
| [`glossary.md`](glossary.md) | Every technical word in these docs, in one simple sentence each |

### The parts (`services/`)

| Page | Part | Code |
| --- | --- | --- |
| [Collector](services/collector.md) | Reads the news feeds and saves stories | [`collector/`](../collector/README.md) |
| [Classifier](services/classifier.md) | Sorts each story into one of 13 topics | [`ml/classifier`](../ml/README.md) |
| [Recommender](services/recommender.md) | Builds snapshots and ranks stories for a reader | [`ml/src/newsrec`, `ml/recommender`](../ml/README.md) |
| [Web server and MCP](services/server.md) | Serves the reader app, handles sign-in, and lets AI agents read | [`server/`](../server/README.md) |
| [Reader app](services/frontend.md) | The AFTERLINE pages in the browser | [`frontend/`](../frontend/README.md) |

### The plan and the status (`project/`)

| File | What it is |
| --- | --- |
| [`roadmap.md`](project/roadmap.md) | The plan: requirements, contracts, tasks, status and every decision. The agents keep it up to date |
| [`status.md`](project/status.md) | A short, plain summary: what works, what is not done, and the key numbers |
| [`recommender-results.md`](project/recommender-results.md) | The full measured results of the first recommender edition, `stories-002` |
| [`recommender-client-review.md`](project/recommender-client-review.md) | The client briefing of 25 Nov 2026, and an older technical review |

## Other guides in the repository

- The [repository front page](../README.md).
- One README for each part: [collector](../collector/README.md), [ml](../ml/README.md),
  [server](../server/README.md), [frontend](../frontend/README.md) and
  [data/labels](../data/labels/README.md).
- [`deployment/README.md`](../deployment/README.md): Docker Compose and the Helm chart.
- [`.github/copilot-instructions.md`](../.github/copilot-instructions.md): the rules
  for AI coding agents working in this repository.

## Writing these docs

Follow [`.github/instructions/docs.instructions.md`](../.github/instructions/docs.instructions.md):
short sentences, everyday words, one idea per sentence, and exact names, numbers,
commands and paths. Update the page that exists instead of adding a new file for
each change. Check that every link works.
