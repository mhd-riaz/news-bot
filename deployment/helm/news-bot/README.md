# Helm chart: news-bot on Kubernetes

This chart runs the whole news-bot app on Kubernetes. Kubernetes runs programs in
containers on one or more computers and restarts them when they stop. At home we use
**k3s**, a small Kubernetes that fits on one laptop. Helm is the tool that installs
this chart. Tested with Helm v4.3.1, kubectl v1.37.2 and k3s v1.36.5.

| Part | What it does | Reachable from |
| --- | --- | --- |
| `mongo` | The MongoDB database, with its own disk | the app's pods only |
| `mongo-users` job | Runs [`mongo-users.js`](../../mongo/mongo-users.js) after every install and upgrade: one database login per part, each with only the rights it needs | - |
| `collector` | Reads the news feeds and saves articles | inside the cluster |
| `classifier` | Sorts articles into topics; downloads its model the first time | the collector only |
| `ranker` | Picks stories from a snapshot on its own disk | the web app and MCP only |
| `web` | The reader's app and Google sign-in | the tunnel or ingress |
| `mcp` (optional) | Read-only tools for AI agents; its database login can only read | the tunnel or ingress |
| `cloudflared` (optional) | A Cloudflare Tunnel that publishes the app without opening your router | - |

Every pod runs as a normal user (never root), with a read-only file system and no
extra Linux rights. Health checks use each program's `/health/live` and
`/health/ready`. Memory limits follow roadmap C15.

**Secrets never go into the chart or its values files.** The chart reads them from
one Kubernetes Secret that you make from an environment file. The values files hold
only settings that are not secret.

## Files

| File | What it is |
| --- | --- |
| `values.yaml` | Every setting, with a comment, and its default |
| `values-home.yaml` | The home server: images from `ghcr.io/mhd-riaz`, Cloudflare Tunnel on |
| `values-local.yaml` | A test on Rancher Desktop: images you built, small memory, no news collecting, sign-in off |
| `files/mongo-users.js` | A link to `deployment/mongo/mongo-users.js`, so install from a full checkout |
| `../copy-snapshot.sh` | Copies a ranker snapshot onto the ranker's disk |

## Install at home

You need k3s (or any Kubernetes 1.29 or newer), `kubectl`, Helm and a checkout of
this repository. Run every command from the top folder of the checkout.

1. **Fill in the secrets.** Copy `deployment/env/home.env.example` to
   `deployment/env/home.env` and fill in every value. The file tells you how to make
   each one. Git ignores `home.env`; never share it.

2. **Make the namespace and the Secret** (a namespace is a separate room in the
   cluster):

   ```bash
   kubectl create namespace news-bot
   kubectl -n news-bot create secret generic news-bot-env --from-env-file=deployment/env/home.env
   ```

3. **Set the web address.** In `values-home.yaml`, set `web.publicUrl` to the address
   your readers open, for example `https://news.example.com`. Set `mcp.publicHost` if
   AI agents should reach the MCP program from outside.

4. **Install:**

   ```bash
   helm upgrade --install news-bot deployment/helm/news-bot -n news-bot \
     -f deployment/helm/news-bot/values-home.yaml --timeout 10m
   ```

   Do not add `--wait` the first time. The users job runs *after* the pods are
   created, and with `--wait` Helm would wait for pods that need those users.

5. **Watch it start:** `kubectl -n news-bot get pods -w`. MongoDB starts, the users job
   makes the logins, the app pods leave their `wait-for-database` step, and the
   classifier downloads its model. The ranker stays "not ready" until step 6.

6. **Give the ranker a snapshot.** A snapshot is a frozen copy of recent stories that
   the ranker learns from. Build it on a computer that can read the same database (for
   example `./run.sh refresh` with `NEWS_MONGO_URI` pointing at a port-forward), then:

   ```bash
   deployment/helm/copy-snapshot.sh ml/artifacts/recommender/<snapshot> news-bot news-bot
   ```

   Repeat this whenever you want newer stories in the ranker.

