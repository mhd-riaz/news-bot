import csv
import hashlib
import json
import math
import pickle
import subprocess
import sys

import joblib
import numpy as np
import pytest

from newsml.annotate import COLUMNS
from newsml.labels import load_taxonomy
from newsmlv4 import sampling, train

VOCABULARY = {
    "politics": ["minister", "parliament", "election", "vote", "party", "senate"],
    "sport": ["goal", "match", "league", "cup", "striker", "coach"],
    "technology": ["software", "chip", "startup", "cloud", "app", "robot"],
}
FILLER = ["today", "report", "new", "says", "after", "week", "city", "plan"]
TOPICS = sorted(load_taxonomy(sampling.TAXONOMY_PATH).ids)
QUIET = {"log": lambda *_: None}


def article(topic, index, rng):
    words = [VOCABULARY[topic][0], *rng.choice(VOCABULARY[topic][1:], 3), *rng.choice(FILLER, 4)]
    rng.shuffle(words)
    return f"{VOCABULARY[topic][1].title()} update {index}", " ".join(words)


def synthetic(per_class, seed=0):
    rng = np.random.default_rng(seed)
    texts, labels = [], []
    for topic in VOCABULARY:
        for index in range(per_class):
            texts.append(train.text_for(*article(topic, index, rng)))
            labels.append(topic)
    return np.array(texts, dtype=object), np.array(labels, dtype=object)


