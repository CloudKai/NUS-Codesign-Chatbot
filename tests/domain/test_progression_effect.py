"""Progression-effect boundary: meta/status/prior-review cannot complete stages.

Deterministic mock providers only. Table-driven coverage across all five
Thinking Path stages plus Phase 1/2 and retrieval contracts.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.coaching.workflow_navigation import (
    apply_progression_effect,
    classify_workflow_intent,
    is_compound_status_guidance_request,
    is_current_stage_status_request,
    is_stage_progression_request,
    progression_effect_for,
    workflow_skips_retrieval,
)
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import settings
from backend.student_journey import STAGE_BY_ID, THINKING_STAGES
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)

_STAGE_IDS = tuple(stage.id for stage in THINKING_STAGES)

_COMPOUND_STATUS = (
    "what stage am i in and how do i continue",
    "what stage am i in and what should i do next?",
    "where are we now and how do i continue?",
    "which stage am i at and what do i need to work on?",
    "where am i in the thinking path and how do i progress?",
    "what stage are we on, and what should i focus on?",
    "what stage am i in and how do i finish?",
)

_META_GUIDANCE = (
    "what should i do here",
    "how do i continue",
    "what am i supposed to focus on",
    "what should i work on next",
    "can you guide me through this stage",
    "what is missing from my process",
    "how should i approach this",
    "what should i focus on for my problem",
    "what should i do in concept generation",
    "what should i work on now",
    "can you explain what belongs in a design specification",
    "what should i think about for ethics",
    "what should i reflect on",
)

_PRIOR_BY_STAGE: dict[str, tuple[str, ...]] = {
    "concept_generation": ("is my problem identification strong?",),
    "design_specification": ("was my concept generation strong enough?",),
    "deep_analysis": ("is my design specification clear?",),
    "reflection": (
        "did I handle the ethics part properly?",
        "did I handle the ethics part well?",
    ),
}

_SUBSTANTIVE: dict[str, str] = {
    "problem_identification": (
        "How might we help first-year students build sustainable study habits "
        "so they feel less overwhelmed during midterms?"
    ),
    "concept_generation": (
        "Concept A is a peer study buddy matching app. Concept B is a campus "
        "quiet-hour booking system. I prefer Concept A because it scales peer "
        "support without needing more rooms."
    ),
    "design_specification": (
        "The design must support anonymous matching, 48-hour response SLAs, "
        "and a hard constraint that no grades leave the campus network."
    ),
    "deep_analysis": (
        "The main trade-off is privacy versus accountability: anonymous matching "
        "protects students but may hide harmful advice, so we need moderated "
        "escalation paths."
    ),
    "reflection": (
        "I learned that I under-weighted evidence early on. Next I will gather "
        "two more student interviews before locking requirements."
    ),
}


def _coaching_payload(
    *,
    recommendation: str = "stay",
    text: str = "What assumption is carrying this preference?",
) -> dict[str, Any]:
    """Return a lightweight fast-chat coaching body, including ADVANCE."""
    return {
        "mode": "coaching",
        "response_text": text,
        "recommendation": recommendation,
        "recommendation_rationale": (
            "More evidence is still needed."
            if recommendation == "stay"
            else "The stage readiness bar is met."
        ),
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }


def _qa_payload(*, text: str = "Week 7 covers concept generation [S1].") -> dict[str, Any]:
    """Return a lightweight fast-chat Q&A body."""
    return {
        "mode": "qa",
        "response_text": text,
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


class _CountingRetriever:
    """Count retrieve calls for workflow/meta skip assertions."""

    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, query: Any) -> Any:
        self.calls += 1
        from backend.retrieval import RetrievalResult

        return RetrievalResult(
            context="Concept generation covers divergent ideation.",
            chunks=(),
        )


class _NoRetrieve:
    """Fail if retrieval is reached unexpectedly."""

    def retrieve(self, query: Any) -> Any:
        message = getattr(query, "current_message", None) or getattr(
            query, "student_message", ""
        )
        raise AssertionError(f"unexpected retrieval for {message!r}")


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    *,
    auto_advance_stages: bool = False,
    retriever: Any | None = None,
) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance_stages,
        retriever=retriever,
    )


def _unlock_to(store: StudentStore, thread_id: str, stage_id: str) -> None:
    """Move focus to ``stage_id`` with earlier stages completed."""
    if stage_id == "problem_identification":
        return
    idx = _STAGE_IDS.index(stage_id)
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = list(_STAGE_IDS[:idx])
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = stage_id
    store.update_thread(thread_id, metadata=metadata)
    store.select_learning_stage(thread_id, stage_id)


def _journey(store: StudentStore, thread_id: str) -> dict[str, Any]:
    """Return the persisted learning journey mapping."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = metadata.get("learning_journey") or {}
    return journey if isinstance(journey, dict) else {}


