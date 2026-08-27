"""Unit tests for ephemeral Thinking Path stage-move composer notices."""

from __future__ import annotations

from ui.session import locked_stage_move_notice


def test_locked_stage_notice_names_immediate_predecessor() -> None:
    assert (
        locked_stage_move_notice("concept_generation")
        == "Must complete Problem identification to reach Concept generation"
    )
    assert (
        locked_stage_move_notice("design_specification")
        == "Must complete Concept generation to reach Design specification"
    )
    assert (
        locked_stage_move_notice("deep_analysis")
        == "Must complete Design specification to reach Ethics & Critical Thinking"
    )
    assert (
        locked_stage_move_notice("reflection")
        == "Must complete Ethics & Critical Thinking to reach Reflection"
    )


def test_locked_stage_notice_ignores_journey_completion_gaps() -> None:
    """Predecessor is path-order; partial completion must not rename it."""
    journey = {
        "current_stage": "concept_generation",
        "completed_stages": ["problem_identification"],
        "response_detail": "short",
    }
    assert (
        locked_stage_move_notice("reflection", journey)
        == "Must complete Ethics & Critical Thinking to reach Reflection"
    )