def make_run(data, name, per_class, *, gold=True):
    """A candidate run as the exporter writes it, plus the gold `make ml4-labels-import` writes.

    Every taxonomy class gets `per_class` articles in its own made-up vocabulary.
    """
    rng = np.random.default_rng(0)
    rows = []
    for topic in TOPICS:
        words = [f"{topic}{j}" for j in range(6)]
        for i in range(per_class):
            summary = " ".join([*rng.choice(words, 4), *rng.choice(FILLER, 4)])
            rows.append((f"{name}-{topic}-{i:03d}", f"{topic} update {i}", summary, topic))
    rows += [(f"{name}-odd-{i}", f"Odd item {i}", "notes and miscellany", "unsorted") for i in range(2)]

    run = data / name
    run.mkdir(parents=True)
    with (run / "labels-01.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for article_id, title, summary, label in rows:
            writer.writerow({"article_id": article_id, "title": title, "summary": summary,
                             "label": label, "notes": ""})
    (run / "selection.jsonl").write_text("".join(
        json.dumps({
            "article_id": article_id,
            "content_hash": article_id,
            "sheet_text_sha256": hashlib.sha256(f"{title}\n{summary}".encode()).hexdigest(),
        }) + "\n"
        for article_id, title, summary, _ in rows
    ), encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({
        "status": "unlabeled_candidates_not_gold",
        "per_class": 200,
        "taxonomy_sha256": hashlib.sha256(sampling.TAXONOMY_PATH.read_bytes()).hexdigest(),
        "sources_sha256": hashlib.sha256(sampling.SOURCES_PATH.read_bytes()).hexdigest(),
        "selected_digest": hashlib.sha256("\n".join(sorted(r[0] for r in rows)).encode()).hexdigest(),
    }), encoding="utf-8")
    if gold:
        (run / "gold.jsonl").write_text("".join(
            json.dumps({"article_id": article_id, "topic": label}) + "\n"
            for article_id, _, _, label in rows
        ), encoding="utf-8")
    return run


def test_formula_escape_is_undone_only_where_the_exporter_added_it():
    for value in ("=SUM(A1)", "-5% rate cut", "+1 for rail", "@handle replies", " =x", "plain"):
        assert sampling.unescape_cell(sampling.safe_cell(value)) == value
    assert sampling.unescape_cell("'Tis the season") == "'Tis the season"


def test_corrected_t_test_widens_the_variance_for_overlapping_folds():
    difference, p_value = train.corrected_t_test([0.81, 0.83], [0.80, 0.80], folds=5)
    # df = 1 is a Cauchy distribution, so the one-sided tail has a closed form.
    corrected_t = 0.02 / math.sqrt((1 / 2 + 1 / 4) * 0.0002)
    assert difference == pytest.approx(0.02)
    assert p_value == pytest.approx(0.5 - math.atan(corrected_t) / math.pi)
    assert train.corrected_t_test([0.7] * 3, [0.7] * 3, folds=5) == (0.0, 1.0)
    assert train.corrected_t_test([0.8] * 3, [0.7] * 3, folds=5)[1] == 0.0


def test_simplest_rung_ships_unless_the_best_is_clearly_better():
    base = np.linspace(0.70, 0.80, 15)
    noise = np.array([0.03, -0.02, 0.01, -0.01, 0.02, -0.03, 0.015, -0.005,
                      0.0, 0.01, -0.01, 0.02, -0.02, 0.01, 0.04])
    tied = {"majority": np.full(15, 0.05), "tfidf_linear_svc": base, "word_char_svc": base + noise}
    best, chosen, comparisons = train.select(tied, folds=5)
    assert (best, chosen) == ("word_char_svc", "tfidf_linear_svc")
    assert comparisons["tfidf_linear_svc"].tied and not comparisons["majority"].tied

    clear = {**tied, "word_char_svc": base + 0.05 + noise / 10}
    assert train.select(clear, folds=5)[:2] == ("word_char_svc", "word_char_svc")


def test_balance_guard_needs_owner_acceptance_and_never_goes_below_the_floor():
    labels = np.array(["sport"] * 12 + ["politics"] * 250, dtype=object)
    with pytest.raises(ValueError, match="sport 12"):
        train.check_balance(labels, ["politics", "sport"], target=200, folds=5, accept_shortfall=False)
    accepted = train.check_balance(labels, ["politics", "sport"], target=200, folds=5,
                                   accept_shortfall=True)
    assert accepted == {"sport": 188}
    thin = np.array(["sport"] * 9 + ["politics"] * 250, dtype=object)
    with pytest.raises(ValueError, match="too few labels"):
        train.check_balance(thin, ["politics", "sport"], target=200, folds=5, accept_shortfall=True)
    absent = np.array(["sport"] * 250 + ["politics"] * 250, dtype=object)
    with pytest.raises(ValueError, match="'technology': 0"):
        train.check_balance(absent, ["politics", "sport", "technology"], target=200, folds=5,
                            accept_shortfall=True)


def test_training_waits_for_imported_gold(tmp_path):
    data = tmp_path / "data"
    make_run(data, "run-a", per_class=10, gold=False)
    with pytest.raises(FileNotFoundError, match="ml4-labels-import"):
        train.load_gold(["run-a"], taxonomy=load_taxonomy(sampling.TAXONOMY_PATH), data_root=data)


def test_corrected_ai_origins_cannot_use_the_human_gold_path(tmp_path):
    data = tmp_path / "data"
    make_run(data, "run-a", per_class=10)
    (data / "provenance-correction.json").write_text(json.dumps({
        "label_source": "ai-agent", "corrected_runs": ["run-a"], "decision": "D16",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="AI-generated.*--dataset"):
        train.load_gold(["run-a"], taxonomy=load_taxonomy(sampling.TAXONOMY_PATH), data_root=data)


def make_ai_dataset(data):
    run = make_run(data, "ai-pool", per_class=10)
    with (run / "labels-01.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["label"] != "unsorted"]
    payload = "".join(json.dumps({
        "article_id": row["article_id"], "title": row["title"], "summary": row["summary"],
        "topic": row["label"], "group_id": row["article_id"],
        "taxonomy_version": load_taxonomy(sampling.TAXONOMY_PATH).version,
        "label_source": "ai-agent", "provenance_decision": "D16", "origins": ["original-ai-effort"],
    }) + "\n" for row in rows)
    (run / "labels.jsonl").write_text(payload, encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({
        "status": "ai_generated_labels_not_gold", "label_source": "ai-agent",
        "human_labels": 0, "provenance_decision": "D16", "per_class_target": 200,
        "sources": [{"run": "original-ai-effort", "label_source": "ai-agent"}],
        "counts": {topic: 10 for topic in TOPICS},
        "taxonomy_sha256": hashlib.sha256(sampling.TAXONOMY_PATH.read_bytes()).hexdigest(),
        "labels_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }), encoding="utf-8")
    return run


def test_ai_corpus_trains_and_persists_truthful_metrics_and_protected_split_ids(tmp_path):
    data = tmp_path / "data"
    dataset = make_ai_dataset(data)
    directory = train.run(
        (), dataset=dataset, data_root=data, models_root=data / "models", models=("complement_nb",),
        folds=3, repeats=1, accept_shortfall=True, min_kept=5, **QUIET,
    )
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["label_source"] == "ai-agent"
    assert manifest["evaluation_basis"] == "ai_label_agreement"
    assert manifest["human_validation"] == "not_met" and manifest["human_labels"] == 0
    assert not manifest["production_approved"]
    assert manifest["model_version"].startswith("v4-ai-")
    splits = [json.loads(line) for line in (directory / "split.jsonl").read_text().splitlines()]
    test_ids = sorted(row["article_id"] for row in splits if row["split"] == "test")
    assert len(test_ids) == manifest["split"]["test"]
    assert hashlib.sha256("\n".join(test_ids).encode()).hexdigest() == manifest["split"]["test_ids_sha256"]
    card = (directory / "model-card.md").read_text(encoding="utf-8")
    assert "not human-validated accuracy" in card and "AI-generated" in card
    model = joblib.load(directory / train.BUNDLE)
    assert model.metadata["evaluation_basis"] == "ai_label_agreement"
    assert model.classify("sport update", "sport0 sport1 sport2 sport3")[0] in {"sport", "unsorted"}
    with pytest.raises(ValueError, match="cannot be mixed"):
        train.run(["human-run"], dataset=dataset, data_root=data, models_root=data / "models", **QUIET)


def test_a_pooled_corpus_cannot_hide_human_rows_behind_a_matching_file_hash(tmp_path):
    data = tmp_path / "data"
    dataset = make_ai_dataset(data)
    path = dataset / "labels.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[0]["label_source"] = "human"
    payload = "".join(json.dumps(row) + "\n" for row in records)
    path.write_text(payload, encoding="utf-8")
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["labels_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="non-AI"):
        train.load_dataset(dataset, taxonomy=load_taxonomy(sampling.TAXONOMY_PATH), data_root=data)


def test_cli_bundle_can_be_loaded_in_a_fresh_process_without_main_module_aliases(tmp_path):
    data = tmp_path / "data"
    dataset = make_ai_dataset(data)
    launch = """
import runpy
import sys
from pathlib import Path
from newsmlv4 import sampling
sampling.DATA_ROOT = Path(sys.argv[1])
sampling.MODELS_ROOT = Path(sys.argv[1]) / "models"
sys.argv = ['newsmlv4.train', *sys.argv[2:]]
runpy.run_module('newsmlv4.train', run_name='__main__', alter_sys=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", launch, str(data), "--dataset", str(dataset),
         "--models", "complement_nb", "--folds", "3", "--repeats", "1", "--accept-shortfall"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    digest = hashlib.sha256((dataset / "labels.jsonl").read_bytes()).hexdigest()
    bundle = data / "models" / f"v4-ai-{digest[:12]}" / train.BUNDLE
    load = """
import sys
import joblib
import newsmlv4.train
model = joblib.load(sys.argv[1])
assert model.metadata['label_source'] == 'ai-agent'
assert len(model.classify('sport update', 'sport0 sport1 sport2 sport3')) == 2
"""
    restored = subprocess.run([sys.executable, "-c", load, str(bundle)],
                              capture_output=True, text=True, check=False)
    assert restored.returncode == 0, restored.stderr[-2000:]


def test_run_chooses_tests_once_and_saves_a_working_model(tmp_path):
    data = tmp_path / "data"
    make_run(data, "run-a", per_class=10)
    options = dict(data_root=data, models_root=data / "models",
                   models=("majority", "complement_nb", "tfidf_linear_svc"),
                   folds=3, repeats=2, accept_shortfall=True, min_kept=5, **QUIET)

    directory = train.run(["run-a"], **options)

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chosen"] != "majority"
    assert manifest["split"]["development"] + manifest["split"]["test"] == 10 * len(TOPICS)
    assert manifest["unsorted_set_aside"] == 2
    assert manifest["shortfall"]["sport"] == 190 and manifest["shortfall_accepted"]
    assert set(manifest["test"]["per_class"]) == set(TOPICS)
    assert (directory / "model-card.md").read_text(encoding="utf-8").startswith("# Model card")

    model = joblib.load(directory / train.BUNDLE)
    text = train.text_for("sport update", "sport0 sport1 sport2 sport3")
    assert model.classes[model.probabilities([text]).argmax()] == "sport"
    assert model.classify("sport update", "sport0 sport1 sport2 sport3")[0] in {"sport", "unsorted"}

    with pytest.raises(FileExistsError, match="opened"):
        train.run(["run-a"], **options)


def test_a_run_stopped_after_opening_the_test_split_cannot_open_it_again(tmp_path, monkeypatch):
    data = tmp_path / "data"
    make_run(data, "run-a", per_class=10)
    options = dict(data_root=data, models_root=data / "models",
                   models=("majority", "complement_nb", "tfidf_linear_svc"),
                   folds=3, repeats=2, accept_shortfall=True, min_kept=5, **QUIET)

    def stop(*_args, **_kwargs):
        raise RuntimeError("stopped while scoring the test split")

    monkeypatch.setattr(train.evaluate, "bootstrap_class_f1", stop)
    with pytest.raises(RuntimeError, match="stopped"):
        train.run(["run-a"], **options)
    monkeypatch.undo()

    with pytest.raises(FileExistsError, match="opened"):
        train.run(["run-a"], **options)


def fake_encoder(texts):
    return np.array([[text.count(VOCABULARY[t][0]) for t in VOCABULARY] for text in texts], dtype=float)


@pytest.mark.parametrize("name", train.EMBEDDING_RUNGS)
def test_embedding_rungs_fit_with_an_injected_encoder(name):
    texts, labels = synthetic(20)
    model = train.build(name, encoder=fake_encoder).fit(texts, labels)
    assert (model.predict(texts) == labels).mean() >= 0.9


def test_sentence_vectors_are_remembered_only_during_a_training_run(monkeypatch):
    calls = []

    class Encoder:
        def encode(self, texts, **_):
            calls.append(list(texts))
            return np.ones((len(texts), 2))

    monkeypatch.setattr(train, "_sentence_model", lambda *_: Encoder())
    embedder = train.SentenceEmbedder()
    with train.embedding_memo():
        embedder.transform(["a", "b"])
        embedder.transform(["b", "c"])
    embedder.transform(["a"])
    assert calls == [["a", "b"], ["c"], ["a"]]
    assert train._EMBEDDINGS is None


def test_keras_mlp_is_reproducible_and_survives_pickling():
    pytest.importorskip("keras")
    texts, labels = synthetic(20)
    first = train.build("keras_mlp", seed=7).fit(texts, labels)
    second = train.build("keras_mlp", seed=7).fit(texts, labels)

    probabilities = first.predict_proba(texts)
    np.testing.assert_allclose(second.predict_proba(texts), probabilities, atol=1e-6)
    assert (first.predict(texts) == labels).mean() >= 0.9
    restored = pickle.loads(pickle.dumps(first))
    np.testing.assert_allclose(restored.predict_proba(texts), probabilities, atol=1e-6)
    np.testing.assert_allclose(first.predict_proba(texts), probabilities, atol=1e-6)


def write_weak(run, *, low=(), unsorted_as=None):
    """AI-agent labels for a run's rows, as `write_weak_labels` writes them.

    Rows humans labelled `unsorted` get the AI class `unsorted_as`, or no AI label.
    """
    version = load_taxonomy(sampling.TAXONOMY_PATH).version
    with (run / "labels-01.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    lines = []
    for row in rows:
        topic = unsorted_as if row["label"] == "unsorted" else row["label"]
        if topic is not None:
            lines.append(json.dumps({
                "article_id": row["article_id"], "topic": topic,
                "confidence": "low" if row["article_id"] in low else "high",
                "label_source": "ai-agent", "taxonomy_version": version,
            }) + "\n")
    (run / sampling.WEAK_LABELS).write_text("".join(lines), encoding="utf-8")


def test_weak_labels_only_add_training_rows_and_human_labels_win(tmp_path):
    data = tmp_path / "data"
    human = make_run(data, "run-a", per_class=10)
    weak_only = make_run(data, "run-b", per_class=4, gold=False)
    write_weak(human, unsorted_as="sport")  # humans said unsorted; the AI label must not be used
    write_weak(weak_only, low={"run-b-sport-000"})

    directory = train.run(
        ["run-a"], weak_runs=["run-a", "run-b"], data_root=data, models_root=data / "models",
        models=("complement_nb",), folds=3, repeats=1, accept_shortfall=True, min_kept=5, **QUIET,
    )

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["ladder"]) == {"complement_nb", "complement_nb+weak"}
    assert manifest["weak"]["used"] == 4 * len(TOPICS) - 1
    assert manifest["weak"]["dropped"] == {"human_label": 10 * len(TOPICS) + 2, "low_confidence": 1}
    assert manifest["split"]["development"] + manifest["split"]["test"] == 10 * len(TOPICS)


def test_a_weak_run_that_has_human_gold_must_also_train_as_a_human_run(tmp_path):
    data = tmp_path / "data"
    make_run(data, "run-a", per_class=10)
    reviewed = make_run(data, "run-b", per_class=10)
    write_weak(reviewed)
    with pytest.raises(ValueError, match="has human gold"):
        train.run(["run-a"], weak_runs=["run-b"], data_root=data, models_root=data / "models",
                  models=("complement_nb",), folds=3, repeats=1, accept_shortfall=True,
                  min_kept=5, **QUIET)


def test_weak_labels_must_beat_human_labels_alone():
    base = np.linspace(0.70, 0.80, 15)
    wobble = np.tile([0.03, -0.02, 0.0], 5)
    best, chosen, comparisons = train.select(
        {"tfidf_linear_svc": base, "tfidf_linear_svc+weak": base + 0.002 + wobble}, folds=5
    )
    assert (best, chosen) == ("tfidf_linear_svc+weak", "tfidf_linear_svc")
    assert comparisons["tfidf_linear_svc"].tied
