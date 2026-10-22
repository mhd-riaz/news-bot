"""Taxonomy integrity and weak-label resolution."""

from __future__ import annotations

import pytest

from newsml.labels import (
    LabelSource,
    from_categories,
    from_feed,
    from_publisher,
    is_geography_only,
    resolve,
)


def test_taxonomy_has_thirteen_groups(taxonomy):
    """The top-level decision stays at 13 no matter how many children exist:
    that is what keeps the labelling job cognitively the same size."""
    assert len(taxonomy.groups) == 13


def test_children_are_declared_under_a_real_group(taxonomy):
    group_ids = {g.id for g in taxonomy.groups}
    for topic in taxonomy.classes:
        if topic.parent:
            assert topic.parent in group_ids, f"{topic.id} has unknown parent {topic.parent}"


def test_hierarchy_is_only_two_levels_deep(taxonomy):
    """A child of a child would make the guide's two-step instruction a lie."""
    by_id = {c.id: c for c in taxonomy.classes}
    for topic in taxonomy.classes:
        if topic.parent:
            assert not by_id[topic.parent].parent, f"{topic.id} is nested three levels deep"


def test_every_class_is_documented(taxonomy):
    """Descriptions are what the labelling guide is generated from, so a blank
    one silently ships an unanswerable question to the annotators."""
    for topic in taxonomy.classes:
        assert topic.description, f"{topic.id} has no description"


def test_every_group_records_its_iptc_parent(taxonomy):
    for group in taxonomy.groups:
        assert group.iptc, f"{group.id} has no IPTC parent"


def test_class_ids_are_unique(taxonomy):
    ids = [c.id for c in taxonomy.classes]
    assert len(ids) == len(set(ids))


def test_merge_chains_terminate(taxonomy):
    """A parent cycle would hang collapse(). Assert the graph is acyclic."""
    for topic in taxonomy.classes:
        seen, current = set(), topic.id
        while current:
            assert current not in seen, f"parent cycle through {current}"
            seen.add(current)
            current = next((c.parent for c in taxonomy.classes if c.id == current), "")


def test_every_mapped_category_points_at_a_real_class(taxonomy):
    """Regression: a partial edit once left category_map pointing at classes that
    had not been declared yet, which would have produced labels for classes the
    model could never predict."""
    for value, topic in taxonomy.category_map.items():
        assert topic in taxonomy.ids, f"category {value!r} maps to unknown class {topic!r}"


def test_every_publisher_topic_points_at_a_real_class(taxonomy):
    for source, topic in taxonomy.publisher_topics.items():
        assert topic in taxonomy.ids, f"publisher {source!r} maps to unknown class {topic!r}"


def test_every_feed_topic_points_at_a_real_class(taxonomy):
    for source, topic in taxonomy.feed_topics.items():
        assert topic in taxonomy.ids, f"feed {source!r} maps to unknown class {topic!r}"


def _configured_source_names() -> set[str]:
    import yaml

    from newsml.config import SOURCES_PATH

    raw = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    return {str(s["name"]) for s in (raw.get("sources") or [])}


def test_every_feed_topic_names_a_configured_source(taxonomy):
    """The map is keyed by source name, so a rename in sources.yaml silently
    drops the label rather than failing. This is what catches that."""
    configured = _configured_source_names()
    unknown = sorted(set(taxonomy.feed_topics) - configured)
    assert not unknown, f"feed_topics names not in sources.yaml: {unknown}"


def test_every_publisher_topic_names_a_configured_source(taxonomy):
    configured = _configured_source_names()
    unknown = sorted(set(taxonomy.publisher_topics) - configured)
    assert not unknown, f"publisher_topics names not in sources.yaml: {unknown}"


def test_a_source_is_not_both_a_section_feed_and_a_publisher_prior(taxonomy):
    """The two maps carry different trust. A source in both would have its label
    accepted or held for review depending only on lookup order."""
    assert not (set(taxonomy.feed_topics) & set(taxonomy.publisher_topics))


def test_world_sections_are_not_treated_as_topics(taxonomy):
    """A world desk files whatever happened abroad, so those sections name a
    place, not a subject. Letting one in would relabel every foreign story.

    Matched on the section after the dash, not the whole name: "The Indian
    Express" contains "India" without being a geographic section.
    """
    places = {"world", "world news", "international", "india", "asia", "europe",
              "us", "uk", "americas", "africa", "middle east", "cities", "bengaluru"}
    offenders = [
        name for name in taxonomy.feed_topics
        if name.split("\u2014")[-1].strip().casefold() in places
    ]
    assert not offenders, f"geographic sections must not carry a topic: {offenders}"


def test_geography_and_categories_do_not_overlap(taxonomy):
    """A value cannot be both a place and a topic; if it were, the label would
    depend on which lookup ran first."""
    assert not (taxonomy.geography & set(taxonomy.category_map))


def test_non_topical_and_categories_do_not_overlap(taxonomy):
    """Regression: `gear / deals` was once both a technology label and affiliate
    content, so deals copy would have trained the technology class."""
    assert not (taxonomy.non_topical & set(taxonomy.category_map))


def test_collapse_is_a_no_op_now_the_taxonomy_is_flat(taxonomy):
    """There is no parent left to fold into: v4 retired the child level."""
    assert taxonomy.collapse("politics", frozenset({"politics"})) == "politics"
    assert taxonomy.collapse("technology", frozenset()) == "technology"


