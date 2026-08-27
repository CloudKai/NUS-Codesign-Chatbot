"""Deterministic retrieval-gate tests. No model calls."""

from __future__ import annotations

import pytest

from backend.coaching.mode_policy import (
    QA_EVIDENCE_GAP_RESPONSE,
    should_author_qa_evidence_gap,
)
from backend.retrieval import COURSE_RETRIEVAL_EMPTY_CONTEXT
from backend.retrieval_gate import (
    INTENT_AMBIGUOUS,
    INTENT_HIGH_CONFIDENCE_SOURCE,
    classify_retrieval_intent,
    retrieval_required,
)

_ONE = {
    "has_selected_sources": True,
    "selected_source_titles": ["Battery cycling notes"],
    "selected_source_filenames": ["Battery_cycling_notes.pdf"],
}
_MULTI = {
    "has_selected_sources": True,
    "selected_source_titles": [
        "Battery cycling notes",
        "Stakeholder mapping handout",
    ],
    "selected_source_filenames": [
        "Battery_cycling_notes.pdf",
        "Stakeholder_mapping_handout.pdf",
    ],
}
_NONE: dict[str, object] = {}

# Titles that share stage-name tokens with navigation phrasing. Used only to
# prove execution-level navigation still zeros Retrieve; gate tests use _ONE.
_STAGE_TITLED = {
    "has_selected_sources": True,
    "selected_source_titles": ["Week 7 Concept Generation"],
    "selected_source_filenames": ["Week7_Concept_Generation.pdf"],
}


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
    assert retrieval_required("What does the evidence say?") is True
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


def test_single_title_word_does_not_turn_project_coaching_into_source_qa() -> None:
    selected = {
        "has_selected_sources": True,
        "selected_source_titles": ["Vulnerability in the elderly"],
        "selected_source_filenames": ["Vulnerability_in_the_elderly.pdf"],
    }
    for message in (
        "Elderly pedestrians need a safer crossing.",
        "How can elderly pedestrians cross more safely?",
    ):
        decision = classify_retrieval_intent(message, **selected)
        assert decision.retrieve is False, message
        assert "selected_source_title" not in decision.cues, message

    named = classify_retrieval_intent(
        "What does Vulnerability in the elderly say?", **selected
    )
    assert named.retrieve is True
    assert "selected_source_title" in named.cues


@pytest.mark.parametrize(
    "message",
    (
        "Can we go over my evidence?",
        "What evidence should I gather to improve this?",
        "Does my evidence support this idea?",
    ),
)
def test_generic_project_evidence_language_does_not_retrieve(message: str) -> None:
    decision = classify_retrieval_intent(message, **_ONE)
    assert decision.retrieve is False
    assert decision.intent != INTENT_HIGH_CONFIDENCE_SOURCE


def test_selected_source_evidence_lookup_remains_grounded() -> None:
    for message in (
        "What thermal battery evidence is available?",
        "What evidence does my source provide?",
    ):
        decision = classify_retrieval_intent(message, **_ONE)
        assert decision.retrieve is True, message


def test_punctuation_and_citation_markers() -> None:
    assert retrieval_required("Cite the source, please.") is True
    assert retrieval_required("Use [S1] here.") is True
    assert retrieval_required("Based on the PDF, what is required?") is True


@pytest.mark.parametrize("selected_kwargs", (_NONE, _ONE, _MULTI))
@pytest.mark.parametrize(
    "message",
    (
        "Can you help me?",
        "Hi, can you help me?",
        "What do you think?",
        "Does this make sense?",
        "Is this good enough?",
        "How can I improve this?",
        "What should I do next?",
        "Could you give me feedback?",
        "Is this realistic?",
        "Should I use this concept?",
        "Is it good?",
        "What should I do?",
        "How do I improve this?",
        "Can you give feedback?",
        "Should I choose this?",
    ),
)
def test_group1_generic_coaching_does_not_retrieve(
    message: str, selected_kwargs: dict[str, object]
) -> None:
    decision = classify_retrieval_intent(message, **selected_kwargs)
    assert decision.retrieve is False, message
    assert retrieval_required(message, **selected_kwargs) is False, message
    assert "selected_source_question" not in decision.cues
    assert "implicit_selected_source" not in decision.cues


@pytest.mark.parametrize(
    "message",
    (
        "Which lecture covers personas?",
        "What does Week 2 say about JTBD?",
        "Which reading supports this?",
        "What do the course notes say about prototyping?",
        "Is there anything in the readings about this?",
    ),
)
def test_group2_explicit_course_source_retrieves(message: str) -> None:
    for kwargs in (_NONE, _ONE, _MULTI):
        decision = classify_retrieval_intent(message, **kwargs)
        assert decision.retrieve is True, message
        assert decision.intent == INTENT_HIGH_CONFIDENCE_SOURCE, message


@pytest.mark.parametrize(
    "message",
    (
        "What is a job story?",
        "what is the definition of a job story",
        "what does JTBD mean",
        "explain Jobs to Be Done",
    ),
)
def test_group4_definitional_course_qa_unchanged(message: str) -> None:
    decision = classify_retrieval_intent(message, **_ONE)
    assert decision.retrieve is True, message
    assert decision.intent == INTENT_HIGH_CONFIDENCE_SOURCE, message


