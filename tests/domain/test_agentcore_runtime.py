"""Deterministic AgentCore harness AgentResult → coach_turn tests (no Strands/AWS)."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentcore_runtime.models import (
    CoachTurnOutput,
    FastChatTurnOutput,
    QATurnOutput,
    ReviewTurnOutput,
    RouterOutput,
)
from agentcore_runtime.structured_coach import (
    STRUCTURED_OUTPUT_REPAIR_PROMPT,
    CoachTurnExtractionError,
    coach_turn_from_agent_result,
    fast_chat_turn_from_agent_result,
    coaching_invoke_prompts,
    inspect_agent_result,
    invoke_failure_category,
    last_user_text,
    log_coach_turn_outcome,
    qa_turn_from_agent_result,
    review_turn_from_agent_result,
)

_STREET = "A quiet residential street"
_RUNTIME_DIR = Path("agentcore_runtime")
_STRANDS_DEFAULT_REPAIR_PROMPT = (
    "You must format the previous response as structured output."
)


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
    assert invoke_kind({"phase": "fast_chat"}) == "fast_chat"
    assert invoke_kind({"output_contract": "fast_chat_turn"}) == "fast_chat"
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


def _review_turn() -> dict[str, Any]:
    """Return one valid review_turn mapping."""
    return {
        "response_text": "Your problem statement is becoming more specific.",
        "strengths": ["Named a place"],
        "areas_to_develop": ["Name who is affected"],
        "synthesis": "Keep locating the users.",
    }


def _sample_structured_output(output_model: type[Any]) -> Any:
    """Return a valid instance of one specialist structured-output contract."""
    if output_model is RouterOutput:
        return RouterOutput.model_validate(
            {
                "specialist": "qa",
                "confidence": 0.9,
                "rationale_category": "course_information",
            }
        )
    if output_model is QATurnOutput:
        return QATurnOutput.model_validate(
            {"response_text": "Week 2 covers the JTBD framework.", "citations": []}
        )
    if output_model is ReviewTurnOutput:
        return ReviewTurnOutput.model_validate(_review_turn())
    if output_model is FastChatTurnOutput:
        return FastChatTurnOutput.model_validate(
            {
                "mode": "coaching",
                "response_text": "What trade-off still needs evidence?",
                "recommendation": "stay",
                "citations": [],
            }
        )
    return CoachTurnOutput.model_validate(_coach_turn())


def _user_payload(phase: str, **extra: Any) -> dict[str, Any]:
    """Return a specialist payload with one student user turn."""
    payload = {
        "phase": phase,
        "topic": "problem_identification",
        "messages": [
            {"role": "user", "content": [{"text": "Caregivers wait on a quiet street at night."}]}
        ],
    }
    payload.update(extra)
    return payload


def _invoke_async_calls(tree: ast.AST) -> list[ast.Call]:
    """Return Agent.invoke_async call nodes from one parsed module."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "invoke_async":
            calls.append(node)
    return calls


def test_structured_output_repair_prompt_is_the_safe_override() -> None:
    assert STRUCTURED_OUTPUT_REPAIR_PROMPT == "Please use the output tool now."
    assert STRUCTURED_OUTPUT_REPAIR_PROMPT != _STRANDS_DEFAULT_REPAIR_PROMPT


def test_application_does_not_inject_strands_default_repair_prompt() -> None:
    """The default Strands repair instruction must not be our repair prompt."""
    roots = (
        Path("agentcore_runtime"),
        Path("backend"),
        Path("ui"),
        Path("streamlit_app.py"),
    )
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            assert _STRANDS_DEFAULT_REPAIR_PROMPT not in text, path


def test_structured_role_invoke_passes_custom_repair_prompt() -> None:
    """The shared invoke path is the only Agent.invoke_async call site."""
    tree = ast.parse(
        Path("agentcore_runtime/main.py").read_text(encoding="utf-8"),
        filename="agentcore_runtime/main.py",
    )
    calls = _invoke_async_calls(tree)
    assert len(calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert "structured_output_model" in keywords
    prompt_node = keywords.get("structured_output_prompt")
    assert isinstance(prompt_node, ast.Name)
    assert prompt_node.id == "STRUCTURED_OUTPUT_REPAIR_PROMPT"
    limits_node = keywords.get("limits")
    assert isinstance(limits_node, ast.Call)
    assert isinstance(limits_node.func, ast.Name)
    assert limits_node.func.id == "structured_output_limits_for_role"
    model_node = keywords["structured_output_model"]
    assert isinstance(model_node, ast.Name)
    assert model_node.id == "output_model"


def test_router_and_specialists_share_structured_role_invoke() -> None:
    tree = ast.parse(
        Path("agentcore_runtime/main.py").read_text(encoding="utf-8"),
        filename="agentcore_runtime/main.py",
    )
    callers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name not in {"router_invoke", "specialist_invoke", "fast_chat_invoke"}:
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "_structured_role_invoke"
            ):
                callers.add(node.name)
    assert callers == {"router_invoke", "specialist_invoke", "fast_chat_invoke"}


