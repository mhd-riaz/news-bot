# Build context is the repository root:
#   docker build -f server/Dockerfile -t newsbot-server .
# One image runs both programs:
#   web (default): gunicorn on port 8090
#   MCP:           docker run ... newsbot-server newsbot-mcp   (port 8091)

# Stage 1: build the React app into /frontend/dist.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: install the server and its locked dependencies into /app/.venv.
FROM python:3.12-slim AS build
ARG UV_VERSION=0.13.9
RUN pip install --no-cache-dir --timeout 120 --retries 5 "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable
COPY server/README.md ./
COPY server/src ./src
RUN uv sync --frozen --no-dev --no-editable

# Stage 3: the runtime image, without build tools, running as user 10001.
FROM python:3.12-slim
RUN apt-get update && \
  apt-get install -y --no-install-recommends ca-certificates && \
  rm -rf /var/lib/apt/lists/* && \
  groupadd --gid 10001 app && \
  useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --from=frontend --chown=10001:10001 /frontend/dist /app/static

# Inside a container the programs must listen on every interface. With sign-in off
# the web app refuses that, except in development with
# NEWS_AUTH_TRUST_PUBLISHED_LOOPBACK=true and the port published on 127.0.0.1 only.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEWS_STATIC_DIR=/app/static \
    NEWS_SERVER_HOST=0.0.0.0 \
    NEWS_MCP_HOST=0.0.0.0

# Never run as root.
USER 10001:10001

EXPOSE 8090 8091

CMD ["gunicorn", "--config", "python:newsbot_server.web.gunicorn_conf"]
