"""Amazon Bedrock AgentCore Runtime adapter for one structured coaching turn.

The adapter invokes ``InvokeAgentRuntime`` once per turn with this
application's composed prompt, validates ``ProviderCoachOutput``, and returns
the provider-neutral result. It does not own phase progression, citations,
persistence, retrieval, or IAM. Tests inject a fake client so automated runs
never contact AWS.

Production coaching uses the AgentCore ``coaching`` specialist with
``output_contract=coach_turn``. Thinking Path stages stay in DSQL; only the
runtime *topic* key maps ``deep_analysis`` to the POC ``ethics_critical``
label. Invokes are stateless (a fresh ``runtimeSessionId`` per turn) so the
runtime LRU cache is not a second transcript. This adapter does not call
RetrieveAndGenerate.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from .domain import (
    CoachImageInput,
    CoachRequest,
    ProviderAssessmentResult,
    ProviderCoachOutput,
)
from .prompts import compose_coach_prompt
from .providers import ProviderUnavailableError

_GENERIC_FAILURE = "AgentCore could not create a structured coaching turn"
_TRUNCATED_FAILURE = "AgentCore truncated the coaching turn"
_MALFORMED_FAILURE = "AgentCore returned a malformed coaching turn"
_IMAGE_FAILURE = "AgentCore does not support this image type"
_PHASE = "coaching"
_OUTPUT_CONTRACT = "coach_turn"
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
        return ProviderUnavailableError("AgentCore is temporarily throttled")
    if code in _TIMEOUT_CODES or isinstance(error, TimeoutError):
        return ProviderUnavailableError("AgentCore timed out")
    if code in _ACCESS_DENIED_CODES:
        return ProviderUnavailableError("AgentCore access was denied")
    if code in _RUNTIME_UNAVAILABLE_CODES:
        return ProviderUnavailableError("AgentCore runtime is unavailable")
    return ProviderUnavailableError(_GENERIC_FAILURE)


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


def _parse_json_object(value: Any) -> dict[str, Any]:
    """Parse a runtime payload into a JSON object without fence fallbacks."""
    if isinstance(value, dict):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
    if raw.startswith("```"):
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProviderUnavailableError(_MALFORMED_FAILURE) from error
    if not isinstance(parsed, dict):
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
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
    """Concatenate assistant text and tool-input deltas from runtime events."""
    text_parts: list[str] = []
    tool_parts: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        inner = event.get("event") if isinstance(event.get("event"), Mapping) else event
        if not isinstance(inner, Mapping):
            continue
        stop = inner.get("messageStop")
        if isinstance(stop, Mapping) and str(stop.get("stopReason") or "") in {
            "max_tokens",
            "content_filtered",
            "timeout_exceeded",
        }:
            raise ProviderUnavailableError(_TRUNCATED_FAILURE)
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
    raise ProviderUnavailableError(_MALFORMED_FAILURE)


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
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
    if raw.startswith("```"):
        raise ProviderUnavailableError(_MALFORMED_FAILURE)

    parsed: Any
    if "text/event-stream" in content_type or raw.startswith("data:"):
        events = _events_from_sse(raw)
        assembled = _text_from_stream_events(
            [item for item in events if isinstance(item, Mapping)]
        )
        if assembled:
            return _unwrap_runtime_object(_parse_json_object(assembled))
        if len(events) == 1 and isinstance(events[0], dict):
            parsed = events[0]
        else:
            raise ProviderUnavailableError(_MALFORMED_FAILURE)
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderUnavailableError(_MALFORMED_FAILURE) from error

    if isinstance(parsed, list):
        assembled = _text_from_stream_events(parsed)
        if assembled:
            return _unwrap_runtime_object(_parse_json_object(assembled))
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
    if not isinstance(parsed, dict):
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
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
        raise ProviderUnavailableError(_MALFORMED_FAILURE) from error
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
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            runtime_arn: AgentCore runtime ARN (non-secret).
            region: AWS region for the data-plane client, typically ``us-west-2``.
            qualifier: Runtime endpoint qualifier, normally ``DEFAULT``.
            timeout_seconds: boto read timeout; retries stay application-owned.
            max_retries: Extra SDK attempts after the first call (0 disables).
            client: Optional injected ``bedrock-agentcore`` client for tests.

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
        """Build the JSON payload for one coaching InvokeAgentRuntime call."""
        prompt = compose_coach_prompt(request).composed_text
        payload: dict[str, Any] = {
            "phase": _PHASE,
            "topic": agentcore_topic_for_stage(request.current_stage),
            "output_contract": _OUTPUT_CONTRACT,
        }
        if request.image_inputs:
            content: list[dict[str, Any]] = [{"text": prompt}]
            for image in request.image_inputs:
                content.append(_payload_image_block(image))
            payload["messages"] = [{"role": "user", "content": content}]
        else:
            payload["prompt"] = prompt
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
                raise ProviderUnavailableError(_MALFORMED_FAILURE)
            parsed = _payload_from_runtime_response(response)
            return _validated_result(parsed, request)
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise _translate_agentcore_error(error) from error
