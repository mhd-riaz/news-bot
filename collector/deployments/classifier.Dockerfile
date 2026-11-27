# Build context is collector/; run from that directory:
#   docker build -f deployments/classifier.Dockerfile .

FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONPATH=/opt/news/ml/src:/opt/news/ml-v4/src \
    HF_HOME=/opt/hf-cache

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY ml-v2/requirements-serve.txt /tmp/requirements-serve.txt
RUN pip install --no-cache-dir -r /tmp/requirements-serve.txt

COPY ml-v2/pyproject.toml /src/pyproject.toml
COPY ml-v2/src /src/src
RUN pip install --no-cache-dir --no-deps /src

# A V4 bundle unpickles classes from newsmlv4.train, which imports newsml.
COPY ml/src /opt/news/ml/src
COPY ml-v4/src /opt/news/ml-v4/src

# The bundle stores only the encoder's name and revision. Fetch exactly the files it
# loads now, then forbid network access so a missing file fails at start-up.
RUN python -c "from newsmlv4.train import SentenceEmbedder; SentenceEmbedder().transform(['warm-up'])" && \
    chmod -R a+rX /opt/hf-cache
ENV HF_HUB_OFFLINE=1

COPY ml-v2/app /app/app
COPY ml-v2/configs/boilerplate.yaml /app/configs/boilerplate.yaml
COPY ml-v2/taxonomy.yaml /app/taxonomy.yaml

USER 10001:10001

EXPOSE 8000

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=1", "--threads=4", "--timeout=120", "app.wsgi:app"]