"""Cross-cutting security invariants for the specialist architecture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.domain import (
    CitationReference,
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    ProviderCoachOutput,
    StageDecision,
)


_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeAgentCoreRuntime:
    def __init__(self, *, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = payload or {}

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "contentType": "application/json",
            "response": _FakeBody(json.dumps(self._payload).encode("utf-8")),
        }


def _output(*, recommendation: StageDecision = StageDecision.STAY) -> dict[str, Any]:
    envelope = ProviderCoachOutput(
        response_text="What still needs evidence?",
        assessment=EducationalAssessment(
            current_stage="problem_identification",
            contribution_summary="The student named a street.",
            stage_assessment="The contribution is a starting point.",
            critical_understanding_level="Developing",
            confidence=0.6,
            recommendation=recommendation,
            recommendation_rationale="More specificity is needed.",
            guidance_questions=["Who is affected at night?"],
            learning_summary="The student is locating the problem.",
            citations=[
                CitationReference(
                    source_id="s1", label="S1", title="Notes", excerpt=""
                )
            ],
            facione_scores=FacioneDimensionScores(analysis=2),
        ),
        research_coding=None,
    )
    return envelope.model_dump(mode="json")


def test_j_agentcore_memory_is_not_authoritative_transcript() -> None:
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
    payload = json.loads(client.calls[0]["payload"].decode("utf-8"))
    session_id = str(client.calls[0]["runtimeSessionId"])
    assert session_id.startswith("stateless-")
    for forbidden in ("memoryId", "memory_id", "AgentCoreMemory", "session_manager"):
        assert forbidden not in payload
    assert payload["student_id"] == "cognito:owner"


def test_g_runtime_specialists_have_no_tools() -> None:
    main = Path("agentcore_runtime/main.py").read_text(encoding="utf-8")
    assert "tools=[]" in main
    assert "RetrieveAndGenerate" not in main
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
