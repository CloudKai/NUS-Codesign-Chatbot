"""Deterministic AgentCore harness AgentResult → coach_turn tests (no Strands/AWS)."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentcore_runtime.models import CoachTurnOutput
from agentcore_runtime.structured_coach import (
    CoachTurnExtractionError,
    coach_turn_from_agent_result,
    coaching_invoke_prompts,
    inspect_agent_result,
    invoke_failure_category,
    last_user_text,
    log_coach_turn_outcome,
)

_STREET = "A quiet residential street"
_RUNTIME_DIR = Path("agentcore_runtime")


def _assessment(**overrides: Any) -> dict[str, Any]:
    """Return one valid harness assessment object."""
    payload = {
        "current_stage": "problem_identification",
        "contribution_summary": "The student named a specific place.",
        "stage_assessment": "The contribution is a starting point.",
        "critical_understanding_level": "Developing",
        "confidence": 0.6,
        "recommendation": "stay",
        "recommendation_rationale": "The affected people are still unnamed.",
        "guidance_questions": ["Who is affected on that street at night?"],
        "learning_summary": "The student is locating the problem.",
        "citations": [],
        "facione_scores": {
            "analysis": 2,
            "interpretation": 1,
            "inference": 1,
            "evaluation": 1,
            "explanation": 1,
            "self_regulation": 1,
        },
    }
    payload.update(overrides)
    return payload


def _coach_turn(**overrides: Any) -> dict[str, Any]:
    """Return one valid coach_turn mapping."""
    payload: dict[str, Any] = {
        "response_text": "Where does this actually happen, and who is there?",
        "assessment": _assessment(),
        "research_coding": None,
    }
    payload.update(overrides)
    return payload


def _result(**overrides: Any) -> SimpleNamespace:
    """Return a Strands AgentResult-shaped test double."""
    payload = {
        "stop_reason": "end_turn",
        "message": None,
        "structured_output": None,
        "metrics": None,
        "state": None,
        "interrupts": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _text_message(text: str) -> dict[str, Any]:
    """Return a Converse assistant message with one text block."""
    return {"role": "assistant", "content": [{"text": text}]}


def test_harness_package_does_not_import_application_backend() -> None:
    """The deployed runtime must not import companion backend packages."""
    for path in sorted(_RUNTIME_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("backend"), path
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("backend"), path


def test_production_harness_starts_agentcore_app() -> None:
    """Direct-code deploy runs main.py as __main__ and must serve invocations."""
    text = Path("agentcore_runtime/main.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in text
    assert "app.run()" in text


def test_production_harness_never_parses_str_agent_result() -> None:
    """str(AgentResult) must not be the coach_turn contract."""
    for relative in (
        "agentcore_runtime/structured_coach.py",
        "agentcore_runtime/main.py",
        "scripts/agentcore/harness_patch/structured_coach.py",
    ):
        text = Path(relative).read_text(encoding="utf-8")
        assert "json.loads(str(result)" not in text
        assert "json.loads(text)" not in text or "str(result)" not in text
        assert "text = str(result)" not in text


def test_a_structured_output_populated_succeeds() -> None:
    output = CoachTurnOutput.model_validate(_coach_turn())
    parsed = coach_turn_from_agent_result(_result(structured_output=output))
    assert parsed.response_text.startswith("Where does this actually happen")
    assert parsed.assessment.recommendation == "stay"


def test_b_text_json_fallback_succeeds() -> None:
    parsed = coach_turn_from_agent_result(
        _result(message=_text_message(json.dumps(_coach_turn())))
    )
    assert parsed.assessment.current_stage == "problem_identification"


def test_c_no_text_blocks_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(
            _result(message={"role": "assistant", "content": []})
        )
    assert raised.value.category == "structured_output_failure"


def test_d_tool_use_only_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(
            _result(
                message={
                    "role": "assistant",
                    "content": [{"toolUse": {"name": "knowledge_base", "input": {}}}],
                }
            )
        )
    assert raised.value.category == "structured_output_failure"


def test_e_ordinary_prose_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(
            _result(message=_text_message("Here is some coaching without JSON."))
        )
    assert raised.value.category == "structured_output_failure"


def test_f_empty_string_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(_result(message=_text_message("")))
    assert raised.value.category == "structured_output_failure"


def test_g_whitespace_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(_result(message=_text_message("   \n  ")))
    assert raised.value.category == "structured_output_failure"


def test_h_none_literal_fails() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(_result(message=_text_message("None")))
    assert raised.value.category == "structured_output_failure"


def test_i_markdown_fenced_json_is_rejected() -> None:
    fenced = "```json\n" + json.dumps(_coach_turn()) + "\n```"
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(_result(message=_text_message(fenced)))
    assert raised.value.category == "structured_output_failure"


def test_j_schema_invalid_assessment_fails_closed() -> None:
    invalid = _coach_turn(assessment=_assessment(recommendation="maybe"))
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(_result(structured_output=invalid))
    assert raised.value.category == "structured_output_failure"


def test_k_guardrail_intervened_is_safety_blocked() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(
            _result(
                stop_reason="guardrail_intervened",
                structured_output=CoachTurnOutput.model_validate(_coach_turn()),
            )
        )
    assert raised.value.category == "safety_blocked"


def test_timeout_stop_reason_is_timeout() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(
            _result(
                stop_reason="timeout",
                structured_output=CoachTurnOutput.model_validate(_coach_turn()),
            )
        )
    assert raised.value.category == "timeout"


def test_object_stage_assessment_is_coerced_to_text() -> None:
    payload = _coach_turn(
        assessment=_assessment(
            stage_assessment={"text": "The street is named but users are not."}
        )
    )
    parsed = coach_turn_from_agent_result(_result(structured_output=payload))
    assert "users are not" in parsed.assessment.stage_assessment


def test_thirty_kb_history_stays_in_prior_messages() -> None:
    from agentcore_runtime.structured_coach import conversation_for_invoke

    blob = "decision-raised-crossing " * 1400
    assert 30_000 <= len(blob) <= 40_000
    prior, current = conversation_for_invoke(
        {
            "messages": [
                {"role": "user", "content": [{"text": blob}]},
                {"role": "assistant", "content": [{"text": "Who is affected?"}]},
                {"role": "user", "content": [{"text": _STREET}]},
            ]
        }
    )
    assert current == _STREET
    assert blob in prior[0]["content"][0]["text"]
    assert _STREET not in prior[0]["content"][0]["text"]


def test_l_uppercase_stay_is_coerced() -> None:
    payload = _coach_turn(assessment=_assessment(recommendation="STAY"))
    parsed = coach_turn_from_agent_result(_result(structured_output=payload))
    assert parsed.assessment.recommendation == "stay"


def test_str_agent_result_is_never_consulted() -> None:
    class MisleadingResult:
        stop_reason = "end_turn"
        structured_output = None
        message = {"role": "assistant", "content": []}

        def __str__(self) -> str:
            return json.dumps(_coach_turn())

    with pytest.raises(CoachTurnExtractionError) as raised:
        coach_turn_from_agent_result(MisleadingResult())
    assert raised.value.category == "structured_output_failure"


def test_invalid_research_coding_is_dropped() -> None:
    payload = _coach_turn(research_coding={"not": "a-coding"})
    parsed = coach_turn_from_agent_result(_result(structured_output=payload))
    assert parsed.response_text
    assert parsed.research_coding is None


def test_short_street_message_survives_prompt_planning() -> None:
    system_prompt, user_prompt = coaching_invoke_prompts(
        {
            "phase": "coaching",
            "topic": "problem_identification",
            "trusted_instructions": "Guidance mode: Strict.",
            "messages": [
                {"role": "assistant", "content": [{"text": "Where does this actually happen?"}]},
                {"role": "user", "content": [{"text": _STREET}]},
            ],
        }
    )
    assert last_user_text(
        {
            "messages": [
                {"role": "assistant", "content": [{"text": "Where does this actually happen?"}]},
                {"role": "user", "content": [{"text": _STREET}]},
            ]
        }
    ) == _STREET
    assert user_prompt == _STREET
    assert _STREET not in system_prompt
    assert "STAGE: PROBLEM IDENTIFICATION" in system_prompt
    assert "Guidance mode: Strict." in system_prompt
    assert user_prompt.strip()


def test_conversation_for_invoke_keeps_history_out_of_current_prompt() -> None:
    from agentcore_runtime.structured_coach import conversation_for_invoke

    prior, current = conversation_for_invoke(
        {
            "messages": [
                {"role": "user", "content": [{"text": "Earlier decision: raised crossing."}]},
                {"role": "assistant", "content": [{"text": "Who is affected at night?"}]},
                {"role": "user", "content": [{"text": _STREET}]},
            ]
        }
    )
    assert len(prior) == 2
    assert prior[0]["content"][0]["text"] == "Earlier decision: raised crossing."
    assert current == _STREET


def test_unknown_phase_falls_closed_to_coaching_not_qa() -> None:
    from agentcore_runtime.specialists.routing import invoke_kind, payload_phase
    from agentcore_runtime.structured_coach import specialist_system_prompt

    assert payload_phase({"phase": "coach"}) == "coaching"
    assert payload_phase({"phase": "scoring"}) == "review"
    assert invoke_kind({"output_contract": "router_turn"}) == "router"
    assert invoke_kind({"phase": "stage_judge"}) == "specialist"
    assert invoke_kind({"phase": "qa"}) == "specialist"
    system = specialist_system_prompt({"phase": "unknown", "topic": "problem_identification"})
    assert "Coaching specialist" in system
    assert "Q&A specialist" not in system
    qa = specialist_system_prompt({"phase": "qa"})
    assert "Q&A specialist" in qa
    assert "Socratic Thinking Path coaching" in qa
    review = specialist_system_prompt({"phase": "review", "review_mode": "deep"})
    assert "Deep Review specialist" in review
    assert "not a grade" in review.lower()
    incremental = specialist_system_prompt(
        {"phase": "review", "review_mode": "incremental"}
    )
    assert "Incremental Review specialist" in incremental


def test_inspect_and_log_omit_student_text(caplog: pytest.LogCaptureFixture) -> None:
    result = _result(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": _STREET}]},
    )
    shape = inspect_agent_result(result)
    assert shape["structured_output_present"] is False
    assert shape["message_present"] is True
    assert shape["text_blocks"] == 1
    assert shape["tool_blocks"] == 0
    assert shape["stop_reason"] == "end_turn"
    with caplog.at_level(logging.INFO, logger="agentcore_runtime.structured_coach"):
        log_coach_turn_outcome(
            ok=False,
            category="structured_output_failure",
            stage="problem_identification",
            result=result,
            elapsed_ms=912,
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "coach_turn_output_invalid" in joined
    assert "structured_output_present=false" in joined
    assert "text_blocks=1" in joined
    assert "elapsed_ms=912" in joined
    assert _STREET not in joined


def test_invoke_failure_category_maps_auth_to_unavailable() -> None:
    """Mantle 401s are provider unavailability, not malformed structured output."""

    class AuthenticationError(Exception):
        """SDK-shaped auth failure without importing openai."""

    class RateLimitError(Exception):
        """SDK-shaped throttle without importing openai."""

    assert invoke_failure_category(AuthenticationError("access_denied")) == "unavailable"
    assert invoke_failure_category(RateLimitError("slow down")) == "throttled"
    assert invoke_failure_category(TimeoutError()) == "timeout"
    assert invoke_failure_category(RuntimeError("parse")) == "structured_output_failure"