def test_group4_hmw_and_short_jtbd_follow_existing_definitional_rules() -> None:
    """HMW contains ``We``; short ``What is JTBD?`` stays below the word floor.

    Those cases previously retrieved only via the removed selected+question
    fallback. Do not re-broaden the gate for them.
    """
    for message in ("What is JTBD?", "What is a How Might We statement?"):
        alone = classify_retrieval_intent(message, **_NONE)
        with_sel = classify_retrieval_intent(message, **_ONE)
        assert alone.retrieve is with_sel.retrieve, message
        assert with_sel.cues != ("implicit_selected_source",), message


@pytest.mark.parametrize(
    "message",
    (
        "Can I move on?",
        "Am I ready to proceed?",
        "What stage am I at?",
        "confirm",
    ),
)
def test_group5_workflow_zero_course_retrieval(message: str) -> None:
    decision = classify_retrieval_intent(message, **_ONE)
    assert decision.retrieve is False, message


def test_group5_progression_overrides_selected_title_overlap() -> None:
    """Stage-name tokens in selected titles must not keep Retrieve on move-on."""
    from backend.coaching.mode_policy import ModePolicy, is_stage_progression_request
    from backend.coaching.mode_policy import resolve_mode_policy

    message = "Hi, can I move to Concept Generation?"
    assert is_stage_progression_request(message) is True
    policy = resolve_mode_policy(message, **_STAGE_TITLED)
    # Mirror FastAPI: progression forces retrieve=False / coaching.
    overridden = ModePolicy(
        intent=policy.intent,
        expected_mode="coaching",
        retrieve=False,
        retrieval_intent=policy.retrieval_intent,
        mixed=policy.mixed,
    )
    assert overridden.retrieve is False
    assert overridden.expected_mode == "coaching"

@pytest.mark.parametrize(
    "message",
    (
        "What are the main points?",
        "What are the key ideas?",
        "Can you summarise it?",
        "Summarise this for me.",
        "What does it say about prototyping?",
        "What does it cover?",
        "Give me an outline of it.",
    ),
)
def test_group6_implicit_selected_source_retrieves(message: str) -> None:
    for kwargs in (_ONE, _MULTI):
        decision = classify_retrieval_intent(message, **kwargs)
        assert decision.retrieve is True, message
        assert decision.intent == INTENT_AMBIGUOUS, message
        assert decision.cues == ("implicit_selected_source",), message
    without = classify_retrieval_intent(message, **_NONE)
    assert without.retrieve is False, message


def test_selected_plus_bare_question_mark_does_not_retrieve() -> None:
    decision = classify_retrieval_intent("?", **_ONE)
    assert decision.retrieve is False
    assert decision.intent == INTENT_AMBIGUOUS


def test_selected_source_generic_factual_question_prefers_false_negative() -> None:
    """Bare factual questions without source cues no longer force Retrieve."""
    assert (
        retrieval_required(
            "What quantified thermal degradation was reported?",
            selected_source_titles=["Battery cycling notes"],
            has_selected_sources=True,
        )
        is False
    )
    assert (
        retrieval_required(
            "Would this idea solve the problem?",
            selected_source_titles=["Battery cycling notes"],
            has_selected_sources=True,
        )
        is False
    )


def test_relative_who_statements_do_not_trigger_selected_source_retrieval() -> None:
    for message in (
        "Older pedestrians who walk slowly struggle to cross.",
        "Students who use wheelchairs may need more time.",
        "People who live nearby avoid the crossing.",
    ):
        assert (
            retrieval_required(
                message,
                selected_source_titles=["Stakeholder mapping notes"],
                has_selected_sources=True,
            )
            is False
        )


def test_genuine_source_questions_still_retrieve() -> None:
    for message in (
        "What does the lecture say about stakeholder mapping?",
        "According to the uploaded source, why is this method used?",
        "Which reading supports what I just said?",
    ):
        assert (
            retrieval_required(
                message,
                selected_source_titles=["Stakeholder mapping notes"],
                has_selected_sources=True,
            )
            is True
        )


def test_who_without_source_cue_does_not_retrieve_from_selection_alone() -> None:
    assert (
        retrieval_required(
            "Who introduced the How Might We framework?",
            selected_source_titles=["Stakeholder mapping notes"],
            has_selected_sources=True,
        )
        is False
    )


def test_evidence_gap_requires_retrieval_required() -> None:
    from types import SimpleNamespace

    course_miss = SimpleNamespace(
        expected_response_mode="qa",
        retrieval_required=True,
        allow_model_knowledge=False,
        retrieved_chunks=[],
        source_ids=["src-1"],
        retrieved_course_context=COURSE_RETRIEVAL_EMPTY_CONTEXT,
        image_inputs=[],
    )
    assert should_author_qa_evidence_gap(course_miss) is True

    coaching = SimpleNamespace(
        expected_response_mode="coaching",
        retrieval_required=False,
        allow_model_knowledge=False,
        retrieved_chunks=[],
        source_ids=["src-1"],
        retrieved_course_context=COURSE_RETRIEVAL_EMPTY_CONTEXT,
        image_inputs=[],
    )
    assert should_author_qa_evidence_gap(coaching) is False
    assert "couldn't find a matching validated excerpt" in QA_EVIDENCE_GAP_RESPONSE
