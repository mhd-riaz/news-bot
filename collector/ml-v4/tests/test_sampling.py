import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import PyMongoError

from newsml import admit, clean
from newsml.labels import load_taxonomy
from newsml.load import _to_article
from newsmlv4 import sampling
from newsmlv4 import cli
from newsmlv4.cli import local_uri, parse_cut


CUT = datetime(2026, 11, 10, tzinfo=timezone.utc)


@pytest.fixture
def taxonomy():
    return load_taxonomy(sampling.TAXONOMY_PATH)


def article_doc(article_id, topic, *, source="Allowed", summary=None, **fields):
    doc = {
        "_id": article_id,
        "source_id": "source-1",
        "source_name": source,
        "title": f"Researchers examine {article_id} in a new international study",
        "summary": summary if summary is not None else (
            f"A detailed report about {article_id} describes the findings from "
            "independent researchers and their review of evidence across several "
            "groups. The authors explain the methodology, potential limitations, "
            "and what the new results could mean for people working in this field."
        ),
        "content_hash": f"hash-{article_id}",
        "language": "en",
        "published_at": CUT - timedelta(days=1),
        "collected_at": CUT - timedelta(hours=12),
        "processing_status": "enriched",
        "scrape_status": "done",
        "topic": topic,
        "confidence": 0.7,
    }
    doc.update(fields)
    return doc


def candidate(article_id, topic, *, source="Allowed", confidence=0.5, content_hash=None):
    fields = {}
    if content_hash is not None:
        fields["content_hash"] = content_hash
    article = _to_article(article_doc(article_id, topic, source=source, **fields))
    return sampling.Candidate(article, topic, confidence, "v2")


def test_choose_balances_thirteen_classes_and_is_deterministic(taxonomy):
    topics = sorted(taxonomy.ids)
    assert len(topics) == 13
    pools = {
        topic: [candidate(f"{index}-{number}", topic, source=f"source-{number % 5}")
                for number in range(205)]
        for index, topic in enumerate(topics)
    }
    group_of = {row.article.id: row.article.id for pool in pools.values() for row in pool}
    quotas = dict.fromkeys(topics, 200)

    first = sampling._choose(pools, quotas, group_of, set(), set(), 42)
    second = sampling._choose(pools, quotas, group_of, set(), set(), 42)

    assert Counter(row.topic for row in first) == quotas
    assert len({row.article.id for row in first}) == 2600
    assert [row.article.id for row in first] == [row.article.id for row in second]


