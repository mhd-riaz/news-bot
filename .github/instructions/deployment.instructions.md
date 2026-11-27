---
applyTo: "deployment/**,run.sh"
---

# Deployment and run.sh

- Real environment files (`deployment/env/<environment>.env`) hold passwords and keys. Git ignores them; only the `*.env.example` templates are committed. Never print, copy or commit their values (hard rule 6).
- `deployment/helm/news-bot` deploys the whole app to Kubernetes. It reads secrets from one existing Secret made from the environment file. Never put a secret value in a values file.
- `deployment/compose/compose.yaml` runs the app on a laptop. Publish ports on 127.0.0.1 only.
- `deployment/compose/coolify.compose.yml` is what production runs today. Change it only together with the owner.
- Collection must keep running during any deployment change (hard rule 1).
- Check with `helm lint` and `helm template` for each values file, `docker compose config` for each compose file, and `bash -n run.sh`.
