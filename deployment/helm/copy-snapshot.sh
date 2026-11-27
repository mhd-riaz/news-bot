#!/usr/bin/env bash
# Copy a ranker snapshot onto the ranker's disk in Kubernetes, make it the one the
# ranker serves (the file LATEST_DEMO), and restart the ranker.
#
#   deployment/helm/copy-snapshot.sh <snapshot folder> [namespace] [release]
#
# Example, after building a snapshot on your computer with ./run.sh refresh:
#   deployment/helm/copy-snapshot.sh ml/artifacts/recommender/demo-20261127T120000Z news-bot news-bot
#
# The snapshot must come from the same database the cluster uses, or the web app
# finds none of its stories. The script starts a small helper pod that mounts the
# snapshot disk, copies the folder with `kubectl cp`, then removes the helper.
set -euo pipefail

folder=${1:-}
namespace=${2:-news-bot}
release=${3:-news-bot}

if [[ -z "$folder" || "$folder" == "-h" || "$folder" == "--help" ]]; then
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
folder=${folder%/}
if [[ ! -f "$folder/manifest.json" || ! -f "$folder/training.json" ]]; then
  echo "$folder is not a finished ranker snapshot (it needs manifest.json and training.json)." >&2
  exit 1
fi
id=$(basename "$folder")
if [[ ! "$id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
  echo "The snapshot folder name '$id' must use only letters, numbers, - and _." >&2
  exit 1
fi
command -v kubectl >/dev/null || { echo "kubectl is not installed." >&2; exit 1; }

selector="app.kubernetes.io/instance=$release,app.kubernetes.io/component=ranker"
pvc=$(kubectl -n "$namespace" get pvc -l "$selector" -o jsonpath='{.items[0].metadata.name}')
deployment=$(kubectl -n "$namespace" get deployment -l "$selector" -o jsonpath='{.items[0].metadata.name}')
if [[ -z "$pvc" || -z "$deployment" ]]; then
  echo "No ranker of the release '$release' in the namespace '$namespace'. Check the names." >&2
  exit 1
fi
image=$(kubectl -n "$namespace" get deployment "$deployment" -o jsonpath='{.spec.template.spec.containers[0].image}')
# The disk can be used on one node only: run the helper where the ranker runs.
node=$(kubectl -n "$namespace" get pod -l "$selector" -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || true)
helper="$deployment-copy"

remove_helper() {
  kubectl -n "$namespace" delete pod "$helper" --ignore-not-found --wait=true >/dev/null 2>&1 || true
}
trap remove_helper EXIT

echo "Starting a helper pod that can write to the snapshot disk ($pvc)..."
kubectl -n "$namespace" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $helper
  labels:
    app.kubernetes.io/name: news-bot
    app.kubernetes.io/instance: $release
    app.kubernetes.io/component: snapshot-copy
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  enableServiceLinks: false
  ${node:+nodeName: $node}
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: copy
      image: $image
      imagePullPolicy: IfNotPresent
      command: ["sleep", "3600"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: [ALL]
      resources:
        requests: {cpu: 10m, memory: 32Mi}
        limits: {memory: 128Mi}
      volumeMounts:
        - name: snapshots
          mountPath: /snapshots
  volumes:
    - name: snapshots
      persistentVolumeClaim:
        claimName: $pvc
EOF
kubectl -n "$namespace" wait --for=condition=Ready "pod/$helper" --timeout=180s >/dev/null

echo "Copying $id ($(du -sh "$folder" | cut -f1))..."
kubectl -n "$namespace" exec "$helper" -- rm -rf "/snapshots/$id.part"
kubectl cp "$folder" "$namespace/$helper:/snapshots/$id.part"
kubectl -n "$namespace" exec "$helper" -- sh -ec "
  rm -rf '/snapshots/$id'
  mv '/snapshots/$id.part' '/snapshots/$id'
  printf '%s\n' '$id' > /snapshots/LATEST_DEMO.tmp
  mv /snapshots/LATEST_DEMO.tmp /snapshots/LATEST_DEMO
"
remove_helper

echo "Restarting the ranker with snapshot $id..."
kubectl -n "$namespace" rollout restart "deployment/$deployment" >/dev/null
kubectl -n "$namespace" rollout status "deployment/$deployment" --timeout=300s
echo "Done: the ranker serves $id."
