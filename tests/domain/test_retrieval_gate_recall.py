"""Table-driven retrieval-gate recall tests. No model calls.

This file records the Phase 13 recall fix. ``retrieval_required`` is the
compatibility bool; ``classify_retrieval_intent`` is the graded signal a
later Q&A/coaching mode hint will consume.

Before this change (imported ``retrieval_required`` on HEAD working tree):

    "What is in Week 1 lecture?"                    True  (token "lecture")
    "tell me about week 2"                          False even with selected sources
    "what does the lecture say about JTBD"          True
    "explain Jobs to Be Done from the notes"        True
    "according to the uploaded slides what matters" True
    "what did the course say about analogy"         False without sources, True with
    "summarise S1"                                  False even with selected sources
    "what does this source mean"                    True
    "I think option B is better for my users"       False
    "I changed my problem statement..."             False
"""

from __future__ import annotations

import pytest

from backend.retrieval_gate import (
    INTENT_AMBIGUOUS,
    INTENT_HIGH_CONFIDENCE_PERSONAL,
    INTENT_HIGH_CONFIDENCE_SOURCE,
    classify_retrieval_intent,
    retrieval_required,
)
from backend.specialists.routing import looks_like_course_question, select_specialist

_SELECTED = {
    "has_selected_sources": True,
    "selected_source_titles": ["Week 1 Introduction to innovation v3.pdf"],
    "selected_source_filenames": ["Week 1 Introduction to innovation v3.pdf"],
}

# (message, kwargs, expected retrieve, note)
POSITIVE: list[tuple[str, dict[str, object], str]] = [
    ("What is in Week 1 lecture?", {}, "week + lecture"),
    ("what is in week 1 lecture", {}, "no question mark, lower case"),
    ("WHAT IS IN WEEK 1 LECTURE?", {}, "all caps"),
    ("tell me about week 2", {}, "bare week N without lecture token"),
    ("Tell me about Week 2", {}, "capitalised week"),
    ("week 2", {}, "bare week token with number"),
    ("what is week two about", {}, "spelled-out week ordinal"),
    ("what does the lecture say about JTBD", {}, "lecture + concept"),
    ("What does the lecture say about JTBD?", {}, "question mark"),
    ("explain Jobs to Be Done from the notes", {}, "from the notes"),
    ("Explain jobs to be done from the notes", {}, "capitalisation"),
    ("according to the uploaded slides what matters", {}, "according to uploaded slides"),
    ("According to the uploaded slides, what matters?", {}, "punctuation"),
    ("what did the course say about analogy", {}, "the course + say"),
    ("What did the course say about analogy?", {}, "question mark"),
    ("summarise S1", {}, "bare S1"),
    ("summarize s2", {}, "bare s2 lower-case"),
    ("Use [S1] here.", {}, "bracketed label"),
    ("use [s3] please", {}, "bracketed lower-case"),
    ("what does this source mean", {}, "this source"),
    ("What does this source mean?", {}, "question mark"),
    ("cite the source please", {}, "citation"),
    ("explain Jobs to Be Done", {}, "impersonal course concept"),
    ("what is the definition of a job story", {}, "explicit definition request"),
    ("what does JTBD mean", {}, "meaning request"),
    (
        "what is the difference between a job story and a user story",
        {},
        "comparison of two course concepts",
    ),
    ("Give me evidence from the selected source.", {}, "evidence request"),
    ("Based on the PDF, what is required?", {}, "based on pdf"),
    ("Compare my idea against the lecture.", {}, "lecture wins over idea"),
    (
        "Please apply Week02_Accessibility.pdf to my concept.",
        {"selected_source_filenames": ["Week02_Accessibility.pdf"]},
        "selected filename",
    ),
    (
        "How does Stakeholder Mapping Notes apply here?",
        {"selected_source_titles": ["Stakeholder Mapping Notes"]},
        "selected title",
    ),
    ("according to the syllabus what is due", {}, "syllabus"),
    ("what do the readings say about jobs", {}, "readings"),
    ("what does reading 3 cover", {}, "reading N"),
    ("lecture 1", {}, "bare lecture N"),
    ("what is in the uploaded document", {}, "uploaded document"),
]

NEGATIVE: list[tuple[str, dict[str, object], str]] = [
    ("I think option B is better for my users", {}, "personal option"),
    ("I think option B is stronger.", {}, "existing personal fixture"),
    ("My users are elderly pedestrians.", {}, "my users"),
    ("I changed my problem statement to focus on older pedestrians", {}, "I changed"),
    ("I changed the entrance location.", {}, "I changed location"),
    ("Would this idea solve the problem?", {}, "idea solve"),
    (
        "Would this idea solve the problem?",
        dict(_SELECTED),
        "idea solve even with selected sources",
    ),
    ("I think privacy is my biggest concern.", {}, "I think"),
    ("hello", {}, "idle"),
    ("thanks", {}, "ack"),
    ("ok", {}, "ack"),
    ("Our elderly users may become stranded halfway across the road", {}, "project scene"),
]

