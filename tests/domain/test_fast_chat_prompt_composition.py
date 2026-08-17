"""Composed Fast Chat system prompt must carry each concern exactly once."""

from __future__ import annotations

from backend.context_planner import estimate_tokens
from backend.domain import CoachRequest
from backend.prompts import compose_coach_prompt
from agentcore_runtime.structured_coach import specialist_system_prompt


def _composed_fast_chat_system_prompt() -> str:
    """Rebuild the Fast Chat system prompt the runtime sends for one turn.

    Uses the same composer + ``specialist_system_prompt`` path as
    ``AgentCoreCoachProvider._invoke_payload`` for a normal
    ``problem_identification`` coaching turn. No AWS or model call.
    """
    request = CoachRequest(
        thread_id="thread-prompt-composition",
        student_message="I think older pedestrians wait too long at the crossing.",
        current_stage="problem_identification",
        response_detail="long",
    )
    prepared = compose_coach_prompt(
        request,
        include_recent_messages=False,
        context_policy="fast_chat",
    )
    return specialist_system_prompt(
        {
            "phase": "fast_chat",
            "topic": "problem_identification",
            "output_contract": "fast_chat_turn",
            "trusted_instructions": prepared.runtime_instructions,
            "runtime_context": {
                "current_stage": "problem_identification",
                "specialist": "fast_chat",
            },
        }
    )


def test_fast_chat_markers_occur_exactly_once() -> None:
    """Facione, tools, contract header, and identity must not be duplicated."""
    system = _composed_fast_chat_system_prompt()
    assert system.count("Do not return Facione scores") == 1
    assert system.count("Do not use application, retrieval, browsing") == 1
    assert system.count("FAST CHAT OUTPUT CONTRACT") == 1
    assert system.count("You are a university educational coach") == 1
    assert '"specialist": "coaching"' not in system
    assert '"specialist": "fast_chat"' in system
    assert "locked Coaching specialist" in system
    assert system.startswith("This turn is Fast Chat")
    assert not system.startswith("You are the Coaching specialist")
    assert "Do not emit an intermediate conversational answer first" in system
    assert "You are not the normal student-facing course assistant" not in system
    assert "You are the normal student-facing course assistant" not in system
    assert "assumptions_identified" not in system
    assert "structured assessment may record" not in system
    assert "FAST CHAT STRUCTURED OUTPUT" not in system
    assert "Return FastChatTurnOutput" not in system
    assert estimate_tokens(system) > 0
    assert "Use Socratic guidance." in system
    assert "STAGE: PROBLEM IDENTIFICATION" in system
    assert "The application, not the model, controls" in system