def _submit(
    service: CoachApplicationService,
    thread_id: str,
    message: str,
    *,
    stage: str,
    key: str,
) -> Any:
    """Submit one turn at the given authoritative stage."""
    return service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage=stage,
            response_detail="short",
            idempotency_key=key,
        )
    )


@pytest.mark.parametrize("message", _COMPOUND_STATUS)
def test_compound_status_guidance_is_none_not_pure_status(message: str) -> None:
    assert is_current_stage_status_request(message) is False
    assert is_compound_status_guidance_request(message) is True
    assert is_stage_progression_request(message) is False
    assert progression_effect_for(message, current_stage="concept_generation") == "none"


@pytest.mark.parametrize("message", _META_GUIDANCE)
def test_meta_guidance_classifies_as_none_effect(message: str) -> None:
    intent = classify_workflow_intent(message, current_stage="concept_generation")
    assert intent.kind == "meta_guidance"
    assert intent.progression_effect == "none"
    assert is_stage_progression_request(message) is False


@pytest.mark.parametrize(
    ("stage", "message"),
    [
        (stage, message)
        for stage, messages in _PRIOR_BY_STAGE.items()
        for message in messages
    ],
)
def test_prior_stage_review_is_none_effect(stage: str, message: str) -> None:
    intent = classify_workflow_intent(message, current_stage=stage)
    assert intent.kind == "prior_stage_review"
    assert intent.progression_effect == "none"


def test_apply_progression_effect_coerces_advance_only_when_none() -> None:
    assessment = EducationalAssessment(
        current_stage="concept_generation",
        contribution_summary="Checked readiness.",
        stage_assessment="Ready.",
        recommendation=StageDecision.ADVANCE,
        response_mode="coaching",
        readiness_candidate=True,
    )
    stayed = apply_progression_effect(assessment, "none")
    assert stayed.recommendation is StageDecision.STAY
    assert stayed.readiness_candidate is False
    assert stayed.response_mode == "coaching"
    assert apply_progression_effect(assessment, "evaluate") is assessment
    assert apply_progression_effect(assessment, "execute") is assessment


@pytest.mark.parametrize("stage_id", _STAGE_IDS)
def test_compound_status_mock_advance_has_no_side_effects(
    tmp_path, stage_id: str
) -> None:
    store = StudentStore(tmp_path / f"compound-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, stage_id)
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(
            recommendation="advance",
            text="Focus on the next concrete decision for this stage.",
        )
    )
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "what stage am i in and how do i continue",
        stage=stage_id,
        key=f"compound-{stage_id}",
    )

    assert turn.pending_transition is None
    assert turn.auto_advanced_to is None
    assert turn.assessment.recommendation is StageDecision.STAY
    assert STAGE_BY_ID[stage_id].label in turn.response_text
    journey = _journey(store, thread_id)
    assert journey["current_stage"] == stage_id
    completed = list(journey.get("completed_stages") or [])
    assert stage_id not in completed


@pytest.mark.parametrize("stage_id", _STAGE_IDS)
def test_meta_guidance_mock_advance_has_no_side_effects(
    tmp_path, stage_id: str
) -> None:
    store = StudentStore(tmp_path / f"meta-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, stage_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "how do i continue",
        stage=stage_id,
        key=f"meta-{stage_id}",
    )

    assert turn.pending_transition is None
    assert turn.assessment.recommendation is StageDecision.STAY
    journey = _journey(store, thread_id)
    assert journey["current_stage"] == stage_id
    assert stage_id not in list(journey.get("completed_stages") or [])


