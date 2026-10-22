# Build context is the repository root:
#   docker build -f deployments/classifier.Dockerfile .

FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY ml-v2/requirements-serve.txt /tmp/requirements-serve.txt
RUN pip install --no-cache-dir -r /tmp/requirements-serve.txt

COPY ml-v2/pyproject.toml /src/pyproject.toml
COPY ml-v2/src /src/src
RUN pip install --no-cache-dir --no-deps /src

COPY ml-v2/app /app/app
COPY ml-v2/taxonomy.yaml /app/taxonomy.yaml

USER 10001:10001

EXPOSE 8000

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=1", "--threads=4", "app.wsgi:app"]