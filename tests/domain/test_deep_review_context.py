"""Deep Review full_history vs checkpoint_delta context planning. No AWS."""

from __future__ import annotations

from typing import Any

import pytest

from backend.coaching.deep_review_context import (
    DEEP_REVIEW_CHECKPOINT_VERSION,
    DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA,
    DEEP_REVIEW_CONTEXT_FULL_HISTORY,
    DEFAULT_CHECKPOINT_TOKEN_THRESHOLD,
    MIN_MEANINGFUL_TOKEN_SAVINGS,
    MIN_MEANINGFUL_TOKEN_SAVINGS_RATIO,
    assign_message_refs,
    bind_supporting_message_ids,
    checkpoint_identity_for_enqueue,
    compact_context_fallback_reason,
    context_metrics,
    estimate_transcript_tokens,
    estimated_savings_ratio,
    is_checkpoint_capable_snapshot,
    plan_deep_review_context,
    source_fingerprint,
    validate_supporting_message_ref,
)
from backend.specialists.review_orchestration import deep_review_snapshot_payload


def _message(
    message_id: str,
    content: str,
    *,
    role: str = "user",
    stage: str = "problem_identification",
    kind: str | None = None,
) -> dict[str, Any]:
    """Return one frozen transcript row for planner tests."""
    metadata: dict[str, Any] = {"thinking_stage": stage}
    if kind:
        metadata["kind"] = kind
    if role == "assistant":
        metadata["assessment"] = {"current_stage": stage, "response_mode": "coaching"}
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "metadata": metadata,
    }


def _long(marker: str, *, words: int = 80) -> str:
    """Return enough text for the conservative 3-chars-per-token estimator."""
    return f"{marker} " + ("evidence " * words)