@pytest.mark.parametrize(
    ("stage_id", "message"),
    [
        (stage, messages[0])
        for stage, messages in _PRIOR_BY_STAGE.items()
    ],
)
def test_prior_stage_review_mock_advance_does_not_complete_current(
    tmp_path, stage_id: str, message: str
) -> None:
    store = StudentStore(tmp_path / f"prior-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, stage_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        message,
        stage=stage_id,
        key=f"prior-{stage_id}",
    )

    assert turn.pending_transition is None
    assert turn.assessment.recommendation is StageDecision.STAY
    journey = _journey(store, thread_id)
    assert journey["current_stage"] == stage_id
    assert stage_id not in list(journey.get("completed_stages") or [])


@pytest.mark.parametrize("stage_id", _STAGE_IDS[1:-1])
def test_explicit_readiness_still_evaluate_may_create_pending(
    tmp_path, monkeypatch: pytest.MonkeyPatch, stage_id: str
) -> None:
    """Skip PI: HMW guard independently blocks ADVANCE without a student HMW."""
    store = StudentStore(tmp_path / f"ready-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, stage_id)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "am i ready to move on",
        stage=stage_id,
        key=f"ready-{stage_id}",
    )

    assert progression_effect_for("am i ready to move on", current_stage=stage_id) == (
        "evaluate"
    )
    assert turn.pending_transition is not None
    assert turn.pending_transition.from_stage == stage_id
    assert "Type exact `confirm` to advance." in turn.response_text


