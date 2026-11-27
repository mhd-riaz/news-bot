# Operations

This page is about running news-bot for real: what runs in production today, how a
new version gets there, where secrets live, how models and backups work, and what
the owner still has to do by hand.

For running the app on your own laptop, see [Getting started](../getting-started/README.md).
The exact deployment commands are in [`deployment/README.md`](../../deployment/README.md).
Hard words are explained in the [glossary](../glossary.md).

## What runs in production today

Production is the owner's **home-lab** laptop (12 GB of memory, an i5 processor). It
runs **Coolify** (a self-hosted tool that runs Docker apps), and a **Cloudflare
Tunnel** carries web traffic to it.

The owner confirmed that Coolify deploys the stack in
[`deployment/compose/coolify.compose.yml`](../../deployment/compose/coolify.compose.yml)
(roadmap D20). It has three services:

| Service | Image | Memory limit | Notes |
| --- | --- | --- | --- |
| `mongo` | `mongo:7.0.48` | 3 GB | 2 GB cache. Port 27017 is open only on the machine itself |
| `classifier` | `ghcr.io/mhd-riaz/news-collector-classifier:latest` | 1.5 GB | Refuses to start unless `bundle.joblib` matches `NEWS_CLASSIFIER_MODEL_SHA256` |
| `api` | `ghcr.io/mhd-riaz/news-bot:latest` | 512 MB | The collector. Production mode, API sign-in on, classifier on |

The roadmap records the collector and MongoDB as running there (requirements R8 and
R9). That is a record, not a check of today's health. Which image version production
runs is not recorded: a release from this repository has not been proven yet (see
below).

**Not deployed yet:** the ranker, the web server, the MCP program and the planned
automatic pipeline. So readers cannot use the hosted site yet.

To reach the production database with Compass or `mongosh`, use an SSH tunnel to the
machine or a Cloudflare Access tunnel. The port is not open to the network.

## How a new version reaches production

1. A pull request to `main` runs CI ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)).
   It has one job per part: `collector`, `ml`, `server`, `frontend` and `deployment`.
   Then it builds four images: `news-bot`, `news-collector-classifier`,
   `news-recommender` and `news-bot-server`. The `ci-passed` job is the one check that
   `main` requires.
