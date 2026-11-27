import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest
from pymongo.errors import PyMongoError

from newsml.annotate import COLUMNS
from newsml.labels import load_taxonomy
from newsmlv4 import importer, sampling, verify


def article_doc(article_id, *, summary="The same original summary", content_hash="hash-1"):
    return {
        "_id": article_id,
        "title": "The same original title",
        "summary": summary,
        "content_hash": content_hash,
        "published_at": datetime(2026, 11, 9, tzinfo=timezone.utc),
        "collected_at": datetime(2026, 11, 9, tzinfo=timezone.utc),
    }


def selection_record(doc):
    article = sampling._article(doc)
    return {
        "article_id": article.id,
        "content_hash": article.content_hash,
        "sheet_text_sha256": hashlib.sha256(
            (article.title + "\n" + article.lede).encode("utf-8")
        ).hexdigest(),
    }


def run_with_selection(tmp_path, records):
    data = tmp_path / "data"
    run = data / "run"
    run.mkdir(parents=True)
    (run / "selection.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    (run / "manifest.json").write_text(json.dumps({
        "status": "unlabeled_candidates_not_gold",
        "taxonomy_sha256": hashlib.sha256(sampling.TAXONOMY_PATH.read_bytes()).hexdigest(),
        "sources_sha256": hashlib.sha256(sampling.SOURCES_PATH.read_bytes()).hexdigest(),
        "selected_digest": hashlib.sha256(
            "\n".join(sorted(record["article_id"] for record in records)).encode()
        ).hexdigest(),
    }), encoding="utf-8")
    return data, run


