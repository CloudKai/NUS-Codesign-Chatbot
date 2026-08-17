"""Amazon Bedrock AgentCore Runtime adapter for one structured specialist turn.

Normal student chat makes exactly one ``InvokeAgentRuntime`` call:

``phase=fast_chat`` / Claude Haiku 4.5

That call both classifies Coaching vs Q&A and generates the student reply.
Incremental Review and the Haiku router are not on the active path.
Deep Sonnet Review remains an explicit ``specialist=review`` operation.

The published runtime still dispatches leftover ``phase`` values for any
principal with ``bedrock-agentcore:InvokeAgentRuntime``. This adapter must
not send those phases. FastAPI authorization does not apply to that IAM
call. See ``docs/SECURITY_BOUNDARIES.md``.

The adapter does not own phase progression, citations, persistence,
retrieval, or IAM. Tests inject a fake client so automated runs never
contact AWS. Planner output is request-local so one cached provider
instance may coach two notebooks for the same owner without cross-notebook
memory contamination.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentcore_runtime.model import HAIKU_4_5_MODEL_ID, SONNET_4_6_MODEL_ID
from agentcore_runtime.models import (
    FastChatContractError,
    ReviewTurnOutput,
    RouterOutput,
    adapt_fast_chat_turn_payload,
    fast_chat_payload_shape_log,
)

from .coaching.mode_policy import enforce_model_mode, policy_from_request
from .context_planner import (
    CONTEXT_POLICY_FAST_CHAT,
    CONTEXT_POLICY_FULL_HISTORY,
    ContextBudget,
    ContextBudgetError,
    HistoryContextPlanner,
    ModelContextPlan,
    estimate_tokens,
    memory_from_metadata,
)
from .domain import (
    CitationReference,
    CoachImageInput,
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    ProviderAssessmentResult,
    ProviderCoachOutput,
    StageDecision,
)
from .prompts import compose_coach_prompt
from .providers import ProviderUnavailableError
from .settings import settings
from .turn_perf import (
    begin_coach_turn_perf,
    current_perf,
    elapsed_ms,
    emit_coach_turn_perf,
    record_failure,
    record_field,
    record_success,
)
from .specialists.review_orchestration import (
    REVIEW_DEPTH_DEEP,
    REVIEW_DEPTH_INCREMENTAL,
)
from .specialists.routing import (
    ALLOWED_SPECIALISTS,
    SPECIALIST_COACHING,
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    apply_semantic_route,
    bound_router_min_confidence,
    select_specialist,
)

logger = logging.getLogger(__name__)

_GENERIC_FAILURE = "AgentCore could not create a structured coaching turn"
_TRUNCATED_FAILURE = "AgentCore truncated the coaching turn"
_MALFORMED_FAILURE = "The coach reply could not be completed"
_BLOCKED_FAILURE = "AgentCore blocked this turn"
_IMAGE_FAILURE = "AgentCore does not support this image type"
_OUTPUT_CONTRACT = "coach_turn"
_FAST_CHAT_CONTRACT = "fast_chat_turn"
_FAST_CHAT_PHASE = "fast_chat"
_CONTRACT_BY_SPECIALIST = {
    SPECIALIST_QA: "qa_turn",
    SPECIALIST_COACHING: "coach_turn",
    SPECIALIST_REVIEW: "review_turn",
}
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
    if isinstance(error, json.JSONDecodeError) or type(error).__name__ == "JSONDecodeError":
        return ProviderUnavailableError(
            _MALFORMED_FAILURE, category="structured_output_failure"
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
    """Return a category-only structured-output failure."""
    return ProviderUnavailableError(
        _MALFORMED_FAILURE, category="structured_output_failure"
    )


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
            logger.warning(
                "agentcore_turn_blocked source=runtime_event %s",
                fast_chat_payload_shape_log(event),
            )
            raise _blocked_error()


def _raise_if_harness_error_envelope(payload: Mapping[str, Any]) -> None:
    """Map a harness category-only error envelope before coach_turn validation.

    The production harness returns ``{"ok": false, "error": true, "category": ...}``
    instead of raising JSONDecodeError on an empty ``str(AgentResult)``.
    """
    if payload.get("error") is not True and payload.get("ok") is not False:
        return
    if "response_text" in payload and "assessment" in payload:
        return
    category = str(payload.get("category") or "").strip()
    logger.warning(
        "agentcore_turn_blocked source=envelope category=%s %s",
        category or "-",
        fast_chat_payload_shape_log(payload),
    )
    if category == "safety_blocked":
        raise _blocked_error()
    if category == "timeout":
        raise ProviderUnavailableError(_TRUNCATED_FAILURE, category="timeout")
    if category == "throttled":
        raise ProviderUnavailableError(
            "AgentCore is temporarily throttled", category="throttled"
        )
    if category in {"structured_output_failure", "malformed"}:
        raise _malformed_error()
    raise ProviderUnavailableError(_GENERIC_FAILURE, category="unavailable")


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
        if "response_text" in current and (
            "assessment" in current or "mode" in current
        ):
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


def _final_coach_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap envelopes, then fail closed on a harness error object."""
    unwrapped = _unwrap_runtime_object(payload)
    _raise_if_harness_error_envelope(unwrapped)
    return unwrapped


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
                    _TRUNCATED_FAILURE, category="structured_output_failure"
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
            return _final_coach_payload(_parse_json_object(assembled))
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
            return _final_coach_payload(_parse_json_object(assembled))
        raise _malformed_error()
    if not isinstance(parsed, dict):
        raise _malformed_error()
    _raise_if_runtime_blocked([parsed])
    if "event" in parsed or "contentBlockDelta" in parsed:
        assembled = _text_from_stream_events([parsed])
        if assembled:
            return _final_coach_payload(_parse_json_object(assembled))
    return _final_coach_payload(parsed)


def _request_specialist(request: CoachRequest) -> str:
    """Return the specialist already stamped on a routed request.

    Args:
        request: Coach request whose ``specialist`` must already be
            server-resolved. This helper does not call the Haiku router.

    Returns:
        ``qa``, ``coaching``, or ``review``.
    """
    return select_specialist(
        request.student_message,
        requested=request.specialist,
    )