def test_collapse_stops_at_a_group(taxonomy):
    """A group has nowhere further to go, even when it is itself starved."""
    assert taxonomy.collapse("sport", frozenset({"sport"})) == "sport"
    assert taxonomy.collapse("politics", frozenset({"politics"})) == "politics"


@pytest.mark.parametrize("raw", ["crime_justice", "CRIME_JUSTICE", " Crime_Justice ", "crime-justice"])
def test_canonical_accepts_case_and_separator_variants(taxonomy, raw):
    assert taxonomy.canonical(raw) == "crime_justice"


def test_group_labels_are_valid_labels(taxonomy):
    """The fallback has to actually be accepted on the way back in."""
    assert taxonomy.canonical("politics") == "politics"
    assert taxonomy.canonical("crime_justice") == "crime_justice"


@pytest.mark.parametrize("raw", ["", "  ", "tech", "not_a_class", "'; DROP TABLE", "unsorted"])
def test_canonical_rejects_anything_not_a_class(taxonomy, raw):
    assert taxonomy.canonical(raw) is None


def test_publisher_label_uses_the_declared_topic(taxonomy, make_article):
    label = from_publisher(make_article(source_name="Wired"), taxonomy)
    assert label is not None and label.topic == "technology"
    assert label.source is LabelSource.PUBLISHER


def test_unknown_source_has_no_publisher_label(taxonomy, make_article):
    assert from_publisher(make_article(source_name="Some Blog"), taxonomy) is None


def test_category_label_is_independent_of_publisher_ordering(taxonomy, make_article):
    forward = from_categories(make_article(categories=("ai", "india")), taxonomy)
    reverse = from_categories(make_article(categories=("india", "ai")), taxonomy)
    assert forward is not None and forward.topic == reverse.topic == "technology"


def test_geography_only_article_yields_no_label(taxonomy, make_article):
    article = make_article(categories=("india", "karnataka", "bengaluru"))
    assert from_categories(article, taxonomy) is None
    assert is_geography_only(article, taxonomy)


def test_agreeing_signals_skip_review(taxonomy, make_article):
    article = make_article(source_name="Wired", categories=("tech",))
    candidates = [c for c in (from_publisher(article, taxonomy), from_categories(article, taxonomy)) if c]
    outcome = resolve(article.id, candidates, taxonomy)

    assert outcome.topic == "technology"
    assert outcome.agreement and not outcome.needs_review


def test_conflicting_signals_route_to_review(taxonomy, make_article):
    article = make_article(source_name="Wired", categories=("cricket",))
    candidates = [c for c in (from_publisher(article, taxonomy), from_categories(article, taxonomy)) if c]
    outcome = resolve(article.id, candidates, taxonomy)

    assert not outcome.agreement and outcome.needs_review


def test_a_lone_publisher_prior_is_not_trusted(taxonomy, make_article):
    """Measured on the pilot gold set, a lone publisher prior named the wrong
    group 42% of the time. "TikTok reaches $400M privacy settlement" arrives on
    Wired's feed and is crime_justice, not technology."""
    article = make_article(source_name="Wired", categories=())
    outcome = resolve(article.id, [from_publisher(article, taxonomy)], taxonomy)

    assert outcome.topic == "technology"
    assert outcome.needs_review


def test_a_lone_section_feed_is_trusted(taxonomy, make_article):
    """The section is a fact about the feed, not a guess about the article:
    everything on theguardian.com/sport/rss is sport."""
    article = make_article(source_name="The Guardian \u2014 Sport", categories=())
    label = from_feed(article, taxonomy)

    assert label is not None and label.source is LabelSource.FEED
    outcome = resolve(article.id, [label], taxonomy)
    assert outcome.topic == "sport" and not outcome.needs_review


def test_a_section_feed_outranks_a_conflicting_category(taxonomy, make_article):
    article = make_article(source_name="The Guardian \u2014 Sport", categories=("ai",))
    candidates = [c for c in (from_feed(article, taxonomy), from_categories(article, taxonomy)) if c]
    outcome = resolve(article.id, candidates, taxonomy)

    assert outcome.topic == "sport"
    assert outcome.needs_review, "a real conflict should still be seen by a human"


def test_a_lone_category_waits_for_a_human(taxonomy, make_article):
    article = make_article(source_name="Some Blog", categories=("cricket",))
    outcome = resolve(article.id, [from_categories(article, taxonomy)], taxonomy)
    assert outcome.topic == "sport" and outcome.needs_review


def test_no_signal_is_unsorted_and_needs_review(taxonomy, make_article):
    outcome = resolve("x", [], taxonomy)
    assert outcome.topic == taxonomy.unsorted and outcome.needs_review


def test_a_human_label_overrides_every_other_signal(taxonomy, make_article):
    from newsml.labels import Label

    article = make_article(source_name="Wired", categories=("tech",))
    candidates = [
        from_publisher(article, taxonomy),
        from_categories(article, taxonomy),
        Label(article.id, "politics", LabelSource.HUMAN, "riaz"),
    ]
    outcome = resolve(article.id, [c for c in candidates if c], taxonomy)

    assert outcome.topic == "politics"
    assert outcome.source is LabelSource.HUMAN and not outcome.needs_review