def write_sheet(run, docs, labels=None):
    with (run / "sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for doc in docs:
            writer.writerow({
                "article_id": doc["_id"],
                "title": doc["title"],
                "summary": doc["summary"],
                "label": (labels or {}).get(doc["_id"], ""),
                "notes": "",
            })


def test_verified_sheet_text_matches_local_article(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    selected = verify.load_selection(run, data)
    assert verify.compare_documents(selected, [doc]) == (1, 0, 0)
    write_sheet(run, [doc])
    assert verify.compare_sheets(run, selected) == (1, 0, 0, 0)


@pytest.mark.parametrize("documents,expected", [
    ([], (0, 1, 0)),
    ([article_doc("fresh", summary="Updated summary")], (1, 0, 1)),
    ([article_doc("fresh", content_hash="revised-hash")], (1, 0, 1)),
])
def test_missing_or_changed_article_is_not_verified(tmp_path, documents, expected):
    data, run = run_with_selection(tmp_path, [selection_record(article_doc("fresh"))])
    assert verify.compare_documents(verify.load_selection(run, data), documents) == expected


def test_duplicate_returned_article_is_rejected(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    with pytest.raises(ValueError, match="duplicate"):
        verify.compare_documents(verify.load_selection(run, data), [doc, doc])


def test_changed_or_missing_review_sheet_is_not_verified(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    selected = verify.load_selection(run, data)
    with pytest.raises(ValueError, match="no candidate CSV"):
        verify.compare_sheets(run, selected)
    write_sheet(run, [])
    assert verify.compare_sheets(run, selected) == (0, 1, 0, 0)
    write_sheet(run, [article_doc("fresh", summary="Human edited the lede")])
    assert verify.compare_sheets(run, selected) == (1, 0, 1, 0)


def test_overlapping_review_rows_must_not_disagree(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    write_sheet(run, [doc], {"fresh": "health"})
    with (run / "overlap.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow({
            "article_id": "fresh", "title": doc["title"], "summary": doc["summary"],
            "label": "technology", "notes": "",
        })
    assert verify.compare_sheets(run, verify.load_selection(run, data)) == (1, 0, 0, 1)


def test_sheet_header_and_article_membership_are_checked(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    path = run / "sheet.csv"
    path.write_text("article_id,label\nfresh,health\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CSV columns"):
        verify.compare_sheets(run, verify.load_selection(run, data))
    write_sheet(run, [article_doc("other")])
    with pytest.raises(ValueError, match="unknown article_id"):
        verify.compare_sheets(run, verify.load_selection(run, data))


def test_sheet_rejects_malformed_row_and_outside_symlink(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    path = run / "sheet.csv"
    path.write_text(
        "article_id,title,summary,label,notes\nfresh,title\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="malformed CSV"):
        verify.compare_sheets(run, verify.load_selection(run, data))
    outside = tmp_path / "outside.csv"
    outside.write_text("article_id,title,summary,label,notes\n", encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        verify.compare_sheets(run, verify.load_selection(run, data))


def test_verification_cli_rejects_invalid_run_without_db(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(verify, "DATA_ROOT", tmp_path / "data")
    assert verify.main(["--run", str(tmp_path / "outside")]) == 1
    assert "directly inside" in capsys.readouterr().err


def test_verification_cli_does_not_log_database_error_details(
    tmp_path, monkeypatch, capsys
):
    data, run = run_with_selection(tmp_path, [selection_record(article_doc("fresh"))])
    monkeypatch.setattr(verify, "DATA_ROOT", data)

    def fail(_run, _selection):
        raise PyMongoError("private connection detail")

    monkeypatch.setattr(verify, "compare_sheets", fail)
    assert verify.main(["--run", str(run)]) == 1
    error = capsys.readouterr().err
    assert "PyMongoError" in error
    assert "private connection detail" not in error


@pytest.mark.parametrize("field,value,error", [
    ("status", "gold", "candidate manifest"),
    ("sources_sha256", "wrong", "sources_sha256"),
    ("taxonomy_sha256", "wrong", "taxonomy_sha256"),
    ("selected_digest", "wrong", "digest"),
])
def test_selection_manifest_must_match_export(tmp_path, field, value, error):
    data, run = run_with_selection(tmp_path, [selection_record(article_doc("fresh"))])
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        verify.load_selection(run, data)


def test_selection_requires_private_directory_and_unique_valid_ids(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    with pytest.raises(ValueError, match="directly inside"):
        verify.load_selection(tmp_path, data)
    path = run / "selection.jsonl"
    path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate article_id"):
        verify.load_selection(run, data)


def test_selection_rejects_missing_fingerprints_and_symlink(tmp_path):
    data, run = run_with_selection(tmp_path, [selection_record(article_doc("fresh"))])
    path = run / "selection.jsonl"
    path.write_text('{"article_id":"fresh"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprints"):
        verify.load_selection(run, data)
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text('{"article_id":"fresh"}\n', encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        verify.load_selection(run, data)


def test_many_selected_documents_verify_without_a_network(tmp_path):
    docs = [article_doc(f"fresh-{index}") for index in range(500)]
    data, run = run_with_selection(tmp_path, [selection_record(doc) for doc in docs])
    assert verify.compare_documents(verify.load_selection(run, data), docs) == (500, 0, 0)
    write_sheet(run, docs)
    assert verify.compare_sheets(run, verify.load_selection(run, data)) == (500, 0, 0, 0)


class FakeCursor(list):
    def close(self):
        pass


class FakeArticles:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None, **_):
        (field, condition), = query.items()
        return FakeCursor(doc for doc in self.docs if doc.get(field) in condition["$in"])


def test_export_verified_import_writes_newsml_gold_and_records_the_recheck(tmp_path):
    kept = article_doc("kept-old")
    gone = article_doc("gone", summary="A summary that was later removed", content_hash="hash-2")
    data, run = run_with_selection(tmp_path, [selection_record(kept), selection_record(gone)])
    write_sheet(run, [kept, gone], {"kept-old": "sport", "gone": "unsorted"})
    # Today's database holds the kept article under a new ID; same title, other text does not count.
    today = FakeArticles([{**kept, "_id": "kept-new"}])
    taxonomy = load_taxonomy(sampling.TAXONOMY_PATH)

    record = importer.import_gold(run, today, taxonomy=taxonomy, data_root=data)

    gold = [json.loads(line) for line in (run / "gold.jsonl").read_text(encoding="utf-8").splitlines()]
    common = {"annotator": "sheet", "label_source": "human", "taxonomy_version": taxonomy.version}
    assert gold == [
        {**common, "article_id": "gone", "topic": "unsorted"},
        {**common, "article_id": "kept-old", "topic": "sport"},
    ]
    assert sampling.reviewed_labels([run / "gold.jsonl"], taxonomy) == {"gone": "unsorted", "kept-old": "sport"}
    assert (run / "current-ids.jsonl").read_text(encoding="utf-8") == (
        '{"article_id": "kept-old", "current_id": "kept-new"}\n'
    )
    assert record["current_database"] == {
        "identical_text": 1, "not_rechecked": 1, "not_rechecked_by_label": {"unsorted": 1},
    }
    with pytest.raises(FileExistsError):
        importer.import_gold(run, today, taxonomy=taxonomy, data_root=data)


def test_export_verified_import_needs_every_row_labelled_and_unchanged(tmp_path):
    doc = article_doc("fresh")
    data, run = run_with_selection(tmp_path, [selection_record(doc)])
    taxonomy = load_taxonomy(sampling.TAXONOMY_PATH)
    write_sheet(run, [doc])
    with pytest.raises(ValueError, match="no label"):
        importer.import_gold(run, FakeArticles([]), taxonomy=taxonomy, data_root=data)
    write_sheet(run, [{**doc, "summary": "Edited after export"}], {"fresh": "sport"})
    with pytest.raises(ValueError, match="1 changed"):
        importer.import_gold(run, FakeArticles([]), taxonomy=taxonomy, data_root=data)
    assert not (run / "gold.jsonl").exists()
