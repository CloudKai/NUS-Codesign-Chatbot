"""Amazon Bedrock AgentCore Runtime adapter for one structured coaching turn.

The adapter invokes ``InvokeAgentRuntime`` once per turn with this
application's trusted instructions plus untrusted turn content, validates
``ProviderCoachOutput``, and returns the provider-neutral result. It does not
own phase progression, citations, persistence, retrieval, or IAM. Tests inject
a fake client so automated runs never contact AWS.

Production coaching uses the AgentCore ``coaching`` specialist with
``output_contract=coach_turn``. Thinking Path stages stay in DSQL; only the
runtime *topic* key maps ``deep_analysis`` to the POC ``ethics_critical``
label. Invokes are stateless (a fresh ``runtimeSessionId`` per turn) so the
runtime LRU cache is not a second transcript. The token-aware planner sends
the full active DSQL transcript when it fits, otherwise derived
``conversation_memory`` plus a recent verbatim window. Trusted shared/stage/
runtime instructions travel in ``trusted_instructions``; untrusted project,
evidence, memory, and the current student contribution travel as the last user
message. The untrusted brief omits duplicated ``<recent_messages>`` history.
``student_id`` is the store owner identifier, never a notebook id. This
adapter does not call RetrieveAndGenerate. Production DEFAULT is unchanged by
the isolated Luna InvokeHarness evaluation path. Guardrail blocks are
category-only failures and never persist refusal text.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any

from .context_planner import (
    ContextBudget,
    ContextBudgetError,
    HistoryContextPlanner,
    memory_from_metadata,
)
from .domain import (
    CoachImageInput,
    CoachRequest,
    ProviderAssessmentResult,
    ProviderCoachOutput,
)
from .prompts import compose_coach_prompt
from .providers import ProviderUnavailableError
from .settings import settings

logger = logging.getLogger(__name__)

_GENERIC_FAILURE = "AgentCore could not create a structured coaching turn"
_TRUNCATED_FAILURE = "AgentCore truncated the coaching turn"
_MALFORMED_FAILURE = "AgentCore returned a malformed coaching turn"
_BLOCKED_FAILURE = "AgentCore blocked this turn"
_IMAGE_FAILURE = "AgentCore does not support this image type"
_PHASE = "coaching"
_OUTPUT_CONTRACT = "coach_turn"
_TRUSTED_INSTRUCTIONS_FIELD = "trusted_instructions"
_BLOCKED_STOP_REASONS = frozenset({"guardrail_intervened", "content_filtered"})
_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.+)$", re.DOTALL | re.IGNORECASE)
_IMAGE_FORMATS = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_TOPIC_BY_STAGE = {
    "problem_identification": "problem_identification",
    "concept_generation": "concept_generation",
    "design_specification": "design_specification",
    "deep_analysis": "ethics_critical",
    "reflection": "reflection",
}
_THROTTLED_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceQuotaExceededException",
    }
)
_TIMEOUT_CODES = frozenset(
    {
        "ModelTimeoutException",
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
        "TimeoutError",
    }
)
_ACCESS_DENIED_CODES = frozenset(
    {
        "AccessDeniedException",
        "UnrecognizedClientException",
        "ExpiredTokenException",
        "AuthFailure",
        "InvalidSignatureException",
    }
)
_RUNTIME_UNAVAILABLE_CODES = frozenset(
    {
        "ResourceNotFoundException",
        "RuntimeClientError",
        "ServiceException",
        "InternalServerException",
    }
)


def agentcore_topic_for_stage(stage_id: str) -> str:
    """Map a Thinking Path stage id onto the AgentCore coaching topic key.

    Args:
        stage_id: Persisted five-phase stage id from this application.

    Returns:
        The POC runtime topic string. ``deep_analysis`` maps to
        ``ethics_critical`` only at this boundary.
    """
    return _TOPIC_BY_STAGE.get(str(stage_id or "").strip(), "problem_identification")


def _error_code(error: BaseException) -> str:
    """Return a boto/botocore error code without copying AWS message bodies."""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping):
        payload = response.get("Error")
        if isinstance(payload, Mapping):
            code = str(payload.get("Code") or "").strip()
            if code:
                return code
    return type(error).__name__


def _translate_agentcore_error(error: BaseException) -> ProviderUnavailableError:
    """Map SDK/runtime failures to a category-only provider error.

    Args:
        error: The original SDK, timeout, or validation exception.

    Returns:
        A ``ProviderUnavailableError`` whose message never includes AWS bodies,
        credentials, prompts, or student content.
    """
    if isinstance(error, ProviderUnavailableError):
        return error
    code = _error_code(error)
    if code in _THROTTLED_CODES:
        return ProviderUnavailableError(
            "AgentCore is temporarily throttled", category="throttled"
        )
    if code in _TIMEOUT_CODES or isinstance(error, TimeoutError):
        return ProviderUnavailableError("AgentCore timed out", category="timeout")
    if code in _ACCESS_DENIED_CODES:
        return ProviderUnavailableError(
            "AgentCore access was denied", category="access_denied"
        )
    if code in _RUNTIME_UNAVAILABLE_CODES:
        return ProviderUnavailableError(
            "AgentCore runtime is unavailable", category="unavailable"
        )
    return ProviderUnavailableError(_GENERIC_FAILURE, category="unavailable")


def _bytes_from_data_url(data_url: str) -> bytes:
    """Decode one ``data:`` URL into raw image bytes."""
    match = _DATA_URL.match(str(data_url or "").strip())
    if not match:
        raise ProviderUnavailableError(_IMAGE_FAILURE)
    try:
        return base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ProviderUnavailableError(_IMAGE_FAILURE) from error


def _payload_image_block(image: CoachImageInput) -> dict[str, Any]:
    """Map one coach image onto a JSON-safe Converse image content block.

    Args:
        image: A selected notebook image already resolved by the application.

    Returns:
        A content block with base64 image bytes for the runtime JSON payload.

    Raises:
        ProviderUnavailableError: When the MIME type or payload is unsupported.
            Images are never dropped silently.
    """
    mime = str(image.mime or "").strip().lower()
    fmt = _IMAGE_FORMATS.get(mime)
    if fmt is None:
        data_match = _DATA_URL.match(str(image.data_url or "").strip())
        if data_match:
            fmt = _IMAGE_FORMATS.get(str(data_match.group(1) or "").strip().lower())
    if fmt is None:
        raise ProviderUnavailableError(_IMAGE_FAILURE)
    raw = _bytes_from_data_url(image.data_url)
    return {
        "image": {
            "format": fmt,
            "source": {"bytes": base64.b64encode(raw).decode("ascii")},
        }
    }


def _blocked_error() -> ProviderUnavailableError:
    """Return a category-only guardrail-block failure with no refusal text."""
    return ProviderUnavailableError(_BLOCKED_FAILURE, category="safety_blocked")


def _malformed_error() -> ProviderUnavailableError:
    """Return a category-only malformed-output failure."""
    return ProviderUnavailableError(_MALFORMED_FAILURE, category="malformed")


def _mapping_indicates_runtime_block(obj: Any, *, depth: int = 0) -> bool:
    """Return True when a runtime event reports a blocked guardrail assessment."""
    if depth > 10 or not isinstance(obj, Mapping):
        return False
    stop = obj.get("messageStop")
    if isinstance(stop, Mapping):
        if str(stop.get("stopReason") or "") in _BLOCKED_STOP_REASONS:
            return True
    if str(obj.get("stopReason") or "") in _BLOCKED_STOP_REASONS:
        return True
    if str(obj.get("action") or "").upper() == "BLOCKED":
        return True
    for value in obj.values():
        if isinstance(value, Mapping) and _mapping_indicates_runtime_block(
            value, depth=depth + 1
        ):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping) and _mapping_indicates_runtime_block(
                    item, depth=depth + 1
                ):
                    return True
    return False


def _raise_if_runtime_blocked(events: list[Any]) -> None:
    """Fail closed on guardrail intervention before parsing model text.

    Args:
        events: Parsed SSE or Converse-style runtime events.

    Raises:
        ProviderUnavailableError: When the runtime blocked the turn. The error
            never includes refusal text, prompt text, or AWS trace bodies.
    """
    for event in events:
        if isinstance(event, Mapping) and _mapping_indicates_runtime_block(event):
            logger.warning("agentcore_turn_blocked")
            raise _blocked_error()


def _parse_json_object(value: Any) -> dict[str, Any]:
    """Parse a runtime payload into a JSON object without fence fallbacks."""
    if isinstance(value, dict):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise _malformed_error()
    if raw.startswith("```"):
        raise _malformed_error()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise _malformed_error() from error
    if not isinstance(parsed, dict):
        raise _malformed_error()
    return parsed


def _unwrap_runtime_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap common AgentCore envelopes until a coach_turn object remains."""
    current = payload
    for _ in range(4):
        if "response_text" in current and "assessment" in current:
            return current
        nested = current.get("result")
        if nested is None:
            nested = current.get("output")
        if nested is None:
            nested = current.get("coach_turn")
        if isinstance(nested, dict):
            current = nested
            continue
        if isinstance(nested, str):
            current = _parse_json_object(nested)
            continue
        break
    return current


