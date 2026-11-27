"""Labelling sheets: blind by construction, and validated on the way back in."""

from __future__ import annotations

import csv
import random
from collections import Counter

import pytest

from newsml import annotate
from newsml.annotate import ENCODING


def _articles(make_article, count=40):
    return [
        make_article(f"a{i:03d}", source_id=f"src-{i % 5}", source_name=f"Source {i % 5}", minutes=i * 30)
        for i in range(count)
    ]


def _read(path):
    with path.open("r", encoding=ENCODING, newline="") as handle:
        return list(csv.DictReader(handle))


def test_sheet_never_reveals_the_source_or_url(tmp_path, make_article):
    """The blindness guarantee. A visible source name turns labelling into
    transcription, and the feed URLs contain the section name outright."""
    sheets = annotate.write_sheets(_articles(make_article, 8), tmp_path)
    header = _read(sheets[0])[0].keys()

    assert set(header) == set(annotate.COLUMNS)
    assert "source_name" not in header and "url" not in header

    body = sheets[0].read_text(encoding=ENCODING)
    assert "Source 0" not in body and "example.test" not in body


def test_label_column_is_empty_for_the_annotator(tmp_path, make_article):
    rows = _read(annotate.write_sheets(_articles(make_article, 6), tmp_path)[0])
    assert all(row["label"] == "" for row in rows)


def test_shards_partition_the_sample_with_a_shared_overlap(tmp_path, make_article):
    articles = _articles(make_article, 40)
    sheets = annotate.write_sheets(articles, tmp_path, shards=4, overlap=8)

    assert len(sheets) == 4
    per_sheet = [{row["article_id"] for row in _read(sheet)} for sheet in sheets]

    shared = set.intersection(*per_sheet)
    assert len(shared) == 8, "the overlap block must appear in every sheet"

    everything = set.union(*per_sheet)
    assert everything == {a.id for a in articles}

    # Outside the overlap, no article is labelled twice.
    once = [aid for aid in everything if sum(aid in s for s in per_sheet) == 1]
    assert len(once) == len(articles) - 8


def test_export_is_reproducible(tmp_path, make_article):
    articles = _articles(make_article, 20)
    first = annotate.write_sheets(articles, tmp_path / "a", shards=2, overlap=4, seed=7)
    second = annotate.write_sheets(articles, tmp_path / "b", shards=2, overlap=4, seed=7)

    for left, right in zip(first, second, strict=True):
        assert left.read_text(encoding=ENCODING) == right.read_text(encoding=ENCODING)


def test_sample_covers_every_source(make_article):
    sample = annotate.choose_sample(_articles(make_article, 50), size=10, seed=1)
    assert len({a.source_id for a in sample}) == 5


def test_sample_takes_one_article_per_story_group(make_article):
    articles = _articles(make_article, 20)
    group_of = {a.id: ("dupes" if i < 10 else a.id) for i, a in enumerate(articles)}

    sample = annotate.choose_sample(articles, size=20, seed=1, group_of=group_of)
    assert len(sample) == 11, "the ten duplicates should contribute one article"


def test_summary_newlines_do_not_break_the_row(tmp_path, make_article):
    article = make_article("a1", summary="First line.\nSecond line,\twith a tab.")
    rows = _read(annotate.write_sheets([article], tmp_path)[0])
    assert rows[0]["summary"] == "First line. Second line, with a tab."


def _sheet(tmp_path, rows, name="sheet.csv"):
    path = tmp_path / name
    with path.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(annotate.COLUMNS)
        writer.writerows(rows)
    return path


