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
    stage_reviews: list[dict[str, Any]] | None = None,
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
        stage_reviews=stage_reviews,
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
    assert "stage_reviews" not in payload


def test_snapshot_payload_distinguishes_legacy_missing_from_explicit_empty_reviews() -> None:
    """Omitted stage reviews retain legacy shape; [] is an explicit new result."""
    legacy = _snapshot()
    explicit_empty = _snapshot(stage_reviews=[])

    assert "stage_reviews" not in legacy
    assert explicit_empty["stage_reviews"] == []


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


def test_stage_reviews_are_authoritative_and_skip_flat_lists() -> None:
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    journey["completed_stages"] = ["problem_identification"]
    messages = [
        _assistant(stage="problem_identification", strengths=["Incremental PI"]),
        _assistant(stage="concept_generation", strengths=["Incremental CG"]),
    ]
    review = learning_review(
        messages,
        journey,
        deep_review_snapshot=_snapshot(
            strengths=["Flat list must not duplicate"],
            stage_id="concept_generation",
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Identified the pedestrian signal timing problem"],
                    "areas_to_develop": ["Could add frequency or location evidence"],
                },
                {
                    "stage_id": "concept_generation",
                    "strengths": ["Named two distinct crossing concepts"],
                    "areas_to_develop": ["Generate a third distinct concept"],
                },
            ],
        ),
    )
    assert _items(review, "strength_sections", "problem_identification") == [
        "Identified the pedestrian signal timing problem",
        "Incremental PI",
    ]
    assert _items(review, "strength_sections", "concept_generation") == [
        "Named two distinct crossing concepts",
        "Incremental CG",
    ]
    assert "Flat list must not duplicate" not in _items(
        review, "strength_sections", "concept_generation"
    )
    assert "Flat list must not duplicate" not in _items(
        review, "strength_sections", "problem_identification"
    )
    assert _items(review, "improvement_sections", "design_specification") == []
    assert _items(review, "improvement_sections", "deep_analysis") == []
    assert _items(review, "improvement_sections", "reflection") == []


def test_explicit_empty_stage_reviews_do_not_fall_back_to_flat_lists() -> None:
    """A valid empty per-stage result must not resurrect stale flat feedback."""
    review = learning_review(
        [_assistant(stage="problem_identification", strengths=["Incremental"])],
        default_journey(),
        deep_review_snapshot=_snapshot(
            strengths=["Stale flat strength"],
            areas=["Stale flat area"],
            stage_reviews=[],
        ),
    )

    assert "Stale flat strength" not in _items(
        review, "strength_sections", "problem_identification"
    )
    assert "Stale flat area" not in _items(
        review, "improvement_sections", "problem_identification"
    )


def test_hmw_strength_stays_under_problem_identification() -> None:
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    review = learning_review(
        [
            _assistant(stage="problem_identification", strengths=["Framed older pedestrians"]),
            _assistant(stage="concept_generation", strengths=[], improvements=[]),
        ],
        journey,
        deep_review_snapshot=_snapshot(
            strengths=["Constructed a How Might We question"],
            stage_id="concept_generation",
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Constructed a How Might We question"],
                    "areas_to_develop": [],
                },
                {
                    "stage_id": "concept_generation",
                    "strengths": [],
                    "areas_to_develop": [
                        "Generate multiple distinct concepts before selecting one."
                    ],
                },
            ],
        ),
    )
    assert "Constructed a How Might We question" in _items(
        review, "strength_sections", "problem_identification"
    )
    assert "Constructed a How Might We question" not in _items(
        review, "strength_sections", "concept_generation"
    )
    assert _items(review, "improvement_sections", "concept_generation") == [
        "Generate multiple distinct concepts before selecting one."
    ]


def test_stage_reviews_update_previous_stage_while_current_is_open() -> None:
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    review = learning_review(
        [_assistant(stage="concept_generation", strengths=["CG incremental"])],
        journey,
        deep_review_snapshot=_snapshot(
            stage_id="concept_generation",
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Updated PI deep strength"],
                    "areas_to_develop": ["Updated PI deep area"],
                },
                {
                    "stage_id": "concept_generation",
                    "strengths": ["Genuine CG deep strength"],
                    "areas_to_develop": [],
                },
            ],
        ),
    )
    assert "Updated PI deep strength" in _items(
        review, "strength_sections", "problem_identification"
    )
    assert "Genuine CG deep strength" in _items(
        review, "strength_sections", "concept_generation"
    )
    assert "CG incremental" in _items(review, "strength_sections", "concept_generation")
    assert _items(review, "strength_sections", "design_specification") == []


def test_stage_reviews_dedupe_with_incremental_case_insensitively() -> None:
    review = learning_review(
        [
            _assistant(
                stage="problem_identification",
                strengths=["Clearly identified the affected users."],
            )
        ],
        default_journey(),
        deep_review_snapshot=_snapshot(
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["clearly identified the affected users."],
                    "areas_to_develop": [],
                }
            ]
        ),
    )
    assert _items(review, "strength_sections", "problem_identification") == [
        "clearly identified the affected users."
    ]