def _text_from_stream_events(events: list[Any]) -> str:
    """Concatenate assistant text and tool-input deltas from runtime events.

    Guardrail intervention is detected across the whole event list before any
    refusal text is assembled or parsed as ``coach_turn`` JSON.
    """
    _raise_if_runtime_blocked(events)
    text_parts: list[str] = []
    tool_parts: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        inner = event.get("event") if isinstance(event.get("event"), Mapping) else event
        if not isinstance(inner, Mapping):
            continue
        stop = inner.get("messageStop")
        if isinstance(stop, Mapping):
            stop_reason = str(stop.get("stopReason") or "")
            if stop_reason == "max_tokens":
                raise ProviderUnavailableError(
                    _TRUNCATED_FAILURE, category="malformed"
                )
            if stop_reason == "timeout_exceeded":
                raise ProviderUnavailableError(_TRUNCATED_FAILURE, category="timeout")
        delta = inner.get("contentBlockDelta")
        if isinstance(delta, Mapping):
            payload = delta.get("delta") if isinstance(delta.get("delta"), Mapping) else delta
            if isinstance(payload, Mapping):
                if isinstance(payload.get("text"), str):
                    text_parts.append(payload["text"])
                tool = payload.get("toolUse")
                if isinstance(tool, Mapping) and "input" in tool:
                    tool_parts.append(str(tool.get("input") or ""))
        if isinstance(inner.get("data"), str):
            text_parts.append(inner["data"])
    if tool_parts:
        return "".join(tool_parts)
    return "".join(text_parts)


