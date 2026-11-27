---
name: run-locally
description: Start, stop and check the whole news-bot app on this computer with run.sh. Use when someone asks to run, restart, debug or check the local app, its services, ports or logs.
---

# Run news-bot on this computer

`run.sh` at the repository root starts every part of the app. Read `README.md` for what to install first.

## Commands

| Command | What it does |
| --- | --- |
| `./run.sh` | Starts everything and prints the reader's web address |
| `./run.sh status` | Shows which services are running and healthy |
| `./run.sh logs <service>` | Shows one service's log |
| `./run.sh refresh` | Builds a new ranker snapshot from the database, then restarts the ranker |
| `./run.sh stop` | Stops everything |
| `./run.sh help` | Lists every command and option |

## Services and ports

| Service | Folder | Port | Health check |
| --- | --- | --- | --- |
| MongoDB (database) | — | 27017 | — |
| Classifier (sorts news into topics) | `ml/classifier` | 8000 | `/health/ready` |
| Ranker (picks stories for each reader) | `ml/recommender` | 8001 | `/health/ready` |
| Collector (reads news feeds) | `collector` | 8080 | `/health/ready` |
| Web server and reader app | `server`, `frontend` | 8090 | `/health/ready` |
| MCP server for AI agents (optional) | `server` | 8091 | — |

Every port listens on 127.0.0.1 only.

## Rules

- Settings come from `deployment/env/local.env`. Never print, paste or commit its values.
- The collector writes to the database it is given. Only run it against a database on this computer.
- If a service is unhealthy, read its log with `./run.sh logs <service>` before changing code. Find the real error first.
- The classifier needs its model file. `run.sh` downloads it from the project's public Google Drive folder, with no sign-in (by hand: `make -C ml models`, which uses uv's Python 3.12).