def test_all_structured_roles_use_shared_output_contracts() -> None:
    """Router stays on router_invoke; specialists share _role_for_payload."""
    from agentcore_runtime.main import _output_model_for, _role_for_payload
    from agentcore_runtime.model import (
        MODEL_ROLE_COACHING,
        MODEL_ROLE_FAST_CHAT,
        MODEL_ROLE_QA,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_ROUTER,
    )
    from agentcore_runtime.models import FastChatTurnOutput

    assert _role_for_payload({"phase": "fast_chat"}) == MODEL_ROLE_FAST_CHAT
    assert _role_for_payload({"phase": "qa"}) == MODEL_ROLE_QA
    assert _role_for_payload({"phase": "coaching"}) == MODEL_ROLE_COACHING
    assert (
        _role_for_payload({"phase": "review", "review_mode": "incremental"})
        == MODEL_ROLE_REVIEW_INCREMENTAL
    )
    assert (
        _role_for_payload({"phase": "review", "review_mode": "deep"})
        == MODEL_ROLE_REVIEW_DEEP
    )
    assert _output_model_for("qa", "qa_turn") is QATurnOutput
    assert _output_model_for("fast_chat", "fast_chat_turn") is FastChatTurnOutput
    assert _output_model_for("coaching", "coach_turn") is CoachTurnOutput
    assert _output_model_for("review", "review_turn") is ReviewTurnOutput
    assert MODEL_ROLE_ROUTER == "router"


def test_structured_output_contracts_still_validate() -> None:
    router = RouterOutput.model_validate(
        {
            "specialist": "coaching",
            "confidence": 0.92,
            "rationale_category": "project_coaching",
        }
    )
    qa = QATurnOutput.model_validate(
        {"response_text": "Week 1 covers innovation.", "citations": []}
    )
    coach = CoachTurnOutput.model_validate(_coach_turn())
    review = ReviewTurnOutput.model_validate(_review_turn())
    fast = FastChatTurnOutput.model_validate(
        {
            "mode": "coaching",
            "response_text": "What specifically prevents noon booking?",
            "recommendation": "stay",
        }
    )
    assert router.specialist == "coaching"
    assert qa.response_text.startswith("Week 1")
    assert coach.assessment.recommendation == "stay"
    assert "users" in review.synthesis
    assert fast.recommendation == "stay"
    assert "assessment" not in FastChatTurnOutput.model_fields