def _runtime_context(
    request: CoachRequest,
    specialist: str,
    *,
    review_mode: str | None = None,
    review_trigger: str | None = None,
) -> dict[str, Any]:
    """Return application-owned runtime constraints for the AgentCore specialist.

    Fast Chat stamps ``specialist=fast_chat`` plus an optional
    ``expected_response_mode``. It must not claim ``specialist=coaching``
    while asking Haiku to choose Coaching versus Q&A.
    """
    labels = sorted(
        {
            str(chunk.label).strip()
            for chunk in request.retrieved_chunks
            if str(chunk.label or "").strip()
        }
    )
    cleaned = str(specialist or "").strip().lower()
    context: dict[str, Any] = {
        "current_stage": request.current_stage,
        "agentcore_topic": agentcore_topic_for_stage(request.current_stage),
        "response_detail": "quick" if request.response_detail == "short" else "strict",
        "language": request.response_language,
        "allowed_citations": labels,
        "allow_model_knowledge": bool(request.allow_model_knowledge),
        "conversation_revision": request.conversation_revision,
    }
    if cleaned == _FAST_CHAT_PHASE:
        context["specialist"] = _FAST_CHAT_PHASE
        expected = str(request.expected_response_mode or "").strip().lower()
        if expected in {"qa", "coaching"}:
            context["expected_response_mode"] = expected
    elif cleaned in ALLOWED_SPECIALISTS:
        context["specialist"] = cleaned
    else:
        context["specialist"] = SPECIALIST_COACHING
    if review_mode in {REVIEW_DEPTH_INCREMENTAL, REVIEW_DEPTH_DEEP}:
        context["review_mode"] = review_mode
    if review_trigger:
        context["review_trigger"] = str(review_trigger)
    return context


def _citations_from_items(items: Any) -> list[CitationReference]:
    """Map specialist citation objects onto application citation references."""
    citations: list[CitationReference] = []
    if not isinstance(items, list):
        return citations
    for item in items:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        citations.append(
            CitationReference(
                source_id=str(item.get("source_id") or "").strip(),
                label=label,
                title=str(item.get("title") or "").strip(),
                excerpt=str(item.get("excerpt") or "").strip(),
            )
        )
    return citations


def _fast_chat_assessment(
    request: CoachRequest,
    *,
    mode: str,
    recommendation: StageDecision | None,
    recommendation_rationale: str,
    citations: list[CitationReference] | None = None,
) -> EducationalAssessment:
    """Build the slim persisted assessment for one Fast Chat turn.

    Facione, review lists, and research coding are omitted. Historical rows
    may still contain those fields; new turns do not invent them.
    """
    return EducationalAssessment(
        current_stage=request.current_stage,
        recommendation=recommendation,
        recommendation_rationale=str(recommendation_rationale or ""),
        citations=citations or [],
        response_mode=mode,
        readiness_candidate=recommendation is StageDecision.ADVANCE,
    )


def _stay_assessment(
    request: CoachRequest,
    *,
    contribution_summary: str,
    stage_assessment: str,
    recommendation_rationale: str,
    learning_summary: str,
    citations: list[CitationReference] | None = None,
    review_strengths: list[str] | None = None,
    review_improvements: list[str] | None = None,
    facione_scores: FacioneDimensionScores | None = None,
) -> EducationalAssessment:
    """Build a non-transitioning assessment for Q&A or Review specialists."""
    summary = " ".join(str(contribution_summary or request.student_message).split())[:500]
    return EducationalAssessment(
        current_stage=request.current_stage,
        contribution_summary=summary or "Student asked a course or review question.",
        stage_assessment=stage_assessment,
        critical_understanding_level="Not assessed",
        confidence=0.5,
        recommendation=StageDecision.STAY,
        recommendation_rationale=recommendation_rationale,
        guidance_questions=[],
        learning_summary=learning_summary,
        citations=citations or [],
        facione_scores=facione_scores or FacioneDimensionScores(),
        review_strengths=review_strengths or [],
        review_improvements=review_improvements or [],
    )


def _validated_result(
    payload: dict[str, Any], request: CoachRequest
) -> ProviderAssessmentResult:
    """Validate structured specialist output and force the persisted phase.

    Q&A never persists a stage transition. Coaching ADVANCE is treated as a
    readiness candidate only. Incremental Review cannot advance. Deep Review
    may record readiness information; FastAPI does not execute a stage
    transition from that recommendation.
    """
    specialist = _request_specialist(request)
    if specialist == SPECIALIST_QA:
        if isinstance(payload.get("assessment"), Mapping):
            try:
                turn = ProviderCoachOutput.model_validate(payload)
            except Exception as error:
                raise _malformed_error() from error
            assessment = turn.assessment.model_copy(
                update={
                    "current_stage": request.current_stage,
                    "recommendation": StageDecision.STAY,
                    "recommendation_rationale": (
                        "Q&A specialist does not recommend Thinking Path changes."
                    ),
                }
            )
            return ProviderAssessmentResult(
                response_text=turn.response_text,
                assessment=assessment,
                research_coding=None,
            )
        text = str(payload.get("response_text") or "").strip()
        if not text:
            raise _malformed_error()
        return ProviderAssessmentResult(
            response_text=text,
            assessment=_stay_assessment(
                request,
                contribution_summary=request.student_message,
                stage_assessment="Course-information question; Thinking Path stage unchanged.",
                recommendation_rationale="Q&A specialist does not recommend Thinking Path changes.",
                learning_summary="The student asked a course-information question.",
                citations=_citations_from_items(payload.get("citations")),
            ),
            research_coding=None,
        )
    if specialist == SPECIALIST_REVIEW:
        if isinstance(payload.get("assessment"), Mapping):
            try:
                turn = ProviderCoachOutput.model_validate(payload)
            except Exception as error:
                raise _malformed_error() from error
            assessment = turn.assessment.model_copy(
                update={
                    "current_stage": request.current_stage,
                    "recommendation": StageDecision.STAY,
                    "recommendation_rationale": (
                        "Formative Review does not recommend Thinking Path changes."
                    ),
                }
            )
            return ProviderAssessmentResult(
                response_text=turn.response_text,
                assessment=assessment,
                research_coding=None,
            )
        text = str(payload.get("response_text") or "").strip()
        synthesis = str(payload.get("synthesis") or "").strip()
        if not text:
            raise _malformed_error()
        strengths = [
            str(item).strip()
            for item in (payload.get("strengths") or [])
            if str(item).strip()
        ]
        improvements = [
            str(item).strip()
            for item in (payload.get("areas_to_develop") or [])
            if str(item).strip()
        ]
        facione = None
        profile = payload.get("facione_profile")
        if isinstance(profile, Mapping):
            try:
                facione = FacioneDimensionScores.model_validate(profile)
            except Exception:
                facione = None
        return ProviderAssessmentResult(
            response_text=text,
            assessment=_stay_assessment(
                request,
                contribution_summary=request.student_message,
                stage_assessment=synthesis or "Formative review of progress so far.",
                recommendation_rationale="Formative Review does not recommend Thinking Path changes.",
                learning_summary=synthesis or "Formative review of the student's reasoning.",
                citations=_citations_from_items(payload.get("citations")),
                review_strengths=strengths[:4],
                review_improvements=improvements[:4],
                facione_scores=facione,
            ),
            research_coding=None,
        )
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


