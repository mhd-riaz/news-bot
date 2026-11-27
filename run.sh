#!/usr/bin/env bash
# run.sh - start the whole news-bot app on this computer with one command.
# Works on Linux and macOS. It uses Docker Compose (deployment/compose/compose.yaml).
#
#   ./run.sh                  start everything (safe to run again at any time)
#   ./run.sh stop             stop everything (your news is kept)
#   ./run.sh status           show what is running
#   ./run.sh logs <service>   show the newest lines of one service's log
#   ./run.sh refresh          build a new ranker snapshot and restart the ranker
#   ./run.sh help             show every command and option
#
# Settings live in deployment/env/local.env. run.sh makes that file the first time
# and fills in new random keys. It never prints a key or a password.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="$ROOT/deployment/compose/compose.yaml"
EXTERNAL_FILE="$ROOT/deployment/compose/compose.external-mongo.yaml"
ENV_EXAMPLE="$ROOT/deployment/env/local.env.example"
ENV_FILE="${NEWS_ENV_FILE:-$ROOT/deployment/env/local.env}"
MODELS_SCRIPT="$ROOT/ml/scripts/download_models.py"
SNAPSHOTS="$ROOT/ml/artifacts/recommender"
POINTER="$SNAPSHOTS/LATEST_DEMO"
ML_PY="$ROOT/ml/.venv/bin/python"
STATE="$ROOT/.run"
ALL_SERVICES="mongo classifier collector ranker web mcp"

# ---------------------------------------------------------------------------------------
# Messages

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

say() { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$BOLD" "$*" "$RESET"; }
good() { printf '%s  ok%s  %s\n' "$GREEN" "$RESET" "$*"; }
note() { printf '%sNote:%s %s\n' "$YELLOW" "$RESET" "$*"; }
die() {
  printf '\n%sProblem:%s %s\n' "$RED" "$RESET" "$1" >&2
  shift
  local line
  for line in "$@"; do printf '         %s\n' "$line" >&2; done
  exit 1
}

usage() {
  cat <<'EOF'
run.sh - start the whole news-bot app on this computer.

Commands
  ./run.sh                  Start everything. Safe to run again at any time.
  ./run.sh stop             Stop everything. Your news stays in the database.
  ./run.sh status           Show each service, its health and its address.
  ./run.sh logs <service>   Show the newest 200 lines of a service's log.
                            Services: mongo classifier collector ranker web mcp
  ./run.sh refresh          Build a new ranker snapshot from the newest news,
                            then restart the ranker so it uses it.
  ./run.sh help             Show this help.

Options
  --mcp                     Also start the MCP program for AI agents (with start).
  --no-build                Do not rebuild the images (with start).
  --allow-remote-mongo      Let the collector write to a MongoDB on another computer.
  --delete-data             With stop: also delete the Docker database (all news).
  -f, --follow              With logs: keep showing new lines (Ctrl+C to stop).

What you need: Docker with Compose v2, uv and python3. The first run downloads the
topic model (about 45 MB) from a public Google Drive folder; no sign-in is needed.

Settings: deployment/env/local.env (made from local.env.example on the first run).
  LOCAL_PORT_WEB=18090      use another port when one is already taken
  NEWS_MONGO_URI=...        use a MongoDB that already runs on this computer
Environment variables with the same names win over the file for one run.
COMPOSE_PROJECT_NAME=<name> runs a separate copy with its own containers and data.
EOF
}

# ---------------------------------------------------------------------------------------
# Command line

COMMAND=start
SERVICE=""
WITH_MCP=false
NO_BUILD=false
ALLOW_REMOTE=false
DELETE_DATA=false
FOLLOW=false
command_given=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    start | stop | status | logs | refresh | help)
      if $command_given; then
        if [[ "$COMMAND" == logs && -z "$SERVICE" ]]; then SERVICE=$1; else die "Give only one command. See: ./run.sh help"; fi
      else
        COMMAND=$1
        command_given=true
      fi
      ;;
    --mcp) WITH_MCP=true ;;
    --no-build) NO_BUILD=true ;;
    --allow-remote-mongo) ALLOW_REMOTE=true ;;
    --delete-data) DELETE_DATA=true ;;
    -f | --follow) FOLLOW=true ;;
    -h | --help) COMMAND=help ;;
    -*) die "Unknown option '$1'. See: ./run.sh help" ;;
    *)
      if [[ "$COMMAND" == logs && -z "$SERVICE" ]]; then SERVICE=$1; else die "Unknown command '$1'. See: ./run.sh help"; fi
      ;;
  esac
  shift
