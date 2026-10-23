"""Fit sparse baselines and a compact Keras denoising autoencoder without topic labels."""

from __future__ import annotations

import platform
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from scipy import sparse
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler, normalize
from threadpoolctl import threadpool_limits

from newsmlv2.dedup import Doc, is_recurring_template

from .data import SEED, digest, documents, read_json, write_json


def story_groups(rows: list[dict], matrix: sparse.csr_matrix) -> list[str]:
    """Conservative duplicate grouping, bounded to 64 query rows at a time."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)

    docs = [
        Doc(row["id"], row["text"], row["publisher"],
            datetime.fromisoformat(row["published_at"]) if row["published_at"] else None)
        for row in rows
    ]
    exact: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows):
        for name in ("normalized_url", "content_hash"):
            value = row.get(name)
            if not value:
                continue
            key = (name, value)
            if key in exact:
                union(i, exact[key])
            exact[key] = i

    # ponytail: O(n^2) offline work on a 20k cohort; time-window blocking before scaling.
    for start in range(0, len(rows), 64):
        scores = (matrix[start:start + 64] @ matrix.T).tocoo()
        for offset, j, score in zip(scores.row, scores.col, scores.data, strict=True):
            i = start + int(offset)
            j = int(j)
            if j <= i or score < 0.90 or is_recurring_template(docs[i], docs[j]):
                continue
            left = set(rows[i]["title"].lower().split())
            right = set(rows[j]["title"].lower().split())
            if len(left & right) >= min(4, len(left), len(right)):
                union(i, j)
    return [rows[find(i)]["id"] for i in range(len(rows))]


def baseline(directory: Path, *, dimensions: int = 256) -> dict:
    """Fit only on older story groups; transform every indexed article in stable ID order."""
    rows = documents(directory)
    texts = [row["text"] for row in rows]
    started = time.perf_counter()
    with threadpool_limits(limits=4):
        grouping_matrix = TfidfVectorizer(
            max_features=20_000, min_df=2, max_df=0.8, stop_words="english",
            sublinear_tf=True, dtype=np.float32,
        ).fit_transform(texts).tocsr()
        groups = story_groups(rows, grouping_matrix)
        group_dates: dict[str, str] = {}
        for row, group in zip(rows, groups, strict=True):
            group_dates[group] = max(group_dates.get(group, row["collected_at"]), row["collected_at"])
        boundary = sorted(row["collected_at"] for row in rows)[int(len(rows) * 0.8)]
        training_groups = {group for group, latest in group_dates.items() if latest < boundary}
        train = np.array([group in training_groups for group in groups])
        if train.all() or not train.any():
            raise ValueError("at least two independent story groups are required")

        vectorizer = TfidfVectorizer(
            max_features=25_000, min_df=2, max_df=0.8, ngram_range=(1, 2),
            stop_words="english", sublinear_tf=True, dtype=np.float32,
        )
        vectorizer.fit([text for text, keep in zip(texts, train, strict=True) if keep])
        matrix = vectorizer.transform(texts).tocsr()
        n_components = min(dimensions, matrix.shape[1] - 1, int(train.sum()) - 1)
        if n_components < 8:
            raise ValueError("too little vocabulary or training data for representation learning")
        svd = TruncatedSVD(n_components=n_components, random_state=SEED)
        svd.fit(matrix[train])
        dense = svd.transform(matrix).astype(np.float32)
        scaler = StandardScaler().fit(dense[train])
        inputs = scaler.transform(dense).astype(np.float32)

    sparse.save_npz(directory / "tfidf.npz", matrix)
    np.save(directory / "svd.npy", normalize(dense).astype(np.float32), allow_pickle=False)
    np.save(directory / "inputs.npy", inputs, allow_pickle=False)
    np.save(directory / "train.npy", train, allow_pickle=False)
    write_json(directory / "groups.json", groups)
    joblib.dump({"tfidf": vectorizer, "svd": svd, "scaler": scaler}, directory / "preprocessing.joblib")
    result = {
        "documents_sha256": digest(directory / "documents.jsonl"),
        "article_ids_sha256": digest(directory / "groups.json"),
        "articles": len(rows), "story_groups": len(set(groups)),
        "train_articles": int(train.sum()), "validation_articles": int((~train).sum()),
        "split": "groups wholly before chronological 80% cutoff train; crossing groups validate",
        "split_boundary": boundary,
        "vocabulary": matrix.shape[1], "svd_dimensions": n_components,
        "svd_explained_variance": float(svd.explained_variance_ratio_.sum()),
        "seconds": round(time.perf_counter() - started, 2),
    }
    write_json(directory / "baseline.json", result)
    return result


def train(directory: Path, *, epochs: int = 30) -> dict:
    """Train reconstruction, persist both models, and index centered latent representations."""
    import tensorflow as tf

    tf.config.set_visible_devices([], "GPU")
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()
    rows = documents(directory)
    base = read_json(directory / "baseline.json")
    if base["documents_sha256"] != digest(directory / "documents.jsonl"):
        raise ValueError("baseline belongs to a different snapshot")
    inputs = np.load(directory / "inputs.npy", allow_pickle=False)
    train_mask = np.load(directory / "train.npy", allow_pickle=False)
    if len(inputs) != len(rows) or not np.isfinite(inputs).all():
        raise ValueError("invalid or mismatched model inputs")
    if not 1 <= epochs <= 100:
        raise ValueError("epochs must be between 1 and 100")

    width = inputs.shape[1]
    source = tf.keras.Input((width,), name="svd_features")
    hidden = tf.keras.layers.GaussianNoise(0.05)(source)
    hidden = tf.keras.layers.Dense(128, activation="gelu")(hidden)
    latent = tf.keras.layers.Dense(64, name="article_representation")(hidden)
    decoded = tf.keras.layers.Dense(128, activation="gelu")(latent)
    reconstructed = tf.keras.layers.Dense(width)(decoded)
    autoencoder = tf.keras.Model(source, reconstructed, name="article_autoencoder")
    encoder = tf.keras.Model(source, latent, name="article_encoder")
    autoencoder.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="mse")
    options = tf.data.Options()
    options.threading.private_threadpool_size = 1
    options.threading.max_intra_op_parallelism = 1

    def dataset(values: np.ndarray, *, shuffle: bool) -> tf.data.Dataset:
        data = tf.data.Dataset.from_tensor_slices((values, values))
        if shuffle:
            data = data.shuffle(len(values), seed=SEED)
        return data.batch(256).with_options(options)

    started = time.perf_counter()
    history = autoencoder.fit(
        dataset(inputs[train_mask], shuffle=True),
        validation_data=dataset(inputs[~train_mask], shuffle=False),
        epochs=epochs, verbose=2, shuffle=False,
        callbacks=[tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=4, restore_best_weights=True
        )],
    )
    raw = np.concatenate([
        encoder(inputs[start:start + 512], training=False).numpy()
        for start in range(0, len(inputs), 512)
    ])
    center = raw[train_mask].mean(axis=0)
    vectors = normalize(raw - center).astype(np.float32)
    if not np.isfinite(vectors).all() or np.mean(np.std(vectors, axis=0)) < 1e-4:
        raise ValueError("neural representations collapsed or contain invalid values")
    autoencoder.save(directory / "autoencoder.keras")
    encoder.save(directory / "encoder.keras")
    np.save(directory / "latent_center.npy", center, allow_pickle=False)
    np.save(directory / "neural.npy", vectors, allow_pickle=False)

    with threadpool_limits(limits=4):
        clusters = MiniBatchKMeans(
            n_clusters=8, random_state=SEED, n_init=5, batch_size=512
        ).fit(vectors[train_mask])
        assignments = clusters.predict(vectors)
    joblib.dump(clusters, directory / "clusters.joblib")
    matrix = sparse.load_npz(directory / "tfidf.npz")
    vocabulary = joblib.load(directory / "preprocessing.joblib")["tfidf"].get_feature_names_out()
    topics = []
    for cluster in range(8):
        positions = np.flatnonzero(assignments == cluster)
        if not len(positions):
            continue
        means = np.asarray(matrix[positions].mean(axis=0)).ravel()
        terms = [str(vocabulary[i]) for i in np.argsort(-means) if " " not in vocabulary[i]][:3]
        centroid = normalize(clusters.cluster_centers_[cluster:cluster + 1])[0]
        representatives = positions[np.argsort(-(vectors[positions] @ centroid))[:12]]
        topics.append({
            "id": str(cluster), "label": " / ".join(terms),
            "keywords": terms, "count": len(positions),
            "representatives": [rows[int(i)]["id"] for i in representatives],
        })
    np.save(directory / "assignments.npy", assignments, allow_pickle=False)
    write_json(directory / "topics.json", topics)
    result = {
        **base, "tensorflow": tf.__version__, "keras": tf.keras.__version__,
        "python": platform.python_version(), "numpy": version("numpy"),
        "scikit_learn": version("scikit-learn"), "seed": SEED,
        "architecture": [width, 128, 64, 128, width],
        "parameters": autoencoder.count_params(), "noise": 0.05,
        "source_sha256": {
            module: digest(Path(__file__).with_name(module)) for module in ("data.py", "model.py", "index.py")
        },
        "epochs": len(history.history["loss"]),
        "train_loss": history.history["loss"], "validation_loss": history.history["val_loss"],
        "training_seconds": round(time.perf_counter() - started, 2),
        "quality_note": "Reconstruction loss is not recommendation relevance.",
    }
    paths = [
        "documents.jsonl", "manifest.json", "groups.json", "tfidf.npz", "svd.npy", "neural.npy",
        "preprocessing.joblib", "train.npy", "assignments.npy", "topics.json",
        "latent_center.npy", "encoder.keras", "autoencoder.keras", "clusters.joblib",
    ]
    result["artifacts"] = {name: digest(directory / name) for name in paths}
    write_json(directory / "training.json", result)
    return result
