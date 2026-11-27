# Build context is ml/; run from that directory:
#   docker build -f recommender/Dockerfile -t news-recommender:dev .
# At run time NEWSREC_MODEL_DIR names a trained snapshot, e.g. one under artifacts/recommender/.

FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app

# Serving loads saved vectors only: no TensorFlow or torch. The pins match ../uv.lock,
# the environment that builds the snapshots.
COPY recommender/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY pyproject.toml /src/pyproject.toml
COPY src /src/src
RUN pip install --no-cache-dir --no-deps /src

USER 10001:10001

EXPOSE 8001

CMD ["gunicorn", "--bind=0.0.0.0:8001", "--workers=1", "--threads=4", "newsrec.api:create_app()"]
