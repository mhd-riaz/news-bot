# server: the AFTERLINE web app and the MCP program

This folder holds two programs that share one Python package, `newsbot_server`:

- **Web app** (`newsbot-server`, port **8090**). It serves the reader's API, Google
  sign-in and the React pages from `frontend/dist`. It replaces the Go reader
  (`collector/cmd/reader`).
- **MCP program** (`newsbot-mcp`, port **8091**). MCP (Model Context Protocol) lets
  AI agents, such as Claude, search and read articles. It can only read. MongoDB
  itself stops it from writing, because it logs in as a user that may only read
  `articles`.

Both programs ask the **ranker** for recommendations. The ranker is the separate
Python service `newsrec.api` on port **8001**. Articles come from MongoDB.

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- MongoDB with the `news` database
- The ranker at `http://127.0.0.1:8001` (only for recommendations)
- Node.js, only to build the React app in `frontend/`

## Run it on your laptop (sign-in off)

```bash
cd server
uv sync
NEWS_AUTH_ENABLED=false uv run newsbot-server
```

Open <http://127.0.0.1:8090/>. With sign-in off you are the "Local reader".
Sign-in can be off only when the server listens on a loopback address
(`127.0.0.1`, `::1` or `localhost`, which only your own computer can reach), and
never when `NEWS_APP_ENVIRONMENT=production`. The server refuses to start otherwise.

**Docker Compose on a laptop.** Inside a container the app must listen on
`0.0.0.0` (every network address of the container), which sign-in off normally
refuses. For a laptop only, set these three values and publish the port on
127.0.0.1 only:

```yaml
environment:
  NEWS_APP_ENVIRONMENT: development
  NEWS_AUTH_ENABLED: "false"
  NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK: "true"
ports:
  - "127.0.0.1:8090:8090"
```

The server then starts with sign-in off and logs one warning about this. Never
publish the port as `"8090:8090"`: then other computers on your network could use
the app as the Local reader. The setting is refused in staging and production,
even with sign-in on. If you publish a different port, set `NEWS_PUBLIC_URL` to
the address you open, for example `http://127.0.0.1:18090`.

Settings come from environment variables. When you run from a checkout, the
programs also read `deployment/env/local.env`, or the file named in `NEWS_ENV_FILE`.
A variable already set in your environment wins over the file. Values from the
file are never logged.

`newsbot-server` is a small development server. In production the same app runs
with gunicorn (a web server for Python apps):

```bash
uv run gunicorn --config python:newsbot_server.web.gunicorn_conf
```

It listens on `NEWS_SERVER_HOST:NEWS_SERVER_PORT` with 2 worker processes and
4 threads each.

## Turn on Google sign-in

1. In Google Cloud Console, create an OAuth client of type **Web application**.
2. Add this redirect URI: `<NEWS_PUBLIC_URL>/auth/google/callback`, for example
   `https://news.example.com/auth/google/callback`.
3. Set `NEWS_AUTH_ENABLED=true` (the default), `NEWS_PUBLIC_URL`,
   `NEWS_GOOGLE_CLIENT_ID` and `NEWS_GOOGLE_CLIENT_SECRET`.
4. Invite your readers:

```bash
uv run newsbot-server readers invite brother@example.com --name "Brother"
uv run newsbot-server readers list
uv run newsbot-server readers revoke brother@example.com   # also signs them out at once
```

These owner commands use `NEWS_OWNER_MONGO_URI` (the owner's MongoDB login), or
`NEWS_MONGO_URI` when that is not set.

How sign-in works:

- The server uses Google's authorization code flow with PKCE (a one-time secret
  that proves the same browser finished the sign-in), a random `state` and a
  `nonce`. The pending sign-in lives for 10 minutes in a signed, HttpOnly cookie.
- Only emails in `readers` with `invited: true` can sign in, and Google must
  say the email is verified. The first sign-in links that Google account to the invite.
- The session cookie is `__Host-newsbot_session`: Secure, HttpOnly, SameSite=Lax.
  MongoDB keeps only the SHA-256 hash of the session token, never the token.
- A session ends after 7 days without use or 30 days in total (change with
  `NEWS_SESSION_IDLE_TIMEOUT` and `NEWS_SESSION_ABSOLUTE_TIMEOUT`). Signing out,
  or revoking the reader, deletes it at once.

## Web routes