def _allowed_citation_labels(request: CoachRequest) -> set[str]:
    """Return FastAPI-supplied [S#] labels that Haiku may cite."""
    return {
        str(chunk.label).strip()
        for chunk in request.retrieved_chunks
        if str(chunk.label or "").strip()
    }


def _record_runtime_cache_metrics(payload: dict[str, Any]) -> None:
    """Copy safe cache telemetry from the runtime JSON onto coach_turn_perf.

    Missing keys are left unset. A cache hit is recorded only when the runtime
    supplied a non-negative ``cache_read_input_tokens`` integer.
    """
    if "prompt_cache_enabled" in payload:
        record_field("prompt_cache_enabled", bool(payload.get("prompt_cache_enabled")))
    read_raw = payload.get("cache_read_input_tokens")
    write_raw = payload.get("cache_write_input_tokens")
    if isinstance(read_raw, bool) or isinstance(write_raw, bool):
        return
    if isinstance(read_raw, (int, float)):
        read_tokens = int(read_raw)
        record_field("cache_read_input_tokens", read_tokens)
        record_field("prompt_cache_hit", read_tokens > 0)
    if isinstance(write_raw, (int, float)):
        record_field("cache_write_input_tokens", int(write_raw))
    cycle_raw = payload.get("event_loop_cycle_count")
    if isinstance(cycle_raw, bool):
        return
    if isinstance(cycle_raw, int) and cycle_raw >= 0:
        record_field("event_loop_cycle_count", cycle_raw)


_RUNTIME_PROVENANCE_MAX_LEN = 80
_RUNTIME_PROVENANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/=-]{0,79}$")
_RUNTIME_PROVENANCE_FIELDS = (
    "runtime_model_role",
    "runtime_model_provider",
    "runtime_model_id",
    "runtime_model_region",
    "runtime_strands_agents",
)


