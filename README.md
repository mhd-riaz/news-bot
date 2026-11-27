# news-bot

**Your own news robot.** news-bot reads 124 news feeds day and night, saves every
new article, sorts each one into a topic, and suggests stories you may like in a
reading app called **AFTERLINE**. It is built for a small group of invited readers and
runs on your own laptop or home server, with no paid service.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What is in each folder

| Folder | What it holds |
| --- | --- |
| [`collector/`](collector/) | The **collector** (Go): reads the news feeds and saves articles in MongoDB |
| [`ml/`](ml/README.md) | Machine learning (Python): the **classifier** that sorts articles into topics, and the **ranker** that picks stories for each reader |
| [`server/`](server/README.md) | The **web server** (Python) for the reading app, with Google sign-in, and the **MCP program** that lets AI agents search the news |
| [`frontend/`](frontend/README.md) | The **reading app** itself (React): the pages you see in the browser |
| [`data/`](data/labels/README.md) | Topic labels used to train and test the classifier (no article text) |
| [`deployment/`](deployment/README.md) | How the app runs: Docker Compose for a laptop, a Helm chart for Kubernetes, and example settings files |
| [`docs/`](docs/README.md) | The detailed documentation: how it works, how to run it, the plan and its status |
| [`.github/`](.github/) | Automatic checks (GitHub Actions) and instructions for AI coding helpers |

## What you need

- **Docker** with Compose v2: [Docker Desktop](https://docs.docker.com/get-docker/), or
  Rancher Desktop, or Docker Engine on Linux. Give it at least 6 GB of memory.
- **[uv](https://docs.astral.sh/uv/)**, which installs Python and its packages for you.
- **python3** (any recent version).
- **Access to the topic model.** It is in the private GitHub repository
  `mhd-riaz/news-bot-archive`. Sign in once with the [GitHub CLI](https://cli.github.com/)
  (`gh auth login`), or set `GITHUB_TOKEN` to a token that can read it.
- About 15 GB of free disk space, and Linux or macOS.

## Start it

From the top folder of the repository:

```bash
./run.sh
```

That one command checks your tools, makes your settings file
(`deployment/env/local.env`), downloads the model, builds and starts every service,
waits until the collector has gathered some news, builds the ranker's first snapshot
and prints the address of the reading app, normally <http://127.0.0.1:8090/>. The
first run takes the longest, because it downloads and builds everything; later runs
take less than a minute.
Running it again is always safe.

| Command | What it does |
| --- | --- |
| `./run.sh status` | Shows each service, its health and its address |
| `./run.sh logs collector` | Shows the newest lines of one service's log |
| `./run.sh refresh` | Builds a new ranker snapshot from the newest news |
| `./run.sh stop` | Stops everything; your news is kept |
| `./run.sh help` | Lists every command and option |

On a laptop, sign-in is off and you are the "Local reader". Every port listens on
127.0.0.1 only, so other computers cannot reach the app.

## Learn more

- [docs/](docs/README.md): start here for everything else: how the parts fit
  together, each service, running the home server, and the project's plan.
- [deployment/helm/news-bot/](deployment/helm/news-bot/README.md): putting the app on
  a home server with Kubernetes (k3s).
- [docs/project/roadmap.md](docs/project/roadmap.md): what is done and what is next.

## License

news-bot is open source under the [MIT License](LICENSE). You may use, copy, change
and share it, as long as you keep the copyright and license notice. It comes with no
warranty.
