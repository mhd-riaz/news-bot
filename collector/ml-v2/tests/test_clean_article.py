"""Field-separate cleaning, and the navigation-body guard."""

from newsmlv2.clean import clean_article, is_navigation

NAV = "\n".join(["Home", "Sport", "Weather", "iPlayer", "Sounds", "Bitesize",
                 "CBeebies", "Food", "Business", "Technology", "Health", "Culture"])


class TestNavigationGuard:
    def test_a_scraped_menu_is_recognised(self):
        assert is_navigation(NAV)

    def test_real_prose_is_not(self):
        prose = "\n".join(
            [
                "The minister told parliament that the new policy would take effect in April.",
                "Opposition members walked out during the debate, calling the timetable rushed.",
                "A vote is expected next week once the committee reports back on the costings.",
            ]
        )
        assert not is_navigation(prose)

    def test_a_short_body_is_never_flagged(self):
        """NDTV files legitimate one-line bodies; those must survive."""
        assert not is_navigation("Police said the man was arrested on Monday.")

    def test_a_headline_stack_under_the_line_floor_is_left_alone(self):
        assert not is_navigation("Home\nSport\nWeather")


class TestCleanArticle:
    def test_the_three_fields_stay_separate(self):
        title, summary, body = clean_article("The headline", "The dek.", "The body text.")
        assert (title.text, summary.text, body.text) == ("The headline", "The dek.", "The body text.")

    def test_only_the_body_gets_dateline_extraction(self):
        """An all-caps headline looks exactly like a dateline; it must not be eaten."""
        title, _, body = clean_article("BREAKING: Bill passes", "", "NEW DELHI: Parliament met.")
        assert title.text == "BREAKING: Bill passes"
        assert body.text == "Parliament met."
        assert body.dateline_city == "NEW DELHI"

    def test_a_navigation_body_is_dropped_but_the_article_survives(self):
        """Falling back to title+summary beats rejecting a perfectly good headline."""
        title, summary, body = clean_article("Inside Health", "A dek.", NAV)
        assert not body.text
        assert title.text == "Inside Health"
        assert summary.text == "A dek."

    def test_per_source_boilerplate_applies_to_the_body_only(self):
        title, _, body = clean_article(
            "Tags:", "", "Real reporting.\nTags:",
            boilerplate=frozenset({"tags:"}),
        )
        assert body.text == "Real reporting."
        # The title is cleaned by the shared rules, which already treat "Tags:" as chrome.
        assert title.text == ""

    def test_missing_fields_produce_empty_strings_not_none(self):
        title, summary, body = clean_article("Headline", "", "")
        assert (summary.text, body.text) == ("", "")
        assert not summary and not body