def _safe_runtime_identifier(value: Any) -> str | None:
    """Return a short plain identifier, or None when the value is unsafe.

    Args:
        value: Runtime-supplied provenance candidate.

    Returns:
        The stripped identifier, or ``None`` when missing, non-string,
        oversized, or not a short plain token.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _RUNTIME_PROVENANCE_MAX_LEN:
        return None
    if _RUNTIME_PROVENANCE_RE.fullmatch(cleaned) is None:
        return None
    return cleaned


def _record_runtime_model_provenance(payload: dict[str, Any]) -> None:
    """Copy safe runtime-loaded model identifiers onto coach_turn_perf.

    Missing, malformed, oversized, or non-string values are omitted. This
    never falls back to the FastAPI-configured model fields.
    """
    for key in _RUNTIME_PROVENANCE_FIELDS:
        identifier = _safe_runtime_identifier(payload.get(key))
        if identifier is not None:
            record_field(key, identifier)


def _validated_fast_chat(
    payload: dict[str, Any], request: CoachRequest
) -> ProviderAssessmentResult:
    """Validate one-call fast-chat output and fail closed on a bad contract.

    Accepts the current slim ``fast_chat_turn_v1`` object. The immediately
    previous nested ``CoachTurnOutput`` is mapped only when
    ``assessment.recommendation`` is stay or advance. A previous Q&A object
    (response_text, no recommendation) maps to mode=qa. Conflicting or
    malformed shapes fail closed with a key-only log line.
    """
    _record_runtime_cache_metrics(payload)
    try:
        output = adapt_fast_chat_turn_payload(payload)
    except FastChatContractError as error:
        logger.warning(
            "fast_chat_contract_mismatch reason=%s %s",
            error.reason,
            fast_chat_payload_shape_log(payload),
        )
        raise _malformed_error() from error
    except (ValidationError, TypeError, ValueError) as error:
        logger.warning(
            "fast_chat_contract_mismatch reason=slim_invalid %s",
            fast_chat_payload_shape_log(payload),
        )
        raise _malformed_error() from error
    allowed = _allowed_citation_labels(request)
    citations = [
        item
        for item in _citations_from_items(
            [item.model_dump(mode="json") for item in output.citations]
        )
        if item.label in allowed
    ]
    if output.needs_source_retrieval:
        record_field("fast_chat_needs_source_retrieval", True)
    record_field("mode_returned", output.mode)
    policy = policy_from_request(request)
    enforcement = enforce_model_mode(policy.expected_mode, output.mode)
    record_field("mode_policy_intent", policy.intent)
    record_field("mode_policy_enforced", enforcement.overridden)
    logger.info(
        "mode_policy intent=%s expected=%s returned=%s enforced=%s",
        policy.intent,
        policy.expected_mode or "none",
        output.mode,
        str(enforcement.overridden).lower(),
    )
    if enforcement.effective_mode == SPECIALIST_QA:
        return ProviderAssessmentResult(
            response_text=output.response_text,
            assessment=_fast_chat_assessment(
                request,
                mode="qa",
                recommendation=None,
                recommendation_rationale="",
                citations=citations,
            ),
            research_coding=None,
            specialist=SPECIALIST_QA,
            qualifying_coaching_turn=False,
            deep_review_succeeded=False,
            review_trigger=None,
            needs_source_retrieval=bool(output.needs_source_retrieval),
        )
    if output.recommendation not in {StageDecision.STAY.value, StageDecision.ADVANCE.value}:
        raise _malformed_error()
    assessment = _fast_chat_assessment(
        request,
        mode="coaching",
        recommendation=StageDecision(output.recommendation),
        recommendation_rationale=str(output.recommendation_rationale or ""),
        citations=citations,
    )
    if assessment.recommendation is StageDecision.ADVANCE:
        assessment = assessment.model_copy(update={"readiness_candidate": True})
    return ProviderAssessmentResult(
        response_text=output.response_text,
        assessment=assessment,
        research_coding=None,
        specialist=SPECIALIST_COACHING,
        qualifying_coaching_turn=True,
        deep_review_succeeded=False,
        review_trigger=None,
        needs_source_retrieval=bool(output.needs_source_retrieval),
    )


def _stateless_session_id() -> str:
    """Return a unique runtime session id that is never notebook-derived.

    AgentCore requires 33+ characters. A fresh id per invoke keeps DSQL as the
    only durable transcript.
    """
    return f"stateless-{uuid.uuid4().hex}"


_SESSION_AFFINITY_PREFIX = "codesign-"
_SESSION_AFFINITY_ROLES = frozenset({"fast_chat", "review_deep"})


def _collapsed_identity(value: Any) -> str:
    """Return a stripped identity string with collapsed whitespace."""
    return " ".join(str(value or "").split()).strip()


def _affinity_session_id(
    owner_id: str, notebook_id: str, role: str, generation: str
) -> str:
    """Return an opaque AgentCore session id for one owner, notebook, and role.

    Args:
        owner_id: Server-authoritative store identifier. Never logged.
        notebook_id: Server-authoritative notebook/thread id. Never logged.
        role: ``fast_chat`` or ``review_deep``.
        generation: Operator-controlled deployment salt.

    Returns:
        ``codesign-`` plus a SHA-256 hex digest (73 characters). The digest
        does not contain owner, notebook, email, or student text.
    """
    # Length-prefix each field so a separator byte inside one value cannot be
    # re-read as a field boundary and alias a different (owner, notebook, role)
    # tuple onto the same compute session.
    parts = (owner_id, notebook_id, role, generation)
    material = "\0".join(f"{len(part)}:{part}" for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return _SESSION_AFFINITY_PREFIX + digest


def _runtime_session_id(request: CoachRequest, role: str) -> str:
    """Return a compute-affinity session id or a fresh stateless id.

    Affinity is optional and FastAPI-owned. Disabled, missing owner or
    notebook identity, or an unsupported role fail open to a unique
    ``stateless-`` id. The returned value is never logged.

    Args:
        request: Server-built coaching input with ``student_id`` and
            ``thread_id``.
        role: Invoke role used for session isolation.

    Returns:
        An AgentCore ``runtimeSessionId`` of at least 33 characters.
    """
    if not bool(getattr(settings, "agentcore_session_affinity_enabled", False)):
        return _stateless_session_id()
    owner_id = _collapsed_identity(request.student_id)
    notebook_id = _collapsed_identity(request.thread_id)
    cleaned_role = str(role or "").strip().lower()
    if (
        not owner_id
        or not notebook_id
        or cleaned_role not in _SESSION_AFFINITY_ROLES
    ):
        return _stateless_session_id()
    generation = (
        str(getattr(settings, "agentcore_session_generation", "") or "").strip()
        or "1"
    )
    return _affinity_session_id(owner_id, notebook_id, cleaned_role, generation)


def _current_turn_content(
    prompt: str, images: list[CoachImageInput]
) -> list[dict[str, Any]]:
    """Build the current-turn Converse content blocks, including images."""
    content: list[dict[str, Any]] = [{"text": prompt}]
    for image in images:
        content.append(_payload_image_block(image))
    return content


def _deep_review_planner_from_settings() -> HistoryContextPlanner:
    """Build the broader Deep Review planner from configured token budgets."""
    return HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(
                getattr(
                    settings,
                    "deep_review_max_input_tokens",
                    settings.model_max_input_tokens,
                )
            ),
            output_reserve_tokens=int(settings.model_output_reserve_tokens),
            safety_margin_tokens=int(settings.model_context_safety_margin_tokens),
            recent_verbatim_messages=int(
                getattr(
                    settings,
                    "deep_review_recent_verbatim_messages",
                    settings.history_recent_verbatim_messages,
                )
            ),
        ),
        policy=CONTEXT_POLICY_FULL_HISTORY,
    )


def _fast_chat_planner_from_settings() -> HistoryContextPlanner:
    """Build the latency-oriented fast-chat planner."""
    return HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(settings.fast_chat_max_input_tokens),
            output_reserve_tokens=4_000,
            safety_margin_tokens=1_000,
            recent_verbatim_messages=int(settings.fast_chat_recent_verbatim_messages),
            recent_history_max_tokens=int(settings.fast_chat_recent_history_max_tokens),
            history_message_max_tokens=int(settings.fast_chat_history_message_max_tokens),
            soft_input_tokens=int(settings.fast_chat_soft_input_tokens),
        ),
        policy=CONTEXT_POLICY_FAST_CHAT,
    )


def _planner_from_settings() -> HistoryContextPlanner:
    """Compatibility alias for the fast-chat planner used by injected tests."""
    return _fast_chat_planner_from_settings()


def _compact_text(value: Any, limit: int) -> str:
    """Return whitespace-normalized text truncated to ``limit`` characters."""
    return " ".join(str(value or "").split())[:limit]


def _compact_string_list(values: Any, *, item_limit: int, max_items: int) -> list[str]:
    """Return unique non-empty strings for bounded Stage Judge context."""
    items: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return items
    for value in values:
        text = _compact_text(value, item_limit)
        if text and text not in seen:
            seen.add(text)
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def _router_payload(request: CoachRequest) -> dict[str, Any]:
    """Build a small Haiku router payload. Never includes RAG or pedagogy.

    ``assess()`` does not call this. Kept for the retired
    :meth:`AgentCoreCoachProvider._resolve_specialist` helper.
    """
    return {
        "phase": "router",
        "output_contract": "router_turn",
        "runtime_context": {"current_stage": request.current_stage},
        "messages": [
            {
                "role": "user",
                "content": [{"text": str(request.student_message)}],
            }
        ],
    }


def _merge_unique_strings(*groups: list[str], limit: int = 8) -> list[str]:
    """Merge assessment bullet lists without duplicates or empty items."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = _compact_text(item, 400)
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged


def _stay_after_deep_review_failure(
    result: ProviderAssessmentResult,
    extra_missing: list[str] | None = None,
) -> ProviderAssessmentResult:
    """Fail closed to STAY while keeping the coaching or review response text."""
    missing = _merge_unique_strings(
        list(result.assessment.missing_reasoning_elements),
        extra_missing or [],
    )
    assessment = result.assessment.model_copy(
        update={
            "recommendation": StageDecision.STAY,
            "missing_reasoning_elements": missing,
        }
    )
    return result.model_copy(update={"assessment": assessment, "deep_review_succeeded": False})


