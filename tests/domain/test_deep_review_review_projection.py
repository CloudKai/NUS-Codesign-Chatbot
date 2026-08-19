"""Review-tab merge of Deep Review snapshot strengths and areas. No AWS."""

from __future__ import annotations

from typing import Any

from backend.learning.journey import (
    _merge_deep_review_feedback,
    _reviewed_stage_id_from_snapshot,
    learning_review,
)
from backend.specialists.review_orchestration import deep_review_snapshot_payload
from backend.student_journey import default_journey


def _assistant(
    *,
    stage: str,
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    summary: str = "Incremental summary.",
) -> dict[str, Any]:
    """Return one persisted incremental assessment message."""
    assessment: dict[str, Any] = {
        "current_stage": stage,
        "recommendation": "stay",
        "learning_summary": summary,
        "stage_assessment": "Incremental stage note.",
        "contribution_summary": "Draft.",
    }
    if strengths is not None:
        assessment["review_strengths"] = strengths
    if improvements is not None:
        assessment["review_improvements"] = improvements
    return {
        "role": "assistant",
        "content": "Coach reply",
        "metadata": {"assessment": assessment},
    }


def _snapshot(
    *,
    strengths: list[str] | None = None,
    areas: list[str] | None = None,
    stage_id: str = "problem_identification",
    include_stage_id: bool = True,
    summary: str = "Deep Review summary.",
    facione: dict[str, int] | None = None,
    conclusion: str = "Deep working conclusion.",
) -> dict[str, Any]:
    """Return one durable Deep Review snapshot mapping."""
    payload = deep_review_snapshot_payload(
        conversation_revision=17,
        created_at="2026-08-19T00:00:00+00:00",
        synthesis=summary,
        summary=summary,
        strengths=list(strengths or []),
        areas_to_develop=list(areas or []),
        facione_scores=facione
        or {
            "analysis": 3,
            "interpretation": 2,
            "inference": 1,
            "evaluation": 1,
            "explanation": 1,
            "self_regulation": 1,
        },
        working_conclusion=conclusion,
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id=stage_id if include_stage_id else "",
    )
    if not include_stage_id:
        payload.pop("reviewed_stage_id", None)
    return payload


def _items(review: dict[str, Any], key: str, stage_id: str) -> list[str]:
    """Return one stage's projected feedback items."""
    return next(
        section["items"]
        for section in review[key]
        if section["stage_id"] == stage_id
    )


def test_snapshot_payload_persists_reviewed_stage_id() -> None:
    payload = deep_review_snapshot_payload(
        conversation_revision=17,
        created_at="2026-08-19T00:00:00+00:00",
        synthesis="Synthesis.",
        summary="Summary.",
        strengths=["Deep strength"],
        areas_to_develop=["Deep improvement"],
        facione_scores={"analysis": 2},
        working_conclusion="Conclusion.",
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id="problem_identification",
    )
    assert payload["reviewed_through_revision"] == 17
    assert payload["reviewed_stage_id"] == "problem_identification"
    assert payload["strengths"] == ["Deep strength"]
    assert payload["areas_to_develop"] == ["Deep improvement"]


def test_deep_review_strengths_appear_under_reviewed_stage() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Normal strength"],
            improvements=["Normal improvement"],
        )
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(strengths=["Deep strength"]),
    )
    assert "Deep strength" in _items(
        review, "strength_sections", "problem_identification"
    )


def test_deep_review_areas_appear_under_reviewed_stage() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Normal strength"],
            improvements=["Normal improvement"],
        )
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(areas=["Deep improvement"]),
    )
    assert "Deep improvement" in _items(
        review, "improvement_sections", "problem_identification"
    )


def test_incremental_and_deep_review_merge_prefers_deep_first() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Normal strength"],
            improvements=["Normal improvement"],
        )
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(
            strengths=["Deep strength"],
            areas=["Deep improvement"],
        ),
    )
    assert _items(review, "strength_sections", "problem_identification") == [
        "Deep strength",
        "Normal strength",
    ]
    assert _items(review, "improvement_sections", "problem_identification") == [
        "Deep improvement",
        "Normal improvement",
    ]


def test_merge_deduplicates_case_insensitively() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Clearly identified the affected users."],
        )
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(
            strengths=["clearly identified the affected users."]
        ),
    )
    items = _items(review, "strength_sections", "problem_identification")
    assert items == ["clearly identified the affected users."]


def test_deep_review_feedback_uses_frozen_stage_not_current_journey() -> None:
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    journey["completed_stages"] = ["problem_identification"]
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Focus strength"],
        ),
        _assistant(
            stage="concept_generation",
            strengths=["Concept strength"],
        ),
    ]
    review = learning_review(
        messages,
        journey,
        deep_review_snapshot=_snapshot(
            strengths=["Deep strength"],
            areas=["Deep improvement"],
            stage_id="problem_identification",
        ),
    )
    assert _items(review, "strength_sections", "problem_identification") == [
        "Deep strength",
        "Focus strength",
    ]
    assert "Deep strength" not in _items(
        review, "strength_sections", "concept_generation"
    )
    assert _items(review, "improvement_sections", "problem_identification") == [
        "Deep improvement"
    ]
    assert _items(review, "improvement_sections", "concept_generation") == []