7. **Publish it with Cloudflare Tunnel.** In the Cloudflare Zero Trust dashboard make a
   tunnel (Networks > Tunnels > Create a tunnel > Cloudflared), copy its token into
   `NEWS_CLOUDFLARE_TUNNEL_TOKEN`, update the Secret (see `home.env.example`) and add
   public host names. `helm install` prints the service addresses to enter, for
   example `http://news-bot-web.news-bot.svc.cluster.local:8090`.

8. **Google sign-in.** In Google Cloud Console make an OAuth client of type "Web
   application" with the redirect URI `<web.publicUrl>/auth/callback`, and put
   its ID and secret in the Secret (see [`server/README.md`](../../../server/README.md)).

9. **Invite readers.** Only invited Google accounts can sign in:

   ```bash
   kubectl -n news-bot port-forward svc/news-bot-mongo 27018:27017
   # in a second terminal (home.env has NEWS_OWNER_MONGO_URI for this):
   cd server && NEWS_ENV_FILE=../deployment/env/home.env uv run newsbot-server readers invite brother@example.com
   ```

## Moving the database from Coolify

Collection must never stop (hard rule 1). A safe order:

1. Install the chart with `collector.scheduler.enabled=false`, so the new collector
   starts but does not collect yet. Coolify keeps collecting.
2. Copy the data: `mongodump` from the Coolify MongoDB, then `mongorestore` into the
   new one through `kubectl port-forward`. Log in as root for both.
3. Count `articles` in both databases and write the numbers down.
4. Turn collecting on in the cluster (`--set collector.scheduler.enabled=true`), check
   that new articles arrive, then stop the Coolify collector. Copy any articles that
   Coolify saved after step 2 again (`mongodump --query` on `collected_at`), and count
   once more: the counts must match.

## Update, roll back, remove

- **Update** to new images: with `tag: latest` and `pullPolicy: Always`,
  `kubectl -n news-bot rollout restart deployment` fetches the newest images. To use
  one version, set `images.tag` to a `sha-<commit>` tag and run `helm upgrade` again.
- **Change a secret:** update the Secret (see `home.env.example`), then
  `kubectl -n news-bot rollout restart deployment`.
- **Roll back:** `helm -n news-bot history news-bot`, then
  `helm -n news-bot rollback news-bot <revision>`.
- **Remove:** `helm -n news-bot uninstall news-bot`. The database disk
  `data-news-bot-mongo-0` is kept on purpose. Delete it only when you really want to
  lose the data: `kubectl -n news-bot delete pvc data-news-bot-mongo-0`.

## Try it on your own computer

With Rancher Desktop (its "dockerd" engine shares the images you build with k3s):

```bash
docker compose -f deployment/compose/compose.yaml build       # builds the four images
kubectl create namespace news-bot-test
kubectl -n news-bot-test create secret generic news-bot-env --from-env-file=<a test env file>
helm install news-bot deployment/helm/news-bot -n news-bot-test -f deployment/helm/news-bot/values-local.yaml
kubectl -n news-bot-test port-forward svc/news-bot-web 18090:8090    # then open http://127.0.0.1:18090/
```

The test env file needs the same keys as `home.env.example`, with made-up values.
Afterwards: `helm -n news-bot-test uninstall news-bot` and
`kubectl delete namespace news-bot-test` (this also deletes the database disk).

## Check the chart

```bash
for values in values.yaml values-home.yaml values-local.yaml; do
  helm lint deployment/helm/news-bot -f deployment/helm/news-bot/$values
done
helm template news-bot deployment/helm/news-bot -n news-bot -f deployment/helm/news-bot/values-home.yaml \
  | kubectl apply --dry-run=server -n news-bot -f -
```

## When something is wrong

| What you see | What it means |
| --- | --- |
| A pod stays in `Init: wait-for-database` | The users job has not made its login yet: `kubectl -n news-bot logs job/news-bot-mongo-users` |
| `CreateContainerConfigError` | A key is missing from the Secret: `kubectl -n news-bot describe pod <pod>` names it |
| The classifier stays in `Init: get-model` | It cannot download the model: check `GITHUB_TOKEN` with `kubectl -n news-bot logs <pod> -c get-model` |
| The ranker is running but not ready | It has no snapshot yet (step 6) |
| The web app is running but not ready | MongoDB or the ranker does not answer; `/health/ready` says which |
| `helm install` stops with a message | A safety check, for example sign-in off outside development |
