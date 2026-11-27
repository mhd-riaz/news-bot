"""Cleaning regressions.

Each test here stands for a failure that actually happened in v1 and cost real time.
They are the reason this package is a rewrite rather than a fresh start.
"""

from newsmlv2.clean import clean, normalise


class TestNormalise:
    def test_nfkc_alone_does_not_fold_curly_quotes_or_dashes(self):
        """The trap: two copies of one wire story differing only in punctuation.

        Without an explicit fold they never compare equal, so near-duplicate detection
        misses them and the same story trains and tests.
        """
        assert normalise("India\u2019s \u201cbig\u201d win \u2014 again") == "India's \"big\" win - again"

    def test_non_breaking_and_thin_spaces_become_ordinary_spaces(self):
        assert normalise("Rs\u00a05,000\u2009crore") == "Rs 5,000 crore"

    def test_control_characters_are_removed(self):
        assert normalise("clean\x00text\x07here") == "cleantexthere"

    def test_runs_of_blank_lines_collapse(self):
        assert normalise("a\n\n\n\n\nb") == "a\n\nb"

    def test_empty_input_is_empty_output_never_the_string_none(self):
        assert normalise("") == ""


class TestFurniture:
    def test_the_single_most_common_line_in_the_corpus_is_removed(self):
        """`Story continues below this ad` sits in 75% of Indian Express bodies."""
        out = clean("Real reporting here.\nStory continues below this ad\nMore reporting.")
        assert "Story continues" not in out.text
        assert "Real reporting here." in out.text
        assert "More reporting." in out.text

    def test_india_today_and_phys_org_markers_are_removed(self):
        out = clean("Body text.\n- Ends\nPublished On:\nWho's behind this story?")
        assert out.text == "Body text."

    def test_a_furniture_phrase_inside_real_prose_survives(self):
        """Anchored patterns only. The word 'advertisement' can be the story."""
        text = "The advertisement watchdog fined the firm for a misleading claim."
        assert clean(text).text == text

    def test_read_more_as_a_sentence_is_not_chrome(self):
        text = "Read more about the policy in the ministry's own filing, published Monday."
        assert clean(text).text == text

    def test_per_source_boilerplate_is_removed_case_insensitively(self):
        out = clean(
            "Story.\nCheck out more of our cartoons here .",
            boilerplate=frozenset({"check out more of our cartoons here ."}),
        )
        assert out.text == "Story."


class TestWireAndDateline:
    def test_agency_input_line_is_removed_and_recorded(self):
        out = clean("The minister spoke.\n(With inputs from PTI)")
        assert out.text == "The minister spoke."
        assert out.wire_agency == "PTI"

    def test_dateline_city_leaves_the_text_and_becomes_a_field(self):
        """Place names are the shortcut Phase D0 removes; the city is not topic signal."""
        out = clean("VIJAYAWADA: Vice-President launched the seed.", dateline=True)
        assert out.text == "Vice-President launched the seed."
        assert out.dateline_city == "VIJAYAWADA"

    def test_dateline_with_date_and_agency_is_parsed(self):
        out = clean("NEW DELHI, Aug 24 (PTI) - Parliament met today.", dateline=True)
        assert out.text == "Parliament met today."
        assert out.dateline_city == "NEW DELHI"
        assert out.wire_agency == "PTI"

    def test_a_headline_is_never_scanned_for_a_dateline(self):
        """dateline=False by default: an all-caps headline would match the pattern."""
        title = "BREAKING: Parliament passes the bill"
        assert clean(title).text == title


class TestShape:
    def test_word_count_reflects_the_cleaned_text(self):
        assert clean("Story continues below this ad\none two three").word_count == 3

    def test_a_body_that_is_entirely_furniture_cleans_to_nothing(self):
        """Deccan Herald `DH Toon` pages: the whole body is a link to more cartoons.

        Admission uses this to reject them; v1 kept two such articles.
        """
        out = clean(
            "Check out more of our cartoons here .",
            boilerplate=frozenset({"check out more of our cartoons here ."}),
        )
        assert not out
        assert out.text == ""
