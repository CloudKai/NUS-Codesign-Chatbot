"""Six evaluation scenarios for the Improve-my-design context spec.

The spec's evaluation table (``docs/operations/COACH_CONTEXT_RESEARCH.md``) lists
six outcomes the coach must reach when the student refers to older work, selects
design evidence, or switches modes:

1. A budget stated many turns earlier is still applied to a later change.
2. A corrected choice surfaces the *current* concept and its constraint, not the
   superseded one.
3. A one-handed design change on a selected sketch needs *no* course search.
4. A question about a named course method *does* retrieve verified course
   evidence.
5. A material absent from the chat is never invented; the coach asks for the
   missing reason.
6. In a mixed chat, an Improve turn is stage-blind, recovers a Design-phase
   constraint, and leaves the pending recommendation available after switching.

Each test drives the real composition or gate the coach uses, so it asserts the
*context that reaches the model* (packing, retrieval scope, stage invariants,
ownership) rather than a live model's reasoning. Deterministic mocks only: the
mock provider is injected and never a paid API, and mock responses cannot measure
recall, which the spec reserves for a separate, explicitly-authorized live model
comparison.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.api import create_app
from backend.coaching.evidence_scope import (
    ScopeInputs,
    ScopeSource,
    decide_first_pass_scope,
)
from backend.domain import CoachRequest
from backend.prompts import compose_coach_prompt
from backend.student_store import StudentStore
from tests.fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the AgentCore adapter against an injected fake client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _assess_payload(
    *,
    intent: str,
    stage: str,
    message: str,
    history: list[dict[str, str]],
) -> str:
    """Compose one coaching turn the way the provider does and return its untrusted turn.

    The provider runs the token-aware planner, derives ``conversation_memory``
    from the aged history, and composes the final untrusted turn the model
    receives. The fake client records that payload; we only read it.
    """
    request = CoachRequest(
        thread_id="thread-scenario",
        student_message=message,
        current_stage=stage,
        response_detail="short",
        interaction_intent=intent,
        history=history,
        conversation_revision=1,
    )
    client = FakeAgentCoreRuntime(
        payload={"mode": "coaching", "response_text": "ok", "recommendation": "stay"}
    )
    _provider(client).assess(request)
    payload = json.loads(client.calls[0]["payload"])
    last = payload["messages"][-1]
    content = last["content"]
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)


def _mem_field(memory_text: str, field: str) -> str:
    """Return the rendered ``field:`` value from a conversation-memory block."""
    index = memory_text.find(f"{field}:")
    if index < 0:
        return ""
    value = memory_text[index + len(field) + 1 :]
    # A field boundary is a top-level ``label:`` line, not a ``- item:`` bullet.
    boundary = re.search(r"(?m)^[a-z][a-z_]*:", value)
    return (value[: boundary.start()] if boundary else value).strip()


def _conversation_memory(untrusted_turn: str) -> str:
    """Extract the ``<conversation_memory>`` block from a composed untrusted turn."""
    match = re.search(
        r"<conversation_memory>(.*?)</conversation_memory>", untrusted_turn, re.S
    )
    return match.group(1).strip() if match else ""


def _scope(message: str, stage: str, intent, sources) -> Any:
    return decide_first_pass_scope(
        ScopeInputs(
            message=message,
            current_stage=stage,
            sources=sources,
            interaction_intent=intent,
        )
    )


def _filler_tail(total: int) -> list[dict[str, str]]:
    """Turns that follow a statement, so the statement ages out of the recent window."""
    turns: list[dict[str, str]] = []
    for index in range(total):
        role = "user" if index % 2 == 0 else "assistant"
        turns.append(
            {
                "role": role,
                "content": (
                    "progress note about the Holland Road crossing"
                    if role == "user"
                    else f"what still needs checking at turn {index}"
                ),
            }
        )
    return turns


# --------------------------------------------------------------------------- #
# Scenario 1 — budget constraint survives many turns and is applied later
# --------------------------------------------------------------------------- #
def test_scenario_one_budget_constraint_reaches_the_model() -> None:
    """$30 budget stated early is still in the context when the student asks for
    an accessible alternative many turns later (spec row 1)."""
    history = [
        {"role": "user", "content": "We can build the sign for at most $30."},
        {"role": "assistant", "content": "Anything else to factor in?"},
    ]
    history += _filler_tail(36)
    untrusted = _assess_payload(
        intent="improve_design",
        stage="concept_generation",
        message="What accessible alternative could we try now?",
        history=history,
    )
    memory = _conversation_memory(untrusted)
    constraint = _mem_field(memory, "constraints")
    assert "$30" in constraint, constraint
    # The current change request is what the model acts on.
    assert "accessible alternative" in untrusted


# --------------------------------------------------------------------------- #
# Scenario 2 — corrected choice surfaces the current concept and its constraint
# --------------------------------------------------------------------------- #
def test_scenario_two_current_concept_and_connectivity_constraint() -> None:
    """QR codes -> pictograms (patchy internet) surfaces the current concept and
    the connectivity constraint, not the superseded QR-code concept (spec row 2)."""
    history = [
        {"role": "user", "content": "We originally chose QR codes to track attendance."},
        {"role": "assistant", "content": "Any constraints on how they attend?"},
        {"role": "user", "content": "The site has patchy internet, so attendance "
            "must work offline."},
        {"role": "assistant", "content": "Should we change the tracking method?"},
        {"role": "user", "content": "Actually we switched to pictograms because of it."},
    ]
    history += _filler_tail(14)
    untrusted = _assess_payload(
        intent="improve_design",
        stage="concept_generation",
        message="Does the latest design still need a phone to work?",
        history=history,
    )
    memory = _conversation_memory(untrusted)
    current_concept = _mem_field(memory, "selected_concept")
    superseded = _mem_field(memory, "changes_in_reasoning")
    # Pictograms is the current concept...
    assert "pictograms" in current_concept, current_concept
    assert "QR codes" not in current_concept, current_concept
    # ...and the superseded QR-code choice is demoted, not kept at equal authority.
    assert "QR codes" in superseded, superseded
    assert "Superseded" in superseded, superseded
    # The connectivity constraint survives into memory.
    constraints = _mem_field(memory, "constraints")
    assert any(
        kw in constraints for kw in ("internet", "offline", "patchy")
    ), constraints


def test_unrelated_budget_correction_preserves_selected_concept() -> None:
    """Correcting the grant is not a new concept selection in provider context."""
    untrusted = _assess_payload(
        intent="improve_design",
        stage="concept_generation",
        message="Does our current concept need a phone?",
        history=[
            {"role": "user", "content": "We chose pictograms for the sign."},
            {"role": "assistant", "content": "What is the budget?"},
            {"role": "user", "content": "Actually the budget is $20 because the grant was cut."},
        ] + _filler_tail(14),
    )
    memory = _conversation_memory(untrusted)
    assert "pictograms" in _mem_field(memory, "selected_concept")
    assert "pictograms" in _mem_field(memory, "key_decisions")
    assert "pictograms" not in _mem_field(memory, "changes_in_reasoning")
    assert "$20" in _mem_field(memory, "constraints")


# --------------------------------------------------------------------------- #
# Scenario 3 — a one-handed design change needs no course search
# --------------------------------------------------------------------------- #
def test_scenario_three_one_handed_change_uses_the_selected_sketch() -> None:
    """A design change on a selected sketch is grounded in the selected artifact,
    with no course-catalog search (spec row 3)."""
    sketch = ScopeSource(source_id="sketch-1", title="Narrow wooden handle")
    decision = _scope(
        "How do I make the narrow handle operable with one hand?",
        "concept_generation",
        "project_coaching",
        (sketch,),
    )
    assert decision.mode_policy.expected_mode == "coaching"
    # The spec's explicit claim: a course search is unnecessary.
    assert decision.include_course_catalog is False
    # The selected sketch grounds the reply directly (kept as evidence).
    assert decision.kept_source_ids == ("sketch-1",)


# --------------------------------------------------------------------------- #
# Scenario 4 — a named-course-method question retrieves verified course evidence
# --------------------------------------------------------------------------- #
def test_scenario_four_course_method_question_fires_course_retrieval() -> None:
    """A question about whether the prototype follows a named course method
    retrieves verified course evidence (spec row 4)."""
    prototype = ScopeSource(source_id="proto-1", title="Selected prototype mockup")
    decision = _scope(
        "What does the CDE2300 course say about usability methods, and does my "
        "selected prototype follow them?",
        "design_specification",
        "project_coaching",
        (prototype,),
    )
    assert decision.include_course_catalog is True
    assert decision.needs_retrieval is True
    # The selected prototype grounds the reply alongside the course evidence.
    assert decision.searches_personal_files is True
    assert decision.kept_source_ids == ("proto-1",)


# --------------------------------------------------------------------------- #
# Scenario 5 — absent material is never invented; the coach asks for it
# --------------------------------------------------------------------------- #
def test_scenario_five_absent_material_is_not_retrieved_or_fabricated() -> None:
    """A question about a rejected material that never appears in the chat is
    personal reasoning: no course search fires and no material is invented
    (spec row 5)."""
    decision = _scope(
        "Why did we reject the bamboo frame?",
        "concept_generation",
        "project_coaching",
        (),
    )
    # Not a course question and no selected source: nothing is searched.
    assert decision.include_course_catalog is False
    assert decision.needs_retrieval is False
    # The composition supplies only the (empty) transcript; the absent material
    # generates no retrieved evidence to fabricate from. The student's own word
    # ("bamboo") is their question, not an invented excerpt.
    untrusted = compose_coach_prompt(
        CoachRequest(
            thread_id="thread-scenario",
            student_message="Why did we reject the bamboo frame?",
            current_stage="concept_generation",
            response_detail="short",
            interaction_intent="project_coaching",
        ),
        include_recent_messages=False,
        context_policy="fast_chat",
    ).untrusted_turn_text
    retrieved = re.search(
        r"<retrieved_course_context>(.*?)</retrieved_course_context>",
        untrusted,
        re.S,
    )
    retrieved_text = retrieved.group(1).strip() if retrieved else ""
    # No evidence was invented about the absent bamboo frame.
    assert "bamboo" not in retrieved_text.lower(), retrieved_text


# --------------------------------------------------------------------------- #
# Scenario 6 — mixed chat: stage-blind Improve, constraint recovery, pending survives
# --------------------------------------------------------------------------- #
def _stage_blind_prompt(intent: str, stage: str, message: str) -> str:
    """Return the composed system prompt for one turn (no provider invoke)."""
    return compose_coach_prompt(
        CoachRequest(
            thread_id="thread-scenario",
            student_message=message,
            current_stage=stage,
            response_detail="short",
            interaction_intent=intent,
        ),
        include_recent_messages=False,
        context_policy="fast_chat",
    )


def test_scenario_six_a_improve_turn_is_stage_blind_and_recovers_the_constraint() -> None:
    """An Improve turn carries no stage instructions yet still packs a Design-phase
    constraint from the aged transcript (spec row 6, composition parts)."""
    stage_prompt = _stage_blind_prompt(
        "project_coaching", "design_specification", "Design-phase coaching turn."
    )
    improve_prompt = _stage_blind_prompt(
        "improve_design", "design_specification", "Could we make this cheaper?"
    )
    # Stage-blind: the Improve request omits application-owned stage instructions.
    assert stage_prompt.stage_instructions.strip(), "expected stage content for coaching"
    assert improve_prompt.stage_instructions.strip() == "", (
        "Improve mode must not carry stage instructions"
    )
    # The aged Design-phase constraint is packed into the Improve turn's memory.
    history = [
        {"role": "user", "content": "We can build the prototype for at most $40."},
        {"role": "assistant", "content": "What constrains the material?"},
    ]
    history += _filler_tail(30)
    untrusted = _assess_payload(
        intent="improve_design",
        stage="design_specification",
        message="Could we make this cheaper to build?",
        history=history,
    )
    constraint = _mem_field(_conversation_memory(untrusted), "constraints")
    assert "$40" in constraint, constraint


def test_scenario_six_b_pending_recommendation_survives_switching_modes(tmp_path: Path) -> None:
    """A pending stage recommendation created during Design coaching is still
    available after the student switches to Improve and back (spec row 6,
    workflow part)."""
    store = StudentStore(tmp_path / "scenario6.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={"response_detail": "short"})
    client = TestClient(create_app(store, auto_advance_stages=False))

    def turn(stage: str, message: str, **overrides) -> dict:
        body = {
            "thread_id": thread_id,
            "current_stage": stage,
            "response_detail": "short",
            "student_message": message,
        }
        body.update(overrides)
        return client.post("/api/v1/coach/turn", json=body)

    # Design coaching states a constraint, then recommends the next stage.
    turn("problem_identification", "We can build the prototype for at most $40.")
    recommendation = turn(
        "problem_identification",
        "How might we improve crossings for older pedestrians so they cross safely?",
    ).json()
    pending = recommendation.get("pending_transition")
    assert pending is not None, "a pending stage recommendation should exist"

    # Switch to Improve while the recommendation is still pending.
    improve_response = turn(
        "problem_identification",
        "Could we make this cheaper to build?",
        interaction_intent="improve_design",
    )
    assert improve_response.status_code == 200, improve_response.text
    improve = improve_response.json()
    # The Improve turn is stage-blind: it does not itself raise a new
    # Thinking Path recommendation.
    assert improve.get("pending_transition") is None

    # Switching back: the same pending recommendation is still resolvable.
    resolution = client.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{pending['id']}/resolve",
        json={"accepted": True},
    )
    assert resolution.status_code == 200, resolution.text
