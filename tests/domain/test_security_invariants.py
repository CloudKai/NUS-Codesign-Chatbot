"""Cross-cutting security invariants for the specialist architecture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.domain import (
    CoachRequest,
    StageDecision,
)
from fake_agentcore_runtime import FakeAgentCoreRuntime


_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _output(*, recommendation: StageDecision = StageDecision.STAY) -> dict[str, Any]:
    return {
        "mode": "coaching",
        "response_text": "What still needs evidence?",
        "recommendation": recommendation.value,
        "recommendation_rationale": "More specificity is needed.",
        "citations": [
            {"source_id": "s1", "label": "S1", "title": "Notes", "excerpt": ""}
        ],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }


def test_j_agentcore_memory_is_not_authoritative_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.settings import settings

    monkeypatch.setattr(settings, "agentcore_session_affinity_enabled", False)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN, client=client, region="us-west-2", qualifier="DEFAULT"
    )
    provider.assess(
        CoachRequest(
            thread_id="thread-notebook",
            student_message="A quiet residential street",
            current_stage="problem_identification",
            response_detail="short",
            student_id="cognito:owner",
        )
    )
    payload = json.loads(
        next(
            call
            for call in client.calls
            if json.loads(call["payload"].decode("utf-8")).get("phase") != "router"
        )["payload"].decode("utf-8")
    )
    session_id = str(client.calls[0]["runtimeSessionId"])
    assert session_id.startswith("stateless-")
    for forbidden in ("memoryId", "memory_id", "AgentCoreMemory", "session_manager"):
        assert forbidden not in payload
    assert payload["student_id"] == "cognito:owner"


def test_g_runtime_specialists_have_no_tools() -> None:
    main = Path("agentcore_runtime/main.py").read_text(encoding="utf-8")
    assert "tools=[]" in main
    assert "RetrieveAndGenerate" not in main
    assert "BedrockModel()" not in main
    coaching = Path("agentcore_runtime/specialists/coaching.py").read_text(encoding="utf-8")
    assert "mcp" not in coaching.lower()


def test_f_agent_recommendation_does_not_write_stage_inside_adapter() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.ADVANCE))
    provider = AgentCoreCoachProvider(_RUNTIME_ARN, client=client)
    result = provider.assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message="Older pedestrians wait too long at the crossing.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert result.assessment.recommendation is StageDecision.ADVANCE
    assert result.assessment.current_stage == "problem_identification"
    assert not hasattr(provider, "persist_stage")


def test_normal_assess_never_invokes_router_or_review_phase() -> None:
    """A normal AgentCore assess() must not send router or Review payloads.

    Catch: re-wiring ``assess()`` through ``_resolve_specialist`` or
    ``_invoke_specialist`` would put ``phase=router`` / ``phase=review`` back
    on the student path. This does not close the IAM InvokeAgentRuntime hole
    on the published runtime; it only locks the FastAPI adapter.
    """
    client = FakeAgentCoreRuntime(payload=_output())
    AgentCoreCoachProvider(_RUNTIME_ARN, client=client).assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message="A quiet residential street",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    phases = [
        str(json.loads(call["payload"].decode("utf-8")).get("phase") or "")
        for call in client.calls
    ]
    assert phases == ["fast_chat"]
    assert "router" not in phases
    assert "review" not in phases
    assert "qa" not in phases
    assert "coaching" not in phases