done

# ---------------------------------------------------------------------------------------
# Settings: an environment variable wins over deployment/env/local.env, which wins
# over the default. Values are read, never printed (only ports and names are shown).

file_value() {
  [[ -f "$ENV_FILE" ]] || return 0
  python3 - "$ENV_FILE" "$1" <<'PY'
import sys

path, wanted = sys.argv[1], sys.argv[2]
value = ""
with open(path, encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, rest = line.partition("=")
        if not sep or key.strip() != wanted:
            continue
        rest = rest.strip()
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "'\"":
            rest = rest[1:-1]
        else:
            rest = rest.split(" #", 1)[0].rstrip()
        value = rest
print(value)
PY
}

setting() {
  local value
  value=$(printenv "$1" 2>/dev/null || true)
  [[ -n "$value" ]] || value=$(file_value "$1")
  [[ -n "$value" ]] || value=${2-}
  printf '%s' "$value"
}

port_setting() {
  local value
  value=$(setting "$1" "$2")
  if [[ ! "$value" =~ ^[0-9]{1,5}$ ]] || ((10#$value < 1 || 10#$value > 65535)); then
    die "$1 must be a port number from 1 to 65535." "Fix it in $(shown "$ENV_FILE")."
  fi
  printf '%s' "$((10#$value))"
}

shown() { # a path as the person sees it: relative to the repository when inside it
  case "$1" in "$ROOT"/*) printf '%s' "${1#"$ROOT"/}" ;; *) printf '%s' "$1" ;; esac
}

load_settings() {
  PROJECT=$(setting COMPOSE_PROJECT_NAME news-bot)
  [[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] ||
    die "COMPOSE_PROJECT_NAME must use only lower-case letters, numbers, - and _."
  PORT_WEB=$(port_setting LOCAL_PORT_WEB 8090)
  PORT_MCP=$(port_setting LOCAL_PORT_MCP 8091)
  PORT_COLLECTOR=$(port_setting LOCAL_PORT_COLLECTOR 8080)
  PORT_CLASSIFIER=$(port_setting LOCAL_PORT_CLASSIFIER 8000)
  PORT_RANKER=$(port_setting LOCAL_PORT_RANKER 8001)
  PORT_MONGO=$(port_setting LOCAL_PORT_MONGO 27017)
  DATABASE=$(setting NEWS_MONGO_DATABASE news)
  [[ "$DATABASE" =~ ^[A-Za-z0-9_-]{1,63}$ ]] ||
    die "NEWS_MONGO_DATABASE must use only letters, numbers, - and _."
  MIN_ARTICLES=$(setting LOCAL_MIN_ARTICLES 500)
  if [[ ! "$MIN_ARTICLES" =~ ^[0-9]{1,7}$ ]] || ((10#$MIN_ARTICLES < 100)); then
    die "LOCAL_MIN_ARTICLES must be a number of 100 or more."
  fi
  MIN_ARTICLES=$((10#$MIN_ARTICLES))
  PINNED_SNAPSHOT=$(setting NEWS_RANKER_SNAPSHOT "")
  SCHEDULER=$(setting NEWS_SCHEDULER_ENABLED true | tr '[:upper:]' '[:lower:]')
  case "$SCHEDULER" in 0 | f | false) SCHEDULER=false ;; *) SCHEDULER=true ;; esac

  MONGO_URI=$(setting NEWS_MONGO_URI "")
  if [[ -z "$MONGO_URI" ]]; then
    MONGO_MODE=compose
    MONGO_WHERE=local
    MONGO_HOSTS="127.0.0.1:$PORT_MONGO"
  else
    MONGO_MODE=external
    describe_external_mongo
  fi

  COMPOSE_ARGS=(-p "$PROJECT" -f "$COMPOSE_FILE")
  [[ "$MONGO_MODE" == external ]] && COMPOSE_ARGS+=(-f "$EXTERNAL_FILE")
  [[ -f "$ENV_FILE" ]] && COMPOSE_ARGS+=(--env-file "$ENV_FILE")
  return 0
}

# Where is the MongoDB in NEWS_MONGO_URI, and how do containers reach it? The URI is
# passed in the environment, never on a command line, and is never printed.
describe_external_mongo() {
  local info
  info=$(RUNSH_MONGO_URI="$MONGO_URI" python3 - <<'PY'
import os
import re

uri = os.environ["RUNSH_MONGO_URI"]
match = re.match(r"^(mongodb(?:\+srv)?)://((?:[^@/?]*@)?)([^/?]*)(.*)$", uri, re.S)
if not match:
    print("invalid")
    raise SystemExit
scheme, credentials, hosts, rest = match.groups()
loopback = {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}
this_computer = loopback | {"host.docker.internal", "host.containers.internal", "host.lima.internal"}


def name_of(host):
    host = host.strip()
    if host.startswith("["):
        return host[1:host.find("]")].lower()
    return host.rsplit(":", 1)[0].lower() if host.count(":") == 1 else host.lower()


def for_containers(host):
    host = host.strip()
    name = name_of(host)
    if name in loopback or name.startswith("127."):
        port = host.rsplit(":", 1)[1] if host.rfind(":") > host.rfind("]") else "27017"
        return "host.docker.internal:" + port
    return host


parts = [part for part in hosts.split(",") if part.strip()]
names = [name_of(part) for part in parts]
local = scheme == "mongodb" and bool(names) and all(
    name in this_computer or name.startswith("127.") for name in names
)
print("local" if local else "remote")
print(",".join(part.strip() for part in parts) or "?")
print(f"{scheme}://{credentials}{','.join(for_containers(part) for part in parts)}{rest}")
PY
)
  [[ "$info" != invalid ]] ||
    die "NEWS_MONGO_URI in $(shown "$ENV_FILE") is not a mongodb:// address." \
      "Leave it empty to use a new MongoDB in Docker."
  MONGO_WHERE=$(printf '%s\n' "$info" | sed -n 1p)
  MONGO_HOSTS=$(printf '%s\n' "$info" | sed -n 2p)
  local derived explicit
  derived=$(printf '%s\n' "$info" | sed -n 3p)
  explicit=$(setting NEWS_EXTERNAL_MONGO_URI "")
  NEWS_EXTERNAL_MONGO_URI=${explicit:-$derived}
  export NEWS_EXTERNAL_MONGO_URI
}

# The database address as programs on this computer (not in containers) see it.
host_mongo_uri() {
  if [[ "$MONGO_MODE" == external ]]; then
    printf '%s' "$MONGO_URI"
  else
    local published
    published=$(compose port mongo 27017 2>/dev/null | tail -n 1 || true)
    printf 'mongodb://127.0.0.1:%s/' "${published##*:}"
  fi
}

compose() { docker compose "${COMPOSE_ARGS[@]}" "$@"; }

# ---------------------------------------------------------------------------------------
# Checks

version_at_least() { # version_at_least 2.24.0 2.20 -> true
  python3 - "$1" "$2" <<'PY'
import re
import sys

def parts(text):
    return [int(number) for number in re.findall(r"\d+", text)[:3]] + [0, 0, 0]

sys.exit(0 if parts(sys.argv[1])[:3] >= parts(sys.argv[2])[:3] else 1)
PY
}

check_prerequisites() { # "all" for start and refresh, "docker" for stop, status and logs
  local problems=()
  if ! command -v python3 >/dev/null 2>&1; then
    problems+=("python3 is not installed. Install Python 3 from https://www.python.org/downloads/ (or your package manager).")
  fi
  if ! command -v docker >/dev/null 2>&1; then
    problems+=("Docker is not installed. Install Docker Desktop, Rancher Desktop or Docker Engine: https://docs.docker.com/get-docker/")
  elif ! docker info >/dev/null 2>&1; then
    problems+=("Docker is installed but not running. Start Docker Desktop (or Rancher Desktop), wait until it is ready, then try again.")
  elif ! docker compose version >/dev/null 2>&1; then
    problems+=("Docker Compose v2 (the 'docker compose' command) is missing. Update Docker: https://docs.docker.com/compose/install/")
  elif command -v python3 >/dev/null 2>&1 &&
    ! version_at_least "$(docker compose version --short 2>/dev/null || echo 0)" 2.24.4; then
    problems+=("Docker Compose is too old ($(docker compose version --short 2>/dev/null)). Version 2.24.4 or newer is needed. Update Docker.")
  fi
  if [[ "${1:-all}" == all ]] && ! command -v uv >/dev/null 2>&1; then
    problems+=("uv is not installed. It installs Python and its packages. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh")
  fi
  if [[ ${#problems[@]} -gt 0 ]]; then
    printf '\n%sSome tools are missing:%s\n' "$RED" "$RESET" >&2
    local problem
    for problem in "${problems[@]}"; do printf '  - %s\n' "$problem" >&2; done
    printf '\nInstall them, then run ./run.sh again.\n' >&2
    exit 1
  fi
}

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# Every port we are about to publish must be free, unless our own container has it.
check_ports() {
  local busy=() entry service inner port variable mine
  for entry in "$@"; do
    IFS=: read -r service inner port variable <<<"$entry"
    mine=$(compose port "$service" "$inner" 2>/dev/null | tail -n 1 || true)
    [[ -n "$mine" && "${mine##*:}" == "$port" ]] && continue
    if port_in_use "$port"; then busy+=("$port (for $service): set $variable=<free port> in $(shown "$ENV_FILE")"); fi
  done
  if [[ ${#busy[@]} -gt 0 ]]; then
    printf '\n%sProblem:%s another program already uses these ports on 127.0.0.1:\n' "$RED" "$RESET" >&2
    for entry in "${busy[@]}"; do printf '  - %s\n' "$entry" >&2; done
    printf '\nStop that program, or choose free ports as shown (for example 18090), then run ./run.sh again.\n' >&2
    if [[ "$MONGO_MODE" == compose && " ${busy[*]} " == *"(for mongo)"* ]]; then
      printf 'If MongoDB already runs on this computer, you can use it instead: set NEWS_MONGO_URI=mongodb://127.0.0.1:27017/\n' >&2
      printf 'in %s (the collector then adds news to it; see the notes in local.env.example).\n' "$(shown "$ENV_FILE")" >&2
    fi
    exit 1
  fi
}

take_lock() {
  mkdir -p "$STATE"
  if ! mkdir "$STATE/lock" 2>/dev/null; then
    local pid
    pid=$(cat "$STATE/lock/pid" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      die "run.sh is already running (process $pid). Wait for it to finish, then try again."
    fi
    rm -rf "$STATE/lock"
    mkdir "$STATE/lock"
  fi
  echo "$$" >"$STATE/lock/pid"
  trap 'rm -rf "$STATE/lock"' EXIT
  trap 'printf "\nStopped. Services that already started keep running; ./run.sh continues from here.\n" >&2; exit 130' INT TERM
}

# ---------------------------------------------------------------------------------------
# The settings file

prepare_env_file() {
  step "Settings"
  if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f "$ENV_EXAMPLE" ]] || die "$(shown "$ENV_EXAMPLE") is missing. Is this a full copy of the repository?"
    mkdir -p "$(dirname "$ENV_FILE")"
    (umask 077 && cp "$ENV_EXAMPLE" "$ENV_FILE")
    good "Made $(shown "$ENV_FILE") from local.env.example."
  fi
  local filled
  filled=$(python3 - "$ENV_FILE" <<'PY'
import hashlib
import os
import secrets
import sys
import tempfile
from datetime import date

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    lines = handle.read().splitlines()


def parse(line):
    text = line.strip()
    if not text or text.startswith("#"):
        return None, None
    if text.startswith("export "):
        text = text[len("export "):].lstrip()
    key, sep, value = text.partition("=")
    if not sep:
        return None, None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return key.strip(), value


values, where = {}, {}
for number, line in enumerate(lines):
    key, value = parse(line)
    if key:
        values[key], where[key] = value, number

new = {}
for key in ("NEWS_CLASSIFIER_API_KEY", "NEWS_RECOMMENDER_API_KEY"):
    if not values.get(key):
        new[key] = secrets.token_hex(32)
if not values.get("NEWS_AUTH_API_KEYS") and not values.get("NEWS_AUTH_BASIC_PASSWORD"):
    new["NEWS_AUTH_API_KEYS"] = secrets.token_hex(32)
if not values.get("NEWS_MCP_API_KEYS"):
    agent_key = values.get("LOCAL_MCP_AGENT_KEY") or secrets.token_urlsafe(32)
    if not values.get("LOCAL_MCP_AGENT_KEY"):
        new["LOCAL_MCP_AGENT_KEY"] = agent_key
    new["NEWS_MCP_API_KEYS"] = "local:" + hashlib.sha256(agent_key.encode()).hexdigest()
if not new:
    raise SystemExit

added = []
for key, value in new.items():
    if key in where:
        lines[where[key]] = f"{key}={value}"
    else:
        added.append(f"{key}={value}")
if added:
    lines += ["", f"# Added by run.sh on {date.today().isoformat()}: new random local keys."] + added
handle, temporary = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".run-sh-", suffix=".tmp")
with os.fdopen(handle, "w", encoding="utf-8") as out:
    out.write("\n".join(lines) + "\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
print(", ".join(new))
PY
) || die "Could not update $(shown "$ENV_FILE")."
  if [[ -n "$filled" ]]; then
    good "Filled in new random keys (kept private, not shown): $filled"
  else
    good "Using $(shown "$ENV_FILE")."
  fi
}

# ---------------------------------------------------------------------------------------
# Model, Python tools and images

stdlib_python() { # the download script needs Python 3.11 or newer
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    python3 "$@"
  else
    uv run --quiet --no-project --python 3.12 python "$@"
  fi
}

download_models() {
  step "Topic model"
  if stdlib_python "$MODELS_SCRIPT" --check >/dev/null 2>&1; then
    good "The topic model is here and matches its SHA-256 fingerprint."
    return
  fi
  say "Downloading the topic model (about 45 MB) and checking its SHA-256 fingerprints..."
  stdlib_python "$MODELS_SCRIPT" ||
    die "The model download failed (see the message above). Check your internet connection, then run ./run.sh again."
}

ensure_ml_tools() {
  step "Python tools for the ranker"
  if [[ ! -x "$ML_PY" ]]; then
    say "Installing them into ml/.venv. The first time this downloads about 1 GB and takes a few minutes."
  fi
  uv sync --project "$ROOT/ml" --frozen --inexact --no-dev --group recommend --quiet ||
    die "uv could not install the Python tools in ml/ (see the message above)."
  good "ml/.venv is ready."
}

build_images() {
  if $NO_BUILD; then return; fi
  step "Docker images"
  say "Building the app's images. The first time takes 10-20 minutes; later runs take seconds."
  compose build || die "Building the images failed (see the messages above)."
}

# ---------------------------------------------------------------------------------------
# Database helpers (they run the ml/.venv Python; the address goes in the environment)

db_run() {
  NEWS_ENV_FILE=/dev/null NEWS_MONGO_URI="$(host_mongo_uri)" NEWS_MONGO_DATABASE="$DATABASE" "$@"
}

# Articles collected more than two minutes ago: the ones a snapshot can use now.
count_ready_articles() {
  db_run "$ML_PY" - <<'PY'
import os
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

cut = datetime.now(timezone.utc) - timedelta(minutes=2)
with MongoClient(os.environ["NEWS_MONGO_URI"], serverSelectionTimeoutMS=10_000) as client:
    print(client[os.environ["NEWS_MONGO_DATABASE"]].articles.count_documents({"collected_at": {"$lt": cut}}))
PY
}

count_all_articles() {
  db_run "$ML_PY" - <<'PY' 2>/dev/null || echo "?"
import os

from pymongo import MongoClient

with MongoClient(os.environ["NEWS_MONGO_URI"], serverSelectionTimeoutMS=5_000) as client:
    print(f'{client[os.environ["NEWS_MONGO_DATABASE"]].articles.estimated_document_count():,}')
PY
}

# "match" when the newest snapshot's stories are in this database, "other" when not,
# "none" when there is no finished snapshot.
snapshot_state() {
  db_run "$ML_PY" - "$SNAPSHOTS" "$PINNED_SNAPSHOT" <<'PY'
import json
import os
import sys
from pathlib import Path

from pymongo import MongoClient

root, pinned = Path(sys.argv[1]), sys.argv[2]
pointer = root / "LATEST_DEMO"
snapshot = pinned or (pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else "")
folder = root / snapshot
if not snapshot or not (folder / "training.json").is_file() or not (folder / "documents.jsonl").is_file():
    print("none")
    raise SystemExit
ids = []
with (folder / "documents.jsonl").open(encoding="utf-8") as handle:
    for line in handle:
        ids.append(json.loads(line)["id"])
        if len(ids) == 20:
            break
with MongoClient(os.environ["NEWS_MONGO_URI"], serverSelectionTimeoutMS=10_000) as client:
    found = client[os.environ["NEWS_MONGO_DATABASE"]].articles.count_documents({"_id": {"$in": ids}})
print("match" if found else "other")
PY
}

# A loopback address can still be an SSH tunnel to another computer, so ask the
# server for its computer name and compare it with ours.
mongo_computer_name() {
  db_run "$ML_PY" - <<'PY' 2>/dev/null || true
import os

from pymongo import MongoClient

with MongoClient(os.environ["NEWS_MONGO_URI"], serverSelectionTimeoutMS=5_000) as client:
    print(client.admin.command("hostInfo")["system"]["hostname"])
PY
}

short_name() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | cut -d. -f1; }

check_mongo_is_here() {
  [[ "$MONGO_MODE" == external ]] || return 0
  step "Database"
  if [[ "$MONGO_WHERE" == remote ]]; then
    $ALLOW_REMOTE || die "NEWS_MONGO_URI points at a MongoDB on another computer ($MONGO_HOSTS)." \
      "The collector writes news into that database, so run.sh refuses it." \
      "If you really want that, run:  ./run.sh --allow-remote-mongo" \
      "To use a new database on this computer instead, empty NEWS_MONGO_URI in $(shown "$ENV_FILE")."
    note "Using the MongoDB at $MONGO_HOSTS on another computer, because of --allow-remote-mongo."
    return
  fi
  local theirs ours
  theirs=$(mongo_computer_name)
  ours=$(hostname 2>/dev/null || uname -n)
  if [[ -n "$theirs" && "$(short_name "$theirs")" != "$(short_name "$ours")" ]] && ! $ALLOW_REMOTE; then
    die "The MongoDB at $MONGO_HOSTS says it runs on a computer named '$theirs', but this computer is '$ours'." \
      "It may be an SSH tunnel to another computer (or a container). The collector would write news into it." \
      "If that is really what you want, run:  ./run.sh --allow-remote-mongo"
  fi
  good "Using your own MongoDB at $MONGO_HOSTS, database '$DATABASE'. The collector adds news to it."
}

# ---------------------------------------------------------------------------------------
# Ranker snapshot

build_snapshot() {
  local id cut log
  id="demo-$(date -u +%Y%m%dT%H%M%SZ)"
  cut=$("$ML_PY" -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(timespec="seconds"))')
  mkdir -p "$STATE/logs" "$SNAPSHOTS"
  log="$STATE/logs/snapshot-$id.log"
  say "Building ranker snapshot $id (full log: $(shown "$log"))"
  say "  1 of 3: reading and cleaning recent articles"
  db_run "$ML_PY" -m newsrec prepare --id "$id" --cut "$cut" --limit 30000 --candidates 40000 --recent-days 7 >>"$log" 2>&1 ||
    snapshot_failed "$log"
  say "  2 of 3: TF-IDF and SVD"
  db_run "$ML_PY" -m newsrec baseline --id "$id" >>"$log" 2>&1 || snapshot_failed "$log"
  say "  3 of 3: training the small neural network"
  db_run "$ML_PY" -m newsrec train --id "$id" >>"$log" 2>&1 || snapshot_failed "$log"
  printf '%s\n' "$id" >"$POINTER.tmp"
  mv "$POINTER.tmp" "$POINTER"
  good "Snapshot $id is ready."
}

snapshot_failed() {
  printf '\nThe last lines of %s:\n' "$(shown "$1")" >&2
  tail -n 25 "$1" >&2
  die "Building the ranker snapshot failed (see above)."
}

wait_for_articles() {
  local have waited=0 limit=1800
  while :; do
    have=$(count_ready_articles) || die "Cannot read the database (see the message above)."
    ((have >= MIN_ARTICLES)) && return 0
    if [[ "$SCHEDULER" == false ]]; then
      die "The database has only $have articles, and the collector is switched off (NEWS_SCHEDULER_ENABLED=false)." \
        "Switch it on in $(shown "$ENV_FILE"), or lower LOCAL_MIN_ARTICLES (at least 100)."
    fi
    if ((waited >= limit)); then
      die "After 30 minutes the database has only $have of $MIN_ARTICLES articles." \
        "Check the collector with: ./run.sh logs collector"
    fi
    if ((waited % 60 == 0)); then
      say "  The collector is gathering news: $have of $MIN_ARTICLES articles so far (waited $((waited / 60)) min)."
    fi
    sleep 15
    waited=$((waited + 15))
  done
}

ensure_snapshot() {
  step "Ranker snapshot"
  local state
  state=$(snapshot_state) || die "Cannot read the database to check the ranker snapshot (see above)."
  case "$state" in
    match)
      good "Using snapshot $(snapshot_name). Build a newer one at any time with ./run.sh refresh."
      return
      ;;
    other)
      if [[ -n "$PINNED_SNAPSHOT" ]]; then
        die "NEWS_RANKER_SNAPSHOT=$PINNED_SNAPSHOT was built from another database: none of its stories are in '$DATABASE'." \
          "Empty NEWS_RANKER_SNAPSHOT in $(shown "$ENV_FILE") to build a new one."
      fi
      say "The newest snapshot ($(snapshot_name)) was built from another database, so run.sh builds a new one."
      ;;
    none)
      [[ -z "$PINNED_SNAPSHOT" ]] ||
        die "NEWS_RANKER_SNAPSHOT=$PINNED_SNAPSHOT is not a finished snapshot in $(shown "$SNAPSHOTS")."
      say "There is no ranker snapshot yet, so run.sh builds the first one."
      ;;
  esac
  say "It needs at least $MIN_ARTICLES articles. Waiting for the collector..."
  wait_for_articles
  build_snapshot
}

snapshot_name() {
  if [[ -n "$PINNED_SNAPSHOT" ]]; then
    printf '%s' "$PINNED_SNAPSHOT"
  elif [[ -f "$POINTER" ]]; then
    tr -d '[:space:]' <"$POINTER"
  else
    printf 'none'
  fi
}

# ---------------------------------------------------------------------------------------
# Status

STATUS_TABLE=$(
  cat <<'PY'
import json
import os
import sys

text = sys.stdin.read().strip()
rows = []
if text.startswith("["):
    rows = json.loads(text)
elif text:
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
by_service = {row.get("Service"): row for row in rows}
web_services = ("classifier", "collector", "ranker", "web", "mcp")
print("  %-12s%-12s%-12s%s" % ("Service", "State", "Health", "Address on this computer"))
for name in os.environ["RUNSH_SERVICES"].split():
    if name == "mongo" and os.environ["RUNSH_MODE"] == "external":
        print("  %-12s%-12s%-12s%s" % (name, "(yours)", "-", "your own MongoDB, not in Docker"))
        continue
    row = by_service.get(name)
    if not row:
        print("  %-12s%s" % (name, "not started"))
        continue
    ports = sorted({"127.0.0.1:%s" % item["PublishedPort"] for item in row.get("Publishers") or [] if item.get("PublishedPort")})
    address = ", ".join(ports)
    if address and name in web_services:
        address = "http://" + address + ("/mcp" if name == "mcp" else "/")
    print("  %-12s%-12s%-12s%s" % (name, row.get("State") or "?", row.get("Health") or "-", address))
PY
)

print_status() {
  compose --profile mcp ps -a --format json 2>/dev/null |
    RUNSH_SERVICES="$ALL_SERVICES" RUNSH_MODE="$MONGO_MODE" python3 -c "$STATUS_TABLE"
}

web_address() {
  local published
  published=$(compose port web 8090 2>/dev/null | tail -n 1 || true)
  if [[ -n "$published" ]]; then printf 'http://127.0.0.1:%s/' "${published##*:}"; fi
  return 0
}

web_answers() { # GET <url> answers 200 within 30 seconds
  python3 - "$1" <<'PY'
import sys
import time
from urllib.request import urlopen

for _ in range(30):
    try:
        with urlopen(sys.argv[1], timeout=5) as response:
            if response.status == 200:
                raise SystemExit(0)
    except OSError:
        pass
    time.sleep(1)
raise SystemExit(1)
PY
}

# ---------------------------------------------------------------------------------------
# Commands

cmd_start() {
  check_prerequisites
  take_lock
  say "${BOLD}news-bot${RESET}: starting everything on this computer. This is safe to run again."
  prepare_env_file
  load_settings
  download_models
  ensure_ml_tools
  mkdir -p "$SNAPSHOTS"

  local first=(classifier collector) second=(ranker web) ports=() profile=()
  [[ "$MONGO_MODE" == compose ]] && first=(mongo "${first[@]}")
  if $WITH_MCP; then
    second+=(mcp)
    profile=(--profile mcp)
  fi
  [[ "$MONGO_MODE" == compose ]] && ports+=("mongo:27017:$PORT_MONGO:LOCAL_PORT_MONGO")
  ports+=("classifier:8000:$PORT_CLASSIFIER:LOCAL_PORT_CLASSIFIER" "collector:8080:$PORT_COLLECTOR:LOCAL_PORT_COLLECTOR"
    "ranker:8001:$PORT_RANKER:LOCAL_PORT_RANKER" "web:8090:$PORT_WEB:LOCAL_PORT_WEB")
  $WITH_MCP && ports+=("mcp:8091:$PORT_MCP:LOCAL_PORT_MCP")
  check_ports "${ports[@]}"
  check_mongo_is_here
  build_images

  if [[ "$MONGO_MODE" == compose ]]; then
    step "Starting the database, the classifier and the collector"
    say "MongoDB runs in Docker on 127.0.0.1:$PORT_MONGO, database '$DATABASE'. Its data stays in the Docker volume ${PROJECT}_mongo-data."
  else
    step "Starting the classifier and the collector"
  fi
  say "The classifier loads its model first; this can take a minute or two."
  compose up -d --no-build --wait --wait-timeout 900 "${first[@]}" || {
    print_status
    die "Some services did not become healthy (see the table above)." "Read a log with: ./run.sh logs <service>"
  }
  good "Running and healthy: ${first[*]}."

  ensure_snapshot

  step "Starting the ranker and the web app"
  compose ${profile[@]+"${profile[@]}"} up -d --no-build --wait --wait-timeout 600 "${second[@]}" || {
    print_status
    die "Some services did not become healthy (see the table above)." "Read a log with: ./run.sh logs <service>"
  }
  local url
  url=$(web_address)
  if [[ -z "$url" ]] || ! web_answers "${url}health/ready"; then
    die "The web app does not answer on ${url:-its port}. Read its log with: ./run.sh logs web"
  fi

  step "news-bot is running"
  print_status
  say ""
  say "  Snapshot:  $(snapshot_name)   (build a newer one with ./run.sh refresh)"
  say "  Database:  '$DATABASE' with $(count_all_articles) articles"
  if $WITH_MCP; then
    say "  MCP:       http://127.0.0.1:$PORT_MCP/mcp  (the agent key is LOCAL_MCP_AGENT_KEY in $(shown "$ENV_FILE"))"
  fi
  say ""
  say "  ${BOLD}Open the reader: ${url}${RESET}"
  say ""
  say "  ./run.sh status   ./run.sh logs <service>   ./run.sh refresh   ./run.sh stop"
}

cmd_refresh() {
  check_prerequisites
  take_lock
  load_settings
  if [[ "$MONGO_MODE" == compose ]] && [[ -z "$(compose ps --status running --services 2>/dev/null | grep -x mongo || true)" ]]; then
    die "The database is not running. Start everything first with: ./run.sh"
  fi
  ensure_ml_tools
  [[ -z "$PINNED_SNAPSHOT" ]] ||
    note "NEWS_RANKER_SNAPSHOT=$PINNED_SNAPSHOT is set, so the ranker keeps serving that one. Empty it to use the new snapshot."
  step "New ranker snapshot"
  local have
  have=$(count_ready_articles) || die "Cannot read the database (see the message above)."
  ((have >= 100)) ||
    die "The database has only $have articles; a snapshot needs at least 100. Let the collector run longer."
  build_snapshot
  step "Restarting the ranker"
  if [[ -n "$(compose ps --status running --services 2>/dev/null | grep -x ranker || true)" ]]; then
    compose restart ranker >/dev/null
  fi
  compose up -d --no-build --wait --wait-timeout 600 ranker ||
    die "The ranker did not become healthy. Read its log with: ./run.sh logs ranker"
  good "The ranker now serves $(snapshot_name)."
}

cmd_stop() {
  check_prerequisites docker
  take_lock
  load_settings
  if $DELETE_DATA; then
    step "Stopping news-bot and deleting its Docker database"
    compose --profile "*" down --remove-orphans --volumes
    good "Stopped. The Docker database (all news collected in Docker) is deleted."
  else
    step "Stopping news-bot"
    compose --profile "*" down --remove-orphans
    if [[ "$MONGO_MODE" == compose ]]; then
      good "Stopped. Your news is kept in the Docker volume ${PROJECT}_mongo-data. Start again with ./run.sh"
    else
      good "Stopped. Your own MongoDB keeps running; run.sh never stops it. Start again with ./run.sh"
    fi
  fi
}

cmd_status() {
  check_prerequisites docker
  load_settings
  printf '%snews-bot%s (Docker Compose project "%s")\n\n' "$BOLD" "$RESET" "$PROJECT"
  print_status
  say ""
  say "  Snapshot:  $(snapshot_name)"
  if [[ "$MONGO_MODE" == compose ]]; then
    say "  Database:  MongoDB in Docker, database '$DATABASE'"
  else
    say "  Database:  your own MongoDB at $MONGO_HOSTS, database '$DATABASE'"
  fi
  local url
  url=$(web_address || true)
  if [[ -n "$url" ]]; then say "  Reader:    $url"; else say "  Reader:    not running (start with ./run.sh)"; fi
}

cmd_logs() {
  [[ -n "$SERVICE" ]] || die "Name a service, for example: ./run.sh logs collector" "Services: $ALL_SERVICES"
  [[ " $ALL_SERVICES " == *" $SERVICE "* ]] || die "There is no service '$SERVICE'." "Services: $ALL_SERVICES"
  check_prerequisites docker
  load_settings
  if $FOLLOW; then
    compose --profile "*" logs --tail 200 --follow "$SERVICE"
  else
    compose --profile "*" logs --tail 200 "$SERVICE"
  fi
}

case "$COMMAND" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  refresh) cmd_refresh ;;
  help) usage ;;
esac