# Ambiguous: documented retrieve decision. Not high-confidence source or personal.
AMBIGUOUS: list[tuple[str, dict[str, object], bool, str]] = [
    (
        "What quantified thermal degradation was reported?",
        {
            "selected_source_titles": ["Battery cycling notes"],
            "has_selected_sources": True,
        },
        True,
        "selected-source factual question with no course noun",
    ),
    (
        "What quantified thermal degradation was reported?",
        {},
        False,
        "same question without selected sources is idle-ish, not course-grounded",
    ),
    (
        "what about analogy?",
        {},
        False,
        "concept question with no source cue",
    ),
    (
        "Can you help me with this?",
        dict(_SELECTED),
        True,
        "help question with selected sources: retrieve, no Q&A hint",
    ),
    (
        "tell me more",
        dict(_SELECTED),
        True,
        "continuation with selected sources",
    ),
    (
        "tell me more",
        {},
        False,
        "continuation without selected sources",
    ),
]

# Must not fire the bare S# pattern.
ADVERSARIAL_S_LABEL: tuple[str, ...] = (
    "as1",
    "ps1",
    "US1",
    "s1mple",
    "this",
    "so",
    "is 1",
    "section 1",
    "class1",
    "S",
    "S0",
    "S00",
    "S100",
    "s1e",
    "yes1",
    "this is so",
)


@pytest.mark.parametrize("message,kwargs,note", POSITIVE)
def test_positive_source_turns_retrieve(
    message: str, kwargs: dict[str, object], note: str
) -> None:
    decision = classify_retrieval_intent(message, **kwargs)
    assert retrieval_required(message, **kwargs) is True, note
    assert decision.retrieve is True, note
    assert decision.intent == INTENT_HIGH_CONFIDENCE_SOURCE, note
    assert decision.cues, note


@pytest.mark.parametrize("message,kwargs,note", NEGATIVE)
def test_personal_and_idle_turns_skip_retrieval(
    message: str, kwargs: dict[str, object], note: str
) -> None:
    decision = classify_retrieval_intent(message, **kwargs)
    assert retrieval_required(message, **kwargs) is False, note
    assert decision.retrieve is False, note
    assert decision.intent in {
        INTENT_HIGH_CONFIDENCE_PERSONAL,
        INTENT_AMBIGUOUS,
    }, note


@pytest.mark.parametrize("message,kwargs,retrieve,note", AMBIGUOUS)
def test_ambiguous_set_has_documented_retrieve_decision(
    message: str,
    kwargs: dict[str, object],
    retrieve: bool,
    note: str,
) -> None:
    decision = classify_retrieval_intent(message, **kwargs)
    assert decision.intent == INTENT_AMBIGUOUS, note
    assert decision.retrieve is retrieve, note
    assert retrieval_required(message, **kwargs) is retrieve, note


@pytest.mark.parametrize("message", ADVERSARIAL_S_LABEL)
def test_bare_source_label_does_not_match_ordinary_prose(message: str) -> None:
    assert retrieval_required(message) is False
    decision = classify_retrieval_intent(message)
    assert "bare_source_label" not in decision.cues
    assert "bracket_source_label" not in decision.cues


def test_bare_s1_retrieves_without_and_with_selected_sources() -> None:
    assert retrieval_required("summarise S1") is True
    assert retrieval_required("summarise S1", **_SELECTED) is True
    assert retrieval_required("SUMMARISE S1") is True


def test_week_reference_retrieves_without_selected_sources() -> None:
    assert retrieval_required("tell me about week 2") is True
    assert retrieval_required("tell me about week 2", **_SELECTED) is True


def test_course_say_retrieves_without_selected_sources() -> None:
    assert retrieval_required("what did the course say about analogy") is True
    assert (
        retrieval_required("what did the course say about analogy", **_SELECTED)
        is True
    )


def test_classify_api_is_stable_for_later_mode_hint() -> None:
    source = classify_retrieval_intent("what does the lecture say about JTBD")
    personal = classify_retrieval_intent("I think option B is better for my users")
    idle = classify_retrieval_intent("hello")
    assert source.intent == INTENT_HIGH_CONFIDENCE_SOURCE
    assert personal.intent == INTENT_HIGH_CONFIDENCE_PERSONAL
    assert idle.intent == INTENT_AMBIGUOUS
    assert idle.retrieve is False
    assert idle.cues == ()


def test_broadened_gate_does_not_widen_mock_specialist_selection() -> None:
    """Callers of looks_like_course_question must keep conservative qa routing.

    Checked callers: retrieval_gate.classify_retrieval_intent,
    specialists.routing.select_specialist, specialists.__init__ re-export,
    mock_provider (select_specialist), agentcore_provider (select_specialist).
    """
    message = "tell me about week 2"
    assert looks_like_course_question(message) is False
    assert select_specialist(message) == "coaching"
    assert retrieval_required(message) is True
    assert looks_like_course_question("What is Week 1 about?") is True
    assert select_specialist("What is Week 1 about?") == "qa"
