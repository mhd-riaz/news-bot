"""Near-duplicate grouping, and the guard that makes it beat v1's precision ceiling."""

from datetime import UTC, datetime, timedelta

from newsmlv2.dedup import Doc, Pair, candidate_pairs, group, is_recurring_template

DAY = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)

WIRE = (
    "Twelve people died and forty were injured when floodwaters swept through the "
    "district overnight, officials said, as rescue teams worked to reach villages "
    "cut off by the rising river."
)
REWORDED = (
    "Officials said twelve people were killed and forty injured after floodwaters "
    "swept through the district overnight, with rescue teams trying to reach villages "
    "cut off by the rising river."
)
UNRELATED = (
    "The central bank held interest rates steady on Tuesday, citing easing inflation "
    "and steady growth, in a decision that markets had widely expected ahead of the "
    "quarterly policy review."
)


def _doc(id_: str, text: str, source: str = "The Hindu", when: datetime = DAY) -> Doc:
    return Doc(id=id_, text=text, publisher=source, published_at=when)


# A varied corpus, and it has to be varied for two separate reasons. Identical fillers
# collapse to one vector and match each other at 1.0; and `min_df=2` drops any word that
# appears in only one document, so a test article whose vocabulary is unique to itself
# becomes an empty vector and matches everything. Both flood and market words therefore
# have to recur here, or the two test articles cannot be told apart.
FILLER = [
    "The district council approved a budget for new roads and storm drains this year.",
    "Councillors debated drainage work in low lying wards before the monsoon arrives.",
    "Rescue teams reached two villages by boat after the river rose during the night.",
    "Officials warned of more rain and said water levels were still rising downstream.",
    "The central bank reviewed its policy on inflation and growth during the quarter.",
    "Traders said the bank would hold rates steady and markets had expected as much.",
    "Analysts expect inflation to ease further before the next quarterly policy review.",
    "The finance ministry said growth remained steady despite weak export demand.",
    "A state highway accident left four injured and they were taken to hospital.",
    "Doctors said the injured were stable and would be discharged later this week.",
    "The health department opened a new clinic in the ward serving nearby villages.",
    "Teachers protested outside the education office over delayed salary payments.",
    "The school board approved a new curriculum for senior secondary students.",
    "A local team won the district cricket tournament after a close final on Sunday.",
    "The football club signed two players before the transfer window closed.",
    "Power supply was restored to the district after engineers repaired the line.",
    "The water board said supply would be cut for a day during pipeline repairs.",
    "Farmers said crop damage from the rain would affect the season's harvest.",
    "The transport department added buses on the route serving the new township.",
    "Police arrested three people in connection with a theft at a construction site.",
]


def _filler(n: int) -> list[Doc]:
    return [_doc(f"z{i:03d}", FILLER[i % len(FILLER)]) for i in range(min(n, len(FILLER)))]


class TestBlocking:
    def test_a_reworded_copy_of_the_same_story_scores_highly(self):
        docs = [_doc("a", WIRE), _doc("b", REWORDED), *_filler(20)]
        pairs = {(p.a, p.b): p.score for p in candidate_pairs(docs)}
        assert pairs[("a", "b")] > 0.5

    def test_unrelated_articles_score_low(self):
        docs = [_doc("a", WIRE), _doc("b", UNRELATED), *_filler(20)]
        pairs = {(p.a, p.b): p.score for p in candidate_pairs(docs)}
        assert pairs.get(("a", "b"), 0.0) < 0.3

    def test_pairs_are_returned_unthresholded_so_a_cut_can_be_calibrated(self):
        docs = [_doc("a", WIRE), _doc("b", UNRELATED), *_filler(20)]
        assert any(p.score < 0.5 for p in candidate_pairs(docs))

    def test_an_empty_or_single_corpus_is_handled(self):
        assert candidate_pairs([]) == ()
        assert candidate_pairs([_doc("a", WIRE)]) == ()


class TestTemplateGuard:
    def test_same_source_far_apart_is_a_recurring_feature(self):
        """Two instalments of a weekly bulletin, not one story. v1's largest FP class."""
        a = _doc("a", WIRE, "The Hindu", DAY)
        b = _doc("b", REWORDED, "The Hindu", DAY + timedelta(days=8))
        assert is_recurring_template(a, b)

    def test_the_guard_is_keyed_on_publisher_not_section_feed(self):
        """One `Watch:` series runs across The Hindu's Science, Business and Sport feeds."""
        a = _doc("a", WIRE, "The Hindu", DAY)
        b = _doc("b", REWORDED, "The Hindu", DAY + timedelta(days=3))
        assert is_recurring_template(a, b)

    def test_same_source_same_day_is_not_a_template(self):
        a = _doc("a", WIRE, "The Hindu", DAY)
        b = _doc("b", REWORDED, "The Hindu", DAY + timedelta(hours=3))
        assert not is_recurring_template(a, b)

    def test_different_publishers_days_apart_is_still_syndication(self):
        """The guard must stay narrow: wire copy runs late at other mastheads."""
        a = _doc("a", WIRE, "The Hindu", DAY)
        b = _doc("b", REWORDED, "Deccan Herald", DAY + timedelta(days=3))
        assert not is_recurring_template(a, b)

    def test_a_missing_timestamp_never_triggers_the_guard(self):
        a = Doc("a", WIRE, "The Hindu", None)
        b = _doc("b", REWORDED, "The Hindu", DAY + timedelta(days=8))
        assert not is_recurring_template(a, b)


class TestGrouping:
    def test_duplicates_share_a_group(self):
        docs = [_doc("a", WIRE), _doc("b", REWORDED), *_filler(20)]
        g = group(docs)
        assert g.group_of["a"] == g.group_of["b"]

    def test_unrelated_articles_do_not(self):
        docs = [_doc("a", WIRE), _doc("b", UNRELATED), *_filler(20)]
        g = group(docs)
        assert g.group_of["a"] != g.group_of["b"]

    def test_the_template_guard_keeps_instalments_apart(self):
        docs = [
            _doc("a", WIRE, "The Hindu", DAY),
            _doc("b", REWORDED, "The Hindu", DAY + timedelta(days=8)),
            *_filler(20),
        ]
        g = group(docs)
        assert g.group_of["a"] != g.group_of["b"]
        assert [(p.a, p.b) for p in g.rejected_as_template] == [("a", "b")]

    def test_the_group_id_is_the_smallest_member_id_so_it_is_stable(self):
        docs = [_doc("m", WIRE), _doc("a", REWORDED), *_filler(20)]
        g = group(docs)
        assert g.group_of["m"] == g.group_of["a"] == "a"

    def test_a_chain_of_similar_articles_merges_transitively(self):
        docs = [_doc("a", WIRE), _doc("b", REWORDED), _doc("c", WIRE), *_filler(20)]
        g = group(docs)
        assert len({g.group_of[x] for x in "abc"}) == 1

    def test_every_article_is_in_exactly_one_group(self):
        docs = [_doc("a", WIRE), _doc("b", REWORDED), *_filler(20)]
        g = group(docs)
        assert set(g.group_of) == {d.id for d in docs}
        assert sum(g.sizes().values()) == len(docs)

    def test_raising_the_threshold_never_creates_larger_groups(self):
        docs = [_doc("a", WIRE), _doc("b", REWORDED), *_filler(20)]
        assert group(docs, threshold=0.95).group_count >= group(docs, threshold=0.30).group_count