def test_later_stage_reviews_replace_previous_deep_review_contribution() -> None:
    messages = [
        _assistant(stage="problem_identification", strengths=["Normal strength"]),
        _assistant(stage="concept_generation", strengths=["CG incremental"]),
    ]
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    first = learning_review(
        messages,
        journey,
        deep_review_snapshot=_snapshot(
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Old PI deep strength"],
                    "areas_to_develop": [],
                }
            ]
        ),
    )
    second = learning_review(
        messages,
        journey,
        deep_review_snapshot=_snapshot(
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["New PI deep strength"],
                    "areas_to_develop": [],
                },
                {
                    "stage_id": "concept_generation",
                    "strengths": ["New CG deep strength"],
                    "areas_to_develop": [],
                },
            ]
        ),
    )
    assert "Old PI deep strength" in _items(
        first, "strength_sections", "problem_identification"
    )
    assert "Old PI deep strength" not in _items(
        second, "strength_sections", "problem_identification"
    )
    assert "New PI deep strength" in _items(
        second, "strength_sections", "problem_identification"
    )
    assert "New CG deep strength" in _items(
        second, "strength_sections", "concept_generation"
    )
    assert "Normal strength" in _items(
        second, "strength_sections", "problem_identification"
    )


def test_legacy_snapshot_without_stage_reviews_still_uses_reviewed_stage() -> None:
    snapshot = _snapshot(
        strengths=["Legacy deep strength"],
        areas=["Legacy deep area"],
        stage_id="problem_identification",
    )
    snapshot.pop("stage_reviews", None)
    review = learning_review(
        [_assistant(stage="problem_identification", strengths=["Incremental"])],
        default_journey(),
        deep_review_snapshot=snapshot,
    )
    assert _items(review, "strength_sections", "problem_identification") == [
        "Legacy deep strength",
        "Incremental",
    ]


def test_review_stage_feedback_is_not_persisted_on_messages() -> None:
    from backend.domain import EducationalAssessment, StageDecision

    feedback = [
        {
            "stage_id": "problem_identification",
            "strengths": ["Deep PI"],
            "areas_to_develop": [],
        }
    ]
    slim = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        response_mode="coaching",
        review_stage_feedback=feedback,
    ).persisted_mapping()
    full = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        review_stage_feedback=feedback,
    ).persisted_mapping()
    assert "review_stage_feedback" not in slim
    assert "review_stage_feedback" not in full


def test_qa_messages_do_not_become_incremental_stage_feedback() -> None:
    messages = [
        {
            "role": "user",
            "content": "What is JTBD in week 2?",
            "metadata": {"thinking_stage": "problem_identification"},
        },
        {
            "role": "assistant",
            "content": "JTBD is jobs to be done.",
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "response_mode": "qa",
                    "citations": [],
                }
            },
        },
        _assistant(stage="problem_identification", strengths=["Named a crossing problem"]),
    ]
    review = learning_review(
        messages,
        default_journey(),
        deep_review_snapshot=_snapshot(
            stage_reviews=[
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Named a crossing problem"],
                    "areas_to_develop": [],
                }
            ]
        ),
    )
    items = _items(review, "strength_sections", "problem_identification")
    assert items == ["Named a crossing problem"]
    assert "jobs to be done" not in " ".join(items).lower()
    assert "JTBD" not in " ".join(items)


def test_haiku_stage_checkpoint_facione_projects_into_review() -> None:
    """Max Facione across Journey checkpoints fills Review when no Deep Review."""
    journey_stage_reviews = {
        "jobs": {},
        "reviews": {
            "problem_identification": {
                "stage": "problem_identification",
                "summary": "Checkpoint summary.",
                "strengths": ["Clear focus"],
                "areas_to_revisit": ["Sharpen the outcome"],
                "facione_scores": {
                    "analysis": 3,
                    "interpretation": 2,
                    "inference": 0,
                    "evaluation": 1,
                    "explanation": 0,
                    "self_regulation": 0,
                },
                "conversation_revision": 4,
            },
            "concept_generation": {
                "stage": "concept_generation",
                "summary": "Later checkpoint.",
                "strengths": ["Divergent options"],
                "areas_to_revisit": [],
                "facione_scores": {
                    "analysis": 2,
                    "interpretation": 1,
                    "inference": 2,
                    "evaluation": 0,
                    "explanation": 0,
                    "self_regulation": 0,
                },
                "conversation_revision": 8,
            },
        },
        "unread": False,
    }
    review = learning_review(
        [],
        default_journey(),
        journey_stage_reviews=journey_stage_reviews,
    )
    assert review["facione_scores"]["analysis"] == 3
    assert review["facione_scores"]["interpretation"] == 2
    assert review["facione_scores"]["inference"] == 2
    assert review["facione_scores"]["evaluation"] == 1


def test_deep_review_facione_overrides_haiku_checkpoint_projection() -> None:
    """Whole-conversation Deep Review Facione replaces checkpoint maxes."""
    journey_stage_reviews = {
        "jobs": {},
        "reviews": {
            "problem_identification": {
                "stage": "problem_identification",
                "summary": "Checkpoint summary.",
                "strengths": ["Clear focus"],
                "areas_to_revisit": [],
                "facione_scores": {
                    "analysis": 4,
                    "interpretation": 4,
                    "inference": 4,
                    "evaluation": 4,
                    "explanation": 4,
                    "self_regulation": 4,
                },
            }
        },
        "unread": False,
    }
    snapshot = _snapshot(
        facione={
            "analysis": 2,
            "interpretation": 1,
            "inference": 1,
            "evaluation": 1,
            "explanation": 1,
            "self_regulation": 1,
        }
    )
    review = learning_review(
        [],
        default_journey(),
        deep_review_snapshot=snapshot,
        journey_stage_reviews=journey_stage_reviews,
    )
    assert review["facione_scores"]["analysis"] == 2
    assert review["facione_scores"]["interpretation"] == 1
    assert review["facione_scores"]["self_regulation"] == 1
