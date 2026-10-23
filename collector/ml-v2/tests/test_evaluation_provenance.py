"""Human judgements and AI-assisted labels must never silently share a result file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsrec import cli, evaluate
from newsrec.data import digest, write_json


@pytest.fixture
def frozen_evaluation(tmp_path):
    directory = tmp_path / "edition"
    directory.mkdir()
    (directory / "documents.jsonl").write_text("{}\n")
    write_json(directory / "training.json", {"model": "fixed"})
    ranking = {method: ["a", "b", "c", "d", "e"] for method in ("tfidf", "svd", "neural")}
    write_json(directory / "evaluation-cases.json", {
        "documents_sha256": digest(directory / "documents.jsonl"),
        "training_sha256": digest(directory / "training.json"),
        "retrieval_sha256": digest(Path(evaluate.__file__).with_name("index.py")),
        "rankings": {"case-1": ranking},
    })
    return directory


def judgement_sheet(directory, filename, label_source, grade):
    path = directory / filename
    rows = [{
        "case_id": "case-1", "article_id": article_id, "grade": grade,
        "label_source": label_source,
    } for article_id in ("a", "b", "c", "d", "e")]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_ai_scoring_is_explicit_and_preserves_human_results(frozen_evaluation):
    directory = frozen_evaluation
    human = judgement_sheet(directory, "human.jsonl", "human", 2)
    ai = judgement_sheet(directory, "ai.jsonl", "ai-assisted", 0)
    human_result = evaluate.score(directory, human)
    human_hash = digest(directory / "relevance.json")
    with pytest.raises(ValueError, match="provenance"):
        evaluate.score(directory, ai)
    ai_result = evaluate.score(directory, ai, label_source="ai-assisted")
    assert human_result["tfidf"]["precision_at_5"] == 1
    assert ai_result["tfidf"]["precision_at_5"] == 0
    assert ai_result["tfidf"]["label_source"] == "ai-assisted"
    assert ai_result["tfidf"]["judgements_sha256"] == digest(ai)
    assert ai_result["tfidf"]["by_case"]["case-1"]["pooled_ndcg_at_5"] == 0
    assert digest(directory / "relevance.json") == human_hash
    assert (directory / "relevance-ai-assisted.json").is_file()
    with pytest.raises(ValueError, match="provenance"):
        evaluate.score(directory, human, label_source="ai-assisted")


def test_mixed_judgement_sources_and_invalid_source_are_rejected(frozen_evaluation):
    directory = frozen_evaluation
    path = judgement_sheet(directory, "mixed.jsonl", "human", 2)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["label_source"] = "ai-assisted"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    for source in ("human", "ai-assisted"):
        with pytest.raises(ValueError, match="provenance"):
            evaluate.score(directory, path, label_source=source)
    with pytest.raises(ValueError, match="label_source"):
        evaluate.score(directory, path, label_source="automatic-human")


def test_selected_ai_cases_have_a_separate_output_file(frozen_evaluation):
    directory = frozen_evaluation
    path = judgement_sheet(directory, "ai.jsonl", "ai-assisted", 1)
    result = evaluate.score(directory, path, case_ids=["case-1"], label_source="ai-assisted")
    assert result["neural"]["cases"] == 1
    assert result["neural"]["pooled_ndcg_at_5"] == 1
    assert (directory / "relevance-ai-assisted-selected.json").is_file()
    assert not (directory / "relevance-selected.json").exists()


def test_cli_passes_explicit_label_source(tmp_path, monkeypatch, capsys):
    captured = {}

    def score(directory, sheet, **kwargs):
        captured.update(kwargs)
        return {"source": kwargs["label_source"]}

    monkeypatch.setattr(evaluate, "score", score)
    assert cli.main([
        "score", "--id", "edition", "--root", str(tmp_path), "--judgements", "ai.jsonl",
        "--label-source", "ai-assisted",
    ]) == 0
    assert captured == {"case_ids": None, "label_source": "ai-assisted"}
    assert json.loads(capsys.readouterr().out)["source"] == "ai-assisted"
