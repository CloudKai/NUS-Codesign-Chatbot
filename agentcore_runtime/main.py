"""Production AgentCore entrypoint for companion specialist invokes.

Copy this package onto the existing runtime
``NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`` and republish a new
READY version. Do not change ``AGENTCORE_RUNTIME_ARN``. Do not create a second
student-facing runtime.

One runtime hosts Q&A, Coaching, and Formative Review. The caller sends
``phase``. Specialists use ``tools=[]`` plus Strands ``structured_output_model``.
The harness never parses ``str(AgentResult)`` as JSON. DSQL history is passed
as Strands ``messages``; AgentCore Memory is not the transcript. The model is
loaded by ``load_runtime_model()`` from explicit environment configuration.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

try:
    from guardrails import enforce_mantle_guardrail
    from model import (
        RuntimeModelError,
        load_runtime_model,
        runtime_model_config_from_environ,
    )
    from models import CoachTurnOutput, QATurnOutput, ReviewTurnOutput
    from specialists.routing import PHASE_QA, PHASE_REVIEW, payload_phase
    from structured_coach import (
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        harness_error_payload,
        log_coach_turn_outcome,
        payload_stage,
        qa_turn_from_agent_result,
        review_turn_from_agent_result,
        specialist_system_prompt,
        structured_wire_payload,
    )
except ImportError:  # pragma: no cover - imported as agentcore_runtime.main
    from agentcore_runtime.guardrails import enforce_mantle_guardrail
    from agentcore_runtime.model import (
        RuntimeModelError,
        load_runtime_model,
        runtime_model_config_from_environ,
    )
    from agentcore_runtime.models import CoachTurnOutput, QATurnOutput, ReviewTurnOutput
    from agentcore_runtime.specialists.routing import (
        PHASE_QA,
        PHASE_REVIEW,
        payload_phase,
    )
    from agentcore_runtime.structured_coach import (
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        harness_error_payload,
        log_coach_turn_outcome,
        payload_stage,
        qa_turn_from_agent_result,
        review_turn_from_agent_result,
        specialist_system_prompt,
        structured_wire_payload,
    )

logger = logging.getLogger("agentcore_runtime")

try:
    from bedrock_agentcore import BedrockAgentCoreApp
except ImportError:  # pragma: no cover - companion tests never import this module
    BedrockAgentCoreApp = None

app = BedrockAgentCoreApp() if BedrockAgentCoreApp is not None else None

_STRUCTURED_CONTRACTS = frozenset({"coach_turn", "qa_turn", "review_turn"})


def _output_model_for(phase: str, output_contract: str) -> type[Any]:
    """Return the Pydantic structured-output class for one specialist invoke."""
    contract = str(output_contract or "").strip().lower()
    if contract == "qa_turn" or phase == PHASE_QA:
        return QATurnOutput
    if contract == "review_turn" or phase == PHASE_REVIEW:
        return ReviewTurnOutput
    return CoachTurnOutput


def _parse_result(phase: str, output_contract: str, result: Any) -> Any:
    """Validate AgentResult against the specialist contract."""
    model = _output_model_for(phase, output_contract)
    if model is QATurnOutput:
        return qa_turn_from_agent_result(result)
    if model is ReviewTurnOutput:
        return review_turn_from_agent_result(result)
    return coach_turn_from_agent_result(result)


async def specialist_invoke(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Invoke one specialist and return validated structured JSON.

    Args:
        payload: Companion InvokeAgentRuntime JSON, including runtime rules
            and Converse ``messages``.

    Returns:
        A validated specialist object, or a category-only error envelope.
        Never returns an empty string, fenced markdown, or ``str(AgentResult)``.
    """
    from strands import Agent

    started = time.monotonic()
    stage = payload_stage(payload)
    phase = payload_phase(payload)
    contract = ""
    if isinstance(payload, Mapping):
        contract = str(payload.get("output_contract") or "").strip().lower()
    system_prompt = specialist_system_prompt(payload)
    prior, prompt = conversation_for_invoke(payload)
    empty_prompt = (isinstance(prompt, str) and not prompt.strip()) or prompt in (
        None,
        [],
        "",
    )
    if empty_prompt:
        log_coach_turn_outcome(
            ok=False,
            category="structured_output_failure",
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload("structured_output_failure")
    try:
        model_config = runtime_model_config_from_environ()
        enforce_mantle_guardrail(str(prompt), config=model_config, source="INPUT")
        model = load_runtime_model(model_config)
    except CoachTurnExtractionError as error:
        log_coach_turn_outcome(
            ok=False,
            category=error.category,
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload(error.category)
    except RuntimeModelError:
        log_coach_turn_outcome(
            ok=False,
            category="unavailable",
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        logger.exception("runtime_model_config_invalid")
        return harness_error_payload("unavailable")
    except Exception:
        log_coach_turn_outcome(
            ok=False,
            category="unavailable",
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        logger.exception("runtime_model_load_failed")
        return harness_error_payload("unavailable")
    agent_kwargs: dict[str, Any] = {
        "model": model,
        "system_prompt": system_prompt,
        "tools": [],
        "callback_handler": None,
    }
    if prior:
        agent_kwargs["messages"] = prior
    agent = Agent(**agent_kwargs)
    result = None
    try:
        result = await agent.invoke_async(
            prompt,
            structured_output_model=_output_model_for(phase, contract),
        )
        output = _parse_result(phase, contract, result)
        output_text = str(getattr(output, "response_text", "") or "")
        enforce_mantle_guardrail(output_text, config=model_config, source="OUTPUT")
        log_coach_turn_outcome(
            ok=True,
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        return structured_wire_payload(output)
    except CoachTurnExtractionError as error:
        log_coach_turn_outcome(
            ok=False,
            category=error.category,
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload(error.category)
    except Exception:
        log_coach_turn_outcome(
            ok=False,
            category="structured_output_failure",
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        logger.exception("specialist_invoke_unhandled")
        return harness_error_payload("structured_output_failure")


async def coach_turn_invoke(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compatibility alias for structured specialist invokes."""
    return await specialist_invoke(payload)


async def _stream_specialist_invoke(payload: Any, context: Any) -> Any:
    """Optional legacy streaming path. Keep this out of structured specialists.

    If this published runtime still serves streaming Q&A, replace this function
    with the existing live ``_stream_specialist_invoke`` implementation. The
    companion application uses structured ``output_contract`` values.
    """
    del payload, context
    return harness_error_payload("unavailable")


if app is not None:

    @app.entrypoint
    async def invoke(payload: Any, context: Any) -> Any:
        """Route companion structured specialists to JSON return; never ``yield``."""
        contract = ""
        if isinstance(payload, dict):
            contract = str(payload.get("output_contract") or "").strip().lower()
        if contract in _STRUCTURED_CONTRACTS or (
            isinstance(payload, dict)
            and payload.get("phase") in {"qa", "coaching", "review"}
        ):
            return await specialist_invoke(payload)
        return await _stream_specialist_invoke(payload, context)