def _read_response_bytes(response: Mapping[str, Any]) -> bytes:
    """Read the InvokeAgentRuntime body without copying AWS error messages."""
    body = response.get("response")
    if body is None:
        body = response.get("body")
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    read = getattr(body, "read", None)
    if callable(read):
        payload = read()
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
        if isinstance(payload, str):
            return payload.encode("utf-8")
    if isinstance(body, list):
        chunks: list[bytes] = []
        for chunk in body:
            if isinstance(chunk, (bytes, bytearray)):
                chunks.append(bytes(chunk))
            elif isinstance(chunk, str):
                chunks.append(chunk.encode("utf-8"))
        if chunks:
            return b"".join(chunks)
    iter_lines = getattr(body, "iter_lines", None)
    if callable(iter_lines):
        lines: list[bytes] = []
        for line in iter_lines():
            if isinstance(line, (bytes, bytearray)):
                lines.append(bytes(line))
            elif isinstance(line, str):
                lines.append(line.encode("utf-8"))
        return b"\n".join(lines)
    raise _malformed_error()


def _events_from_sse(raw: str) -> list[Any]:
    """Parse SSE ``data:`` lines into JSON values when present."""
    events: list[Any] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            stripped = stripped[5:].strip()
        if not stripped:
            continue
        try:
            events.append(json.loads(stripped))
        except json.JSONDecodeError:
            events.append(stripped)
    return events


