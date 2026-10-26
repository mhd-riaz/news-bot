FROM python:3.12-slim AS build

ARG UV_VERSION=0.13.2
RUN pip install --no-cache-dir --timeout 120 --retries 5 "uv==${UV_VERSION}"

WORKDIR /app

COPY ml-v2/pyproject.toml ml-v2/uv.lock ./
COPY ml-v2/src ./src
RUN uv sync --frozen --no-dev --group recommend --group serve

FROM python:3.12-slim

RUN apt-get update && \
  apt-get install -y --no-install-recommends ca-certificates libgomp1 && \
  rm -rf /var/lib/apt/lists/* && \
  groupadd --gid 10001 app && \
  useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --from=build --chown=10001:10001 /app/src /app/src

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

USER 10001:10001

EXPOSE 8001

CMD ["gunicorn", "--bind=0.0.0.0:8001", "--workers=1", "--threads=4", "newsrec.api:create_app()"]
