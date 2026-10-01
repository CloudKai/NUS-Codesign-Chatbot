"""Unit tests for deterministic stage-move enter/revisit briefings."""

from __future__ import annotations

from backend.learning.stage_briefing import compose_stage_move_briefing
from backend.student_journey import default_journey, normalize_journey


def test_already_selected_returns_none() -> None:
    assert (
        compose_stage_move_briefing(
            target_stage="concept_generation",
            journey=default_journey(),
            already_selected=True,
        )
        is None
    )


def test_enter_briefing_includes_heading_purpose_and_how_commands() -> None:
    journey = normalize_journey(
        {
            **default_journey(),
            "working_conclusion": "Older pedestrians need more crossing time at night.",
            "completed_stages": ["problem_identification"],
            "current_stage": "problem_identification",
        }
    )
    text = compose_stage_move_briefing(
        target_stage="concept_generation",
        journey=journey,
        messages=[
            {
                "role": "user",
                "content": "Crossing times feel too short for older adults.",
            }
        ],
    )
    assert text is not None
    assert text.startswith("Moved to Stage: Concept generation.")
    assert "Generate and compare plausible concepts" in text
    assert "Older pedestrians need more crossing time at night." in text
    assert "What to work on next:" in text
    assert "1." in text and "2." in text
    assert "What to improve:" not in text


def test_revisit_briefing_uses_areas_and_working_conclusion() -> None:
    journey = normalize_journey(
        {
            **default_journey(),
            "working_conclusion": "Night crossing remains the core risk.",
            "completed_stages": ["problem_identification", "concept_generation"],
            "current_stage": "concept_generation",
        }
    )
    reviews = {
        "jobs": {},
        "reviews": {
            "problem_identification": {
                "stage": "problem_identification",
                "summary": "Solid framing.",
                "strengths": ["Named the users."],
                "areas_to_revisit": [
                    "Make the night-time constraint explicit.",
                    "Name who is most affected.",
                ],
                "reasoning_progress": "",
                "important_message_ids": [],
                "important_artifacts": {},
                "facione_scores": {},
                "conversation_revision": 1,
            }
        },
        "unread": False,
    }
    text = compose_stage_move_briefing(
        target_stage="problem_identification",
        journey=journey,
        journey_stage_reviews=reviews,
        deep_review_snapshot={
            "working_conclusion": "Night crossing remains the core risk.",
        },
    )
    assert text is not None
    assert text.startswith("Moved to Stage: Problem identification.")
    assert "Night crossing remains the core risk." in text
    assert "What to improve:" in text
    assert "Make the night-time constraint explicit." in text
    assert "How to improve:" in text
    assert "Revise your work so that you address:" in text


def test_revisit_without_areas_falls_back_to_stage_how() -> None:
    journey = normalize_journey(
        {
            **default_journey(),
            "completed_stages": ["problem_identification"],
            "current_stage": "concept_generation",
        }
    )
    text = compose_stage_move_briefing(
        target_stage="problem_identification",
        journey=journey,
        messages=[],
    )
    assert text is not None
    assert text.startswith("Moved to Stage: Problem identification.")
    assert "Revisit Problem identification" in text
    assert "How to improve:" in text
    assert "1." in text and "2." in text
