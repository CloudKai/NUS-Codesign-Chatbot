"""Deterministic retrieval-gate tests. No model calls."""

from __future__ import annotations

from backend.retrieval_gate import retrieval_required


def test_project_reasoning_skips_retrieval() -> None:
    assert retrieval_required("I think option B is stronger.") is False
    assert retrieval_required("My users are elderly pedestrians.") is False
    assert retrieval_required("I changed the entrance location.") is False
    assert retrieval_required("Would this idea solve the problem?") is False
    assert retrieval_required("I think privacy is my biggest concern.") is False


def test_course_and_source_intent_triggers_retrieval() -> None:
    assert retrieval_required("What does lecture 3 say about accessibility?") is True
    assert (
        retrieval_required(
            "According to my uploaded report, what constraint matters most?"
        )
        is True
    )
    assert retrieval_required("Give me evidence from the selected source.") is True
    assert retrieval_required("Compare my idea against the lecture.") is True
    assert retrieval_required("WHAT DOES LECTURE 3 SAY ABOUT ACCESSIBILITY?") is True
    assert retrieval_required("What does lecture 3 say about accessibility?") is True


def test_selected_source_title_triggers_retrieval() -> None:
    assert (
        retrieval_required(
            "Please apply Week02_Accessibility.pdf to my concept.",
            selected_source_filenames=["Week02_Accessibility.pdf"],
        )
        is True
    )
    assert (
        retrieval_required(
            "How does Stakeholder Mapping Notes apply here?",
            selected_source_titles=["Stakeholder Mapping Notes"],
        )
        is True
    )


def test_punctuation_and_citation_markers() -> None:
    assert retrieval_required("Cite the source, please.") is True
    assert retrieval_required("Use [S1] here.") is True
    assert retrieval_required("Based on the PDF, what is required?") is True


def test_selected_source_factual_question_retrieves() -> None:
    assert (
        retrieval_required(
            "What quantified thermal degradation was reported?",
            selected_source_titles=["Battery cycling notes"],
            has_selected_sources=True,
        )
        is True
    )
    assert (
        retrieval_required(
            "Would this idea solve the problem?",
            selected_source_titles=["Battery cycling notes"],
            has_selected_sources=True,
        )
        is False
    )