def _coaching_without_advancement(
    result: ProviderAssessmentResult,
) -> tuple[ProviderAssessmentResult, bool]:
    """Force Coaching STAY and surface ADVANCE as a readiness candidate."""
    assessment = result.assessment
    candidate = bool(assessment.readiness_candidate) or (
        assessment.recommendation is StageDecision.ADVANCE
    )
    if assessment.recommendation is StageDecision.ADVANCE or candidate:
        assessment = assessment.model_copy(
            update={
                "recommendation": StageDecision.STAY,
                "readiness_candidate": True if candidate else False,
            }
        )
        result = result.model_copy(update={"assessment": assessment})
    return result, bool(result.assessment.readiness_candidate)


def _overlay_review_fields(
    result: ProviderAssessmentResult,
    review: ReviewTurnOutput,
    *,
    review_depth: str,
    review_model: str,
    review_trigger: str,
    force_stay: bool,
) -> ProviderAssessmentResult:
    """Copy Review projection fields onto the current assessment."""
    strengths = _merge_unique_strings(
        list(review.strengths), list(result.assessment.review_strengths), limit=4
    )
    improvements = _merge_unique_strings(
        list(review.areas_to_develop),
        list(result.assessment.review_improvements),
        limit=4,
    )
    facione = result.assessment.facione_scores
    if review.facione_profile is not None:
        try:
            facione = FacioneDimensionScores.model_validate(
                review.facione_profile.model_dump(mode="json")
            )
        except (ValidationError, TypeError, ValueError):
            facione = result.assessment.facione_scores
    synthesis = _compact_text(review.synthesis, 4_000)
    working = _compact_text(review.working_conclusion, 4_000) or (
        result.assessment.working_conclusion
    )
    learning = synthesis or result.assessment.learning_summary
    update: dict[str, Any] = {
        "review_strengths": strengths,
        "review_improvements": improvements,
        "facione_scores": facione,
        "learning_summary": learning,
        "working_conclusion": working,
        "review_depth": review_depth,
        "review_model": review_model,
        "review_trigger": review_trigger,
        "readiness_candidate": bool(
            result.assessment.readiness_candidate or review.readiness_candidate
        ),
    }
    if review_depth == REVIEW_DEPTH_DEEP and synthesis:
        update["stage_assessment"] = synthesis
    if force_stay:
        update["recommendation"] = StageDecision.STAY
    assessment = result.assessment.model_copy(update=update)
    return result.model_copy(update={"assessment": assessment})


