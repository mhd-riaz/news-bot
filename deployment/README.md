# deployment: how news-bot runs

This folder holds everything that starts the app outside a code editor.

| Path | What it is | Used for |
| --- | --- | --- |
| [`compose/compose.yaml`](compose/compose.yaml) | Docker Compose file for the whole app | a laptop; `./run.sh` uses it |
| [`compose/compose.external-mongo.yaml`](compose/compose.external-mongo.yaml) | Add-on file: use a MongoDB that already runs on your computer | a laptop |
| [`compose/coolify.compose.yml`](compose/coolify.compose.yml) | What production runs today in Coolify (MongoDB, classifier, collector) | the home server, until the switch to Helm |
| [`helm/news-bot/`](helm/news-bot/README.md) | Helm chart for the whole app on Kubernetes (k3s at home) | the home server after the switch |
| [`helm/copy-snapshot.sh`](helm/copy-snapshot.sh) | Copies a ranker snapshot into the cluster | the home server |
| [`env/`](env/README.md) | Example settings files, one per environment | everywhere |
| [`mongo/mongo-users.js`](mongo/mongo-users.js) | Makes one MongoDB login per part of the app, with only the rights it needs | Coolify and Helm |

## Which one do I use?

- **On your laptop:** run `./run.sh` at the top of the repository. It uses
  `compose/compose.yaml` and `env/local.env`. See the [root README](../README.md).
- **On the home server today:** Coolify with `compose/coolify.compose.yml`. Change that
  file only together with the owner.
- **On the home server after the switch:** the Helm chart. Follow
  [`helm/news-bot/README.md`](helm/news-bot/README.md).

## Images and releases

GitHub Actions ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) builds four
images on every pull request. On `main` it also publishes them to
`ghcr.io/mhd-riaz/` with a `sha-<commit>` tag:

| Image | Built from | Used by |
| --- | --- | --- |
| `news-bot` | `collector/Dockerfile` | the collector |
| `news-collector-classifier` | `ml/classifier/Dockerfile` | the classifier |
| `news-recommender` | `ml/recommender/Dockerfile` | the ranker |
| `news-bot-server` | `server/Dockerfile` | the web app and the MCP program |

The `release` job then moves all four `latest` tags to the same commit and asks Coolify
to deploy. It runs only on `main` and only when the repository variable
`DEPLOY_ENABLED` is `true`. On a laptop, Compose builds the same images itself and tags
them `:local`; the Helm test settings (`values-local.yaml`) use those.

## Rules

- Real settings files (`env/local.env`, `env/home.env`) hold passwords and keys. Git
  ignores them. Never print, copy or commit them.
- Every port on a laptop listens on 127.0.0.1 only.
- The collector is the only program that writes articles, and collection must keep
  running during any change (hard rule 1).
- Check your changes: `helm lint` and `helm template` for each values file,
  `docker compose config` for each Compose file, `bash -n run.sh`, and
  `node --test deployment/mongo/mongo-users.test.mjs`.
