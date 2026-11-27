# env: settings files

Each place that runs news-bot reads its settings from one file. Only the **examples**
are in git. The real files hold passwords and keys, so git ignores them.

| Example | Real file | Used by |
| --- | --- | --- |
| [`local.env.example`](local.env.example) | `local.env` | `./run.sh` and Docker Compose on a laptop; also the programs when you run them from the code without Docker |
| [`home.env.example`](home.env.example) | `home.env` | the Kubernetes Secret for the Helm chart on the home server |

Production in Coolify does not use a file here: its settings are typed into the
Coolify web page (see the notes at the top of
[`../compose/coolify.compose.yml`](../compose/coolify.compose.yml)).

## On a laptop

You usually do nothing: the first `./run.sh` copies `local.env.example` to `local.env`
and fills in new random keys. It never prints them. To change a setting (a port, the
database), edit `local.env`; every line is explained in the example.

## On the home server

1. Copy `home.env.example` to `home.env` and fill in every value. Make each password
   and key with `openssl rand -hex 32`.
2. Make the Secret: `kubectl -n news-bot create secret generic news-bot-env --from-env-file=deployment/env/home.env`
3. Keep `home.env` somewhere safe (a password manager), and delete it from computers
   that do not need it.

## Safety rules

- Never commit, print, paste or share a real `.env` file. If one leaks, make new keys
  and passwords at once.
- Write `KEY=value` with no spaces around `=` and no comment after a value.
- Values that are not secret (web address, image versions, memory) belong in the Helm
  values files or `compose.yaml`, not here.