def test_pi_explicit_readiness_evaluate_but_hmw_guard_still_applies(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PI readiness stays EVALUATE; HMW structural guard may still force STAY."""
    store = StudentStore(tmp_path / "ready-pi.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", False)
    assert progression_effect_for(
        "am i ready to move on", current_stage="problem_identification"
    ) == "evaluate"
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "am i ready to move on",
        stage="problem_identification",
        key="ready-pi",
    )

    assert turn.pending_transition is None
    assert turn.assessment.recommendation is StageDecision.STAY


def test_phase1_none_never_auto_advances_even_with_flag(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "phase1-none.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", False)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(
        store,
        client,
        auto_advance_stages=True,
        retriever=_NoRetrieve(),
    )

    turn = _submit(
        service,
        thread_id,
        "what stage am i in and how do i continue",
        stage="problem_identification",
        key="phase1-none",
    )

    assert turn.auto_advanced_to is None
    assert turn.pending_transition is None
    assert _journey(store, thread_id)["current_stage"] == "problem_identification"


def test_phase1_explicit_move_on_still_pending_with_confirm_copy(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "phase1-ready.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "concept_generation")
    monkeypatch.setattr(settings, "student_stage_selection", False)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "can i proceed to the next stage",
        stage="concept_generation",
        key="phase1-ready",
    )

    assert turn.pending_transition is not None
    assert turn.pending_transition.to_stage == "design_specification"
    assert "Type exact `confirm` to advance." in turn.response_text


def test_phase2_linear_select_stage_after_legitimate_advance(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "phase2-select.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "concept_generation")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    first = _submit(
        service,
        thread_id,
        "am i ready to move on",
        stage="concept_generation",
        key="phase2-ready",
    )
    assert first.pending_transition is not None
    assert "is Ready." in first.response_text

    move = _submit(
        service,
        thread_id,
        "Move to Design specification",
        stage="concept_generation",
        key="phase2-move",
    )
    assert move.pending_transition is None
    assert _journey(store, thread_id)["current_stage"] == "design_specification"


@pytest.mark.parametrize("stage_id", _STAGE_IDS)
def test_substantive_work_still_evaluate(tmp_path, stage_id: str) -> None:
    store = StudentStore(tmp_path / f"work-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, stage_id)
    message = _SUBSTANTIVE[stage_id]
    assert progression_effect_for(message, current_stage=stage_id) == "evaluate"
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="stay"))
    service = _service(store, client)

    turn = _submit(
        service,
        thread_id,
        message,
        stage=stage_id,
        key=f"work-{stage_id}",
    )

    assert turn.assessment.response_mode == "coaching"
    assert turn.pending_transition is None


def test_reflection_complete_in_place_preserved_for_genuine_advance(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "reflection-done.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "reflection")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client)

    turn = _submit(
        service,
        thread_id,
        _SUBSTANTIVE["reflection"],
        stage="reflection",
        key="reflection-done",
    )

    assert turn.pending_transition is None
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    journey = _journey(store, thread_id)
    assert journey["current_stage"] == "reflection"
    assert "reflection" in list(journey.get("completed_stages") or [])


def test_terminal_completion_request_preserved(tmp_path) -> None:
    store = StudentStore(tmp_path / "terminal.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "reflection")
    message = "Am I done with the Thinking Path?"
    assert progression_effect_for(message, current_stage="reflection") == "evaluate"
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        message,
        stage="reflection",
        key="terminal",
    )

    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert "reflection" in list(_journey(store, thread_id).get("completed_stages") or [])


def test_workflow_meta_skips_retrieval_with_selected_sources(tmp_path) -> None:
    store = StudentStore(tmp_path / "meta-retrieve.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    from backend.source_library import add_text_source

    add_text_source(
        store,
        thread_id,
        "Week 7 Concept Generation",
        "Concept generation covers divergent ideation.",
    )
    retriever = _CountingRetriever()
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=retriever)

    turn = _submit(
        service,
        thread_id,
        "what stage am i in and how do i continue",
        stage="problem_identification",
        key="meta-retrieve",
    )

    assert retriever.calls == 0
    assert turn.pending_transition is None
    assert workflow_skips_retrieval(
        "what stage am i in and how do i continue",
        current_stage="problem_identification",
    )


def test_genuine_source_qa_still_retrieves(tmp_path) -> None:
    store = StudentStore(tmp_path / "source-qa.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "concept_generation")
    from backend.source_library import add_text_source

    add_text_source(
        store,
        thread_id,
        "Week 7 Concept Generation",
        "Concept generation covers divergent ideation and preference.",
    )
    retriever = _CountingRetriever()
    client = FakeAgentCoreRuntime(payload=_qa_payload())
    service = _service(store, client, retriever=retriever)
    message = "what does Week 7 say about concept generation?"

    assert workflow_skips_retrieval(message, current_stage="concept_generation") is False
    turn = _submit(
        service,
        thread_id,
        message,
        stage="concept_generation",
        key="source-qa",
    )

    assert retriever.calls >= 1
    assert turn.pending_transition is None


def test_none_advance_mock_does_not_persist_proposed_stage_pending(tmp_path) -> None:
    store = StudentStore(tmp_path / "persist-none.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock_to(store, thread_id, "concept_generation")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(
        service,
        thread_id,
        "is my problem identification strong?",
        stage="concept_generation",
        key="persist-none",
    )

    assert turn.pending_transition is None
    assistant = [
        message
        for message in store.get_messages(thread_id)
        if message.get("role") == "assistant"
    ][-1]
    metadata = dict(assistant.get("metadata") or {})
    assert metadata.get("proposed_stage") is None
    assert metadata.get("decision_status") is None
    assert metadata.get("pending_transition_id") is None
    assessment = metadata.get("assessment") or {}
    assert str(assessment.get("recommendation") or "").lower() == "stay"


def test_long_substantive_paragraph_with_next_is_not_meta() -> None:
    message = (
        "I compared two concepts for elderly pedestrian crossings and prefer the "
        "raised table because it slows traffic. Next I will list the constraints "
        "for night-time visibility and maintenance access so the specification is "
        "testable against the council brief."
    )
    intent = classify_workflow_intent(
        message, current_stage="design_specification"
    )
    assert intent.kind == "none"
    assert intent.progression_effect == "evaluate"
