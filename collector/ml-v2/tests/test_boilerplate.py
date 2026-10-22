"""Boilerplate discovery, and specifically the author-bio hole v1 had."""

from newsmlv2.boilerplate import LONG_LINE_WORDS, as_lookup, discover

BIO = (
    "Andrew Zinin holds a master's in physics with research experience and has been a "
    "long-time science news enthusiast who plays badminton at the weekend and has "
    "covered space missions, particle physics and climate modelling for over a decade "
    "across several outlets before joining the science desk full time last year."
)


def _docs(source: str, n: int, extra: str = "", *, every: int = 1):
    """n articles from one source, each with its own reporting plus an optional line."""
    for i in range(n):
        lines = [f"Unique reporting about subject number {i} and its consequences."]
        if extra and i % every == 0:
            lines.append(extra)
        yield source, "\n".join(lines)


def test_a_repeated_short_line_is_found():
    found = discover(_docs("The Indian Express", 40, "Story continues below this ad"))
    assert [c.line for c in found] == ["Story continues below this ad"]
    assert found[0].doc_count == 40
    assert found[0].doc_fraction == 1.0


def test_author_bios_are_caught_which_v1_could_not():
    """v1 skipped lines over 25 words, so a multi-sentence bio was never a candidate.

    Bios are the worst case: they are long, repeated, and carry the wrong topic.
    """
    assert len(BIO.split()) > LONG_LINE_WORDS
    found = discover(_docs("Phys.org", 40, BIO))
    assert [c.line for c in found] == [BIO]
    assert found[0].is_long


def test_a_long_line_needs_stronger_evidence_than_a_short_one():
    """Repetition, not brevity, is what separates a template from real reporting."""
    occasional = list(_docs("Some Paper", 40, BIO, every=10))          # 10% of articles
    assert not discover(occasional), "10% is below the long-line bar"

    frequent = list(_docs("Some Paper", 40, BIO, every=2))             # 50% of articles
    assert [c.line for c in discover(frequent)] == [BIO]


def test_a_line_below_the_document_floor_is_ignored():
    found = discover(_docs("Small Source", 40, "Rare footer", every=20))  # 2 of 40
    assert not found


def test_a_source_with_too_few_articles_is_skipped():
    """A fraction computed over 5 articles says nothing."""
    assert not discover(_docs("Tiny Source", 5, "Repeated line"))


def test_one_article_cannot_vote_twice_for_its_own_footer():
    repeated_within_one = [("Solo Source", "Footer\n" * 30)] + list(_docs("Solo Source", 39))
    assert not discover(repeated_within_one)


def test_lookup_is_case_folded_for_clean():
    found = discover(_docs("The Hindu", 40, "Also Read"))
    assert as_lookup(found) == {"The Hindu": frozenset({"also read"})}


def test_sources_do_not_share_boilerplate():
    docs = list(_docs("A", 40, "A footer")) + list(_docs("B", 40, "B footer"))
    lookup = as_lookup(discover(docs))
    assert lookup["A"] == frozenset({"a footer"})
    assert lookup["B"] == frozenset({"b footer"})