def _checkpoint(
    messages: list[dict[str, Any]],
    *,
    supporting_ids: list[str],
    source_ids: list[str] | None = None,
    revision: int = 20,
    stage_id: str = "problem_identification",
    extra_reviews: list[dict[str, Any]] | None = None,
    readiness_evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Return one checkpoint-capable Deep Review snapshot."""
    reviews = [
        {
            "stage_id": stage_id,
            "strengths": ["Named a real constraint"],
            "areas_to_develop": ["Name who is affected"],
            "supporting_message_ids": list(supporting_ids),
        }
    ]
    if extra_reviews:
        reviews.extend(extra_reviews)
    return deep_review_snapshot_payload(
        conversation_revision=revision,
        created_at="2026-08-20T00:00:00+00:00",
        synthesis="Prior whole-conversation synthesis.",
        summary="Prior whole-conversation synthesis.",
        strengths=["Named a real constraint"],
        areas_to_develop=["Name who is affected"],
        facione_scores={
            "interpretation": 2,
            "analysis": 2,
            "inference": 2,
            "evaluation": 2,
            "explanation": 2,
            "self_regulation": 2,
        },
        working_conclusion="Prior working conclusion.",
        readiness_candidate=False,
        readiness_evidence=list(readiness_evidence or []),
        missing_requirements=["Name the outcome"],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id=stage_id,
        stage_reviews=reviews,
        reviewed_message_ids=[str(item["id"]) for item in messages],
        source_ids=list(source_ids or []),
        checkpoint_version=DEEP_REVIEW_CHECKPOINT_VERSION,
    )


def test_default_threshold_is_twenty_thousand_transcript_tokens() -> None:
    assert DEFAULT_CHECKPOINT_TOKEN_THRESHOLD == 20_000
    assert MIN_MEANINGFUL_TOKEN_SAVINGS == 1_000
    assert MIN_MEANINGFUL_TOKEN_SAVINGS_RATIO == 0.20


def test_first_review_without_checkpoint_uses_full_history() -> None:
    history = [
        _message("u1", _long("FIRST_USER"), role="user"),
        _message("a1", "Which users?", role="assistant"),
    ]
    plan = plan_deep_review_context(
        frozen_history=history,
        frozen_source_ids=[],
        frozen_revision=1,
        frozen_stage="problem_identification",
        snapshot=None,
        expected_checkpoint_revision=None,
        expected_checkpoint_version=None,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "no_checkpoint"
    text = "\n".join(str(item.get("content") or "") for item in plan.converse_history)
    assert "FIRST_USER" in text
    assert plan.ref_map["M1"] == "u1"


def test_small_second_review_stays_full_history() -> None:
    prior = [_message("u1", "Short PI student turn.", role="user")]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=1)
    current = [
        *prior,
        _message("u2", "Short later turn.", role="user"),
    ]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=2,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=1,
        expected_checkpoint_version=1,
        threshold=20_000,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "below_threshold"


def test_legacy_snapshot_is_not_checkpoint_capable() -> None:
    legacy = deep_review_snapshot_payload(
        conversation_revision=4,
        created_at="2026-08-01T00:00:00+00:00",
        synthesis="Legacy.",
        summary="Legacy.",
        strengths=["Legacy strength"],
        areas_to_develop=[],
        facione_scores={},
        working_conclusion="",
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id="problem_identification",
    )
    assert is_checkpoint_capable_snapshot(legacy) is False
    assert checkpoint_identity_for_enqueue(legacy) == (None, None)
    history = [_message("u1", _long("LEGACY_USER"), role="user")]
    plan = plan_deep_review_context(
        frozen_history=history,
        frozen_source_ids=[],
        frozen_revision=5,
        frozen_stage="problem_identification",
        snapshot=legacy,
        expected_checkpoint_revision=4,
        expected_checkpoint_version=1,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason in {"legacy_snapshot", "malformed_checkpoint"}


def test_branch_change_invalidates_checkpoint() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 6)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    current = [item for item in prior if item["id"] != "u3"]
    current.append(_message("u9", _long("NEW_BRANCH"), role="user"))
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=35,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "branch_changed"


def test_superseded_anchor_invalidates_checkpoint() -> None:
    prior = [_message("u1", _long("ANCHOR"), role="user")]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=4)
    current = [_message("u2", _long("REPLACEMENT"), role="user")]
    snapshot["reviewed_message_ids"] = ["u2"]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=5,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=4,
        expected_checkpoint_version=1,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "anchors_invalid"


def test_source_fingerprint_change_uses_full_history() -> None:
    prior = [_message("u1", _long("SRC_USER"), role="user")]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=3, source_ids=["src-a"])
    plan = plan_deep_review_context(
        frozen_history=prior,
        frozen_source_ids=["src-b"],
        frozen_revision=4,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=3,
        expected_checkpoint_version=1,
        threshold=10,
    )
    assert source_fingerprint(["src-a"]) != source_fingerprint(["src-b"])
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "source_changed"


def test_matching_empty_sources_remain_compatible() -> None:
    assert source_fingerprint([]) == source_fingerprint(None)


def test_reflection_force_full_final() -> None:
    prior = [_message(f"u{i}", _long(f"FINAL{i}"), role="user") for i in range(1, 12)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=8)
    current = [*prior, _message("u99", _long("MORE"), role="user")]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=9,
        frozen_stage="reflection",
        snapshot=snapshot,
        expected_checkpoint_revision=8,
        expected_checkpoint_version=1,
        threshold=10,
        force_full_final=True,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "force_full_final"


def test_checkpoint_delta_keeps_raw_delta_and_anchors() -> None:
    prior = [
        _message("u1", _long("PI_ANCHOR_A"), role="user", stage="problem_identification"),
        _message(
            "u2",
            _long("CG_ANCHOR_B"),
            role="user",
            stage="concept_generation",
        ),
    ]
    prior.extend(
        _message(f"f{i}", _long(f"FILLER{i}"), role="user") for i in range(30)
    )
    snapshot = _checkpoint(
        prior,
        supporting_ids=["u1"],
        revision=20,
        extra_reviews=[
            {
                "stage_id": "concept_generation",
                "strengths": ["Named two concepts"],
                "areas_to_develop": [],
                "supporting_message_ids": ["u2"],
            }
        ],
    )
    snapshot["stage_reviews"][1]["supporting_message_ids"] = ["u2"]
    delta = [
        _message("d21", _long("DELTA_21"), role="user", stage="concept_generation"),
        _message("d28", _long("DELTA_28"), role="assistant", stage="concept_generation"),
        _message(
            "d35",
            _long("DELTA_35"),
            role="user",
            stage="design_specification",
        ),
    ]
    current = [*prior, *delta]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=35,
        frozen_stage="design_specification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.converse_history == []
    assert "PI_ANCHOR_A" in plan.compact_context
    assert "CG_ANCHOR_B" in plan.compact_context
    assert "DELTA_21" in plan.compact_context
    assert "DELTA_28" in plan.compact_context
    assert "DELTA_35" in plan.compact_context
    assert "FILLER0" not in plan.compact_context
    assert plan.delta_message_count == 3
    assert plan.anchor_count == 2
    assert plan.actual_context_estimated_tokens < plan.full_estimated_tokens
    assert plan.estimated_tokens_saved > 0


def test_synthetic_long_history_checkpoint_delta_saves_tokens() -> None:
    prior = [
        _message(
            f"p{i}",
            _long(f"PRIOR{i}", words=100),
            role="user" if i % 2 == 0 else "assistant",
        )
        for i in range(30)
    ]
    prior[0] = _message("p0", _long("ANCHOR_PRIOR0", words=100), role="user")
    snapshot = _checkpoint(prior, supporting_ids=["p0"], revision=30)
    delta = [
        _message(
            f"d{i}",
            _long(f"DELTA{i}", words=100),
            role="user" if i % 2 == 0 else "assistant",
        )
        for i in range(50)
    ]
    current = [*prior, *delta]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=80,
        frozen_stage="concept_generation",
        snapshot=snapshot,
        expected_checkpoint_revision=30,
        expected_checkpoint_version=1,
        threshold=DEFAULT_CHECKPOINT_TOKEN_THRESHOLD,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.full_estimated_tokens > DEFAULT_CHECKPOINT_TOKEN_THRESHOLD
    assert plan.estimated_tokens_saved >= MIN_MEANINGFUL_TOKEN_SAVINGS
    assert plan.estimated_savings_ratio >= MIN_MEANINGFUL_TOKEN_SAVINGS_RATIO
    assert plan.actual_context_estimated_tokens < plan.full_estimated_tokens
    assert plan.delta_message_count == 50
    assert "ANCHOR_PRIOR0" in plan.compact_context
    for index in (0, 24, 49):
        assert f"DELTA{index}" in plan.compact_context
    assert estimate_transcript_tokens(current) == plan.full_estimated_tokens


def test_welcome_and_synthetic_rows_are_not_labeled() -> None:
    history = [
        _message(
            "welcome",
            "Welcome to your critical-thinking coach",
            role="assistant",
            kind="coach_welcome",
        ),
        _message("u1", "Student turn.", role="user"),
    ]
    _eligible, ref_to_id, _id_to_ref = assign_message_refs(history)
    assert "welcome" not in ref_to_id.values()
    assert ref_to_id["M1"] == "u1"


def test_bind_supporting_message_ids_maps_and_drops_invalid_refs() -> None:
    history = [
        _message("pi-user", "HMW for older pedestrians.", role="user"),
        _message("cg-user", "A countdown timer concept.", role="user", stage="concept_generation"),
        _message("coach", "What assumption is that?", role="assistant"),
    ]
    _eligible, ref_map, _id_to_ref = assign_message_refs(history)
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Framed an HMW"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M1", "M9999", "M2", "M3"],
            }
        ],
        ref_map=ref_map,
        frozen_history=history,
    )
    assert bound[0]["supporting_message_ids"] == ["pi-user"]
    assert "supporting_message_refs" not in bound[0]


def test_wrong_stage_and_assistant_refs_are_dropped() -> None:
    history = [
        _message("pi-user", "PI student.", role="user", stage="problem_identification"),
        _message("cg-user", "CG student.", role="user", stage="concept_generation"),
        _message("coach", "Coach.", role="assistant", stage="problem_identification"),
    ]
    _eligible, ref_map, id_to_ref = assign_message_refs(history)
    frozen = {item["id"]: item for item in history}
    assert (
        validate_supporting_message_ref(
            id_to_ref["cg-user"],
            stage_id="problem_identification",
            ref_map=ref_map,
            frozen_by_id=frozen,
        )
        is None
    )
    assert (
        validate_supporting_message_ref(
            id_to_ref["coach"],
            stage_id="problem_identification",
            ref_map=ref_map,
            frozen_by_id=frozen,
        )
        is None
    )
    assert (
        validate_supporting_message_ref(
            id_to_ref["pi-user"],
            stage_id="problem_identification",
            ref_map=ref_map,
            frozen_by_id=frozen,
        )
        == "pi-user"
    )


def test_hmw_anchor_stays_attributed_to_problem_identification() -> None:
    history = [
        _message(
            "hmw",
            "How might we help older pedestrians finish crossing?",
            role="user",
            stage="problem_identification",
        )
    ]
    _eligible, ref_map, id_to_ref = assign_message_refs(history)
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Constructed a How Might We question"],
                "areas_to_develop": [],
                "supporting_message_refs": [id_to_ref["hmw"]],
            },
            {
                "stage_id": "concept_generation",
                "strengths": ["Should not steal the HMW"],
                "areas_to_develop": [],
                "supporting_message_refs": [id_to_ref["hmw"]],
            },
        ],
        ref_map=ref_map,
        frozen_history=history,
    )
    by_stage = {item["stage_id"]: item["supporting_message_ids"] for item in bound}
    assert by_stage["problem_identification"] == ["hmw"]
    assert by_stage["concept_generation"] == []


def test_checkpoint_mismatch_at_worker_falls_back() -> None:
    prior = [_message("u1", _long("OLD_CHECKPOINT"), role="user")]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=35)
    plan = plan_deep_review_context(
        frozen_history=[*prior, _message("u2", _long("NEWER"), role="user")],
        frozen_source_ids=[],
        frozen_revision=40,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "checkpoint_replaced"


def _compatible_follow_on_history() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return a compatible checkpoint plus a short delta for savings tests."""
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 8)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=8)
    current = [
        *prior,
        _message("d1", _long("DELTA_USER"), role="user"),
        _message("d2", _long("DELTA_COACH"), role="assistant"),
    ]
    return current, snapshot