| Route | What it does |
| --- | --- |
| `GET /` and `GET /stories` | The React app (`index.html`) |
| `GET /assets/...` | The app's files, cached for a year (their names change with each build) |
| `GET /health/live` | Is the process running |
| `GET /health/ready` | Are MongoDB and the ranker reachable (503 if not) |
| `GET /api/v1/session` | `auth_enabled`, `signed_in`, `reader` (`email`, `name`) and `login_url` |
| `GET /auth/google/login?next=/path` | Starts sign-in. `next` must be a path on this site |
| `GET /auth/google/callback` | Google sends the reader back here. Not invited: `/?auth_error=not_invited`; any other problem: `/?auth_error=sign_in_failed` |
| `POST /auth/logout` | Signs out: 204 |
| `GET /api/v1/recommendations/meta` | The ranker's index details, as the Go reader returned them |
| `POST /api/v1/recommendations` | Ranked stories with their article details, as the Go reader returned them |
| `GET /api/v1/articles` | Newest-first article list with filters and a cursor, as the Go reader returned it |
| `GET /api/v1/articles/{id}` | One article with its text |
| `POST /read-events` | Still switched off: 405, as in the Go reader |

With sign-in on, every `/api/v1/` route except `/api/v1/session` needs a session,
or it answers 401 with the code `sign_in_required`. Errors always look like
`{"error": {"code": "...", "message": "..."}}`.

Safety rules:

- **Cross-site requests.** Any request other than GET, HEAD or OPTIONS is refused
  with 403 `cross_site_request` unless the browser's `Sec-Fetch-Site` header is
  `same-origin` or `none`. If that header is missing, the `Origin` header must equal
  `NEWS_PUBLIC_URL`. This stops other websites from sending requests with your cookie.
- **Content Security Policy** on pages: scripts, styles, fonts and API calls only
  from this site, images from this site, any `https:` address or `data:`, no inline
  scripts or styles, no form submissions, no framing. Publisher images load in the
  browser; the server never fetches them.
- Every response also has `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and an `X-Request-Id`.
  API and sign-in responses are never cached (`Cache-Control: no-store`).
- Request bodies are limited to 128 KiB, as in the Go reader.

## The MCP program

Make a key for each agent. This prints the key (give it to the agent) and the
line to add to `NEWS_MCP_API_KEYS`. Only the hash is stored on the server.

```bash
python3 -c "import secrets,hashlib; k=secrets.token_urlsafe(32); print('agent key:', k); print('NEWS_MCP_API_KEYS entry: claude:' + hashlib.sha256(k.encode()).hexdigest())"
```

Separate several entries with commas. To take a key away, remove its entry and
restart the program.

Run it:

```bash
# HTTP for agents anywhere (needs keys): http://127.0.0.1:8091/mcp
NEWS_MCP_MONGO_URI='mongodb://mcp:...' NEWS_MCP_API_KEYS='claude:<hash>' uv run newsbot-mcp