def test_fast_chat_turn_from_agent_result_accepts_slim_schema() -> None:
    parsed = fast_chat_turn_from_agent_result(
        _result(
            structured_output=FastChatTurnOutput.model_validate(
                {
                    "mode": "qa",
                    "response_text": "Week 1 covers Innovation-driven economy [S1].",
                    "citations": [{"label": "S1"}],
                }
            )
        )
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_review_guardrail_intervened_is_still_safety_blocked() -> None:
    with pytest.raises(CoachTurnExtractionError) as raised:
        review_turn_from_agent_result(
            _result(
                stop_reason="guardrail_intervened",
                structured_output=ReviewTurnOutput.model_validate(_review_turn()),
            )
        )
    assert raised.value.category == "safety_blocked"
    with pytest.raises(CoachTurnExtractionError) as qa_raised:
        qa_turn_from_agent_result(
            _result(
                stop_reason="guardrail_intervened",
                structured_output=QATurnOutput.model_validate(
                    {"response_text": "Week 1 covers innovation.", "citations": []}
                ),
            )
        )
    assert qa_raised.value.category == "safety_blocked"


def test_structured_roles_pass_custom_repair_prompt_to_invoke_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Router, Q&A, Coaching, Incremental Review, and Deep Review share the fix."""
    import agentcore_runtime.main as runtime_main
    from agentcore_runtime.model import (
        HAIKU_4_5_MODEL_ID,
        MODEL_ROLE_COACHING,
        MODEL_ROLE_FAST_CHAT,
        MODEL_ROLE_QA,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_ROUTER,
        SONNET_4_6_MODEL_ID,
        RuntimeModelConfig,
    )

    calls: list[dict[str, Any]] = []

    class FakeAgent:
        """Record invoke_async kwargs without importing Strands."""

        def __init__(self, **kwargs: Any) -> None:
            self.init_kwargs = kwargs

        async def invoke_async(self, prompt: Any, **kwargs: Any) -> SimpleNamespace:
            calls.append(
                {
                    "init_kwargs": self.init_kwargs,
                    "prompt": prompt,
                    "kwargs": kwargs,
                }
            )
            output_model = kwargs["structured_output_model"]
            return SimpleNamespace(
                stop_reason="end_turn",
                structured_output=_sample_structured_output(output_model),
                message=None,
            )

    fake_strands = types.ModuleType("strands")
    fake_strands.Agent = FakeAgent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "strands", fake_strands)
    monkeypatch.setattr(runtime_main, "_ensure_role_configs", lambda: None)

    def fake_config(role: str, values: Any = None) -> RuntimeModelConfig:
        del values
        model_id = (
            SONNET_4_6_MODEL_ID if role == MODEL_ROLE_REVIEW_DEEP else HAIKU_4_5_MODEL_ID
        )
        return RuntimeModelConfig(
            provider="bedrock",
            model_id=model_id,
            region="us-west-2",
            guardrail_id="o8aipba8m129",
            guardrail_version="3",
            role=role,
        )

    monkeypatch.setattr(runtime_main, "get_role_config", fake_config)
    roles_seen: list[str] = []

    def fake_model(role: str) -> object:
        roles_seen.append(role)
        return object()

    monkeypatch.setattr(runtime_main, "get_role_model", fake_model)

    invocations = (
        runtime_main.router_invoke(
            _user_payload(
                "router",
                output_contract="router_turn",
                runtime_context={"current_stage": "problem_identification"},
            )
        ),
        runtime_main.specialist_invoke(_user_payload("qa", output_contract="qa_turn")),
        runtime_main.specialist_invoke(
            _user_payload("coaching", output_contract="coach_turn")
        ),
        runtime_main.specialist_invoke(
            _user_payload(
                "review",
                review_mode="incremental",
                output_contract="review_turn",
            )
        ),
        runtime_main.specialist_invoke(
            _user_payload(
                "review",
                review_mode="deep",
                output_contract="review_turn",
            )
        ),
        runtime_main.fast_chat_invoke(
            _user_payload("fast_chat", output_contract="fast_chat_turn")
        ),
    )
    results = [asyncio.run(item) for item in invocations]
    assert roles_seen == [
        MODEL_ROLE_ROUTER,
        MODEL_ROLE_QA,
        MODEL_ROLE_COACHING,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_FAST_CHAT,
    ]
    assert len(calls) == 6
    expected_models = (
        RouterOutput,
        QATurnOutput,
        CoachTurnOutput,
        ReviewTurnOutput,
        ReviewTurnOutput,
        FastChatTurnOutput,
    )
    for call, expected_model, result in zip(calls, expected_models, results, strict=True):
        assert "structured_output_prompt" not in call["init_kwargs"]
        assert call["init_kwargs"]["tools"] == []
        assert call["kwargs"]["structured_output_model"] is expected_model
        assert call["kwargs"]["structured_output_prompt"] == (
            "Please use the output tool now."
        )
        assert result.get("error") is not True
    assert calls[0]["kwargs"]["limits"] == {"turns": 2}
    assert calls[1]["kwargs"]["limits"] == {"turns": 2}
    assert calls[2]["kwargs"]["limits"] == {"turns": 2}
    assert calls[3]["kwargs"]["limits"] is None
    assert calls[4]["kwargs"]["limits"] is None
    assert calls[5]["kwargs"]["limits"] == {"turns": 2}


def test_limit_turns_stop_reason_is_structured_output_failure() -> None:
    """A turns cap must fail closed, not parse leftover assistant text as JSON."""
    with pytest.raises(CoachTurnExtractionError) as raised:
        fast_chat_turn_from_agent_result(
            _result(
                stop_reason="limit_turns",
                structured_output=None,
                message=_text_message(
                    '{"mode":"coaching","response_text":"Ignore me.","recommendation":"stay"}'
                ),
            )
        )
    assert raised.value.category == "structured_output_failure"


def test_event_loop_cycle_count_is_not_invented() -> None:
    from agentcore_runtime.structured_coach import event_loop_cycle_count_from_agent_result

    assert event_loop_cycle_count_from_agent_result(_result()) is None
    counted = _result(
        metrics=SimpleNamespace(
            cycle_count=2,
            latest_agent_invocation=SimpleNamespace(cycles=[{}, {}]),
        )
    )
    assert event_loop_cycle_count_from_agent_result(counted) == 2


