"""UI helpers for the Sources panel."""

from ui.sources import _select_all_checkbox_state, _sort_course_sources_by_name


def test_select_all_checkbox_has_unchecked_indeterminate_and_checked_states() -> None:
    assert _select_all_checkbox_state(0, 3) == (False, False)
    assert _select_all_checkbox_state(1, 3) == (False, True)
    assert _select_all_checkbox_state(2, 3) == (False, True)
    assert _select_all_checkbox_state(3, 3) == (True, False)
    assert _select_all_checkbox_state(1, 0) == (False, False)


def test_course_sources_sorted_numerically() -> None:
    sources = [
        {"title": "Week 10 Storytelling.pdf"},
        {"title": "Week 2 Design.pdf"},
        {"title": "Week 1 Introduction.pdf"},
    ]
    ordered = _sort_course_sources_by_name(sources)
    assert [item["title"] for item in ordered] == [
        "Week 1 Introduction.pdf",
        "Week 2 Design.pdf",
        "Week 10 Storytelling.pdf",
    ]
