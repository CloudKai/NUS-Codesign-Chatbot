"""A coaching reply with no recommendation is recorded as ``stay`` (stub runtime only).

Covers the Phase 4 item 1 fix: the live greeting failures were coaching replies
that carried no ``recommendation``. The default is always ``stay``. These tests
prove it never advances a stage, never opens a pending transition that an
explicit ``stay`` would not, and leaves explicit ``advance`` and Q&A replies
unchanged. No AWS call is made: a fake AgentCore runtime returns each payload.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from agentcore_runtime.models import (
    FastChatContractError,
    FastChatTurnOutput,
    adapt_fast_chat_turn_payload,
)
from agentcore_runtime.structured_coach import structured_wire_payload
from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
_STAGE = "problem_identification"


def _coaching(**overrides: Any) -> dict[str, Any]:
    """Return a coaching wire payload; pass ``recommendation=None`` to omit it."""
    payload: dict[str, Any] = {
        "mode": "coaching",
        "response_text": "Hello! What problem are you exploring today?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if not (k == "recommendation" and v is _OMIT)}


_OMIT = object()


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _service(
    store: StudentStore, client: FakeAgentCoreRuntime, *, auto_advance: bool = False
) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance,
    )


def _stage(store: StudentStore, thread_id: str) -> str:
    metadata = (store.get_thread(thread_id) or {}).get("metadata") or {}
    journey = metadata.get("learning_journey") or {}
    return str(journey.get("current_stage") or metadata.get("thinking_stage") or "")


def _perf_event(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    """Return the last ``coach_turn_perf`` JSON event the service logged."""
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    return events[-1]


def _submit(
    tmp_path: Path,
    payload: dict[str, Any],
    *,
    message: str = "hello",
    detail: str = "short",
    auto_advance: bool = False,
    key: str = "k1",
) -> tuple[Any, StudentStore, str]:
    """Run one turn through the application service; return turn, store, thread."""
    store = StudentStore(tmp_path / f"{key}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=payload)
    turn = _service(store, client, auto_advance=auto_advance).submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage=_STAGE,
            response_detail=detail,
            idempotency_key=key,
        )
    )
    return turn, store, thread_id


# --- schema and adapter -------------------------------------------------------


@pytest.mark.parametrize("missing", [_OMIT, None, "", "  ", "none", "null"])
def test_coaching_without_recommendation_defaults_to_stay(missing: Any) -> None:
    payload = _coaching(recommendation=missing)
    output = FastChatTurnOutput.model_validate(payload)
    assert output.mode == "coaching"
    assert output.recommendation == "stay"
    assert output.recommendation_defaulted is True


def test_explicit_stay_and_advance_are_not_marked_defaulted() -> None:
    stay = FastChatTurnOutput.model_validate(_coaching(recommendation="stay"))
    advance = FastChatTurnOutput.model_validate(_coaching(recommendation="advance"))
    assert (stay.recommendation, stay.recommendation_defaulted) == ("stay", False)
    assert (advance.recommendation, advance.recommendation_defaulted) == ("advance", False)


def test_default_is_never_advance_and_unknown_token_still_fails() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(recommendation="maybe"))
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(recommendation="ADVANCE!"))


def test_qa_reply_is_unchanged_and_never_defaulted() -> None:
    qa = FastChatTurnOutput.model_validate(
        {"mode": "qa", "response_text": "Week 1 covers X.", "recommendation": "advance"}
    )
    assert qa.recommendation is None
    assert qa.recommendation_defaulted is False
    bare = FastChatTurnOutput.model_validate({"mode": "qa", "response_text": "Week 1."})
    assert bare.recommendation is None and bare.recommendation_defaulted is False


def test_out_of_scope_reply_still_becomes_plain_qa() -> None:
    output = FastChatTurnOutput.model_validate(
        _coaching(recommendation=_OMIT, out_of_scope=True)
    )
    assert output.mode == "qa"
    assert output.recommendation is None
    assert output.recommendation_defaulted is False


def test_model_facing_schema_still_requires_recommendation_for_coaching() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    assert schema["then"]["required"] == ["recommendation"]
    assert "recommendation_defaulted" not in schema["properties"]
    assert "_recommendation_defaulted" not in schema["properties"]


def test_marker_is_a_wire_field_only_when_defaulted() -> None:
    defaulted = FastChatTurnOutput.model_validate(_coaching(recommendation=_OMIT))
    explicit = FastChatTurnOutput.model_validate(_coaching())
    assert "recommendation_defaulted" not in defaulted.model_dump(mode="json")
    wire = structured_wire_payload(defaulted)
    assert wire["recommendation"] == "stay" and wire["recommendation_defaulted"] is True
    assert "recommendation_defaulted" not in structured_wire_payload(explicit)


def test_adapter_defaults_slim_coaching_reply_to_stay() -> None:
    parsed = adapt_fast_chat_turn_payload(_coaching(recommendation=_OMIT))
    assert parsed.recommendation == "stay" and parsed.recommendation_defaulted is True


def test_adapter_prefers_nested_legacy_recommendation_over_the_default() -> None:
    payload = _coaching(recommendation=_OMIT)
    payload["assessment"] = {"recommendation": "advance", "recommendation_rationale": "r"}
    parsed = adapt_fast_chat_turn_payload(payload)
    assert parsed.recommendation == "advance"
    assert parsed.recommendation_defaulted is False


def test_adapter_bad_nested_recommendation_still_fails_closed() -> None:
    payload = _coaching(recommendation=_OMIT)
    payload["assessment"] = {"recommendation": "maybe"}
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(payload)
    assert raised.value.reason == "legacy_recommendation_missing"


# --- provider, workflow and persistence ---------------------------------------


def test_missing_recommendation_on_coaching_reply_is_stay_with_perf_field(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    turn, store, thread_id = _submit(tmp_path, _coaching(recommendation=_OMIT))
    perf = _perf_event(caplog)
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.assessment.readiness_candidate is False
    assert turn.pending_transition is None
    assert store.get_pending_phase_transition(thread_id) is None
    assert _stage(store, thread_id) == _STAGE
    assert perf["fast_chat_recommendation_defaulted"] is True


def test_explicit_stay_does_not_set_the_perf_field(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    turn, _store, _thread = _submit(tmp_path, _coaching())
    perf = _perf_event(caplog)
    assert turn.assessment.recommendation is StageDecision.STAY
    assert "fast_chat_recommendation_defaulted" not in perf


@pytest.mark.parametrize("auto_advance", [False, True])
def test_defaulted_stay_never_advances_even_with_auto_advance(
    tmp_path: Path, auto_advance: bool
) -> None:
    turn, store, thread_id = _submit(
        tmp_path, _coaching(recommendation=_OMIT), auto_advance=auto_advance
    )
    assert turn.pending_transition is None
    assert turn.auto_advanced_to is None
    assert _stage(store, thread_id) == _STAGE


def test_explicit_advance_is_unchanged_and_stays_confirmation_gated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    turn, store, thread_id = _submit(
        tmp_path,
        _coaching(recommendation="advance", recommendation_rationale="Ready."),
        message="Elderly commuters cannot read small timetable text, so I will study that.",
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.pending_transition is not None
    assert turn.auto_advanced_to is None
    # The proposal is persisted but the stage only moves after confirmation.
    assert _stage(store, thread_id) == _STAGE
    assert store.get_pending_phase_transition(thread_id) is not None
    assert "fast_chat_recommendation_defaulted" not in _perf_event(caplog)


@pytest.mark.parametrize("detail", ["short", "long"])
@pytest.mark.parametrize(
    "message",
    ["hello", "thanks!", "Elderly commuters cannot read small timetable text."],
)
def test_defaulted_stay_matches_explicit_stay_in_every_downstream_decision(
    tmp_path: Path, detail: str, message: str
) -> None:
    """A defaulted ``stay`` may do nothing an explicit ``stay`` would not."""
    explicit, e_store, e_thread = _submit(
        tmp_path, _coaching(), message=message, detail=detail, key="explicit"
    )
    defaulted, d_store, d_thread = _submit(
        tmp_path, _coaching(recommendation=_OMIT), message=message, detail=detail, key="defaulted"
    )

    def _decisions(turn: Any, store: StudentStore, thread: str) -> tuple[Any, ...]:
        return (
            turn.assessment.recommendation,
            turn.assessment.readiness_candidate,
            turn.assessment.response_mode,
            turn.pending_transition is not None,
            turn.auto_advanced_to,
            store.get_pending_phase_transition(thread) is not None,
            _stage(store, thread),
        )

    assert _decisions(defaulted, d_store, d_thread) == _decisions(explicit, e_store, e_thread)


def test_non_coaching_reply_is_unchanged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    qa = {
        "mode": "qa",
        "response_text": "Week 1 covers the innovation-driven economy.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }
    turn, store, thread_id = _submit(
        tmp_path, qa, message="What does week 1 cover in the lecture?", key="qa"
    )
    assert turn.assessment.recommendation is None
    assert turn.pending_transition is None
    assert _stage(store, thread_id) == _STAGE
    assert "fast_chat_recommendation_defaulted" not in _perf_event(caplog)


@pytest.mark.parametrize("stage", ["concept_generation", "deep_analysis"])
@pytest.mark.parametrize("detail", ["short", "long"])
@pytest.mark.parametrize("message", ["hello", "I sketched two concepts for the timetable display."])
def test_defaulted_stay_matches_explicit_stay_in_workflow_outside_the_hmw_stage(
    tmp_path: Path, stage: str, detail: str, message: str
) -> None:
    """Free mode promotes ``stay`` to ``advance`` outside Problem Identification.

    That promotion (``backend/workflow.py::_promote_free_mode_advance``) acts on
    the recommendation value only, so a defaulted ``stay`` must get the same
    outcome as a model-sent ``stay``. The pending proposal it can open still
    needs explicit student confirmation; nothing here changes a stage.
    """
    store = StudentStore(tmp_path / "wf.sqlite3")
    transitions = SQLitePhaseTransitionRepository(store)

    def _run(payload: dict[str, Any]) -> tuple[Any, ...]:
        workflow = CoachWorkflow(_provider(FakeAgentCoreRuntime(payload=payload)), transitions)
        turn = workflow.run(
            CoachRequest(
                thread_id="wf-thread",
                student_message=message,
                current_stage=stage,
                response_detail=detail,
            )
        )
        return (
            turn.assessment.recommendation,
            turn.assessment.readiness_candidate,
            turn.pending_transition is not None,
        )

    assert _run(_coaching(recommendation=_OMIT)) == _run(_coaching())