def test_failed_deep_review_does_not_change_projected_feedback() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Kept strength"],
            improvements=["Kept improvement"],
        )
    ]
    previous = _snapshot(
        strengths=["Previous deep strength"],
        areas=["Previous deep area"],
    )
    with_snapshot = learning_review(
        messages, default_journey(), deep_review_snapshot=previous
    )
    # A failed job leaves the previous snapshot in place, so projection
    # is unchanged. A missing snapshot (failed first review) adds nothing.
    still_previous = learning_review(
        messages, default_journey(), deep_review_snapshot=previous
    )
    without_snapshot = learning_review(
        messages, default_journey(), deep_review_snapshot=None
    )
    assert with_snapshot["strength_sections"] == still_previous["strength_sections"]
    assert with_snapshot["improvement_sections"] == still_previous["improvement_sections"]
    assert "Previous deep strength" in _items(
        still_previous, "strength_sections", "problem_identification"
    )
    assert _items(
        without_snapshot, "strength_sections", "problem_identification"
    ) == ["Kept strength"]
    assert _items(
        without_snapshot, "improvement_sections", "problem_identification"
    ) == ["Kept improvement"]


def test_later_snapshot_replaces_previous_deep_review_contribution() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["Normal strength"],
        )
    ]
    first = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(strengths=["Old deep strength"]),
    )
    second = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(strengths=["New deep strength"]),
    )
    assert "Old deep strength" in _items(
        first, "strength_sections", "problem_identification"
    )
    items = _items(second, "strength_sections", "problem_identification")
    assert "New deep strength" in items
    assert "Old deep strength" not in items
    assert "Normal strength" in items


def test_normal_coaching_after_deep_review_keeps_snapshot_feedback() -> None:
    messages = [
        _assistant(
            stage="problem_identification",
            strengths=["First incremental"],
        ),
        _assistant(
            stage="problem_identification",
            strengths=["Later incremental"],
        ),
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(strengths=["Deep strength"], areas=["Deep area"]),
    )
    items = _items(review, "strength_sections", "problem_identification")
    assert items[0] == "Deep strength"
    assert "First incremental" in items
    assert "Later incremental" in items
    assert "Deep area" in _items(
        review, "improvement_sections", "problem_identification"
    )


def test_old_snapshot_without_stage_id_does_not_assign_unrelated_stage() -> None:
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    messages = [
        _assistant(
            stage="concept_generation",
            strengths=["Concept strength"],
        )
    ]
    snapshot = _snapshot(
        strengths=["Orphan deep strength"],
        areas=["Orphan deep area"],
        include_stage_id=False,
        summary="Legacy Deep Review summary.",
        facione={"analysis": 4, "interpretation": 0, "inference": 0, "evaluation": 0, "explanation": 0, "self_regulation": 0},
        conclusion="Legacy conclusion.",
    )
    assert _reviewed_stage_id_from_snapshot(snapshot) is None
    review = learning_review(messages, journey, deep_review_snapshot=snapshot)
    assert review["summary"] == "Legacy Deep Review summary."
    assert review["conclusion"] == "Legacy conclusion."
    assert review["facione_scores"]["analysis"] == 4
    for section in review["strength_sections"]:
        assert "Orphan deep strength" not in section["items"]
    for section in review["improvement_sections"]:
        assert "Orphan deep area" not in section["items"]
    assert _items(review, "strength_sections", "concept_generation") == [
        "Concept strength"
    ]


def test_old_snapshot_stage_at_start_alias_is_used_when_valid() -> None:
    snapshot = _snapshot(strengths=["Aliased deep strength"], include_stage_id=False)
    snapshot["stage_at_start"] = "problem_identification"
    review = learning_review(
        [_assistant(stage="problem_identification", strengths=["Normal"])],
        default_journey(),
        deep_review_snapshot=snapshot,
    )
    assert _items(review, "strength_sections", "problem_identification")[0] == (
        "Aliased deep strength"
    )


def test_merge_helper_ignores_unknown_stage_ids() -> None:
    empty_strengths = [
        {"stage_id": stage, "stage": stage, "items": []}
        for stage in (
            "problem_identification",
            "concept_generation",
            "design_specification",
            "deep_analysis",
            "reflection",
        )
    ]
    merged_s, merged_i = _merge_deep_review_feedback(
        empty_strengths,
        empty_strengths,
        {"reviewed_stage_id": "not-a-stage", "strengths": ["Nope"]},
    )
    assert all(section["items"] == [] for section in merged_s)
    assert all(section["items"] == [] for section in merged_i)


def test_review_projection_keeps_five_thinking_path_stages() -> None:
    review = learning_review(
        [_assistant(stage="problem_identification", strengths=["Normal"])],
        default_journey(),
        deep_review_snapshot=_snapshot(strengths=["Deep strength"]),
    )
    expected = [
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    ]
    assert [section["stage_id"] for section in review["strength_sections"]] == expected
    assert [
        section["stage_id"] for section in review["improvement_sections"]
    ] == expected