def _plan_with_token_estimates(
    monkeypatch: pytest.MonkeyPatch,
    *,
    full_tokens: int,
    compact_tokens: int,
    threshold: int,
) -> Any:
    """Plan one compatible review with injected token estimates."""
    import backend.coaching.deep_review_context as module

    current, snapshot = _compatible_follow_on_history()
    monkeypatch.setattr(module, "estimate_transcript_tokens", lambda _messages: full_tokens)
    monkeypatch.setattr(module, "estimate_tokens", lambda _text: compact_tokens)
    return plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=10,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=8,
        expected_checkpoint_version=1,
        threshold=threshold,
        force_full_final=False,
    )


def test_unexposed_historical_ref_is_dropped_in_checkpoint_delta() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    delta = [
        _message("d1", _long("DELTA_USER"), role="user"),
        _message("d2", _long("DELTA_COACH"), role="assistant"),
    ]
    current = [*prior, *delta]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=22,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert "M1" in plan.ref_map
    assert "M4" not in plan.ref_map
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Should not cite unseen history"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M4"],
            }
        ],
        ref_map=plan.ref_map,
        frozen_history=current,
    )
    assert bound[0]["supporting_message_ids"] == []


def test_exposed_anchor_ref_maps_to_durable_id() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    current = [*prior, _message("d1", _long("DELTA_USER"), role="user")]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=21,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.ref_map["M1"] == "u1"
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Named a constraint"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M1"],
            }
        ],
        ref_map=plan.ref_map,
        frozen_history=current,
    )
    assert bound[0]["supporting_message_ids"] == ["u1"]


