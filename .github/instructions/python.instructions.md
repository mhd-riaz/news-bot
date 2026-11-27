---
applyTo: "ml/**,server/**"
---

# Python (ml/ and server/)

- Python 3.12 and uv everywhere. `ml/` and `server/` are separate uv projects, each with a committed `uv.lock`. Install with `uv sync --frozen` and run tools with `uv run`.
- `ml/`: keep the package names `newsml`, `newsmlv2`, `newsrec` and `newsmlv4`. The production classifier model stores the module paths `newsmlv4.train` and `newsmlv2.models`, so renaming them stops the model from loading.
- `ml/`: models are not in git. `ml/models.toml` lists them with SHA-256 checksums, and `make -C ml models` fetches them into `ml/models/` (it runs the download script with uv's Python 3.12, because the script needs Python 3.11 or newer). Files you build locally (ranker snapshots, training runs) go in `ml/artifacts/`, which git also ignores.
- `ml/`: the ranker image installs `ml/recommender/requirements.txt`, pinned to the same versions as `ml/uv.lock`, because snapshots store scikit-learn objects. Change both together.
- Pin, seed and make training reproducible. Notebooks may call `src/` but never hold logic (hard rule 12). Never tune or train on sealed test cases (hard rule 4).
- `server/`: the web app (`newsbot_server.web`) and the MCP program (`newsbot_server.mcp`) share `newsbot_server.core`. MCP is read-only: it has no write tools and uses its own MongoDB user that can only read `articles`.
- `server/`: every state-changing request needs a signed-in session and must pass the cross-site check (`Sec-Fetch-Site`, then `Origin`). Sign-in may be off only on localhost, or in development behind `NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK`.
- Check with `make -C ml test` and `cd server && uv run pytest`. Tests that write to MongoDB use throwaway databases, never `news`.
