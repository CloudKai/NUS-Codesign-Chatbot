"""Deterministic specialist routing tests."""

from __future__ import annotations

from backend.specialists.routing import (
    SPECIALIST_COACHING,
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    apply_semantic_route,
    select_specialist,
)


def test_mock_qa_labels_specialist_and_does_not_qualify() -> None:
    """Offline Q&A must not count as a Deep Review coaching turn."""
    from backend.domain import CoachRequest, StageDecision
    from backend.mock_provider import DeterministicCoachProvider

    result = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="thread-qa",
            student_message="What does week 1 say about stakeholders?",
            current_stage="problem_identification",
            response_detail="long",
        )
    )
    assert result.specialist == SPECIALIST_QA
    assert result.qualifying_coaching_turn is False
    assert result.assessment.recommendation is StageDecision.STAY
    assert select_specialist("What is Week 1 about?") == SPECIALIST_QA
    assert select_specialist("What are the Week 1 contents talking about?") == SPECIALIST_QA


def test_jtbd_lecture_routes_to_qa() -> None:
    assert select_specialist("What does the JTBD lecture say?") == SPECIALIST_QA


def test_reading_and_deadline_questions_route_to_qa() -> None:
    assert select_specialist("What does Reading 2 discuss?") == SPECIALIST_QA
    assert select_specialist("When is the assignment due?") == SPECIALIST_QA


def test_project_reasoning_routes_to_coaching() -> None:
    message = "Our elderly users may become stranded halfway across the road"
    assert select_specialist(message) == SPECIALIST_COACHING


def test_ambiguous_message_defaults_to_coaching() -> None:
    assert select_specialist("I don't understand this.") == SPECIALIST_COACHING
    assert select_specialist("hello") == SPECIALIST_COACHING


def test_explicit_progress_review_routes_to_review() -> None:
    assert select_specialist("Review my progress so far.") == SPECIALIST_REVIEW


def test_client_cannot_force_qa_on_project_reasoning() -> None:
    """HTTP handlers pass requested=None; unknown names are ignored."""
    message = "Our elderly users may become stranded halfway across the road"
    assert select_specialist(message, requested=None) == SPECIALIST_COACHING
    assert select_specialist(message, requested="admin") == SPECIALIST_COACHING
    assert select_specialist(message, requested="qa") == SPECIALIST_QA


def test_server_surface_review_is_honored() -> None:
    assert select_specialist("Keep going.", surface="review") == SPECIALIST_REVIEW


def test_semantic_router_examples_map_to_expected_specialists() -> None:
    assert apply_semantic_route("qa", 0.9) == SPECIALIST_QA
    assert apply_semantic_route("coaching", 0.7) == SPECIALIST_COACHING
    assert apply_semantic_route("review", 0.8) == SPECIALIST_REVIEW


def test_malformed_or_low_confidence_semantic_route_falls_back_to_coaching() -> None:
    assert apply_semantic_route("admin", 0.99) == SPECIALIST_COACHING
    assert apply_semantic_route("qa", 0.2) == SPECIALIST_COACHING
    assert apply_semantic_route("qa", None) == SPECIALIST_COACHING
    assert apply_semantic_route("review", 1.2) == SPECIALIST_COACHING
    assert (
        select_specialist("What is Week 2 about?", use_semantic=True, semantic_specialist="qa", semantic_confidence=0.1)
        == SPECIALIST_COACHING
    )


def test_use_semantic_skips_regex_fallback() -> None:
    assert (
        select_specialist(
            "What is Week 2 about?",
            use_semantic=True,
            semantic_specialist="coaching",
            semantic_confidence=0.9,
        )
        == SPECIALIST_COACHING
    )