2. A run on `main` also publishes each image to GHCR (GitHub's image store) with a
   `sha-<first 7 letters of the commit>` tag.
3. The `release` job runs only on `main`, and only when the GitHub repository
   variable `DEPLOY_ENABLED` is `true`. It first checks the deploy secrets. Then it
   moves the `latest` tag of all four images to this commit, and asks Coolify to
   redeploy. Coolify must answer with a 2xx status.

**Status:** on 22 Nov 2026, `DEPLOY_ENABLED` was set to `false` until the first green
`main` run. `COOLIFY_WEBHOOK` was not yet a repository secret then (roadmap work log).
A release and a Coolify deploy have not been proven yet (roadmap M0.5, now carried by
RS6). A local image build is not a deployment.

**Roll back** by setting `NEWS_IMAGE` and `NEWS_CLASSIFIER_IMAGE` in Coolify to an
earlier release's `sha-` tags, both from the same commit, and redeploying. Unset them
to follow `latest` again.

### Settings production needs

In **Coolify**, the compose file stops with an error if one of these is missing:

| Variable | What it is |
| --- | --- |
| `NEWS_AUTH_API_KEYS` | Keys for the collector API, comma-separated. Make one with `openssl rand -hex 32` |
| `NEWS_AUTH_BASIC_USERNAME`, `NEWS_AUTH_BASIC_PASSWORD` | A user name and a password of at least 16 characters |
| `NEWS_MONGO_COLLECTOR_PASSWORD` | The `collector` database user's password: 64 hex characters |
| `NEWS_CLASSIFIER_API_KEY` | The key the collector and the classifier share |
| `NEWS_CLASSIFIER_MODEL_SHA256` | The model's checksum (see [the classifier guide](../services/classifier.md#deploy-the-v4-classifier-d19)) |

Coolify makes the MongoDB root user and password itself (`SERVICE_USER_MONGO`,
`SERVICE_PASSWORD_64_MONGO`). Optional ones include `NEWS_IMAGE`,
`NEWS_CLASSIFIER_IMAGE`, `NEWS_MONGO_DATABASE`, `NEWS_BOOTSTRAP_SOURCES_PATH` and
`NEWS_LOGGING_LEVEL`.

In **GitHub**, the repository needs the secrets `COOLIFY_WEBHOOK` and
`COOLIFY_TOKEN`, plus `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` if
Cloudflare Access protects Coolify.

## The home-lab move to Helm (planned)

The owner chose to move the home lab from Coolify to **k3s** (a small Kubernetes).
A **Helm** chart in `deployment/helm/news-bot` will run the app there, with one
settings file per environment (roadmap D21, task RS6). Docker Compose stays for
laptops.

**Status:** in progress. Nothing runs on k3s yet. Coolify stays until the switch.
The switch must not stop collection, and the article counts must match before and
after (project hard rule 1). Start at [`deployment/README.md`](../../deployment/README.md);
the chart's own steps, including moving the database from Coolify, are in
[`deployment/helm/news-bot/README.md`](../../deployment/helm/news-bot/README.md).

## Environment files and secrets

- Real settings files are `deployment/env/<environment>.env`: `local.env` for a laptop
  and `home.env` for the home server. **Git ignores them.** They hold passwords and
  keys.
- Only the templates are committed: `deployment/env/*.env.example`. Copy one, then
  fill in the values. [`deployment/env/README.md`](../../deployment/env/README.md)
  explains each file.
- Never print, paste or commit a real env file (project hard rule 6). Never put a
  secret in `configs/`, in code, or in a log.
- In production today, the secrets are typed into the Coolify web page; Coolify uses
  no file. The Helm chart will read them from one Kubernetes Secret made from
  `home.env`.
- To check which database a command will use without printing its address, run
  `make -C ml rec-inspect`.

### Database users

[`deployment/mongo/mongo-users.js`](../../deployment/mongo/mongo-users.js) creates one
MongoDB user per program: `collector`, `batch`, `ranker`, `reader`, `owner` and
`mcp`. Run it once as the MongoDB root user, with the passwords in the environment:

```bash
mongosh "$NEWS_MONGO_ROOT_URI" --quiet --file deployment/mongo/mongo-users.js
```

It needs `NEWS_MONGO_DATABASE` and six passwords:
`NEWS_MONGO_COLLECTOR_PASSWORD`, `NEWS_MONGO_BATCH_PASSWORD`,
`NEWS_MONGO_RANKER_PASSWORD`, `NEWS_MONGO_READER_PASSWORD`,
`NEWS_MONGO_OWNER_PASSWORD` and `NEWS_MONGO_MCP_PASSWORD`. Each must be 64 hex
characters (`openssl rand -hex 32`), and all must differ. You can run it again; it
updates the users. What each user may do is on the
[architecture page](../architecture/README.md#who-may-read-and-write).

**Status:** the owner confirmed on 26 Oct that production has its database users. The
`mcp` user was added to the script on 27 Nov. Whether production has it is not
recorded.

## Models

- Model files are not in git. [`ml/models.toml`](../../ml/models.toml) lists them with
  their SHA-256 checksums.
- They are stored as releases in the private repository `mhd-riaz/news-bot-archive`.
  `make -C ml models` downloads them into `ml/models/` and checks them. It needs
  `gh auth login` or a `GITHUB_TOKEN` that can read that repository.
- Production does not download models. The owner copies the bundle onto the
  `classifier-models` volume by hand. The steps and the checksum are in
  [Deploy the V4 classifier](../services/classifier.md#deploy-the-v4-classifier-d19).
- Keep every old release, so that a rollback is only a change of folder and checksum.

## Backups

- **Decision (roadmap D2, 26 Oct):** database backups go to a disk or a NAS on the
  home network. Neither one protects against losing the whole site, for example to
  theft or fire.
- **Plan (roadmap C15):** a daily, encrypted `mongodump` to that disk, and a practice
  restore into a scratch database.
- **Status:** not set up yet (roadmap M1.8). No restore has been rehearsed.

The code itself is backed up: on 27 Nov 2026 the owner made a private copy of the
repository, `mhd-riaz/news-bot-archive`, and a copy on the laptop (roadmap RS0). Those
are not database backups.

## Health checks and alerts

- The compose files check each service: MongoDB with a `ping`, the classifier and the
  collector with `/health/ready`. The collector's check covers MongoDB only, not the
  classifier.
- Alerts are deferred to V2 (roadmap D3). Nothing sends the owner a message when
  something breaks.

## What the owner still has to do by hand

Each item links to its roadmap task.

1. **Google sign-in (D10).** Create a Google OAuth client of type "Web application".
   Its redirect address is `<NEWS_PUBLIC_URL>/auth/callback`; for the chosen
   hostname that is `https://news.mxdio.com/auth/callback`. Set
   `NEWS_GOOGLE_CLIENT_ID` and `NEWS_GOOGLE_CLIENT_SECRET` (RS4 waits for this).
2. **Invite readers (M3.9)** with `uv run newsbot-server readers invite <email>`.
3. **Turn on deployment (M0.5, now RS6).** Add the GitHub secrets above, then set
   `DEPLOY_ENABLED` to `true` when ready.
4. **Put the V4 classifier into production (ML4.7, now RS6).** Copy the bundle onto
   the volume, set `NEWS_CLASSIFIER_MODEL_SHA256` and deploy. Then relabel the old
   stories until the command reports `updated` as 0. The command is
   `make -C collector backfill-reclassify` with production settings, or the same
   program inside the production `api` container: `/app/backfill -reclassify`.
5. **Fill old articles (M1.5, now RS6).** After that deploy, run the C1 backfill until
   nothing is left: `make -C collector backfill` with production settings, or
   `/app/backfill` inside the `api` container. The roadmap plans to run it in the
   `api` container once the deploy is healthy.
6. **Add the `mcp` database user** in production before the MCP program is deployed.
7. **Set up k3s on the home lab (RS6)** and copy the database across, without stopping
   collection.
8. **Set up database backups (M1.8, D2)** and rehearse a restore.
9. **Arrange the human reading review (M0.2):** confirm the testers and their times.
10. **Decide the open questions** in [roadmap §7](../project/roadmap.md#7-open-decisions-owner),
    such as how long to keep reader data (D4) and the content and image rights (D6).

Commands that write to the production database must be chosen on purpose. Never run
them by accident from a laptop.