def test_exposed_delta_ref_maps_to_durable_id() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    current = [
        *prior,
        _message("d1", _long("DELTA_USER"), role="user"),
        _message("d2", _long("DELTA_COACH"), role="assistant"),
    ]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=22,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.ref_map["M21"] == "d1"
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Later student turn"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M21"],
            }
        ],
        ref_map=plan.ref_map,
        frozen_history=current,
    )
    assert bound[0]["supporting_message_ids"] == ["d1"]


def test_full_history_still_accepts_visible_old_refs() -> None:
    history = [
        _message("u1", _long("FIRST_USER"), role="user"),
        _message("a1", "Which users?", role="assistant"),
        _message("u2", _long("SECOND_USER"), role="user"),
    ]
    plan = plan_deep_review_context(
        frozen_history=history,
        frozen_source_ids=[],
        frozen_revision=2,
        frozen_stage="problem_identification",
        snapshot=None,
        expected_checkpoint_revision=None,
        expected_checkpoint_version=None,
        threshold=10,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.ref_map["M1"] == "u1"
    assert plan.ref_map["M3"] == "u2"
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Two student turns"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M1", "M3"],
            }
        ],
        ref_map=plan.ref_map,
        frozen_history=history,
    )
    assert bound[0]["supporting_message_ids"] == ["u1", "u2"]


