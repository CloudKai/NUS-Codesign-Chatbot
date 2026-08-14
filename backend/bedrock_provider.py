"""Amazon Bedrock Converse adapter for one structured coaching turn.

The adapter invokes ``bedrock-runtime`` once per turn, validates
``ProviderCoachOutput``, and returns the provider-neutral result. It does not
own phase progression, citations, persistence, retrieval, or IAM. Tests inject
a fake client so automated runs never contact AWS.

Structured output uses one required ``coach_turn`` Converse tool whose input
schema is the provider-neutral Pydantic contract. Markdown fences and prose
are not parsed as a fallback. Application ``[S#]`` citations stay in the
composed prompt; this adapter does not call RetrieveAndGenerate.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Iterator, Mapping
from typing import Any

from .domain import (
    CoachImageInput,
    CoachRequest,
    ProviderAssessmentResult,
    ProviderCoachOutput,
    openai_strict_schema,
)
from .prompts import compose_coach_prompt
from .providers import ProviderUnavailableError

_SYSTEM_TEXT = (
    "You are a university critical-thinking coach. Return the coaching result "
    "only by calling the coach_turn tool."
)
_GENERIC_FAILURE = "Bedrock could not create a structured coaching turn"
_TRUNCATED_FAILURE = "Bedrock truncated the coaching turn"
_MALFORMED_FAILURE = "Bedrock returned a malformed coaching turn"
_TOOL_NAME = "coach_turn"
_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.+)$", re.DOTALL | re.IGNORECASE)
_IMAGE_FORMATS = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
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
_MODEL_UNAVAILABLE_CODES = frozenset(
    {
        "ResourceNotFoundException",
        "ModelNotReadyException",
        "ModelNotAccessibleException",
    }
)
_TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "content_filtered"})


def _inline_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Expand ``$ref`` / ``$defs`` so Bedrock tool schemas stay self-contained.

    Args:
        schema: A JSON Schema object, typically from ``openai_strict_schema``.

    Returns:
        A copy of *schema* with local refs inlined and definition maps removed.
    """
    defs = dict(schema.get("$defs") or schema.get("definitions") or {})

    def resolve(node: Any, stack: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [resolve(item, stack) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            name = ref.rsplit("/", 1)[-1]
            if name in defs and name not in stack:
                return resolve(defs[name], stack | {name})
        return {
            key: resolve(value, stack)
            for key, value in node.items()
            if key not in {"$ref", "$defs", "definitions"}
        }

    return resolve(
        {key: value for key, value in schema.items() if key not in {"$defs", "definitions"}},
        frozenset(),
    )


def _coach_tool_json_schema() -> dict[str, Any]:
    """Return the provider-neutral coach schema for a Bedrock tool input."""
    return _inline_json_schema(openai_strict_schema(ProviderCoachOutput))


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


def _translate_bedrock_error(error: BaseException) -> ProviderUnavailableError:
    """Map SDK/model failures to a category-only provider error.

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
        return ProviderUnavailableError("Bedrock is temporarily throttled")
    if code in _TIMEOUT_CODES or isinstance(error, TimeoutError):
        return ProviderUnavailableError("Bedrock timed out")
    if code in _ACCESS_DENIED_CODES:
        return ProviderUnavailableError("Bedrock access was denied")
    if code in _MODEL_UNAVAILABLE_CODES:
        return ProviderUnavailableError("Bedrock model is unavailable")
    return ProviderUnavailableError(_GENERIC_FAILURE)


def _bytes_from_data_url(data_url: str) -> bytes:
    """Decode one ``data:`` URL into raw image bytes.

    Args:
        data_url: A base64 data URL from ``CoachImageInput``.

    Returns:
        The decoded image bytes.

    Raises:
        ProviderUnavailableError: When the URL is not a supported data URL.
    """
    match = _DATA_URL.match(str(data_url or "").strip())
    if not match:
        raise ProviderUnavailableError("Bedrock does not support this image type")
    try:
        return base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ProviderUnavailableError("Bedrock does not support this image type") from error


def _converse_image_block(image: CoachImageInput) -> dict[str, Any]:
    """Map one coach image input onto a Converse ``image`` content block.

    Args:
        image: A selected notebook image already resolved by the application.

    Returns:
        A Converse content block with raw image bytes.

    Raises:
        ProviderUnavailableError: When the MIME type or payload is unsupported.
    """
    mime = str(image.mime or "").strip().lower()
    fmt = _IMAGE_FORMATS.get(mime)
    if fmt is None:
        data_match = _DATA_URL.match(str(image.data_url or "").strip())
        if data_match:
            fmt = _IMAGE_FORMATS.get(str(data_match.group(1) or "").strip().lower())
    if fmt is None:
        raise ProviderUnavailableError("Bedrock does not support this image type")
    return {
        "image": {
            "format": fmt,
            "source": {"bytes": _bytes_from_data_url(image.data_url)},
        }
    }


def _parse_json_object(value: Any) -> dict[str, Any]:
    """Parse a tool/text payload into a JSON object without fence fallbacks.

    Args:
        value: A dict from Converse ``toolUse.input`` or a JSON string.

    Returns:
        The parsed JSON object.

    Raises:
        ProviderUnavailableError: When the payload is fenced, truncated, or not
            an object.
    """
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


def _payload_from_content_blocks(
    blocks: Any, *, stop_reason: str
) -> dict[str, Any]:
    """Extract the coach_turn tool input (or structured text) from Converse blocks.

    Args:
        blocks: The assistant ``content`` list from Converse or ConverseStream.
        stop_reason: The Converse ``stopReason`` value.

    Returns:
        The structured JSON object for ``ProviderCoachOutput``.

    Raises:
        ProviderUnavailableError: When the stream is truncated, the tool is
            missing, or the payload is not valid structured JSON.
    """
    if stop_reason == "content_filtered":
        raise ProviderUnavailableError(_TRUNCATED_FAILURE)
    if not isinstance(blocks, list) or not blocks:
        if stop_reason in _TRUNCATED_STOP_REASONS:
            raise ProviderUnavailableError(_TRUNCATED_FAILURE)
        raise ProviderUnavailableError(_MALFORMED_FAILURE)

    tool_input: Any = None
    text_parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise ProviderUnavailableError(_MALFORMED_FAILURE)
        tool = block.get("toolUse")
        if isinstance(tool, Mapping) and str(tool.get("name") or "") == _TOOL_NAME:
            tool_input = tool.get("input")
            break
        text = block.get("text")
        if isinstance(text, str) and text:
            text_parts.append(text)

    if stop_reason == "max_tokens" and tool_input is None and not text_parts:
        raise ProviderUnavailableError(_TRUNCATED_FAILURE)

    if tool_input is not None:
        if stop_reason == "max_tokens" and isinstance(tool_input, str):
            try:
                return _parse_json_object(tool_input)
            except ProviderUnavailableError as error:
                raise ProviderUnavailableError(_TRUNCATED_FAILURE) from error
        return _parse_json_object(tool_input)

    if text_parts:
        raw = "".join(text_parts)
        if stop_reason == "max_tokens":
            try:
                return _parse_json_object(raw)
            except ProviderUnavailableError as error:
                raise ProviderUnavailableError(_TRUNCATED_FAILURE) from error
        return _parse_json_object(raw)

    raise ProviderUnavailableError(_MALFORMED_FAILURE)


def _payload_from_converse(response: Mapping[str, Any]) -> dict[str, Any]:
    """Read the structured coach payload from one Converse response.

    Args:
        response: The boto3 ``converse`` mapping.

    Returns:
        The JSON object for ``ProviderCoachOutput``.
    """
    stop_reason = str(response.get("stopReason") or "")
    output = response.get("output")
    message = output.get("message") if isinstance(output, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    return _payload_from_content_blocks(content, stop_reason=stop_reason)


def _iter_stream_events(stream_response: Any) -> Iterator[Any]:
    """Yield ConverseStream events from a boto3-style stream wrapper.

    Args:
        stream_response: Either an iterable or a mapping with a ``stream`` key.

    Yields:
        Individual stream events.
    """
    stream = stream_response
    if isinstance(stream_response, Mapping):
        stream = stream_response.get("stream")
    if stream is None:
        raise ProviderUnavailableError(_MALFORMED_FAILURE)
    try:
        yield from stream
    except Exception as error:
        raise _translate_bedrock_error(error) from error


def _payload_from_stream(stream_response: Any) -> dict[str, Any]:
    """Assemble ConverseStream events into the same JSON object as ``converse``.

    Args:
        stream_response: The boto3 ``converse_stream`` return value.

    Returns:
        The JSON object for ``ProviderCoachOutput``.
    """
    tool_name = ""
    tool_parts: list[str] = []
    text_parts: list[str] = []
    stop_reason = ""
    saw_event = False
    for event in _iter_stream_events(stream_response):
        if not isinstance(event, Mapping):
            raise ProviderUnavailableError(_MALFORMED_FAILURE)
        saw_event = True
        start = event.get("contentBlockStart")
        if isinstance(start, Mapping):
            tool_start = (start.get("start") or {}).get("toolUse") if isinstance(start.get("start"), Mapping) else None
            if isinstance(tool_start, Mapping):
                tool_name = str(tool_start.get("name") or tool_name)
        delta = event.get("contentBlockDelta")
        if isinstance(delta, Mapping):
            inner = delta.get("delta") if isinstance(delta.get("delta"), Mapping) else {}
            if isinstance(inner, Mapping):
                tool_delta = inner.get("toolUse")
                if isinstance(tool_delta, Mapping) and "input" in tool_delta:
                    tool_parts.append(str(tool_delta.get("input") or ""))
                if isinstance(inner.get("text"), str):
                    text_parts.append(inner["text"])
        stop = event.get("messageStop")
        if isinstance(stop, Mapping) and stop.get("stopReason"):
            stop_reason = str(stop.get("stopReason") or "")

    if not saw_event:
        raise ProviderUnavailableError(_MALFORMED_FAILURE)

    blocks: list[dict[str, Any]] = []
    if tool_parts:
        blocks.append(
            {
                "toolUse": {
                    "name": tool_name or _TOOL_NAME,
                    "input": "".join(tool_parts),
                }
            }
        )
    elif text_parts:
        blocks.append({"text": "".join(text_parts)})
    return _payload_from_content_blocks(blocks, stop_reason=stop_reason)


def _validated_result(
    payload: dict[str, Any], request: CoachRequest
) -> ProviderAssessmentResult:
    """Validate structured coaching output and force the persisted phase.

    Args:
        payload: JSON object returned by Converse tool use or structured text.
        request: The server-built coaching request; its stage is authoritative.

    Returns:
        The provider-neutral assessment result.

    Raises:
        ProviderUnavailableError: When coaching fields are invalid. Invalid
            optional research coding is dropped by the domain model.
    """
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


class BedrockCoachProvider:
    """Call Amazon Bedrock Converse for one validated structured coaching turn."""

    provider_id = "bedrock"

    def __init__(
        self,
        model_id: str,
        *,
        region: str = "us-west-2",
        timeout_seconds: float = 110.0,
        max_retries: int = 0,
        client: Any | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            model_id: Bedrock model or inference-profile ID (non-secret).
            region: AWS region for the runtime client, typically ``us-west-2``.
            timeout_seconds: boto read timeout; retries stay application-owned.
            max_retries: Extra SDK attempts after the first call (0 disables).
            client: Optional injected ``bedrock-runtime`` client for tests.

        Raises:
            ProviderUnavailableError: When ``BEDROCK_MODEL_ID`` is empty.
        """
        cleaned_model = str(model_id or "").strip()
        if not cleaned_model:
            raise ProviderUnavailableError("BEDROCK_MODEL_ID is not configured")
        self._model_id = cleaned_model
        self._region = str(region or "").strip() or "us-west-2"
        self._timeout_seconds = float(timeout_seconds)
        self._max_retries = int(max_retries)
        self._client = client

    def model_id_for(self, request: CoachRequest) -> str:
        """Return the configured Bedrock model or inference-profile ID."""
        del request
        return self._model_id

    def _runtime_client(self) -> Any:
        """Return the injected client or construct a bedrock-runtime client.

        Returns:
            A boto3-compatible ``bedrock-runtime`` client.

        Raises:
            ProviderUnavailableError: When boto3 cannot be imported.
        """
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
            "bedrock-runtime",
            region_name=self._region,
            config=config,
        )
        return self._client

    def _converse_kwargs(self, request: CoachRequest) -> dict[str, Any]:
        """Build the single Converse request for this coaching turn.

        Args:
            request: The server-composed coaching request.

        Returns:
            Keyword arguments for ``converse`` / ``converse_stream``.
        """
        prompt = compose_coach_prompt(request).composed_text
        content: list[dict[str, Any]] = [{"text": prompt}]
        for image in request.image_inputs:
            content.append(_converse_image_block(image))
        return {
            "modelId": self._model_id,
            "system": [{"text": _SYSTEM_TEXT}],
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": {"maxTokens": 4096},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": _TOOL_NAME,
                            "description": (
                                "Structured coaching turn for the CDE2300 companion."
                            ),
                            "inputSchema": {"json": _coach_tool_json_schema()},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": _TOOL_NAME}},
            },
        }

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Request one structured coaching turn from Bedrock Converse.

        Args:
            request: Server-built coaching input, including the persisted phase.

        Returns:
            Validated coaching text, assessment, and optional research coding.

        Raises:
            ProviderUnavailableError: When Bedrock cannot produce a valid turn.
        """
        kwargs = self._converse_kwargs(request)
        try:
            response = self._runtime_client().converse(**kwargs)
            if not isinstance(response, Mapping):
                raise ProviderUnavailableError(_MALFORMED_FAILURE)
            payload = _payload_from_converse(response)
            return _validated_result(payload, request)
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise _translate_bedrock_error(error) from error

    def assess_stream(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Assemble ConverseStream into the same validated contract as ``assess``.

        Args:
            request: Server-built coaching input, including the persisted phase.

        Returns:
            The same provider-neutral result shape as ``assess``.

        Raises:
            ProviderUnavailableError: When the stream is truncated, malformed,
                or Bedrock cannot be reached.
        """
        kwargs = self._converse_kwargs(request)
        try:
            stream_fn = getattr(self._runtime_client(), "converse_stream", None)
            if not callable(stream_fn):
                raise ProviderUnavailableError(_GENERIC_FAILURE)
            response = stream_fn(**kwargs)
            payload = _payload_from_stream(response)
            return _validated_result(payload, request)
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise _translate_bedrock_error(error) from error
