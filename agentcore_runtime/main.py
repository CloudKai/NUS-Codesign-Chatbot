"""Production AgentCore entrypoint for companion specialist invokes.

Copy this package onto the existing runtime
``NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`` and republish a new
READY version. Do not change ``AGENTCORE_RUNTIME_ARN``. Do not create a second
student-facing runtime.

One runtime hosts the Luna router, Q&A, Coaching, Incremental Review, and
Deep Review. The caller sends ``phase`` / ``output_contract`` and
``review_mode`` for Review. Specialists use ``tools=[]`` plus Strands
``structured_output_model``. The harness never parses ``str(AgentResult)``
as JSON. DSQL history is passed as Strands ``messages``; AgentCore Memory
is not the transcript. Models are loaded per role from explicit environment
configuration.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, Callable

try:
    from guardrails import enforce_mantle_guardrail
    from model import (
        MODEL_ROLE_COACHING,
        MODEL_ROLE_QA,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_ROUTER,
        RuntimeModelError,
        get_role_config,
        get_role_model,
        validate_all_role_configs,
    )
    from models import CoachTurnOutput, QATurnOutput, ReviewTurnOutput, RouterOutput
    from router import (
        router_output_from_agent_result,
        router_output_text,
        router_system_prompt,
        router_user_prompt,
    )
    from specialists.routing import (
        PHASE_QA,
        PHASE_REVIEW,
        PHASE_ROUTER,
        REVIEW_MODE_INCREMENTAL,
        invoke_kind,
        payload_phase,
        payload_review_mode,
    )
    from structured_coach import (
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        harness_error_payload,
        invoke_failure_category,
        log_coach_turn_outcome,
        log_role_invocation,
        last_user_text,
        payload_stage,
        qa_turn_from_agent_result,
        review_turn_from_agent_result,
        specialist_system_prompt,
        structured_wire_payload,
    )
except ImportError:  # pragma: no cover - imported as agentcore_runtime.main
    from agentcore_runtime.guardrails import enforce_mantle_guardrail
    from agentcore_runtime.model import (
        MODEL_ROLE_COACHING,
        MODEL_ROLE_QA,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_ROUTER,
        RuntimeModelError,
        get_role_config,
        get_role_model,
        validate_all_role_configs,
    )
    from agentcore_runtime.models import (
        CoachTurnOutput,
        QATurnOutput,
        ReviewTurnOutput,
        RouterOutput,
    )
    from agentcore_runtime.router import (
        router_output_from_agent_result,
        router_output_text,
        router_system_prompt,
        router_user_prompt,
    )
    from agentcore_runtime.specialists.routing import (
        PHASE_QA,
        PHASE_REVIEW,
        PHASE_ROUTER,
        REVIEW_MODE_INCREMENTAL,
        invoke_kind,
        payload_phase,
        payload_review_mode,
    )
    from agentcore_runtime.structured_coach import (
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        harness_error_payload,
        invoke_failure_category,
        log_coach_turn_outcome,
        log_role_invocation,
        last_user_text,
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

_ROLE_CONFIGS_READY = False


def _ensure_role_configs() -> None:
    """Fail closed once if any production role config is unsafe."""
    global _ROLE_CONFIGS_READY
    if _ROLE_CONFIGS_READY:
        return
    validate_all_role_configs()
    _ROLE_CONFIGS_READY = True


def _role_for_payload(payload: Mapping[str, Any] | None) -> str:
    """Map a specialist payload onto a model role."""
    phase = payload_phase(payload)
    if phase == PHASE_QA:
        return MODEL_ROLE_QA
    if phase == PHASE_REVIEW:
        if payload_review_mode(payload) == REVIEW_MODE_INCREMENTAL:
            return MODEL_ROLE_REVIEW_INCREMENTAL
        return MODEL_ROLE_REVIEW_DEEP
    return MODEL_ROLE_COACHING


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


def _log_role(
    *,
    role: str,
    started: float,
    success: bool,
    failure_category: str = "",
) -> None:
    """Emit safe per-role provenance without reading student content."""
    try:
        config = get_role_config(role)
    except RuntimeModelError:
        log_role_invocation(
            role=role,
            provider="unknown",
            model_id="unknown",
            latency_ms=elapsed_ms_since(started),
            success=success,
            failure_category=failure_category or "unavailable",
            guardrail_configured=False,
        )
        return
    log_role_invocation(
        role=role,
        provider=config.provider,
        model_id=config.model_id,
        latency_ms=elapsed_ms_since(started),
        success=success,
        failure_category=failure_category,
        guardrail_configured=bool(config.guardrail_id and config.guardrail_version),
    )


async def _structured_role_invoke(
    *,
    role: str,
    payload: Mapping[str, Any] | None,
    system_prompt: str,
    user_prompt: Any,
    output_model: type[Any],
    parse: Callable[[Any], Any],
    output_text: Callable[[Any], str],
    include_history: bool,
) -> dict[str, Any]:
    """Run one tools-free structured invoke for a named model role."""
    from strands import Agent

    started = time.monotonic()
    stage = payload_stage(payload)
    empty_prompt = (
        user_prompt in (None, [], "")
        or (isinstance(user_prompt, str) and not user_prompt.strip())
    )
    if empty_prompt:
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category="structured_output_failure",
        )
        log_coach_turn_outcome(
            ok=False,
            category="structured_output_failure",
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload("structured_output_failure")
    try:
        _ensure_role_configs()
        model_config = get_role_config(role)
        if isinstance(user_prompt, str):
            untrusted = user_prompt
        else:
            untrusted = last_user_text(payload)
        if untrusted:
            enforce_mantle_guardrail(untrusted, config=model_config, source="INPUT")
        model = get_role_model(role)
    except CoachTurnExtractionError as error:
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category=error.category,
        )
        log_coach_turn_outcome(
            ok=False,
            category=error.category,
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload(error.category)
    except RuntimeModelError:
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category="unavailable",
        )
        log_coach_turn_outcome(
            ok=False,
            category="unavailable",
            stage=stage,
            elapsed_ms=elapsed_ms_since(started),
        )
        logger.exception("runtime_model_config_invalid")
        return harness_error_payload("unavailable")
    except Exception:
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category="unavailable",
        )
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
    if include_history:
        prior, _current = conversation_for_invoke(payload)
        if prior:
            agent_kwargs["messages"] = prior
    agent = Agent(**agent_kwargs)
    result = None
    try:
        result = await agent.invoke_async(
            user_prompt,
            structured_output_model=output_model,
        )
        output = parse(result)
        enforce_mantle_guardrail(
            output_text(output), config=model_config, source="OUTPUT"
        )
        _log_role(role=role, started=started, success=True)
        log_coach_turn_outcome(
            ok=True,
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        return structured_wire_payload(output)
    except CoachTurnExtractionError as error:
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category=error.category,
        )
        log_coach_turn_outcome(
            ok=False,
            category=error.category,
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        return harness_error_payload(error.category)
    except Exception as error:
        category = invoke_failure_category(error)
        _log_role(
            role=role,
            started=started,
            success=False,
            failure_category=category,
        )
        log_coach_turn_outcome(
            ok=False,
            category=category,
            stage=stage,
            result=result,
            elapsed_ms=elapsed_ms_since(started),
        )
        logger.exception("specialist_invoke_unhandled")
        return harness_error_payload(category)


async def specialist_invoke(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Invoke one specialist and return validated structured JSON.

    Args:
        payload: Companion InvokeAgentRuntime JSON, including runtime rules
            and Converse ``messages``.

    Returns:
        A validated specialist object, or a category-only error envelope.
        Never returns an empty string, fenced markdown, or ``str(AgentResult)``.
    """
    phase = payload_phase(payload)
    contract = ""
    if isinstance(payload, Mapping):
        contract = str(payload.get("output_contract") or "").strip().lower()
    system_prompt = specialist_system_prompt(payload)
    prior, prompt = conversation_for_invoke(payload)
    del prior
    return await _structured_role_invoke(
        role=_role_for_payload(payload),
        payload=payload,
        system_prompt=system_prompt,
        user_prompt=prompt,
        output_model=_output_model_for(phase, contract),
        parse=lambda result: _parse_result(phase, contract, result),
        output_text=lambda output: str(getattr(output, "response_text", "") or ""),
        include_history=True,
    )


async def router_invoke(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Classify one free-text message as qa, coaching, or review."""
    return await _structured_role_invoke(
        role=MODEL_ROLE_ROUTER,
        payload=payload,
        system_prompt=router_system_prompt(),
        user_prompt=router_user_prompt(payload),
        output_model=RouterOutput,
        parse=router_output_from_agent_result,
        output_text=router_output_text,
        include_history=False,
    )


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
        kind = invoke_kind(payload if isinstance(payload, dict) else None)
        if kind == PHASE_ROUTER:
            return await router_invoke(payload)
        if kind == "specialist":
            return await specialist_invoke(payload)
        return await _stream_specialist_invoke(payload, context)


if __name__ == "__main__":
    # AgentCore executes `main.py` as __main__. Without app.run() the process
    # imports and exits, and InvokeAgentRuntime returns HTTP 502.
    if app is None:
        raise RuntimeError("bedrock-agentcore is required to start this runtime")
    app.run()
