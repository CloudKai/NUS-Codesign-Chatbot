"""UI helpers for the Sources panel."""

from ui.sources import _sort_course_sources_by_name


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
