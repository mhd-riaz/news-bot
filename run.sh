#!/usr/bin/env bash
# Start the local news-bot stack, each service in its own macOS terminal window.
#
#   ./run.sh                   # mongo, api, ranker, reader
#   ./run.sh ranker reader     # only the named services
#   RUN_TERMINAL=iterm ./run.sh
#
# A service whose port is already listening is skipped, so re-running is safe.
# Services read deployment/env/local.env themselves; nothing secret passes through this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR="$ROOT/collector"
TERMINAL_APP="${RUN_TERMINAL:-terminal}"
ALL_SERVICES=(mongo api ranker reader)

port_of() {
  case "$1" in
    mongo) echo 27017 ;;
    api) echo 8080 ;;
    ranker) echo 8001 ;;
    reader) echo 8090 ;;
  esac
}

command_of() {
  case "$1" in
    api) echo "make run" ;; # the collector: migrates and writes to the configured database
    ranker) echo "make -C ../ml demo-serve" ;;
    reader) echo "make reader" ;;
  esac
}

process_of() {
  case "$1" in
    api) echo "cmd/api" ;;
    ranker) echo "newsrec serve" ;;
    reader) echo "cmd/reader" ;;
  esac
}

listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

wait_for_port() {
  local port=$1 seconds=$2
  for _ in $(seq "$seconds"); do
    listening "$port" && return 0
    sleep 1
  done
  return 1
}

applescript_quote() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

open_terminal() {
  local title=$1 cmd=$2 script
  script="$(applescript_quote "cd '$COLLECTOR' && printf '\\033]0;news-bot: $title\\007' && $cmd")"
  case "$TERMINAL_APP" in
    iterm)
      osascript >/dev/null <<EOF
tell application "iTerm"
  activate
  set w to (create window with default profile)
  tell current session of w to write text "$script"
end tell
EOF
      ;;
    terminal)
      osascript >/dev/null <<EOF
tell application "Terminal"
  activate
  do script "$script"
end tell
EOF
      ;;
    *)
      echo "RUN_TERMINAL must be 'terminal' or 'iterm', got '$TERMINAL_APP'" >&2
      exit 1
      ;;
  esac
}

start_mongo() {
  if listening 27017; then
    echo "mongo   already running on :27017"
    return
  fi
  if command -v brew >/dev/null 2>&1 && brew list --formula mongodb-community >/dev/null 2>&1; then
    echo "mongo   starting with brew services"
    brew services start mongodb-community >/dev/null
  else
    echo "mongo   starting with docker compose"
    (cd "$COLLECTOR" && make mongo-up >/dev/null)
  fi
  wait_for_port 27017 30 || { echo "mongo   did not start on :27017" >&2; exit 1; }
  echo "mongo   ready on :27017"
}

start_service() {
  local name=$1 port
  port="$(port_of "$name")"
  if listening "$port"; then
    printf "%-7s already running on :%s (skipped)\n" "$name" "$port"
    return
  fi
  # Catches a service that is still compiling or loading and has not bound its port yet.
  if pgrep -f "$(process_of "$name")" >/dev/null 2>&1; then
    printf "%-7s already starting (skipped)\n" "$name"
    return
  fi
  if [[ $name == ranker && ! -s "$ROOT/ml/artifacts/recommender/LATEST_DEMO" ]]; then
    echo "ranker  no demo snapshot yet: run 'make demo-refresh' in ml/ first (skipped)" >&2
    return
  fi
  # The first run asks macOS for permission to control the terminal app; a slow answer
  # can time out here even though the window still opens once allowed.
  if open_terminal "$name" "$(command_of "$name")"; then
    printf "%-7s opened in a new terminal (port :%s)\n" "$name" "$port"
  else
    printf "%-7s could not confirm its terminal opened; allow terminal control in System Settings > Privacy & Security > Automation\n" "$name" >&2
  fi
}

main() {
  [[ "$(uname)" == Darwin ]] || { echo "run.sh opens macOS terminal windows; run the make targets by hand elsewhere." >&2; exit 1; }

  local services=("$@")
  [[ ${#services[@]} -gt 0 ]] || services=("${ALL_SERVICES[@]}")
  for s in "${services[@]}"; do
    [[ -n "$(port_of "$s")" ]] || { echo "Unknown service '$s'. Choose from: ${ALL_SERVICES[*]}" >&2; exit 1; }
  done

  local started=()
  for s in "${services[@]}"; do
    if [[ $s == mongo ]]; then
      start_mongo
    else
      start_service "$s"
      started+=("$s")
    fi
  done

  # Go and Python startup (compiling, loading the snapshot) can take a while.
  for s in "${started[@]+"${started[@]}"}"; do
    local port
    port="$(port_of "$s")"
    if wait_for_port "$port" 120; then
      printf "%-7s listening on :%s\n" "$s" "$port"
    else
      printf "%-7s not listening on :%s after 120 s: check its terminal window\n" "$s" "$port" >&2
    fi
  done

  echo
  echo "Reader: http://127.0.0.1:8090/stories   Stop a service with Ctrl+C in its window."
}

main "$@"