def _payload_from_runtime_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the structured coach_turn object from one runtime response."""
    content_type = str(response.get("contentType") or response.get("content_type") or "")
    raw_bytes = _read_response_bytes(response)
    raw = raw_bytes.decode("utf-8", errors="replace").strip()
    if not raw:
        raise _malformed_error()
    if raw.startswith("```"):
        raise _malformed_error()

    parsed: Any
    if "text/event-stream" in content_type or raw.startswith("data:"):
        events = _events_from_sse(raw)
        mappings = [item for item in events if isinstance(item, Mapping)]
        _raise_if_runtime_blocked(mappings)
        assembled = _text_from_stream_events(mappings)
        if assembled:
            return _unwrap_runtime_object(_parse_json_object(assembled))
        if len(events) == 1 and isinstance(events[0], dict):
            parsed = events[0]
        else:
            raise _malformed_error()
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise _malformed_error() from error

    if isinstance(parsed, list):
        _raise_if_runtime_blocked(parsed)
        assembled = _text_from_stream_events(parsed)
        if assembled:
            return _unwrap_runtime_object(_parse_json_object(assembled))
        raise _malformed_error()
    if not isinstance(parsed, dict):
        raise _malformed_error()
    _raise_if_runtime_blocked([parsed])
    if "event" in parsed or "contentBlockDelta" in parsed:
        assembled = _text_from_stream_events([parsed])
        if assembled:
            return _unwrap_runtime_object(_parse_json_object(assembled))
    return _unwrap_runtime_object(parsed)


def _validated_result(
    payload: dict[str, Any], request: CoachRequest
) -> ProviderAssessmentResult:
    """Validate structured coaching output and force the persisted phase."""
    try:
        turn = ProviderCoachOutput.model_validate(payload)
    except Exception as error:
        raise _malformed_error() from error
    assessment = turn.assessment.model_copy(
        update={"current_stage": request.current_stage}
    )
    return ProviderAssessmentResult(
        response_text=turn.response_text,
        assessment=assessment,
        research_coding=turn.research_coding,
    )


def _stateless_session_id() -> str:
    """Return a unique runtime session id that is never notebook-derived.

    AgentCore requires 33+ characters. A fresh id per invoke keeps DSQL as the
    only durable transcript.
    """
    return f"stateless-{uuid.uuid4().hex}"


def _current_turn_content(
    prompt: str, images: list[CoachImageInput]
) -> list[dict[str, Any]]:
    """Build the current-turn Converse content blocks, including images."""
    content: list[dict[str, Any]] = [{"text": prompt}]
    for image in images:
        content.append(_payload_image_block(image))
    return content


def _planner_from_settings() -> HistoryContextPlanner:
    """Build the production planner from configured conservative token budgets."""
    return HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(settings.model_max_input_tokens),
            output_reserve_tokens=int(settings.model_output_reserve_tokens),
            safety_margin_tokens=int(settings.model_context_safety_margin_tokens),
            recent_verbatim_messages=int(settings.history_recent_verbatim_messages),
        )
    )


class AgentCoreCoachProvider:
    """Call Bedrock AgentCore Runtime for one validated structured coaching turn."""

    provider_id = "agentcore"

    def __init__(
        self,
        runtime_arn: str,
        *,
        region: str = "us-west-2",
        qualifier: str = "DEFAULT",
        timeout_seconds: float = 110.0,
        max_retries: int = 0,
        client: Any | None = None,
        planner: HistoryContextPlanner | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            runtime_arn: AgentCore runtime ARN (non-secret).
            region: AWS region for the data-plane client, typically ``us-west-2``.
            qualifier: Runtime endpoint qualifier, normally ``DEFAULT``.
            timeout_seconds: boto read timeout; retries stay application-owned.
            max_retries: Extra SDK attempts after the first call (0 disables).
            client: Optional injected ``bedrock-agentcore`` client for tests.
            planner: Optional history planner. Defaults to full-history-first
                with extractive compression only (no extra model call).

        Raises:
            ProviderUnavailableError: When ``AGENTCORE_RUNTIME_ARN`` is empty.
        """
        cleaned_arn = str(runtime_arn or "").strip()
        if not cleaned_arn:
            raise ProviderUnavailableError("AGENTCORE_RUNTIME_ARN is not configured")
        self._runtime_arn = cleaned_arn
        self._region = str(region or "").strip() or "us-west-2"
        self._qualifier = str(qualifier or "").strip() or "DEFAULT"
        self._timeout_seconds = float(timeout_seconds)
        self._max_retries = int(max_retries)
        self._client = client
        self._planner = planner or _planner_from_settings()
        self._last_plan = None

    def model_id_for(self, request: CoachRequest) -> str:
        """Return the configured AgentCore runtime ARN."""
        del request
        return self._runtime_arn

    def _runtime_client(self) -> Any:
        """Return the injected client or construct a bedrock-agentcore client."""
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:
            raise ProviderUnavailableError(_GENERIC_FAILURE) from error
        attempts = max(1, self._max_retries + 1)
        config = Config(
            retries={"max_attempts": attempts, "mode": "standard"},
            read_timeout=self._timeout_seconds,
            connect_timeout=min(10.0, self._timeout_seconds),
        )
        self._client = boto3.client(
            "bedrock-agentcore",
            region_name=self._region,
            config=config,
        )
        return self._client

    def _invoke_payload(self, request: CoachRequest) -> dict[str, Any]:
        """Build the JSON payload for one coaching InvokeAgentRuntime call.

        Always sends Converse ``messages``: planner-selected DSQL history plus
        the untrusted current-turn content. Trusted shared/stage/runtime
        instructions travel in ``trusted_instructions``. The untrusted brief
        omits duplicated ``<recent_messages>``. Derived memory appears only in
        ``<conversation_memory>`` when compression was required. A top-level
        ``prompt`` string is never used. Token budgeting still uses the full
        ordered ``composed_text`` so the split cannot overflow the window.
        """
        existing = memory_from_metadata(
            {"conversation_memory": request.conversation_memory},
            conversation_revision=int(request.conversation_revision or 0),
        )
        seed_request = request.model_copy(update={"conversation_memory": None})
        preliminary = compose_coach_prompt(
            seed_request, include_recent_messages=False
        ).composed_text
        try:
            plan = self._planner.plan(
                seed_request,
                prompt_text=preliminary,
                existing_memory=existing,
            )
        except ContextBudgetError as error:
            raise ProviderUnavailableError(
                "AgentCore context exceeds the safe token budget"
            ) from error
        self._last_plan = plan
        planned_request = request
        if plan.compressed_memory is not None:
            planned_request = request.model_copy(
                update={
                    "conversation_memory": plan.compressed_memory.model_dump(mode="json")
                }
            )
        prepared = compose_coach_prompt(
            planned_request, include_recent_messages=False
        )
        messages = list(plan.messages)
        messages.append(
            {
                "role": "user",
                "content": _current_turn_content(
                    prepared.untrusted_turn_text, list(request.image_inputs)
                ),
            }
        )
        payload: dict[str, Any] = {
            "phase": _PHASE,
            "topic": agentcore_topic_for_stage(request.current_stage),
            "output_contract": _OUTPUT_CONTRACT,
            _TRUSTED_INSTRUCTIONS_FIELD: prepared.trusted_instructions,
            "messages": messages,
        }
        student_id = " ".join(str(request.student_id or "").split()).strip()
        if student_id and student_id != str(request.thread_id or "").strip():
            payload["student_id"] = student_id[:128]
        return payload

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Request one structured coaching turn from AgentCore Runtime.

        Args:
            request: Server-built coaching input, including the persisted phase.

        Returns:
            Validated coaching text, assessment, and optional research coding.

        Raises:
            ProviderUnavailableError: When AgentCore cannot produce a valid turn.
        """
        payload = self._invoke_payload(request)
        encoded = json.dumps(payload).encode("utf-8")
        try:
            response = self._runtime_client().invoke_agent_runtime(
                agentRuntimeArn=self._runtime_arn,
                qualifier=self._qualifier,
                runtimeSessionId=_stateless_session_id(),
                payload=encoded,
                contentType="application/json",
                accept="application/json",
            )
            if not isinstance(response, Mapping):
                raise _malformed_error()
            parsed = _payload_from_runtime_response(response)
            result = _validated_result(parsed, request)
            plan = self._last_plan
            memory_payload = request.conversation_memory
            if plan is not None and plan.compressed_memory is not None:
                memory_payload = plan.compressed_memory.model_dump(mode="json")
            return result.model_copy(update={"conversation_memory": memory_payload})
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise _translate_agentcore_error(error) from error
