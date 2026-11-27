# Web server and MCP program

The folder [`server/`](../../server/README.md) holds two Python programs that share
one package, `newsbot_server`:

- **`newsbot-server`**, the web server. It serves the reader's pages and API, and it
  handles Google sign-in. Port **8090**.
- **`newsbot-mcp`**, the MCP program. It lets AI agents search and read stories. It
  can only read. Port **8091**.

Both ask the ranker for recommendations over HTTP, and both read stories from
MongoDB. This page is a short summary. The full guide, with every setting, is
[`server/README.md`](../../server/README.md).

Hard words are explained in the [glossary](../glossary.md).

## At a glance

| Item | Value |
| --- | --- |
| Language | Python 3.12, managed with uv |
| Shared code | `server/src/newsbot_server/core` (reading articles, calling the ranker, settings) |
| Web code | `server/src/newsbot_server/web` |
| MCP code | `server/src/newsbot_server/mcp` |
| Docker image | `ghcr.io/mhd-riaz/news-bot-server`, built from [`server/Dockerfile`](../../server/Dockerfile) (the first stage builds the React app) |
| Settings | `NEWS_*` environment variables; in a checkout also `deployment/env/local.env` or the file in `NEWS_ENV_FILE` |

## Run it on a laptop

```bash
cd server
uv sync
NEWS_AUTH_ENABLED=false uv run newsbot-server
```

Then open <http://127.0.0.1:8090/>. With sign-in off you are the "Local reader".
Sign-in may be off only when the server listens on this computer alone
(`127.0.0.1`, `::1` or `localhost`), and never in production. In production the
same app runs under gunicorn with 2 worker processes and 4 threads each.

## The web routes

| Route | What it does |
| --- | --- |
| `GET /` and `GET /stories` | The React app |
| `GET /assets/...` | The app's files |
| `GET /health/live`, `GET /health/ready` | Is it running; can it reach MongoDB and the ranker |
| `GET /api/v1/session` | Is sign-in on, and who is signed in |
| `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout` | Sign-in and sign-out |
| `GET /api/v1/recommendations/meta`, `POST /api/v1/recommendations` | The ranker's details, and ranked stories with their details |
| `GET /api/v1/articles`, `GET /api/v1/articles/{id}` | Newest-first story list, and one story |

With sign-in on, every `/api/v1/` route except `/api/v1/session` needs a session.
Errors look like `{"error": {"code": "...", "message": "..."}}`.

## Sign-in

- Google sign-in uses the authorization code flow with **PKCE**. Only emails in the
  `readers` collection with `invited: true` can sign in.
- The owner manages invites:

  ```bash
  uv run newsbot-server readers invite brother@example.com --name "Brother"
  uv run newsbot-server readers list
  uv run newsbot-server readers revoke brother@example.com   # also signs them out
  ```

- The session cookie is `__Host-newsbot_session` (Secure, HttpOnly, SameSite=Lax).
  MongoDB keeps only a SHA-256 hash of it. Sessions end after 7 days without use or
  30 days in total.
- Any request that changes something must pass the cross-site check
  (`Sec-Fetch-Site`, then `Origin`).
- To turn it on, create a Google OAuth client of type "Web application" with the
  redirect address `<NEWS_PUBLIC_URL>/auth/callback`, and set
  `NEWS_PUBLIC_URL`, `NEWS_GOOGLE_CLIENT_ID` and `NEWS_GOOGLE_CLIENT_SECRET`.

**Not done yet:** sign-in has not been tried end to end with a real Google OAuth
client (roadmap D10). The tests use a fake Google.

## The MCP program for AI agents

**MCP** (Model Context Protocol) lets AI agents call tools. `newsbot-mcp` offers
five read-only tools:

| Tool | What it returns |
| --- | --- |
| `search_articles` | Newest stories that match words in the title or summary, with filters. No full text |
| `get_article` | One story with its stored text |
| `get_related` | Related reading for one story |
| `get_recommendations` | Recommendations from liked or disliked story IDs, or a topic |
| `list_topics` | The ranker's topic circles |

`get_story_group` and `get_rules` are **not met** yet. They need story groups and
association rules (roadmap M5).

How access works:

- **Keys.** Each agent gets its own key. Only its SHA-256 hash goes into
  `NEWS_MCP_API_KEYS`, as `name:hash`. Agents send `Authorization: Bearer <key>` to
  `POST /mcp`. Remove an entry and restart to take a key away.
- **Two ways to run.** Over HTTP for agents anywhere (needs keys), or over stdio for
  an agent on the same computer (no key). [`/.mcp.json`](../../.mcp.json) starts it
  over stdio for editors.
- **Read-only database login.** It logs in as the MongoDB user `mcp`, which may only
  read `articles`. At start it asks MongoDB what its login may do, and refuses to
  run if the login can write. In production it also refuses a login without a
  password.
- **Limits.** 60 requests a minute per key by default (`NEWS_MCP_RATE_LIMIT`). At most
  100 search results and 30 recommendations. One log line per call, without the
  arguments or story text.

## Database

The web server reads `articles`. It writes only `readers` and `reader_sessions`.
Both are declared in `collector/internal/mongodb`, because only the collector creates
collections. The full rules are on the
[architecture page](../architecture/README.md#who-may-read-and-write).

## Checks

```bash
cd server
uv sync --frozen
uv run pytest                        # unit and integration tests
uv run pytest -m "not integration"   # unit tests only
```

Integration tests need MongoDB on `localhost:27017`. Each test makes its own
`news_it_py_*` database and deletes it afterwards.

## Not done yet

- Sign-in with a real Google OAuth client (D10).
- `get_story_group` and `get_rules` (M5).
- Reader settings, saved items, reader feeds and daily editions on the server (roadmap
  C8 and C9). Today the app keeps saved stories and settings in the browser.
- The server and the MCP program are not deployed in production yet.
