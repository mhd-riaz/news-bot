# Getting started

This page tells you what to install and how to start news-bot on your own laptop.
It is short on purpose. The exact commands live in two places that are kept up to
date:

- `./run.sh help`, at the repository root, lists every `run.sh` command.
- [`deployment/README.md`](../../deployment/README.md) explains Docker Compose and
  the Helm chart.

Hard words are explained in the [glossary](../glossary.md).

## What to install

**To run the app:**

| Tool | Why |
| --- | --- |
| Git | To get the code |
| Docker, with Docker Compose 2.24.4 or newer | Runs every part of the app in containers. For example Docker Desktop, Rancher Desktop or Docker Engine |
| [uv](https://docs.astral.sh/uv/) | Installs the Python tools that build the ranker's snapshots into `ml/.venv` (about 1 GB the first time) |
| Python 3, as `python3` | Runs the model download script. If your `python3` is older than 3.11, `run.sh` uses uv to get Python 3.12 |
| GitHub access | Downloads the classifier model from a private release (see below) |

**To work on the code** (not needed just to run it):

| Tool | For | Version |
| --- | --- | --- |
| Go | The collector | 1.27 |
| Python and [uv](https://docs.astral.sh/uv/) | The ML tools, the ranker and the web server. uv installs the Python packages | Python 3.12 |
| Node.js and npm | The reader app | Node 22 (22.22.2 or later), 24 (24.15.0 or later), or 26 and newer |
| make | Short commands in each folder | any |

**The model download needs permission.** The classifier model is in the private
repository `mhd-riaz/news-bot-archive`. Sign in once with `gh auth login` (the GitHub
command-line tool) using an account that can read it, or set `GITHUB_TOKEN` to a
token that can.

## Start the app

1. **Get the code.**

   ```bash
   git clone https://github.com/mhd-riaz/news-bot.git
   cd news-bot
   ```

   The new folder layout is on the `v4` branch until it is merged into `main`
   (`git checkout v4`).

2. **Your settings file.** The app reads its keys and passwords from
   `deployment/env/local.env`. The first `./run.sh` makes this file for you from
   `deployment/env/local.env.example`, with new random keys. You can also copy the
   example and fill it in by hand; the example explains each key. Git ignores
   `local.env`. Never commit it, print it or paste it anywhere.

3. **See the commands.**

   ```bash
   ./run.sh help
   ```

4. **Start everything.**

   ```bash
   ./run.sh
   ```

   It downloads the classifier model, builds the parts and starts them in Docker,
   with a database on your own computer. Add `--mcp` to also start the MCP program.
   `./run.sh status`, `./run.sh logs <service>` and `./run.sh stop` do what their
   names say. If this page and `./run.sh help` ever disagree, trust `./run.sh help`.

5. **Open the reader** at <http://127.0.0.1:8090/>.

## What starts, and where

| Part | Port | Health check |
| --- | --- | --- |
| MongoDB (the database) | 27017 | — |
| Classifier | 8000 | `/health/ready` |
| Ranker | 8001 | `/health/ready` |
| Collector | 8080 | `/health/ready` |
| Web server and reader app | 8090 | `/health/ready` |
| MCP program, for AI agents (optional) | 8091 | — |

Ports must be open on `127.0.0.1` only, so that only your own computer can reach
them. Never open them to your whole network.

How they fit together is on the [architecture page](../architecture/README.md).

## The first run

- **The database starts empty.** The collector starts reading the 124 feeds right
  away. Give it a few minutes before you expect many stories.
- **The ranker needs a snapshot.** A snapshot is a frozen copy of recent stories. The
  ranker cannot start without one, and `run.sh` builds the first one. Newer stories
  appear in the reader only after a new snapshot: `./run.sh refresh` builds one and
  restarts the ranker. The
  [recommender guide](../services/recommender.md#make-a-fresh-snapshot) explains
  snapshots.
- **Sign-in is off on a laptop.** You are the "Local reader". Your likes, saved
  stories and notes stay in your browser.

## Stay safe

- The collector **writes** to the database it is given. Keep `local.env` pointed at
  the database on your own computer. `run.sh` refuses a database on another computer
  unless you add `--allow-remote-mongo`.
- To check which database you will use, run `make -C ml rec-inspect`. It prints the
  database name and the number of stories, never the connection address.
- Never run the collector's writing commands against the production database. The
  list is in the [collector guide](../services/collector.md#first-choose-the-database).

## Work on one part

Each part has its own checks. CI runs all of them.

| Part | Guide | Checks |
| --- | --- | --- |
| Collector | [collector](../services/collector.md) | `make check`, `make test-race`, `make test-integration` in `collector/` |
| ML: classifier and ranker | [classifier](../services/classifier.md), [recommender](../services/recommender.md) | `make setup` once, then `make test` in `ml/` |
| Web server and MCP | [server](../services/server.md) | `uv sync --frozen`, then `uv run pytest` in `server/` |
| Reader app | [frontend](../services/frontend.md) | `npm ci`, then `npm run ci` in `frontend/` |
| Deployment | [`deployment/README.md`](../../deployment/README.md) | `helm lint`, `docker compose config` and `node --test deployment/mongo/mongo-users.test.mjs` |
