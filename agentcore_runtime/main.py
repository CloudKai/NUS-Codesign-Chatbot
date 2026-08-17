"""Production AgentCore entrypoint for companion specialist invokes.

Copy this package onto the existing runtime
``NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`` and republish a new
READY version. Do not change ``AGENTCORE_RUNTIME_ARN``. Do not create a second
student-facing runtime.

Normal student chat uses one Haiku ``phase=fast_chat`` invoke. Legacy router,
Q&A, Coaching, Incremental Review, and Deep Review phases remain for
compatibility. Specialists use ``tools=[]`` plus Strands
``structured_output_model`` and a shared ``structured_output_prompt``. The
harness never parses ``str(AgentResult)`` as JSON. DSQL history is passed
as Strands ``messages``; AgentCore Memory is not the transcript. Models are
loaded per role from explicit environment configuration.
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
        MODEL_ROLE_FAST_CHAT,
        MODEL_ROLE_QA,
        MODEL_ROLE_REVIEW_DEEP,
        MODEL_ROLE_REVIEW_INCREMENTAL,
        MODEL_ROLE_ROUTER,
        RuntimeModelError,
        get_role_config,
        get_role_model,
        validate_all_role_configs,
    )
    from models import (
        CoachTurnOutput,
        FastChatTurnOutput,
        QATurnOutput,
        ReviewTurnOutput,
        RouterOutput,
    )
    from router import (
        router_output_from_agent_result,
        router_output_text,
        router_system_prompt,
        router_user_prompt,
    )
    from specialists.routing import (
        PHASE_FAST_CHAT,
        PHASE_QA,
        PHASE_REVIEW,
        PHASE_ROUTER,
        REVIEW_MODE_INCREMENTAL,
        invoke_kind,
        payload_phase,
        payload_review_mode,
    )
    from structured_coach import (
        STRUCTURED_OUTPUT_REPAIR_PROMPT,
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        event_loop_cycle_count_from_agent_result,
        fast_chat_turn_from_agent_result,
        harness_error_payload,
        invoke_failure_category,
        log_coach_turn_outcome,
        log_role_invocation,
        last_user_text,
        payload_stage,
        qa_turn_from_agent_result,
        review_turn_from_agent_result,
        agent_system_prompt,
        model_retry_policy_for_role,
        runtime_model_provenance_fields,
        structured_output_limits_for_role,
        structured_wire_payload,
    )
except ImportError:  # pragma: no cover - imported as agentcore_runtime.main
    from agentcore_runtime.guardrails import enforce_mantle_guardrail
    from agentcore_runtime.model import (
        MODEL_ROLE_COACHING,
        MODEL_ROLE_FAST_CHAT,
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
        FastChatTurnOutput,
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
        PHASE_FAST_CHAT,
        PHASE_QA,
        PHASE_REVIEW,
        PHASE_ROUTER,
        REVIEW_MODE_INCREMENTAL,
        invoke_kind,
        payload_phase,
        payload_review_mode,
    )
    from agentcore_runtime.structured_coach import (
        STRUCTURED_OUTPUT_REPAIR_PROMPT,
        CoachTurnExtractionError,
        conversation_for_invoke,
        coach_turn_from_agent_result,
        elapsed_ms_since,
        event_loop_cycle_count_from_agent_result,
        fast_chat_turn_from_agent_result,
        harness_error_payload,
        invoke_failure_category,
        log_coach_turn_outcome,
        log_role_invocation,
        last_user_text,
        payload_stage,
        qa_turn_from_agent_result,
        review_turn_from_agent_result,
        agent_system_prompt,
        model_retry_policy_for_role,
        runtime_model_provenance_fields,
        structured_output_limits_for_role,
        structured_wire_payload,
    )

logger = logging.getLogger("agentcore_runtime")

try:
    from bedrock_agentcore import BedrockAgentCoreApp
except ImportError:  # pragma: no cover - companion tests never import this module
    BedrockAgentCoreApp = None

app = BedrockAgentCoreApp() if BedrockAgentCoreApp is not None else None

_ROLE_CONFIGS_READY = False


def _with_cache_telemetry(
    payload: dict[str, Any],
    result: Any,
    system_prompt: str | list[dict[str, Any]],
    model_config: Any = None,
) -> dict[str, Any]:
    """Attach numeric cache, cycle, and safe model provenance without student text.

    ``prompt_cache_enabled`` is true only when this invoke actually sent a
    SystemContentBlock cachePoint. Cache token counts and event-loop cycle
    count are copied only when AgentResult metrics expose them. Repair count
    is not stamped: 1.52.0 has no such field. Loaded-model identifiers come
    from the already-resolved runtime config and omit secrets.
    """
    enabled = isinstance(system_prompt, list) and any(
        isinstance(block, Mapping) and "cachePoint" in block for block in system_prompt
    )
    payload["prompt_cache_enabled"] = bool(enabled)
    try:
        from prompt_cache import cache_usage_from_agent_result
    except ImportError:  # pragma: no cover - companion package import
        from agentcore_runtime.prompt_cache import cache_usage_from_agent_result
    payload.update(cache_usage_from_agent_result(result))
    cycle_count = event_loop_cycle_count_from_agent_result(result)
    if cycle_count is not None:
        payload["event_loop_cycle_count"] = cycle_count
    payload.update(runtime_model_provenance_fields(model_config))
    if enabled:
        logger.info(
            "prompt_cache_enabled=true cache_read_input_tokens=%s "
            "cache_write_input_tokens=%s",
            payload.get("cache_read_input_tokens", "absent"),
            payload.get("cache_write_input_tokens", "absent"),
        )
    return payload


def _ensure_role_configs() -> None:
    """Fail closed once if any production role config is unsafe."""
    global _ROLE_CONFIGS_READY
    if _ROLE_CONFIGS_READY:
        return
    validate_all_role_configs()
    _ROLE_CONFIGS_READY = True


def _role_for_payload(payload: Mapping[str, Any] | None) -> str:
    """Map a specialist payload onto a model role."""
    raw_phase = ""
    contract = ""
    if isinstance(payload, Mapping):
        raw_phase = str(payload.get("phase") or "").strip().lower()
        contract = str(payload.get("output_contract") or "").strip().lower()
    if raw_phase == PHASE_FAST_CHAT or contract == "fast_chat_turn":
        return MODEL_ROLE_FAST_CHAT
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
    cleaned_phase = str(phase or "").strip().lower()
    if contract == "fast_chat_turn" or cleaned_phase == PHASE_FAST_CHAT:
        return FastChatTurnOutput
    if contract == "qa_turn" or cleaned_phase == PHASE_QA:
        return QATurnOutput
    if contract == "review_turn" or cleaned_phase == PHASE_REVIEW:
        return ReviewTurnOutput
    return CoachTurnOutput


def _parse_result(phase: str, output_contract: str, result: Any) -> Any:
    """Validate AgentResult against the specialist contract."""
    model = _output_model_for(phase, output_contract)
    if model is FastChatTurnOutput:
        return fast_chat_turn_from_agent_result(result)
    if model is QATurnOutput:
        return qa_turn_from_agent_result(result)
    if model is ReviewTurnOutput:
        return review_turn_from_agent_result(result)
    return coach_turn_from_agent_result(result)


def _retry_strategy_for_role(role: str) -> Any:
    """Return a new Strands ``ModelRetryStrategy`` for one invoke.

    The SDK object is stateful. Never reuse it across Agent instances.

    Args:
        role: Runtime model role id.

    Returns:
        A ``ModelRetryStrategy`` constructed from
        :func:`model_retry_policy_for_role`.
    """
    policy = model_retry_policy_for_role(role)
    try:
        from strands import ModelRetryStrategy
    except ImportError:  # pragma: no cover - 1.52.0 fallback path
        from strands.event_loop._retry import ModelRetryStrategy
    return ModelRetryStrategy(
        max_attempts=policy.max_attempts,
        initial_delay=policy.initial_delay,
        max_delay=policy.max_delay,
    )


def _log_role(
    *,
    role: str,
    started: float,
    success: bool,
    failure_category: str = "",
) -> None:
    """Emit safe per-role provenance without reading student content."""
    limits = structured_output_limits_for_role(role)
    retry = model_retry_policy_for_role(role)
    event_loop_limit_turns = None if limits is None else int(limits.get("turns") or 0) or None
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
            event_loop_limit_turns=event_loop_limit_turns,
            model_retry_max_attempts=retry.max_attempts,
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
        event_loop_limit_turns=event_loop_limit_turns,
        model_retry_max_attempts=retry.max_attempts,
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
    """Run one tools-free structured invoke for a named model role.

    Every Bedrock role passes ``STRUCTURED_OUTPUT_REPAIR_PROMPT`` so Strands'
    structured-output recovery turn is not classified as PROMPT_ATTACK.
    Fast Chat / router / legacy Haiku roles pass ``limits={"turns": 2}``
    (verified 1.52.0: initial generation plus at most one recovery). Deep
    Review passes ``limits={"turns": 3}``. Model retries are a separate
    ``ModelRetryStrategy`` on the Agent, not the event-loop cap.
    """
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
        "retry_strategy": _retry_strategy_for_role(role),
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
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits=structured_output_limits_for_role(role),
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
        payload_out = structured_wire_payload(output)
        return _with_cache_telemetry(
            payload_out, result, system_prompt, model_config
        )
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
    system_prompt = agent_system_prompt(payload)
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


async def fast_chat_invoke(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Invoke one Haiku fast-chat generation for Coaching or Q&A.

    The runtime must not call another AgentCore phase internally. Application
    code issues one ``invoke_agent``. Whether Strands performs one event-loop
    cycle is a live-trace concern, not a unit-test invariant.
    """
    return await _structured_role_invoke(
        role=MODEL_ROLE_FAST_CHAT,
        payload=payload,
        system_prompt=agent_system_prompt(payload),
        user_prompt=conversation_for_invoke(payload)[1],
        output_model=FastChatTurnOutput,
        parse=fast_chat_turn_from_agent_result,
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
        if kind == PHASE_FAST_CHAT:
            return await fast_chat_invoke(payload)
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