def test_choose_prior_story_and_hash_exclusions_never_pad(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    rows = [candidate("duplicate", topic), candidate("same-hash", topic, content_hash="old-hash"),
            candidate("new", topic)]
    chosen = sampling._choose(
        {topic: rows},
        {topic: 3},
        {"duplicate": "old-group", "same-hash": "hash-group", "new": "new-group"},
        {"old-group"},
        {"old-hash"},
        3,
    )
    assert [row.article.id for row in chosen] == ["new"]


def test_choose_zero_remaining_quota_skips_the_class(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    assert sampling._choose({topic: [candidate("new", topic)]},
                            {topic: 0}, {"new": "new"}, set(), set(), 1) == ()


def test_sample_documents_filters_prior_and_ineligible_rows(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    documents = [
        article_doc("old", topic),
        article_doc("bad-source", topic, source="Unknown", source_id="reader-feed"),
        article_doc("bad-language", topic, detected_language="fr"),
        article_doc("future", topic, collected_at=CUT),
        article_doc("new", topic),
    ]
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[article_doc("old", topic)],
        documents=documents,
        cut=CUT,
        per_class=2,
        seed=3,
        old_ids=frozenset({"old"}),
        source_ids=frozenset({"source-1"}),
    )
    assert result.queried == 5
    assert result.skipped["prior_id"] == 1
    assert result.skipped["unapproved_source"] == 1
    assert result.skipped["non_english"] == 1
    assert result.skipped["after_cut"] == 1
    assert all(row.article.id != "old" for row in result.selected)
    assert result.counts()[topic]["shortfall"] >= 1


@pytest.mark.parametrize("value", [True, "high", float("nan"), -0.1, 1.1])
def test_stored_classifier_fields_are_not_used_as_training_labels(taxonomy, value):
    topic = sorted(taxonomy.ids)[0]
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[],
        documents=[article_doc("new", "not-a-taxonomy-class", confidence=value)],
        cut=CUT,
        per_class=1,
        seed=1,
        old_ids=frozenset(),
        source_ids=frozenset({"source-1"}),
    )
    assert result.queried == 1
    assert all(row.topic in taxonomy.ids for row in result.selected)


def test_provisional_topic_uses_current_taxonomy_feed_hint_without_old_gold(taxonomy):
    source, topic = next(
        (name, value) for name, value in taxonomy.feed_topics.items()
        if value in taxonomy.ids
    )
    article = _to_article(article_doc(
        "hinted", "ignored", source=source,
        title="Xyzzy quokka zyzzy", summary="Marmoset quokka zyzzy xyzzles",
    ))
    row = admit.Admitted(article, clean.clean(article.text("title_summary")))

    inferred = sampling.provisional_topics([row], taxonomy)

    assert inferred["hinted"][0] == topic
    assert inferred["hinted"][2] == "taxonomy-hint-only"


def test_provisional_topic_does_not_invent_class_without_any_signal(taxonomy):
    article = _to_article(article_doc(
        "unassigned", "ignored", source="Unknown",
        title="Xyzzy quokka zyzzy", summary="Marmoset quokka zyzzy xyzzles",
    ))
    row = admit.Admitted(article, clean.clean(article.text("title_summary")))
    assert sampling.provisional_topics([row], taxonomy) == {}


def test_provisional_topic_accepts_taxonomy_category_hint(taxonomy):
    category, topic = next(
        (name, value) for name, value in taxonomy.category_map.items()
        if value in taxonomy.ids
    )
    article = _to_article(article_doc(
        "categorized", "ignored", source="Unknown", categories=[category],
        title="Xyzzy quokka zyzzy", summary="Marmoset quokka zyzzy xyzzles",
    ))
    row = admit.Admitted(article, clean.clean(article.text("title_summary")))
    assert sampling.provisional_topics([row], taxonomy)["categorized"][0] == topic


def test_sample_documents_excludes_old_near_duplicate_without_hash_match(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    same_title = "Researchers examine a new international study of urban health"
    same_summary = (
        "An independent research team compared public health responses in several "
        "cities and described its methods, findings, and practical limitations."
    )
    old = article_doc("old", topic, title=same_title, summary=same_summary)
    fresh = article_doc("fresh", topic, title=same_title, summary=same_summary)
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[old],
        documents=[fresh],
        cut=CUT,
        per_class=1,
        seed=3,
        old_ids=frozenset({"old"}),
        source_ids=frozenset({"source-1"}),
    )
    assert result.selected == ()
    assert result.skipped["prior_near_duplicate"] == 1


def test_sample_documents_records_exact_hash_and_missing_lede(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[article_doc("old", topic, content_hash="shared")],
        documents=[
            article_doc("same-hash", topic, content_hash="shared"),
            article_doc("no-summary", topic, summary=""),
        ],
        cut=CUT,
        per_class=2,
        seed=3,
        old_ids=frozenset({"old"}),
        source_ids=frozenset({"source-1"}),
    )
    assert result.skipped["prior_content_hash"] == 1
    assert result.skipped["no_title_or_lede"] == 1
    assert result.selected == ()


def test_no_admitted_rows_need_no_vectorizer_fit(taxonomy):
    assert sampling.provisional_topics([], taxonomy) == {}
    assert sampling._article({"_id": "fallback", "clean_summary": "Available lede"}).summary == "Available lede"


@pytest.mark.parametrize("per_class,cut,sources,expected", [
    (0, CUT, frozenset({"source-1"}), "per_class"),
    (1, datetime(2026, 11, 10), frozenset({"source-1"}), "timezone"),
    (1, CUT, frozenset(), "approved shipped source"),
])
def test_sample_documents_rejects_invalid_configuration(
    taxonomy, per_class, cut, sources, expected
):
    with pytest.raises(ValueError, match=expected):
        sampling.sample_documents(
            taxonomy, old_documents=[], documents=[],
            cut=cut, per_class=per_class, seed=1,
            old_ids=frozenset(), source_ids=sources,
        )


def test_mongo_scan_rejects_invalid_limit_before_using_collection(taxonomy):
    with pytest.raises(ValueError, match="scan_limit"):
        sampling.sample(
            None, taxonomy, cut=CUT, per_class=200, scan_limit=100,
            seed=1, old_ids=frozenset(), source_ids=frozenset({"source-1"}),
        )


def test_reviewed_gold_reduces_refill_quota(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[],
        documents=[article_doc("reviewed", topic), article_doc("new", topic)],
        cut=CUT,
        per_class=2,
        seed=1,
        old_ids=frozenset(),
        source_ids=frozenset({"source-1"}),
        confirmed={"reviewed": topic},
        prior_candidates=frozenset({"reviewed"}),
    )
    assert result.quotas[topic] == 1
    assert result.skipped["prior_id"] == 1
    assert result.counts()[topic]["selected"] <= 1


def test_private_csv_preserves_schema_and_hides_predictions(tmp_path, monkeypatch, taxonomy):
    monkeypatch.setattr(sampling, "DATA_ROOT", tmp_path / "data")
    topic = sorted(taxonomy.ids)[0]
    row = candidate("spreadsheet", topic)
    row = sampling.Candidate(
        _to_article(article_doc("spreadsheet", topic, title="=2+2",
                                summary="@unexpected formula input")),
        topic,
        row.sampling_score,
        row.sampling_method,
    )
    result = sampling.Sample((row,), {topic: 1}, {topic: 1}, {topic: 1}, 0, 0, 0, {}, {})
    out = sampling.DATA_ROOT / "run-1"
    sheets = sampling.write_sample(
        result, out, cut=CUT, seed=2, per_class=1,
        scan_limit=10, taxonomy=taxonomy, shards=1, overlap=0,
    )
    with sheets[0].open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["article_id", "title", "summary", "label", "notes"]
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["title"].startswith("'=")
    assert rows[0]["summary"].startswith("'@")
    assert rows[0]["label"] == rows[0]["notes"] == ""
    assert "predicted_topic" not in rows[0]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "unlabeled_candidates_not_gold"
    assert "sources_sha256" in manifest
    assert manifest["counts"][topic]["selected"] == 1
    assert json.loads((out / "selection.jsonl").read_text(encoding="utf-8"))["predicted_topic"] == topic

    with pytest.raises(FileExistsError, match="overwrite"):
        sampling.write_sample(
            result, out, cut=CUT, seed=2, per_class=1,
            scan_limit=10, taxonomy=taxonomy, shards=1, overlap=0,
        )
    with pytest.raises(ValueError, match="inside"):
        sampling.write_sample(
            result, tmp_path / "outside", cut=CUT, seed=2, per_class=1,
            scan_limit=10, taxonomy=taxonomy, shards=1, overlap=0,
        )


def test_export_refuses_empty_or_invalid_sheet_layout(tmp_path, monkeypatch, taxonomy):
    monkeypatch.setattr(sampling, "DATA_ROOT", tmp_path / "data")
    topic = sorted(taxonomy.ids)[0]
    empty = sampling.Sample((), {topic: 0}, {topic: 0}, {topic: 1}, 0, 0, 0, {}, {})
    with pytest.raises(ValueError, match="no eligible"):
        sampling.write_sample(
            empty, sampling.DATA_ROOT / "empty", cut=CUT, seed=1,
            per_class=1, scan_limit=10, taxonomy=taxonomy,
        )
    one = sampling.Sample(
        (candidate("fresh", topic),), {topic: 1}, {topic: 1},
        {topic: 1}, 0, 0, 0, {}, {},
    )
    with pytest.raises(ValueError, match="shards"):
        sampling.write_sample(
            one, sampling.DATA_ROOT / "invalid", cut=CUT, seed=1,
            per_class=1, scan_limit=10, taxonomy=taxonomy, shards=0,
        )


def test_prior_gold_ids_are_exclusions_not_labels(tmp_path, monkeypatch):
    old = tmp_path / "ml" / "data" / "labels"
    old.mkdir(parents=True)
    (old / "gold-combined.jsonl").write_text(
        '\n{"article_id":"old-1","topic":"irrelevant"}\n', encoding="utf-8"
    )
    (old / "v1").mkdir()
    (old / "v1" / "gold.jsonl").write_text(
        '{"article_id":"old-2","topic":"other"}\n', encoding="utf-8"
    )
    monkeypatch.setattr(sampling, "OLD_LABELS_ROOTS", (old, tmp_path / "ml-v2"))
    assert sampling.old_gold_ids() == frozenset({"old-1", "old-2"})


@pytest.mark.parametrize("body,expected", [
    ("not json\n", "invalid JSON"),
    ("[]\n", "expected an object"),
    ('{"topic":"missing-id"}\n', "invalid article_id"),
])
def test_prior_gold_validation_rejects_malformed_records(tmp_path, monkeypatch, body, expected):
    root = tmp_path / "labels"
    root.mkdir()
    (root / "gold-combined.jsonl").write_text(body, encoding="utf-8")
    monkeypatch.setattr(sampling, "OLD_LABELS_ROOTS", (root, tmp_path / "empty"))
    with pytest.raises(ValueError, match=expected):
        sampling.old_gold_ids()


def test_prior_gold_file_must_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(sampling, "OLD_LABELS_ROOTS", (tmp_path, tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="prior-gold"):
        sampling.old_gold_ids()


def test_human_gold_validation_and_prior_candidates(tmp_path, taxonomy):
    topic = sorted(taxonomy.ids)[0]
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps({
        "article_id": "fresh", "topic": topic,
        "label_source": "human", "taxonomy_version": taxonomy.version,
    }) + "\n", encoding="utf-8")
    assert sampling.reviewed_labels([gold], taxonomy) == {"fresh": topic}
    run = tmp_path / "run"
    run.mkdir()
    (run / "selection.jsonl").write_text('{"article_id":"fresh"}\n', encoding="utf-8")
    assert sampling.prior_candidate_ids(tmp_path) == frozenset({"fresh"})

    gold.write_text('{"article_id":"fresh","topic":"invalid","label_source":"ai"}\n',
                    encoding="utf-8")
    with pytest.raises(ValueError, match="human label"):
        sampling.reviewed_labels([gold], taxonomy)


def test_conflicting_human_labels_are_rejected(tmp_path, taxonomy):
    topic, other = sorted(taxonomy.ids)[:2]
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        "\n".join(json.dumps({
            "article_id": "same", "topic": value,
            "label_source": "human", "taxonomy_version": taxonomy.version,
        }) for value in (topic, other)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting"):
        sampling.reviewed_labels([gold], taxonomy)


def test_prior_selection_symlink_outside_private_root_is_rejected(tmp_path):
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"article_id":"not-private"}\n', encoding="utf-8")
    data = tmp_path / "data"
    run = data / "run"
    run.mkdir(parents=True)
    (run / "selection.jsonl").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        sampling.prior_candidate_ids(data)


def test_prior_selection_requires_article_id(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "selection.jsonl").write_text('{"missing":"id"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="article_id"):
        sampling.prior_candidate_ids(tmp_path)


def test_source_policy_excludes_medium_and_unlisted_sources(tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "sources:\n"
        "  - name: Allowed\n    feed_url: https://allowed.example/feed\n"
        "  - name: Medium\n    feed_url: https://medium.com/feed/tag/ai\n",
        encoding="utf-8",
    )
    assert sampling.approved_feed_urls(sources) == frozenset({"https://allowed.example/feed"})


@pytest.mark.parametrize("body,expected", [
    ("not-a-mapping\n", "sources list"),
    ("sources:\n  - item\n", "invalid source entry"),
    ("sources:\n  - name: Missing URL\n", "no feed URL"),
    ("sources:\n  - name: Invalid URL\n    feed_url: not-a-url\n", "invalid feed URL"),
])
def test_source_manifest_requires_valid_entries(tmp_path, body, expected):
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        sampling.approved_feed_urls(path)


@pytest.mark.parametrize("uri", [
    "mongodb://remote.example/news",
    "mongodb+srv://cluster.example/news",
    "mongodb://127.0.0.1/other",
    "mongodb://127.0.0.1,remote.example/news",
])
def test_local_uri_refuses_nonlocal_or_wrong_database(monkeypatch, uri):
    monkeypatch.setenv("NEWS_ML_MONGO_URI", uri)
    with pytest.raises(ValueError, match="local news"):
        local_uri()


def test_local_uri_requires_explicit_environment_and_cut_timezone(monkeypatch):
    monkeypatch.delenv("NEWS_ML_MONGO_URI", raising=False)
    with pytest.raises(ValueError, match="NEWS_ML_MONGO_URI"):
        local_uri()
    monkeypatch.setenv("NEWS_ML_MONGO_URI", "mongodb://127.0.0.1:27017/news")
    assert local_uri() == "mongodb://127.0.0.1:27017/news"
    assert parse_cut("2026-11-10T05:30:00+05:30") == CUT
    with pytest.raises(ValueError, match="timezone"):
        parse_cut("2026-11-10T00:00:00")
    with pytest.raises(ValueError, match="future"):
        parse_cut("2999-01-01T00:00:00+00:00")
    assert parse_cut(None).tzinfo is timezone.utc


def test_local_uri_rejects_malformed_ipv6_without_printing_it(monkeypatch):
    monkeypatch.setenv("NEWS_ML_MONGO_URI", "mongodb://[broken/news")
    with pytest.raises(ValueError, match="malformed"):
        local_uri()


def test_cli_rejects_reviewed_gold_outside_private_data(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    args = SimpleNamespace(
        cut="2026-11-10T00:00:00+00:00",
        out=tmp_path / "data" / "new",
        per_class=200,
        scan_limit=26000,
        reviewed_gold=[tmp_path / "gold.jsonl"],
    )
    with pytest.raises(ValueError, match="inside ml-v4/data"):
        cli.export(args)


def test_cli_blocks_second_export_until_all_prior_candidates_are_reviewed(
    tmp_path, monkeypatch, taxonomy
):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    run = cli.DATA_ROOT / "previous"
    run.mkdir(parents=True)
    (run / "selection.jsonl").write_text(
        '{"article_id":"reviewed"}\n{"article_id":"pending"}\n', encoding="utf-8"
    )
    args = SimpleNamespace(
        cut="2026-11-10T00:00:00+00:00",
        out=cli.DATA_ROOT / "new",
        per_class=200,
        scan_limit=26000,
        reviewed_gold=None,
    )
    with pytest.raises(ValueError, match="need human review"):
        cli.export(args)
    topic = sorted(taxonomy.ids)[0]
    gold = run / "gold.jsonl"
    gold.write_text(json.dumps({
        "article_id": "reviewed", "topic": topic,
        "label_source": "human", "taxonomy_version": taxonomy.version,
    }) + "\n", encoding="utf-8")
    args.reviewed_gold = [gold]
    with pytest.raises(ValueError, match="lack reviewed human labels"):
        cli.export(args)


def test_refill_requires_only_exported_ids_and_can_merge_reviewed_runs(
    tmp_path, monkeypatch, taxonomy
):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    topic = sorted(taxonomy.ids)[0]
    paths = []
    for index in range(2):
        run = cli.DATA_ROOT / f"previous-{index}"
        run.mkdir(parents=True)
        article_id = f"reviewed-{index}"
        (run / "selection.jsonl").write_text(
            json.dumps({"article_id": article_id}) + "\n", encoding="utf-8"
        )
        gold = run / "gold.jsonl"
        gold.write_text(json.dumps({
            "article_id": article_id, "topic": topic,
            "label_source": "human", "taxonomy_version": taxonomy.version,
        }) + "\n", encoding="utf-8")
        paths.append(gold)
    assert sampling.reviewed_labels(paths, taxonomy) == {
        "reviewed-0": topic, "reviewed-1": topic,
    }
    args = SimpleNamespace(
        cut="2026-11-10T00:00:00+00:00",
        out=cli.DATA_ROOT / "new",
        per_class=200,
        scan_limit=26000,
        reviewed_gold=paths,
    )
    paths[1].write_text(json.dumps({
        "article_id": "unexported", "topic": topic,
        "label_source": "human", "taxonomy_version": taxonomy.version,
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not exported"):
        cli.export(args)


def test_cli_reports_shortfall_without_claiming_balance(tmp_path, monkeypatch, taxonomy, capsys):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(sampling, "DATA_ROOT", tmp_path / "data")
    topic = sorted(taxonomy.ids)[0]
    result = sampling.Sample(
        (candidate("fresh", topic),),
        {topic: 1}, {topic: 1}, {topic: 2},
        0, 0, 0, {}, {"taxonomy-tfidf-v1": 1}, 1,
    )
    args = SimpleNamespace(seed=1, scan_limit=10, per_class=2, shards=1, overlap=0)
    assert cli.report_sample(result, args, cli.DATA_ROOT / "new", CUT, taxonomy) == 0
    output = capsys.readouterr()
    assert "shortfall 1" in output.out
    assert "Not balanced" in output.err


@pytest.mark.parametrize("options,expected", [
    (["--cut", "not-a-date"], "ISO-8601"),
    (["--per-class", "0"], "positive"),
])
def test_cli_invalid_arguments_fail_before_db(tmp_path, monkeypatch, capsys, options, expected):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    assert cli.main(["--out", str(cli.DATA_ROOT / "new"), *options]) == 1
    assert expected in capsys.readouterr().err


def test_cli_does_not_log_database_error_details(monkeypatch, capsys):
    def fail(_args):
        raise PyMongoError("private connection detail")

    monkeypatch.setattr(cli, "export", fail)
    assert cli.main([]) == 1
    error = capsys.readouterr().err
    assert "PyMongoError" in error
    assert "private connection detail" not in error


def test_agent_topics_replace_provisional_topics_and_prior_sheet_stories_stay_excluded(taxonomy):
    disaster, sport = "disaster_accident", "sport"
    title = "Flood waters cut off villages after record monsoon rain in the hills"
    summary = (
        "Rescue teams used boats to reach families stranded by rising water, officials said, "
        "as roads collapsed and power failed across the district overnight."
    )
    # Rebuilt from an earlier sheet: no source, no dates, an ID today's database lacks.
    prior_sheet_doc = {"_id": "round-1-id", "title": title, "summary": summary, "content_hash": "old-hash"}
    documents = [
        article_doc("same-story", sport, title=title, summary=summary),
        article_doc("judged", sport),
        article_doc("not-judged", sport),
    ]
    result = sampling.sample_documents(
        taxonomy,
        old_documents=[prior_sheet_doc],
        documents=documents,
        cut=CUT,
        per_class=200,
        seed=1,
        old_ids=frozenset(),
        source_ids=frozenset({"source-1"}),
        topics={
            "same-story": (disaster, 0.9, sampling.AGENT_METHOD),
            "judged": (disaster, 0.6, sampling.AGENT_METHOD),
        },
    )
    assert [(c.article.id, c.topic, c.sampling_method) for c in result.selected] == [
        ("judged", disaster, sampling.AGENT_METHOD)
    ]
    assert result.skipped["prior_near_duplicate"] == 1
    assert result.skipped["no_provisional_topic"] == 1


def write_proposals(directory, *records):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "agent.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_agent_proposals_drop_disagreements_and_keep_the_surest_repeat(tmp_path, monkeypatch, taxonomy):
    monkeypatch.setattr(sampling, "PROPOSALS_ROOT", tmp_path / "proposals")
    judged = lambda article_id, topic, confidence: {  # noqa: E731
        "article_id": article_id, "topic": topic, "confidence": confidence, "target": "conflict_war",
    }
    write_proposals(
        tmp_path / "proposals" / "r2",
        judged("a", "conflict_war", "low"), judged("a", "conflict_war", "high"),
        judged("b", "conflict_war", "high"), judged("b", "politics", "medium"),
        judged("c", "unsorted", "medium"),
    )
    proposals, provenance = sampling.load_proposals(tmp_path / "proposals" / "r2", taxonomy)
    assert proposals == {
        "a": sampling.Proposal("conflict_war", "high", "conflict_war"),
        "c": sampling.Proposal("unsorted", "medium", "conflict_war"),
    }
    assert (provenance["judgements"], provenance["disputed_dropped"]) == (5, 1)

    write_proposals(tmp_path / "proposals" / "bad", judged("d", "war", "high"))
    with pytest.raises(ValueError, match="taxonomy topic"):
        sampling.load_proposals(tmp_path / "proposals" / "bad", taxonomy)
    write_proposals(tmp_path / "elsewhere", judged("e", "sport", "high"))
    with pytest.raises(ValueError, match="inside"):
        sampling.load_proposals(tmp_path / "elsewhere", taxonomy)


def test_prior_documents_come_from_sheets_and_current_ids(tmp_path):
    run = tmp_path / "data" / "round-1"
    run.mkdir(parents=True)
    (run / "selection.jsonl").write_text(
        json.dumps({"article_id": "old-id", "content_hash": "h1"}) + "\n", encoding="utf-8"
    )
    with (run / "labels-01.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["article_id", "title", "summary", "label", "notes"])
        writer.writeheader()
        writer.writerow({"article_id": "old-id", "title": sampling.safe_cell("-5% rate cut"),
                         "summary": "Markets fell", "label": "business_economy", "notes": ""})
    (run / "current-ids.jsonl").write_text(
        json.dumps({"article_id": "old-id", "current_id": "new-id"}) + "\n", encoding="utf-8"
    )
    documents, current = sampling.prior_documents(tmp_path / "data")
    assert documents == [{"_id": "old-id", "title": "-5% rate cut", "summary": "Markets fell", "content_hash": "h1"}]
    assert current == frozenset({"new-id"})


def test_weak_labels_are_written_once_as_ai_agent_judgements(tmp_path, taxonomy):
    chosen = candidate("fresh", "conflict_war")
    proposals = {"fresh": sampling.Proposal("conflict_war", "medium", "conflict_war")}
    path = sampling.write_weak_labels(tmp_path, [chosen], proposals, taxonomy)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "article_id": "fresh", "topic": "conflict_war", "confidence": "medium",
        "target": "conflict_war", "label_source": "ai-agent",
        "method": sampling.AGENT_METHOD, "taxonomy_version": taxonomy.version,
    }
    with pytest.raises(FileExistsError):
        sampling.write_weak_labels(tmp_path, [chosen], proposals, taxonomy)


class FakeCursor(list):
    def sort(self, *_):
        return self

    def limit(self, count):
        return FakeCursor(self[:count])

    def close(self):
        pass


class FakeArticles:
    """Enough of a collection for `sample`: `$in` and `$lt` filters, sort, limit."""

    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None, **_):
        def matches(doc):
            for field, condition in query.items():
                value = doc.get(field)
                if "$in" in condition and value not in condition["$in"]:
                    return False
                if "$lt" in condition and not value < condition["$lt"]:
                    return False
            return True

        return FakeCursor(doc for doc in self.docs if matches(doc))


def test_scan_excludes_earlier_round_stories_and_counts_only_old_gold_found(taxonomy):
    topic = sorted(taxonomy.ids)[0]
    title = "Researchers examine a new international study of urban health"
    summary = (
        "An independent research team compared public health responses in several "
        "cities and described its methods, findings, and practical limitations."
    )
    # An earlier round rebuilt from its sheet: today's database holds it under another ID and hash.
    rebuilt = {"_id": "round-1-id", "title": title, "summary": summary, "content_hash": "round-1-hash"}
    documents = [article_doc("same-story", topic, title=title, summary=summary), article_doc("old-gold", topic)]
    result = sampling.sample(
        FakeArticles(documents), taxonomy, cut=CUT, per_class=2, scan_limit=50, seed=3,
        old_ids=frozenset({"old-gold", "absent-gold"}), source_ids=frozenset({"source-1"}),
        prior_docs=[rebuilt],
    )
    assert result.selected == ()
    assert result.skipped["prior_near_duplicate"] == 1
    assert result.old_documents_found == 1


class FakeClient:
    def __init__(self, _uri):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_database(self, _name):
        return SimpleNamespace(get_collection=lambda name: name)


def test_default_export_excludes_earlier_rounds_by_text_and_current_id(tmp_path, monkeypatch, taxonomy):
    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path / "data")
    run = cli.DATA_ROOT / "round-1"
    run.mkdir(parents=True)
    (run / "selection.jsonl").write_text(
        json.dumps({"article_id": "old-id", "content_hash": "h1"}) + "\n", encoding="utf-8"
    )
    with (run / "labels-01.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["article_id", "title", "summary", "label", "notes"])
        writer.writeheader()
        writer.writerow({"article_id": "old-id", "title": "A story", "summary": "Its summary",
                         "label": "sport", "notes": ""})
    (run / "current-ids.jsonl").write_text(
        json.dumps({"article_id": "old-id", "current_id": "new-id"}) + "\n", encoding="utf-8"
    )
    gold = run / "gold.jsonl"
    gold.write_text(json.dumps({
        "article_id": "old-id", "topic": "sport",
        "label_source": "human", "taxonomy_version": taxonomy.version,
    }) + "\n", encoding="utf-8")
    captured = {}

    def stop(_collection, _taxonomy, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before writing")

    monkeypatch.setattr(cli, "sample", stop)
    monkeypatch.setattr(cli, "local_uri", lambda: "mongodb://localhost:27017/news")
    monkeypatch.setattr(cli, "MongoClient", FakeClient)
    monkeypatch.setattr(cli, "approved_source_ids", lambda *_: frozenset({"source-1"}))
    monkeypatch.setattr(cli, "approved_feed_urls", lambda: frozenset())
    monkeypatch.setattr(cli, "old_gold_ids", lambda: frozenset())
    monkeypatch.setattr(cli.os, "umask", lambda _mask: 0)
    args = SimpleNamespace(cut="2026-11-10T00:00:00+00:00", out=cli.DATA_ROOT / "new", seed=1,
                           per_class=200, scan_limit=26000, reviewed_gold=[gold])
    with pytest.raises(RuntimeError, match="stop"):
        cli.export(args)
    assert captured["prior_candidates"] == frozenset({"old-id", "new-id"})
    assert [doc["_id"] for doc in captured["prior_docs"]] == ["old-id"]
