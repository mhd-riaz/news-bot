import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sklearn.model_selection import train_test_split

from newsml import admit
from newsml.labels import load_taxonomy
from newsmlv4 import pool, sampling

TAXONOMY = load_taxonomy(sampling.TAXONOMY_PATH)
NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)


def test_module_entry_point_does_not_silently_succeed_without_required_inputs():
    result = subprocess.run([sys.executable, "-m", "newsmlv4.pool"],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "--articles" in result.stderr and "--sources" in result.stderr


def row(article_id, topic="technology", **kwargs):
    return pool.Row(
        article_id, topic, "Researchers announce a new computer architecture",
        "The laboratory designed novel silicon chips for energy efficient computing and artificial intelligence.",
        (f"proposal:{article_id}",), verified_export=True, **kwargs,
    )


@pytest.fixture(autouse=True)
def language(monkeypatch):
    monkeypatch.setattr(admit, "_language_of", lambda _: "en")


def test_all_usable_ai_effort_is_kept_without_inventing_human_or_confidence_labels():
    first = row("new", confidence="high")
    older = replace(row("old"), title="Football team wins international championship",
                    summary="The players scored three goals in the final match against their rivals on Sunday.",
                    topic="sport")
    result = pool.pool_rows([first, older], taxonomy=TAXONOMY, now=NOW)
    assert {value.article_id for value in result.rows} == {"old", "new"}
    assert {value.record()["label_source"] for value in result.rows} == {"ai-agent"}
    assert {value.confidence for value in result.rows} == {"high", "unknown"}
    assert result.input_rows == len(result.rows) + len(result.excluded)


def test_duplicate_reviews_and_rekeyed_ids_are_not_extra_training_examples():
    first = row("first", aliases=frozenset({"current"}))
    second = replace(row("current"), origins=("legacy:1",))
    result = pool.pool_rows([first, first, second], taxonomy=TAXONOMY, now=NOW)
    assert len(result.rows) == 1
    assert result.rows[0].ids == {"first", "current"}
    assert result.reasons == {"duplicate_annotation_or_text": 2}
    assert set(result.rows[0].origins) == {"proposal:first", "legacy:1"}


def test_conflicting_ai_labels_are_quarantined_instead_of_last_row_winning():
    result = pool.pool_rows([row("a"), row("b", topic="science_space")], taxonomy=TAXONOMY, now=NOW)
    assert not result.rows
    assert result.reasons == {"conflicting_labels": 2}


def test_historical_tests_are_protected_by_alias_and_by_near_duplicate_text():
    alias = row("renamed", aliases=frozenset({"sealed"}))
    similar = replace(row("similar"), title="Researchers announce a new computer architecture today")
    result = pool.pool_rows(
        [alias, similar], taxonomy=TAXONOMY, protected_ids=frozenset({"sealed"}),
        protected_texts={"held-out": row("original").text}, now=NOW,
    )
    assert not result.rows
    assert result.reasons == {"protected_evaluation_id": 1, "protected_near_duplicate": 1}


def test_low_confidence_unsorted_and_missing_text_are_accounted_for():
    result = pool.pool_rows(
        [row("uncertain", confidence="low"),
         replace(row("odd"), topic="unsorted", title="Different unusual story"),
         replace(row("empty"), title="", summary="")],
        taxonomy=TAXONOMY, now=NOW,
    )
    assert not result.rows
    assert result.input_rows == len(result.excluded)
    assert result.reasons == {"low_confidence": 1, "missing_title_or_summary": 1, "unsorted": 1}


def test_legacy_summary_recovery_handles_normalized_and_removed_headlines_without_guessing():
    title = "Engineers\u2019 chips improve computing"
    summary = "A detailed laboratory report describes their new energy efficient processor."
    recovered, evidence = pool._legacy_summary({"title": title, "text": title.replace("\u2019", "'") + "\n" + summary})
    assert recovered == summary and evidence == "legacy_clean_title_summary_snapshot"
    assert pool._legacy_summary({"title": "Explained: Latest research", "text": summary})[0] == summary
    assert pool._legacy_summary({"title": title, "text": "Unrelated first line\n" + summary}) == (
        "", "legacy_summary_not_recoverable",
    )


def test_existing_test_split_is_recovered_only_when_both_recorded_hashes_match():
    labels = {f"{topic}-{index}": topic for topic in ("politics", "technology") for index in range(10)}
    raw = b"original annotation bytes"
    digest = hashlib.sha256(b"run\0" + raw + b"\0").hexdigest()
    ids = sorted(labels)
    _, test = train_test_split(list(range(len(ids))), stratify=[labels[value] for value in ids],
                              random_state=20261110, test_size=0.2)
    expected = {ids[index] for index in test}
    manifest = {
        "runs": [{"run": "run", "gold_sha256": hashlib.sha256(raw).hexdigest()}],
        "gold_digest": digest, "protocol": {"seed": 20261110, "test_share": 0.2},
        "split": {"test": len(expected), "test_ids_sha256": hashlib.sha256(
            "\n".join(sorted(expected)).encode()).hexdigest()},
    }
    assert pool.recover_test_ids(manifest, labels_by_run={"run": labels},
                                 raw_by_run={"run": raw}, unsorted="unsorted") == expected
    manifest["split"]["test_ids_sha256"] = "wrong"
    with pytest.raises(ValueError, match="reproduced exactly"):
        pool.recover_test_ids(manifest, labels_by_run={"run": labels},
                              raw_by_run={"run": raw}, unsorted="unsorted")
