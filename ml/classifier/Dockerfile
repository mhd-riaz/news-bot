# Build context is ml/; run from that directory:
#   docker build -f classifier/Dockerfile -t news-classifier:dev .

FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    HF_HOME=/opt/hf-cache

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY classifier/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# One project holds all four packages. A V4 bundle unpickles classes from
# newsmlv4.train and newsmlv2.models, and newsmlv4 imports newsml.
COPY pyproject.toml /src/pyproject.toml
COPY src /src/src
RUN pip install --no-cache-dir --no-deps /src

# The bundle stores only the encoder's name and revision. Fetch exactly the files it
# loads now, then forbid network access so a missing file fails at start-up.
RUN python -c "from newsmlv4.train import SentenceEmbedder; SentenceEmbedder().transform(['warm-up'])" && \
    chmod -R a+rX /opt/hf-cache
ENV HF_HUB_OFFLINE=1

COPY classifier/app /app/app
COPY configs/boilerplate.yaml /app/configs/boilerplate.yaml
COPY taxonomy.yaml /app/taxonomy.yaml

# The model download script and its list, so a Kubernetes init container can fill the
# model volume: python /app/scripts/download_models.py --dest <volume>
COPY scripts/download_models.py /app/scripts/download_models.py
COPY models.toml /app/models.toml

USER 10001:10001

EXPOSE 8000

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=1", "--threads=4", "--timeout=120", "app.wsgi:app"]