def test_exposed_assistant_delta_ref_is_still_rejected() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    current = [
        *prior,
        _message("d1", _long("DELTA_USER"), role="user"),
        _message("d2", _long("DELTA_COACH"), role="assistant"),
    ]
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=22,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.ref_map["M22"] == "d2"
    bound = bind_supporting_message_ids(
        [
            {
                "stage_id": "problem_identification",
                "strengths": ["Must stay student evidence"],
                "areas_to_develop": [],
                "supporting_message_refs": ["M22"],
            }
        ],
        ref_map=plan.ref_map,
        frozen_history=current,
    )
    assert bound[0]["supporting_message_ids"] == []


def test_checkpoint_ref_map_matches_exposed_anchor_and_delta_objects() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(prior, supporting_ids=["u1"], revision=20)
    delta = [
        _message("d1", _long("DELTA_USER"), role="user"),
        _message("d2", _long("DELTA_COACH"), role="assistant"),
    ]
    current = [*prior, *delta]
    _eligible, _ref_to_id, id_to_ref = assign_message_refs(current)
    plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=22,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    exposed_ids = {"u1", "d1", "d2"}
    expected_labels = {id_to_ref[message_id] for message_id in exposed_ids}
    assert set(plan.ref_map.keys()) == expected_labels
    assert set(plan.ref_map.values()) == exposed_ids
    assert expected_labels.isdisjoint({"M2", "M4", "M10", "M20"})


def test_readiness_evidence_appears_in_checkpoint_delta_only() -> None:
    prior = [_message(f"u{i}", _long(f"OLD{i}"), role="user") for i in range(1, 21)]
    snapshot = _checkpoint(
        prior,
        supporting_ids=["u1"],
        revision=20,
        readiness_evidence=["UNIQUE_READINESS_MARKER"],
    )
    current = [*prior, _message("d1", _long("DELTA_USER"), role="user")]
    compact_plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=21,
        frozen_stage="problem_identification",
        snapshot=snapshot,
        expected_checkpoint_revision=20,
        expected_checkpoint_version=1,
        threshold=200,
        force_full_final=False,
    )
    assert compact_plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert "UNIQUE_READINESS_MARKER" in compact_plan.compact_context
    assert "Readiness evidence:" in compact_plan.compact_context
    full_plan = plan_deep_review_context(
        frozen_history=current,
        frozen_source_ids=[],
        frozen_revision=21,
        frozen_stage="problem_identification",
        snapshot=None,
        expected_checkpoint_revision=None,
        expected_checkpoint_version=None,
        threshold=200,
    )
    assert full_plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    converse = "\n".join(str(item.get("content") or "") for item in full_plan.converse_history)
    assert "UNIQUE_READINESS_MARKER" not in converse
    assert full_plan.compact_context == ""


def test_compact_savings_helper_requires_absolute_and_ratio() -> None:
    assert compact_context_fallback_reason(10_500, 10_250) == "compact_savings_too_small"
    assert compact_context_fallback_reason(100_000, 85_000) == (
        "compact_savings_ratio_too_small"
    )
    assert compact_context_fallback_reason(2_000, 1_500) == "compact_savings_too_small"
    assert compact_context_fallback_reason(25_000, 15_000) == ""
    assert compact_context_fallback_reason(8_000, 8_000) == "compact_not_smaller"
    assert estimated_savings_ratio(0, 100) == 0.0


def test_tiny_saving_does_not_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan_with_token_estimates(
        monkeypatch, full_tokens=25_000, compact_tokens=24_500, threshold=20_000
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "compact_savings_too_small"


def test_absolute_pass_but_ratio_fail_does_not_compact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan_with_token_estimates(
        monkeypatch, full_tokens=100_000, compact_tokens=85_000, threshold=20_000
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "compact_savings_ratio_too_small"


def test_ratio_pass_but_absolute_fail_does_not_compact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan_with_token_estimates(
        monkeypatch, full_tokens=2_000, compact_tokens=1_500, threshold=100
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_FULL_HISTORY
    assert plan.fallback_reason == "compact_savings_too_small"


def test_meaningful_absolute_and_ratio_saving_uses_checkpoint_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan_with_token_estimates(
        monkeypatch, full_tokens=25_000, compact_tokens=15_000, threshold=20_000
    )
    assert plan.mode == DEEP_REVIEW_CONTEXT_CHECKPOINT_DELTA
    assert plan.estimated_tokens_saved == 10_000
    assert plan.estimated_savings_ratio == 0.4
    metrics = context_metrics(plan)
    assert metrics["deep_review_estimated_savings_ratio"] == 0.4
    assert metrics["deep_review_estimated_tokens_saved"] == 10_000