def _merge_deep_review(
    request: CoachRequest,
    result: ProviderAssessmentResult,
    review: ReviewTurnOutput,
    *,
    review_model: str,
    review_trigger: str,
) -> tuple[ProviderAssessmentResult, bool]:
    """Combine prior output with Deep Review. Wrong stage fails closed to STAY."""
    merged = _overlay_review_fields(
        result,
        review,
        review_depth=REVIEW_DEPTH_DEEP,
        review_model=review_model,
        review_trigger=review_trigger,
        force_stay=True,
    )
    judged_stage = str(review.current_stage or "").strip()
    if judged_stage and judged_stage != str(request.current_stage).strip():
        logger.info(
            "agentcore_invoke role=review review_depth=deep success=false "
            "failure_category=wrong_stage"
        )
        return _stay_after_deep_review_failure(
            merged, list(review.missing_requirements)
        ), False
    missing = _merge_unique_strings(
        list(merged.assessment.missing_reasoning_elements),
        list(review.missing_requirements),
    )
    rationale = _compact_text(review.rationale_summary, 4_000) or (
        merged.assessment.recommendation_rationale
    )
    evidence = _merge_unique_strings(
        list(merged.assessment.evidence_identified),
        list(review.readiness_evidence),
    )
    review_ready = bool(getattr(review, "readiness_candidate", False)) or (
        str(review.recommendation or "").strip().lower() == "advance"
    )
    assessment = merged.assessment.model_copy(
        update={
            "recommendation": StageDecision.STAY,
            "recommendation_rationale": rationale,
            "missing_reasoning_elements": missing,
            "evidence_identified": evidence,
            "readiness_candidate": review_ready
            or merged.assessment.readiness_candidate,
        }
    )
    return merged.model_copy(
        update={"assessment": assessment, "deep_review_succeeded": True}
    ), True


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
        deep_planner: HistoryContextPlanner | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            runtime_arn: AgentCore runtime ARN (non-secret).
            region: AWS region for the data-plane client, typically ``us-west-2``.
            qualifier: Runtime endpoint qualifier, normally ``DEFAULT``.
            timeout_seconds: boto read timeout; retries stay application-owned.
            max_retries: Extra SDK attempts after the first call (0 disables).
            client: Optional injected ``bedrock-agentcore`` client for tests.
            planner: Optional fast-chat history planner.
            deep_planner: Optional Deep Review history planner.

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
        self._planner = planner or _fast_chat_planner_from_settings()
        self._deep_planner = deep_planner or _deep_review_planner_from_settings()

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
        # ``total_max_attempts`` includes the initial call. The legacy
        # ``max_attempts`` key is normalised by botocore to ``value + 1``,
        # which would silently double the configured invoke budget.
        config = Config(
            retries={"total_max_attempts": attempts, "mode": "standard"},
            read_timeout=self._timeout_seconds,
            connect_timeout=min(10.0, self._timeout_seconds),
        )
        self._client = boto3.client(
            "bedrock-agentcore",
            region_name=self._region,
            config=config,
        )
        return self._client

    def _invoke_payload(
        self,
        request: CoachRequest,
        specialist: str,
        *,
        review_mode: str | None = None,
        review_trigger: str | None = None,
        context_policy: str = CONTEXT_POLICY_FAST_CHAT,
        phase: str | None = None,
        output_contract: str | None = None,
    ) -> tuple[dict[str, Any], ModelContextPlan]:
        """Build the JSON payload and request-local context plan for one invoke.

        Fast chat sends bounded recent Converse ``messages`` plus compact
        untrusted turn text. Deep Review may use the broader history policy.
        Canonical pedagogy lives in the AgentCore runtime.
        """
        existing = memory_from_metadata(
            {"conversation_memory": request.conversation_memory},
            conversation_revision=int(request.conversation_revision or 0),
        )
        seed_request = request.model_copy(update={"conversation_memory": None})
        compose_policy = (
            "fast_chat"
            if context_policy == CONTEXT_POLICY_FAST_CHAT
            else "deep_review"
        )
        planner = (
            self._planner
            if context_policy == CONTEXT_POLICY_FAST_CHAT
            else self._deep_planner
        )
        compose_started = time.perf_counter()
        preliminary = compose_coach_prompt(
            seed_request,
            include_recent_messages=False,
            context_policy=compose_policy,
        )
        record_field("prompt_compose_ms", elapsed_ms(compose_started))
        system_prompt_tokens = 0
        prompt_text = preliminary.composed_text
        if context_policy == CONTEXT_POLICY_FAST_CHAT:
            try:
                from agentcore_runtime.system_prompt_budget import (
                    fast_chat_system_prompt_for_estimate,
                )
            except ImportError:
                from agentcore_runtime.structured_coach import specialist_system_prompt

                def fast_chat_system_prompt_for_estimate(
                    *,
                    topic: str,
                    trusted_runtime_rules: str = "",
                    runtime_context: dict[str, Any] | None = None,
                ) -> str:
                    payload: dict[str, Any] = {
                        "phase": "fast_chat",
                        "topic": topic,
                        "output_contract": "fast_chat_turn",
                        "trusted_instructions": trusted_runtime_rules,
                    }
                    if runtime_context:
                        payload["runtime_context"] = runtime_context
                    return specialist_system_prompt(payload)

            estimate_specialist = str(specialist or "").strip().lower()
            if (
                estimate_specialist not in ALLOWED_SPECIALISTS
                and estimate_specialist != _FAST_CHAT_PHASE
            ):
                estimate_specialist = SPECIALIST_COACHING
            system_text = fast_chat_system_prompt_for_estimate(
                topic=agentcore_topic_for_stage(request.current_stage),
                trusted_runtime_rules=preliminary.runtime_instructions,
                runtime_context=_runtime_context(
                    request,
                    estimate_specialist,
                    review_mode=review_mode,
                    review_trigger=review_trigger,
                ),
            )
            system_prompt_tokens = estimate_tokens(system_text)
            prompt_text = preliminary.untrusted_turn_text
        plan_started = time.perf_counter()
        try:
            plan = planner.plan(
                seed_request,
                prompt_text=prompt_text,
                existing_memory=existing,
                policy=context_policy,
                system_prompt_tokens=system_prompt_tokens,
            )
        except ContextBudgetError as error:
            raise ProviderUnavailableError(
                "AgentCore context exceeds the safe token budget"
            ) from error
        record_field("context_planner_ms", elapsed_ms(plan_started))
        record_field("estimated_input_tokens", int(plan.estimated_input_tokens))
        record_field("estimated_system_prompt_tokens", int(plan.estimated_system_prompt_tokens))
        record_field(
            "estimated_dynamic_input_tokens", int(plan.estimated_dynamic_input_tokens)
        )
        record_field(
            "estimated_total_model_input_tokens", int(plan.estimated_input_tokens)
        )
        record_field("history_tokens", int(plan.history_tokens))
        record_field("evidence_tokens", int(plan.evidence_tokens))
        record_field("estimated_rag_tokens", int(plan.evidence_tokens))
        record_field("estimated_memory_tokens", int(plan.estimated_memory_tokens))
        record_field(
            "estimated_current_message_tokens",
            int(plan.estimated_current_message_tokens),
        )
        record_field("prompt_tokens", int(plan.prompt_tokens))
        record_field("original_message_count", int(plan.original_message_count))
        record_field("verbatim_message_count", int(plan.verbatim_message_count))
        if context_policy == CONTEXT_POLICY_FAST_CHAT:
            record_field(
                "fast_chat_recent_message_count", int(plan.verbatim_message_count)
            )
            record_field(
                "estimated_recent_history_tokens",
                int(plan.estimated_recent_history_tokens),
            )
            record_field(
                "recent_history_budget_tokens", int(plan.recent_history_budget_tokens)
            )
            record_field(
                "largest_historical_message_tokens",
                int(plan.largest_historical_message_tokens),
            )
            record_field(
                "historical_messages_trimmed", int(plan.historical_messages_trimmed)
            )
            record_field(
                "historical_message_tokens_trimmed",
                int(plan.historical_message_tokens_trimmed),
            )
            record_field(
                "fast_chat_soft_input_tokens",
                int(settings.fast_chat_soft_input_tokens),
            )
            record_field(
                "fast_chat_hard_input_tokens",
                int(settings.fast_chat_max_input_tokens),
            )
        is_review = str(specialist or "").strip().lower() == SPECIALIST_REVIEW
        record_field("deep_review_invoked", is_review)
        if is_review:
            record_field("deep_review_model_role", "review_deep")
        record_field("compressed_message_count", int(plan.compressed_message_count))
        record_field("compression_used", bool(plan.compression_used))
        record_field("context_policy", context_policy)
        soft_ceiling = int(getattr(settings, "fast_chat_soft_input_tokens", 12_000))
        if (
            context_policy == CONTEXT_POLICY_FAST_CHAT
            and int(plan.estimated_input_tokens) > soft_ceiling
        ):
            record_field("input_over_soft_budget", True)
            logger.info(
                "fast_chat_input_over_soft_budget estimated_input_tokens=%s "
                "soft_ceiling=%s verbatim_messages=%s",
                int(plan.estimated_input_tokens),
                soft_ceiling,
                int(plan.verbatim_message_count),
            )
        planned_request = request
        if plan.compressed_memory is not None:
            planned_request = request.model_copy(
                update={
                    "conversation_memory": plan.compressed_memory.model_dump(mode="json")
                }
            )
        prepared = compose_coach_prompt(
            planned_request,
            include_recent_messages=False,
            context_policy=compose_policy,
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
        specialist = str(specialist or "").strip().lower()
        if specialist not in ALLOWED_SPECIALISTS and specialist != _FAST_CHAT_PHASE:
            specialist = SPECIALIST_COACHING
        resolved_phase = str(phase or specialist).strip().lower()
        resolved_contract = str(
            output_contract
            or _CONTRACT_BY_SPECIALIST.get(specialist, _OUTPUT_CONTRACT)
        ).strip()
        runtime_specialist = specialist
        payload: dict[str, Any] = {
            "phase": resolved_phase,
            "topic": agentcore_topic_for_stage(request.current_stage),
            "output_contract": resolved_contract,
            "runtime_context": _runtime_context(
                request,
                runtime_specialist,
                review_mode=review_mode,
                review_trigger=review_trigger,
            ),
            _TRUSTED_INSTRUCTIONS_FIELD: prepared.runtime_instructions,
            "messages": messages,
        }
        if review_mode in {REVIEW_DEPTH_INCREMENTAL, REVIEW_DEPTH_DEEP}:
            payload["review_mode"] = review_mode
        student_id = " ".join(str(request.student_id or "").split()).strip()
        if student_id and student_id != str(request.thread_id or "").strip():
            payload["student_id"] = student_id[:128]
        return payload, plan

    def _call_runtime(
        self,
        payload: dict[str, Any],
        *,
        request: CoachRequest,
        role: str,
    ) -> dict[str, Any]:
        """Invoke AgentCore once and return the parsed JSON object.

        Args:
            payload: Companion InvokeAgentRuntime JSON.
            request: Server-built coaching input used only for optional
                session affinity. Identity values are never logged.
            role: ``fast_chat`` or ``review_deep`` for affinity isolation.

        Returns:
            Unwrapped runtime JSON. Harness error envelopes raise.

        Raises:
            ProviderUnavailableError: When the runtime is blocked, malformed,
                timed out, or otherwise unavailable.
        """
        encoded = json.dumps(payload).encode("utf-8")
        response = self._runtime_client().invoke_agent_runtime(
            agentRuntimeArn=self._runtime_arn,
            qualifier=self._qualifier,
            runtimeSessionId=_runtime_session_id(request, role),
            payload=encoded,
            contentType="application/json",
            accept="application/json",
        )
        perf = current_perf()
        if perf is not None:
            current = int(perf.fields.get("agentcore_call_count") or 0)
            perf.set("agentcore_call_count", current + 1)
        if not isinstance(response, Mapping):
            raise _malformed_error()
        parsed = _payload_from_runtime_response(response)
        _record_runtime_model_provenance(parsed)
        # Recorded here so Deep Review reports cycle/cache telemetry too; the
        # Fast Chat validator repeats it with the same payload, which is a
        # no-op rewrite of identical values.
        _record_runtime_cache_metrics(parsed)
        return parsed

    def _role_provider_model(self, role: str) -> tuple[str, str]:
        """Return configured provider/model ids for one role without secrets."""
        mapping = {
            "router": (settings.router_model_provider, settings.router_model_id),
            "qa": (settings.qa_model_provider, settings.qa_model_id),
            "coaching": (
                settings.coaching_model_provider,
                settings.coaching_model_id,
            ),
            "fast_chat": (
                settings.coaching_model_provider,
                settings.coaching_model_id,
            ),
            "review": (
                settings.review_deep_model_provider or settings.review_model_provider,
                settings.review_deep_model_id or settings.review_model_id,
            ),
            "review_incremental": (
                settings.review_incremental_model_provider,
                settings.review_incremental_model_id,
            ),
            "review_deep": (
                settings.review_deep_model_provider,
                settings.review_deep_model_id,
            ),
        }
        provider, model_id = mapping.get(role, ("", ""))
        if provider and model_id:
            return provider, model_id
        return settings.agentcore_model_provider, settings.agentcore_model_id

    def _log_role_precise(
        self,
        *,
        role: str,
        started: float,
        success: bool,
        failure_category: str = "",
        extra: str = "",
        model_role: str | None = None,
    ) -> None:
        """Log role provenance using per-role settings when present."""
        provider, model_id = self._role_provider_model(model_role or role)
        logger.info(
            "agentcore_invoke role=%s provider=%s model_id=%s latency_ms=%s "
            "success=%s failure_category=%s guardrail_configured=%s%s",
            role,
            provider or "unknown",
            model_id or "unknown",
            max(0, int((time.monotonic() - started) * 1000)),
            "true" if success else "false",
            failure_category or ("ok" if success else "unavailable"),
            "true" if (settings.guardrail_id and settings.guardrail_version) else "false",
            extra,
        )

    def _resolve_specialist(self, request: CoachRequest) -> str:
        """Return a non-review specialist for the retired Haiku router path.

        ``assess()`` does not call this. If it is reattached, ``review`` is
        never honored here so a browser or router hint cannot select Sonnet.
        Explicit Deep Review uses ``_assess_explicit_review``.
        """
        requested = str(request.specialist or "").strip().lower()
        if requested == SPECIALIST_REVIEW:
            requested = SPECIALIST_COACHING
        if requested in ALLOWED_SPECIALISTS:
            logger.info(
                "agentcore_invoke role=router router_fallback=false "
                "router_skipped=true router_specialist=%s",
                requested,
            )
            return requested
        started = time.monotonic()
        min_confidence = bound_router_min_confidence(settings.router_min_confidence)
        try:
            parsed = self._call_runtime(
                _router_payload(request), request=request, role="router"
            )
            routed = RouterOutput.model_validate(parsed)
            specialist = apply_semantic_route(
                routed.specialist,
                routed.confidence,
                min_confidence=min_confidence,
            )
            if specialist == SPECIALIST_REVIEW:
                specialist = SPECIALIST_COACHING
            fallback = (
                routed.confidence < min_confidence
                or specialist != routed.specialist
            )
            self._log_role_precise(
                role="router",
                started=started,
                success=True,
                extra=(
                    f" router_specialist={specialist} router_confidence="
                    f"{routed.confidence:.2f} router_fallback="
                    f"{'true' if fallback else 'false'}"
                ),
            )
            return specialist
        except ProviderUnavailableError as error:
            if error.category == "safety_blocked":
                self._log_role_precise(
                    role="router",
                    started=started,
                    success=False,
                    failure_category="safety_blocked",
                    extra=" router_fallback=false",
                )
                raise
            self._log_role_precise(
                role="router",
                started=started,
                success=False,
                failure_category=error.category,
                extra=" router_fallback=true router_specialist=coaching",
            )
            return SPECIALIST_COACHING
        except (ValidationError, TypeError, ValueError):
            self._log_role_precise(
                role="router",
                started=started,
                success=False,
                failure_category="structured_output_failure",
                extra=" router_fallback=true router_specialist=coaching",
            )
            return SPECIALIST_COACHING
        except Exception as error:
            translated = _translate_agentcore_error(error)
            if translated.category == "safety_blocked":
                self._log_role_precise(
                    role="router",
                    started=started,
                    success=False,
                    failure_category="safety_blocked",
                    extra=" router_fallback=false",
                )
                raise translated from error
            self._log_role_precise(
                role="router",
                started=started,
                success=False,
                failure_category=translated.category,
                extra=" router_fallback=true router_specialist=coaching",
            )
            return SPECIALIST_COACHING

    def _parse_review_turn(self, parsed: dict[str, Any]) -> ReviewTurnOutput:
        """Validate Review structured output or raise."""
        return ReviewTurnOutput.model_validate(parsed)

    def _with_memory(
        self,
        request: CoachRequest,
        result: ProviderAssessmentResult,
        plan: ModelContextPlan | None,
    ) -> ProviderAssessmentResult:
        """Attach this invocation's planner memory without changing pedagogy."""
        memory_payload = request.conversation_memory
        if plan is not None and plan.compressed_memory is not None:
            memory_payload = plan.compressed_memory.model_dump(mode="json")
        return result.model_copy(update={"conversation_memory": memory_payload})

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Request one structured coaching turn from AgentCore Runtime.

        Normal chat is one Haiku ``fast_chat`` invoke. Explicit Review remains
        a separate Deep Review operation. The Haiku router and Incremental
        Review are not invoked on this path.

        Args:
            request: Server-built coaching input, including the persisted phase.

        Returns:
            Validated coaching text, assessment, and optional research coding.

        Raises:
            ProviderUnavailableError: When AgentCore cannot produce a valid turn.
        """
        for image in request.image_inputs:
            _payload_image_block(image)
        requested = str(request.specialist or "").strip().lower()
        if requested == SPECIALIST_REVIEW:
            return self._assess_explicit_review(request)
        return self._assess_fast_chat(request)

    def _assess_fast_chat(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Run one Haiku fast-chat invoke and validate Coaching or Q&A output."""
        owns_perf = current_perf() is None
        if owns_perf:
            begin_coach_turn_perf()
        record_field("model_role", "fast_chat")
        record_field("model_id", self._role_provider_model("fast_chat")[1] or HAIKU_4_5_MODEL_ID)
        payload, plan = self._invoke_payload(
            request,
            _FAST_CHAT_PHASE,
            context_policy=CONTEXT_POLICY_FAST_CHAT,
            phase=_FAST_CHAT_PHASE,
            output_contract=_FAST_CHAT_CONTRACT,
        )
        started = time.monotonic()
        try:
            parsed = self._call_runtime(
                payload, request=request, role="fast_chat"
            )
            result = _validated_fast_chat(parsed, request)
            self._log_role_precise(
                role="fast_chat",
                started=started,
                success=True,
                model_role="fast_chat",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
            record_success()
            return self._with_memory(request, result, plan)
        except ProviderUnavailableError as error:
            self._log_role_precise(
                role="fast_chat",
                started=started,
                success=False,
                failure_category=error.category,
                model_role="fast_chat",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
            record_failure(error.category)
            raise
        except Exception as error:
            translated = _translate_agentcore_error(error)
            self._log_role_precise(
                role="fast_chat",
                started=started,
                success=False,
                failure_category=translated.category,
                model_role="fast_chat",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
            record_failure(translated.category)
            raise translated from error
        finally:
            if owns_perf:
                emit_coach_turn_perf()

    def _assess_explicit_review(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Run one explicit Deep Review invoke. Never used for normal chat."""
        routed = request.model_copy(update={"specialist": SPECIALIST_REVIEW})
        started = time.monotonic()
        try:
            payload, plan = self._invoke_payload(
                routed,
                SPECIALIST_REVIEW,
                review_mode=REVIEW_DEPTH_DEEP,
                review_trigger="explicit",
                context_policy=CONTEXT_POLICY_FULL_HISTORY,
            )
            parsed = self._call_runtime(
                payload, request=routed, role="review_deep"
            )
            result = _validated_result(parsed, routed)
            self._log_role_precise(
                role="review",
                started=started,
                success=True,
                extra=" review_depth=deep review_trigger=explicit",
                model_role="review_deep",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
        except ProviderUnavailableError as error:
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=error.category,
                extra=" review_depth=deep review_trigger=explicit",
                model_role="review_deep",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
            record_failure(error.category)
            raise
        except Exception as error:
            translated = _translate_agentcore_error(error)
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=translated.category,
                extra=" review_depth=deep review_trigger=explicit",
                model_role="review_deep",
            )
            record_field("agentcore_invoke_ms", max(0, int((time.monotonic() - started) * 1000)))
            record_failure(translated.category)
            raise translated from error
        review = self._parse_review_turn(parsed)
        model_id = self._role_provider_model("review_deep")[1]
        merged, succeeded = _merge_deep_review(
            routed,
            result,
            review,
            review_model=model_id or SONNET_4_6_MODEL_ID,
            review_trigger="explicit",
        )
        if not succeeded:
            merged = _stay_after_deep_review_failure(merged)
        text = str(review.response_text or "").strip()
        if text:
            merged = merged.model_copy(update={"response_text": text})
        return self._with_memory(
            request,
            merged.model_copy(
                update={
                    "specialist": SPECIALIST_REVIEW,
                    "qualifying_coaching_turn": False,
                    "deep_review_succeeded": succeeded,
                    "review_trigger": "explicit",
                }
            ),
            plan,
        )

    def _invoke_specialist(
        self, request: CoachRequest, specialist: str
    ) -> tuple[ProviderAssessmentResult, ModelContextPlan]:
        """Invoke one Q&A or Coaching specialist and validate the result.

        ``assess()`` does not call this. Normal chat uses ``_assess_fast_chat``;
        explicit Deep Review uses ``_assess_explicit_review``.
        """
        payload, plan = self._invoke_payload(request, specialist)
        started = time.monotonic()
        try:
            affinity_role = (
                "review_deep" if specialist == SPECIALIST_REVIEW else specialist
            )
            parsed = self._call_runtime(
                payload, request=request, role=affinity_role
            )
            result = _validated_result(parsed, request)
            self._log_role_precise(role=specialist, started=started, success=True)
            return result, plan
        except ProviderUnavailableError as error:
            self._log_role_precise(
                role=specialist,
                started=started,
                success=False,
                failure_category=error.category,
            )
            raise
        except Exception as error:
            translated = _translate_agentcore_error(error)
            self._log_role_precise(
                role=specialist,
                started=started,
                success=False,
                failure_category=translated.category,
            )
            raise translated from error
