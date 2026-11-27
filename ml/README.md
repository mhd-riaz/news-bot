# ml — the machine-learning part of news-bot

This folder holds the Python code that does the "smart" work:

- the **topic classifier**: a small web service that reads a news story and says which of
  13 topics it is about, such as `sport` or `politics`;
- the **recommender** (also called the ranker): a small web service that picks stories you
  may like, for the AFTERLINE reader;
- the tools that were used to build and test these models.

Everything here is one Python project called `newsbot-ml`. It runs on **Python 3.12**.

## What is in this folder

| Path | What it is |
| --- | --- |
| `src/newsmlv4/` | The V4 topic classifier: picking articles to label, checking labels, and training. Production uses its model. |
| `src/newsrec/` | The recommender: preparing a snapshot (a frozen copy of stories), training, ranking and its web service. |
| `src/newsmlv2/` | Text cleaning shared by the other parts, and an older classifier study. |
| `src/newsml/` | The first (v1) classifier. It is closed: kept only so old results can be checked. |
| `classifier/` | The classifier web service: `app/` (the code), `Dockerfile` and `requirements.txt`. |
| `recommender/` | The recommender web service's `Dockerfile` and `requirements.txt` (only what serving needs: no TensorFlow or torch). |
| `tests/` | Automatic tests, one folder for each package in `src/`. |
| `configs/boilerplate.yaml` | Repeated lines (like "Subscribe now") that the classifier removes from stories. |
| `taxonomy.yaml` | The list of 13 topics and what each one covers. |
| `models.toml` | The list of model files to download, with their SHA-256 fingerprints. |
| `scripts/` | `download_models.py` (gets the model files) and `build_label_dataset.py` (builds [`../data/labels/`](../data/labels/README.md)). |
| `Makefile` | Short commands for everything below. Run `make help` to see them all. |

Three folders are **not** in git, because they are big or private. Never commit them:

- `models/` — model files downloaded by `make models`;
- `artifacts/` — things you build on your own computer: recommender snapshots and private V4 work;
- `data/` — private working data of the old classifier studies.

The history of the older studies (reports, model cards, plans) is in
[`../docs/history/ml/`](../docs/history/ml/v1/README.md). How the V4 classifier was made
and how it is deployed is in [`../docs/services/classifier.md`](../docs/services/classifier.md).
The recommender guide is [`../docs/services/recommender.md`](../docs/services/recommender.md).

## Set up

You need [uv](https://docs.astral.sh/uv/) (a tool that installs Python packages) and `make`.
Run every command from this `ml/` folder.

```bash
make setup     # once: makes .venv (a private Python environment) with every package; a few GB
make models    # downloads the classifier model into models/ and checks it
```

`make models` reads `models.toml`. The model is in the project's public Google Drive
folder, so no sign-in is needed. A file that is already there and matches its
fingerprint is not downloaded again. `make models-check` only checks, and downloads
nothing.

## Test

```bash
make test      # every ML test; it never reads your settings file
```

Smaller groups: `make ml-test` (v1), `make ml2-test` (cleaning, recommender and classifier
service), `make ml4-test` (V4), `make classifier-test` and `make rec-test`.

## Train

- **Recommender, quick demo:** `make demo-refresh` makes a new snapshot of recent stories
  from your local database and trains all three methods (TF-IDF, SVD and a small neural
  network). `make rec-prepare`, `rec-baseline` and `rec-train` do the same steps for a
  snapshot name you choose. See the recommender guide first.
- **V4 classifier:** `make ml4-train DATASET=v4-ai-pooled-20261122T000000Z` trains from the
  private pooled labels in `artifacts/v4/`. A new model goes to `models/classifier/` and needs
  the owner's approval before production. The training refuses to run again on the same
  labels, because that would reopen their test set. Read the classifier guide first.

Commands that read the news database use the collector's settings file,
`../deployment/env/local.env`. Set `NEWS_ENV_FILE` to use another file. Check which database
you will read with `make rec-inspect`; it never prints the connection string.

## Serve

**Recommender**, on your computer, after `make demo-refresh`:

```bash
make demo-serve    # http://127.0.0.1:8001
```

**Classifier**, with Docker:

```bash
make classifier-build                  # builds the image news-classifier:dev
docker run --rm -p 127.0.0.1:8000:8000 \
  -v "$PWD/models/classifier/v4-ai-072b01a9ceaf:/models/v4-ai-072b01a9ceaf:ro" \
  -e NEWSML_MODEL_DIR=/models/v4-ai-072b01a9ceaf \
  -e NEWSML_API_KEY=choose-a-long-random-key \
  news-classifier:dev
```

Then `curl http://127.0.0.1:8000/health/ready` should answer with the model's name. The
recommender image is built with `make recommender-build`. Production images are built by
GitHub Actions from `classifier/Dockerfile` and `recommender/Dockerfile`.

## Settings the services read

| Service | Setting | Meaning |
| --- | --- | --- |
| Classifier | `NEWSML_MODEL_DIR` | Folder with `bundle.joblib`. Required. |
| Classifier | `NEWSML_API_KEY` | If set, every request except `/health/...` must send it in the `X-Classifier-Key` header. |
| Classifier | `NEWSML_TAXONOMY_PATH` | Another `taxonomy.yaml` to use. Optional. |
| Classifier | `NEWSML_MAX_BATCH`, `NEWSML_MAX_REQUEST_BYTES` | Most stories (100) and bytes (1 MiB) in one request. Optional. |
| Classifier | `NEWSML_MODEL_SHA256` | Production only: its start command checks `bundle.joblib` against this fingerprint. |
| Recommender | `NEWSREC_MODEL_DIR` | Folder of a trained snapshot. Required. |
| Recommender | `NEWS_RECOMMENDER_API_KEY` | If set, every request except `/health/...` must send it in the `X-Recommender-Key` header. |
| Tools | `NEWS_ENV_FILE` | Which settings file to read instead of `../deployment/env/local.env`. |
| Tools | `NEWS_MONGO_URI`, `NEWS_MONGO_DATABASE`, `NEWSMLV2_MONGO_URI`, `NEWS_ML_MONGO_URI` | Which database the tools read. Never print these. |
| `make models` | `GITHUB_TOKEN` | Only for a model kept in a private GitHub release, when the GitHub command-line tool is not signed in. Today's model needs no sign-in. |