# stdio, for an agent on this computer that starts the program itself (no key)
NEWS_MCP_MONGO_URI='mongodb://mcp:...' uv run newsbot-mcp --transport stdio
```

Agents call `POST /mcp` with the header `Authorization: Bearer <agent key>`.
Each call is answered with plain JSON and needs no session.

| Tool | What it returns |
| --- | --- |
| `search_articles` | Newest articles that match words in the title or summary, with filters (source, language, country, topic, dates) and paging. No full text |
| `get_article` | One article with its stored text |
| `get_related` | Related reading for one article, from fresh and archived stories |
| `get_recommendations` | Recommendations from liked or disliked article IDs, or a topic, sent in the call |
| `list_topics` | The ranker's topics with labels, keywords and sizes |

`get_story_group` and `get_rules` are not offered yet: story groups and
association rules do not exist until roadmap milestone M5.

Limits and logs:

- A request body may be at most 128 KiB. A search returns at most 100 articles,
  a recommendation at most 30, and a call may send at most 50 liked and 50
  disliked IDs. A tool result is at most 1 MiB; a longer article text is cut and
  marked `content_truncated`.
- Each key may make `NEWS_MCP_RATE_LIMIT` requests a minute (default 60). Extra
  requests get 429 with `Retry-After`.
- A tool call may use MongoDB for at most 5 seconds. A search for words that
  match nothing reads every English article; that took 0.4-1.3 s on a laptop copy
  of about 250,000 articles.
- Each tool call writes one log line with the agent's name, the tool, the result
  (`ok`, `refused`, `error`), the time taken and the result size. Arguments and
  article text are never logged.
- `search_articles` filters on the language the source declares (`en` by default).
  The detected language from roadmap C1 is still empty for most stored articles.

**Read-only database login.** `deployment/mongo/mongo-users.js` creates a MongoDB
user `mcp` (password from `NEWS_MONGO_MCP_PASSWORD`) that may only run `find` on
`articles`. When `newsbot-mcp` starts, it asks MongoDB what its login may do. It
refuses to start if the login can write anything, and in production it also
refuses a login without a password, because then MongoDB cannot enforce read-only.

## Settings

| Variable | Default | Used by |
| --- | --- | --- |
| `NEWS_ENV_FILE` | `deployment/env/local.env` in a checkout | both |
| `NEWS_APP_ENVIRONMENT` | `development` (or `staging`, `production`) | both |
| `NEWS_SERVER_HOST`, `NEWS_SERVER_PORT` | `127.0.0.1`, `8090` | web |
| `NEWS_PUBLIC_URL` | required with sign-in on; `https` unless loopback | web |
| `NEWS_AUTH_ENABLED` | `true` | web |
| `NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK` | `false`; `true` only in development, with sign-in off and the port published on 127.0.0.1 | web |
| `NEWS_GOOGLE_CLIENT_ID`, `NEWS_GOOGLE_CLIENT_SECRET` | required with sign-in on | web |
| `NEWS_SESSION_IDLE_TIMEOUT`, `NEWS_SESSION_ABSOLUTE_TIMEOUT` | `168h`, `720h` | web |
| `NEWS_STATIC_DIR` | `frontend/dist` in a checkout, `/app/static` in the image | web |
| `NEWS_MONGO_URI` | `mongodb://localhost:27017` | web (the `reader` login) |
| `NEWS_OWNER_MONGO_URI` | falls back to `NEWS_MONGO_URI` | `newsbot-server readers` |
| `NEWS_MCP_MONGO_URI` | required | MCP (the `mcp` login) |
| `NEWS_MONGO_DATABASE` | `news` | all |
| `NEWS_MONGO_CONNECT_TIMEOUT`, `NEWS_MONGO_SERVER_SELECTION_TIMEOUT`, `NEWS_MONGO_OPERATION_TIMEOUT` | `10s`, `10s`, `30s` | all |
| `NEWS_MONGO_MAX_POOL_SIZE`, `NEWS_MONGO_MIN_POOL_SIZE`, `NEWS_MONGO_MAX_CONNECTION_IDLE_TIME` | `50`, `0`, `60s` | all |
| `NEWS_RECOMMENDER_ENDPOINT` | `http://127.0.0.1:8001` | both |
| `NEWS_RECOMMENDER_API_KEY` | none | both (sent as `X-Recommender-Key`) |
| `NEWS_MCP_HOST`, `NEWS_MCP_PORT` | `127.0.0.1`, `8091` | MCP |
| `NEWS_MCP_API_KEYS` | required for HTTP | MCP |
| `NEWS_MCP_RATE_LIMIT` | `60` (requests a minute per key) | MCP |
| `NEWS_MCP_ALLOWED_HOSTS` | `127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>` | MCP (the `Host` names it answers) |
| `NEWS_LOGGING_LEVEL`, `NEWS_LOGGING_FORMAT` | `info`, `json` | both |

Durations use Go's style: `15s`, `90m`, `168h`.

## Database

- `readers`: `_id` (the reader ID), `email` (lower case), `name`, `invited`,
  `created_at`, `google_sub` (the Google account, linked at first sign-in) and
  `last_login_at`. Indexes: `uq_email` (unique) and `uq_google_sub` (unique once set).
- `reader_sessions`: `_id` (SHA-256 of the session token), `reader_id`,
  `created_at`, `last_seen_at` and `expires_at`. Indexes: `ttl_expires_at` (MongoDB
  deletes a session after `expires_at`) and `ix_reader`.

Both are declared in `collector/internal/mongodb`, because only the collector
creates collections and indexes (roadmap C14). The web app reads `articles` and
writes only `readers` and `reader_sessions`.

## Docker

Build from the repository root. The first stage builds the React app.

```bash
docker build -f server/Dockerfile -t newsbot-server .
docker run -p 127.0.0.1:8090:8090 --env-file <your env file> newsbot-server
docker run -p 127.0.0.1:8091:8091 --env-file <your env file> newsbot-server newsbot-mcp
```

The image runs as user 10001 and listens on all interfaces inside the container,
so the web app needs sign-in on there, or the laptop-only setting
`NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK=true` described above. A local build on
27 Nov 2026 was 284 MB.

## Tests

```bash
cd server
uv run pytest                        # unit and integration tests
uv run pytest -m "not integration"   # unit tests only
```

Integration tests need MongoDB on `localhost:27017` (or `NEWS_TEST_MONGO_URI`).
Each test makes its own `news_it_py_*` database and deletes it afterwards.
`tests/integration/test_read_only_login.py` also checks a real read-only login when
`NEWS_TEST_MCP_MONGO_URI` (the `mcp` user) and `NEWS_TEST_WRITER_MONGO_URI` (a user
that can write) point at a MongoDB set up with `mongo-users.js`.

## Not done yet

- Google sign-in has not been tried end to end with a real Google OAuth client.
  The tests use a fake Google token endpoint.
- `get_story_group` and `get_rules` (roadmap M5).
- Reader settings, saved items, reader feeds and daily editions (roadmap C8 and C9).