def test_reads_back_valid_labels(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", "sport", ""], ["a2", "t", "s", "politics", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert not problems
    assert {(lbl.article_id, lbl.topic) for lbl in labels} == {("a1", "sport"), ("a2", "politics")}


def test_accepts_the_capitalisation_a_spreadsheet_introduces(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", " Sport ", ""], ["a2", "t", "s", "Crime-Justice", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert not problems
    assert {lbl.topic for lbl in labels} == {"sport", "crime_justice"}


def test_rejects_a_value_that_is_not_a_class(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", "sprot", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert not labels
    assert problems[0].row == 2 and "sprot" in problems[0].detail


def test_unsorted_is_accepted_as_an_honest_answer(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", "unsorted", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert not problems and labels[0].topic == taxonomy.unsorted


def test_blank_labels_are_skipped_not_errors(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", "", ""], ["a2", "t", "s", "sport", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert not problems and len(labels) == 1


def test_unknown_article_id_is_reported(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["ghost", "t", "s", "sport", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy, known_ids=frozenset({"a1"}))

    assert not labels and "not in the corpus" in problems[0].detail


def test_duplicate_rows_are_reported(tmp_path, taxonomy):
    path = _sheet(tmp_path, [["a1", "t", "s", "sport", ""], ["a1", "t", "s", "politics", ""]])
    labels, problems = annotate.read_sheet(path, taxonomy)

    assert len(labels) == 1 and "duplicate" in problems[0].detail


def test_a_sheet_missing_the_label_column_fails_loudly(tmp_path, taxonomy):
    path = tmp_path / "broken.csv"
    with path.open("w", encoding=ENCODING, newline="") as handle:
        csv.writer(handle).writerows([["article_id", "title"], ["a1", "t"]])

    labels, problems = annotate.read_sheet(path, taxonomy)
    assert not labels and "missing column" in problems[0].detail


def test_disagreement_between_annotators_is_detected(taxonomy):
    from newsml.labels import Label, LabelSource

    labels = [
        Label("a1", "sport", LabelSource.HUMAN, "riaz"),
        Label("a1", "politics", LabelSource.HUMAN, "friend"),
        Label("a2", "sport", LabelSource.HUMAN, "riaz"),
        Label("a2", "sport", LabelSource.HUMAN, "friend"),
    ]
    assert annotate.disagreements(labels) == {"a1": {"sport", "politics"}}


def test_guide_lists_every_class_and_the_escape_hatch(tmp_path, taxonomy):
    guide = annotate.write_guide(taxonomy, tmp_path / "guide.md").read_text(encoding="utf-8")

    for topic in taxonomy.classes:
        assert f"`{topic.id}`" in guide
    assert f"`{taxonomy.unsorted}`" in guide


def test_guide_carries_the_tie_breaks(tmp_path, taxonomy):
    guide = annotate.write_guide(taxonomy, tmp_path / "guide.md").read_text(encoding="utf-8")

    for rule in annotate.TIE_BREAKS:
        assert rule in guide


def _labels_from(sheets, taxonomy):
    return [lbl for p in sheets for lbl in annotate.read_sheet(p, taxonomy, annotator=p.stem)[0]]


def test_only_disputed_articles_reach_the_adjudication_sheet(tmp_path, taxonomy):
    sheets = [
        _sheet(tmp_path, [["a1", "T1", "S1", "sport", ""], ["a2", "T2", "S2", "health", ""]], "s1.csv"),
        _sheet(tmp_path, [["a1", "T1", "S1", "politics", ""], ["a2", "T2", "S2", "health", ""]], "s2.csv"),
    ]
    disputed = annotate.conflicts(_labels_from(sheets, taxonomy), annotate.read_sheet_texts(sheets))

    assert [c.article_id for c in disputed] == ["a1"]
    assert (disputed[0].title, disputed[0].summary) == ("T1", "S1")


def test_votes_are_ordered_by_how_often_each_label_was_chosen(tmp_path, taxonomy):
    sheets = [
        _sheet(tmp_path, [["a1", "T", "S", topic, ""]], f"s{index}.csv")
        for index, topic in enumerate(("politics", "sport", "sport"))
    ]
    disputed = annotate.conflicts(_labels_from(sheets, taxonomy), annotate.read_sheet_texts(sheets))

    assert disputed[0].votes == (("sport", 2), ("politics", 1))
    assert disputed[0].rendered_votes == "sport x2 | politics x1"


def test_adjudication_sheet_shows_the_votes_but_leaves_the_ruling_blank(tmp_path):
    conflict = annotate.Conflict("a1", "T", "S", (("sport", 2), ("politics", 1)))
    row = _read(annotate.write_adjudication_sheet([conflict], tmp_path / "adjudicate.csv"))[0]

    assert row["votes"] == "sport x2 | politics x1"
    assert row["label"] == ""


def test_a_filled_adjudication_sheet_parses_as_labels(tmp_path, taxonomy):
    path = tmp_path / "adjudicate.csv"
    with path.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(annotate.ADJUDICATION_COLUMNS)
        writer.writerow(["a1", "T", "S", "sport x2 | politics x1", "sport", "clearer on rule 8"])

    labels, problems = annotate.read_sheet(path, taxonomy, annotator="adjudicated")

    assert not problems
    assert (labels[0].topic, labels[0].detail) == ("sport", "adjudicated")


def _gold(counts: dict[str, int]) -> dict[str, str]:
    return {f"{topic}-{i}": topic for topic, n in counts.items() for i in range(n)}


def test_split_gold_puts_every_label_on_exactly_one_side():
    gold = _gold({"sport": 40, "politics": 24, "conflict_war": 8})
    train, scoring = annotate.split_gold(gold)

    assert not set(train) & set(scoring)
    assert set(train) | set(scoring) == set(gold)


def test_split_gold_scores_a_share_of_every_class_not_of_the_corpus():
    """A uniform draw could take every rare label at once; stratifying cannot."""
    gold = _gold({"sport": 40, "politics": 24, "conflict_war": 8})
    _, scoring = annotate.split_gold(gold, eval_share=0.25)

    assert Counter(scoring.values()) == {"sport": 10, "politics": 6, "conflict_war": 2}


def test_split_gold_lets_a_class_too_small_to_score_still_teach():
    train, scoring = annotate.split_gold(_gold({"conflict_war": 3}), eval_share=0.25)

    assert scoring == {}
    assert len(train) == 3


def test_split_gold_is_reproducible():
    gold = _gold({"sport": 40, "politics": 24})

    assert annotate.split_gold(gold, seed=7) == annotate.split_gold(gold, seed=7)
    assert annotate.split_gold(gold, seed=7) != annotate.split_gold(gold, seed=8)


@pytest.mark.parametrize("share", [0.0, 1.0, -0.1, 1.5])
def test_split_gold_rejects_a_share_that_is_not_a_share(share):
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        annotate.split_gold({"a1": "sport"}, eval_share=share)


SPORT = "India beat Australia by six wickets chasing 240 in the fourth innings at Galle"
WAR = "Air strikes hit the northern province as the ceasefire talks collapse in the capital"

_WORDS = {
    "wr": "airstrike ceasefire shelling militants insurgents artillery troops refugees"
          " frontline offensive truce convoy battalion siege ammunition evacuation".split(),
    "sp": "wickets innings striker penalty tournament semifinal medal dressage"
          " transfer batsman midfielder knockout aggregate sprinter pavilion coach".split(),
}


def _targetable(make_article, each=120):
    """Two topics with distinct vocabulary, and real variety inside each one.

    Deliberately far larger than the total demand: every leaf class asks for a
    quota, so a small pool is exhausted by the classes that have no examples and
    the retrieval under test never gets a fair turn. Articles within a topic must
    also differ from each other, or the near-duplicate guard correctly refuses
    them and the test is measuring the wrong thing.
    """
    articles, texts = [], {}
    for i in range(each):
        for tag, pool in _WORDS.items():
            rng = random.Random(f"{tag}{i}")
            body = " ".join(rng.sample(pool, 6)) + f" reported on day {i}"
            article = make_article(f"{tag}{i:03d}", title=body, summary="")
            articles.append(article)
            texts[article.id] = body
    return articles, texts


def test_targeted_sample_finds_articles_like_the_ones_a_class_already_has(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {f"wr{i:03d}": "conflict_war" for i in range(3)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=8, seeds=seeds, random_share=0.0
    )

    found = [a.id for a in sample.articles if sample.retrieved_for[a.id] == "conflict_war"]
    assert found, "the rare class was not served at all"
    assert all(a.startswith("wr") for a in found), f"retrieval pulled the wrong topic: {found}"


def test_targeted_sample_never_re_labels_an_article_that_already_has_a_label(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {f"wr{i:03d}": "conflict_war" for i in range(3)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=8, seeds=seeds, random_share=0.0
    )

    assert set(seeds).isdisjoint({a.id for a in sample.articles})


def test_a_class_that_already_has_enough_is_not_asked_for_again(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {f"sp{i:03d}": "sport" for i in range(10)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=10, seeds=seeds, random_share=0.0
    )

    assert "sport" not in sample.asked_for
    assert "sport" not in sample.quota


def test_a_short_class_retrieves_more_candidates_than_the_gap(make_article, taxonomy):
    """Retrieval is roughly half right, so asking for the gap yields half of it."""
    articles, texts = _targetable(make_article)
    seeds = {f"wr{i:03d}": "conflict_war" for i in range(40)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=60, seeds=seeds, random_share=0.0, max_similarity=1.0
    )

    assert sample.quota["conflict_war"] == 20, "the gap should be the shortfall in labels"
    assert sample.asked_for["conflict_war"] >= 20, "no allowance was made for retrieval being wrong"


def test_the_over_ask_is_capped_so_one_class_cannot_eat_the_pool(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {f"wr{i:03d}": "conflict_war" for i in range(40)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=60, seeds=seeds,
        random_share=0.0, min_precision=0.5, max_similarity=1.0,
    )

    assert sample.asked_for["conflict_war"] <= 40, "the min_precision cap did not hold"


@pytest.mark.parametrize("bad", [0.0, -0.2, 1.5])
def test_min_precision_must_be_a_rate(bad, make_article, taxonomy):
    articles, texts = _targetable(make_article, each=4)
    with pytest.raises(ValueError, match="min_precision"):
        annotate.choose_targeted_sample(
            articles, texts, taxonomy, per_class=3, seeds={"wr000": "conflict_war"}, min_precision=bad
        )


def test_excluded_class_is_never_targeted_even_when_short(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {f"wr{i:03d}": "conflict_war" for i in range(3)}

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=8, seeds=seeds, random_share=0.0,
        exclude=["conflict_war"],
    )

    assert "conflict_war" not in sample.quota
    assert "conflict_war" not in sample.asked_for


def test_targeted_sample_reports_what_the_corpus_could_not_supply(make_article, taxonomy):
    articles, texts = _targetable(make_article)

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=500, seeds={"wr000": "conflict_war"}, random_share=0.0
    )

    assert sample.shortfall, "asking for more than exists reported no shortfall"
    assert len(sample.articles) <= len(articles)


def test_targeted_sample_keeps_a_random_slice(make_article, taxonomy):
    articles, texts = _targetable(make_article)

    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=5, seeds={"wr000": "conflict_war"}, random_share=0.25
    )

    assert sample.asked_for["random"] > 0


def test_the_sheet_never_reveals_which_class_an_article_was_retrieved_for(tmp_path, make_article, taxonomy):
    """A labeller shown a proposed class agrees with it, which would fake the labels."""
    articles, texts = _targetable(make_article)
    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=6, seeds={"wr000": "conflict_war"}, random_share=0.0
    )

    written = annotate.write_sheets(sample.articles, tmp_path, shards=1)
    body = written[0].read_text(encoding=ENCODING)

    assert "conflict_war" not in body
    assert set(_read(written[0])[0]) == set(annotate.COLUMNS)


def test_targeted_sample_is_reproducible(make_article, taxonomy):
    articles, texts = _targetable(make_article)
    seeds = {"wr000": "conflict_war"}
    twice = [
        annotate.choose_targeted_sample(articles, texts, taxonomy, per_class=6, seeds=seeds, seed=3)
        for _ in range(2)
    ]

    assert [a.id for a in twice[0].articles] == [a.id for a in twice[1].articles]


def test_one_heavily_covered_story_cannot_fill_a_class_quota(make_article, taxonomy):
    """Six newsrooms rewording one settlement is one story's worth of information."""
    retold = "TikTok agrees to pay $400 million to settle the children privacy lawsuit"
    articles, texts = _targetable(make_article)
    for i in range(12):
        article = make_article(f"dup{i:02d}", title=f"{retold} number {i}", summary="")
        articles.append(article)
        texts[article.id] = f"{retold} number {i}"

    seeds = {"dup00": "technology", "dup01": "technology"}
    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=8, seeds=seeds, random_share=0.0, max_similarity=0.5
    )

    picked = [a.id for a in sample.articles if sample.retrieved_for[a.id] == "technology"]
    assert sum(a.startswith("dup") for a in picked) <= 1, f"the same story was picked repeatedly: {picked}"


def test_the_publishers_own_tag_pulls_an_article_towards_its_class(make_article, taxonomy):
    """Every article here has the same bland text, so only the tag can separate them.

    `badminton` is not in `category_map`; the pull comes from it co-occurring with
    the seed articles, which is the point — no hand-mapping is needed.
    """
    bland = "The organisers confirmed the schedule after a meeting that ran late into the evening"
    articles, texts = [], {}

    def _add(article_id, tags):
        article = make_article(article_id, title=f"{bland} {article_id}", summary="", categories=tags)
        articles.append(article)
        texts[article.id] = f"{bland} {article_id}"

    for i in range(6):
        _add(f"seed{i}", ("badminton",))
    for i in range(60):
        _add(f"tagged{i:02d}", ("badminton",))
        _add(f"bare{i:02d}", ())

    seeds = {f"seed{i}": "sport" for i in range(6)}
    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=7, seeds=seeds, random_share=0.0, max_similarity=1.0
    )

    picked = [a.id for a in sample.articles if sample.retrieved_for[a.id] == "sport"]
    assert picked, "sport was not served at all"
    assert all(a.startswith("tagged") for a in picked), f"the untagged twin ranked just as high: {picked}"


def test_a_place_tag_is_never_used_to_rank(make_article, taxonomy):
    """`india` outnumbers every real topic here; ranking on it finds where, not what."""
    article = make_article("g1", title="A quiet day", summary="", categories=("india", "opinion", "cricket"))

    folded = annotate._with_topical_categories(article, {"g1": "A quiet day"}, taxonomy)

    assert "cricket" in folded
    assert "india" not in folded and "opinion" not in folded


# A section feed in taxonomy.yaml's feed_topics, and a general desk that is not.
SECTIONED = "The Guardian — Sport"
GENERAL_DESK = "India Today"


def test_a_source_carrying_its_own_topic_label_is_recognised(make_article, taxonomy):
    assert not annotate._from_unlabelled_desk(make_article(source_name=SECTIONED), taxonomy)
    assert annotate._from_unlabelled_desk(make_article(source_name=GENERAL_DESK), taxonomy)


def test_desk_prior_is_smoothed_so_a_thin_class_cannot_claim_certainty():
    """14 of 14 is not 100%: unsmoothed it becomes a hard filter, not a preference."""
    desks = {f"a{i}": True for i in range(14)}
    prior = annotate._desk_prior({a: "politics" for a in desks}, desks, base=0.5)

    assert 0.8 < prior["politics"] < 1.0
    assert prior["a class never seen"] == 0.5


def test_a_class_only_ever_found_on_general_desks_is_hunted_there(make_article, taxonomy):
    """Identical text on both kinds of source, so only the desk prior can separate them."""
    bland = "Officials said the situation was being monitored closely and would be reviewed"
    articles, texts = [], {}

    def _add(article_id, source_name):
        article = make_article(article_id, title=f"{bland} {article_id}", summary="",
                               categories=(), source_name=source_name)
        articles.append(article)
        texts[article.id] = f"{bland} {article_id}"

    for i in range(8):
        _add(f"seed{i}", GENERAL_DESK)
    for i in range(60):
        _add(f"desk{i:02d}", GENERAL_DESK)
        _add(f"section{i:02d}", SECTIONED)

    seeds = {f"seed{i}": "politics" for i in range(8)}
    sample = annotate.choose_targeted_sample(
        articles, texts, taxonomy, per_class=9, seeds=seeds, random_share=0.0, max_similarity=1.0
    )

    picked = [a.id for a in sample.articles if sample.retrieved_for[a.id] == "politics"]
    assert picked, "the class was not served at all"
    assert all(a.startswith("desk") for a in picked), f"hunted the wrong kind of source: {picked}"
