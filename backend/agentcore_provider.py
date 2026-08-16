"""Amazon Bedrock AgentCore Runtime adapter for one structured specialist turn.

The adapter may invoke ``InvokeAgentRuntime`` more than once per student turn
on the same runtime ARN:

1. Haiku router (unless the specialist is already server-owned)
2. The selected specialist (Q&A, Coaching, or explicit Deep Review)
3. Incremental Haiku Review after a successful Coaching turn
4. Deep Sonnet Review on periodic or event triggers

It does not own phase progression, citations, persistence, retrieval, or IAM.
Tests inject a fake client so automated runs never contact AWS. Planner
output is request-local so one cached provider instance may coach two
notebooks for the same owner without cross-notebook memory contamination.

FastAPI remains the authority for authentication, source ownership, and DSQL
writes. Thinking Path stages stay in DSQL; only the runtime *topic* key maps
``deep_analysis`` to the POC ``ethics_critical`` label. Invokes are stateless
(a fresh ``runtimeSessionId`` per invoke) so the runtime LRU cache is not a
second transcript. Guardrail blocks are category-only failures and never
persist refusal text.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentcore_runtime.model import HAIKU_4_5_MODEL_ID, SONNET_4_6_MODEL_ID
from agentcore_runtime.models import ReviewTurnOutput, RouterOutput

from .context_planner import (
    ContextBudget,
    ContextBudgetError,
    HistoryContextPlanner,
    ModelContextPlan,
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
from .specialists.review_orchestration import (
    REVIEW_DEPTH_DEEP,
    REVIEW_DEPTH_INCREMENTAL,
    REVIEW_TRIGGER_INCREMENTAL,
    bound_deep_review_interval,
    resolve_deep_review_trigger,
    should_run_deep_review,
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
            logger.warning("agentcore_turn_blocked")
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
    """Return application-owned runtime constraints for the AgentCore specialist."""
    labels = sorted(
        {
            str(chunk.label).strip()
            for chunk in request.retrieved_chunks
            if str(chunk.label or "").strip()
        }
    )
    cleaned = str(specialist or "").strip().lower()
    if cleaned not in ALLOWED_SPECIALISTS:
        cleaned = SPECIALIST_COACHING
    context = {
        "current_stage": request.current_stage,
        "agentcore_topic": agentcore_topic_for_stage(request.current_stage),
        "response_detail": "quick" if request.response_detail == "short" else "strict",
        "language": request.response_language,
        "allowed_citations": labels,
        "allow_model_knowledge": bool(request.allow_model_knowledge),
        "conversation_revision": request.conversation_revision,
        "specialist": cleaned,
    }
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
    may recommend stay/advance; FastAPI still executes the transition.
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
    """Build a small Haiku router payload. Never includes RAG or pedagogy."""
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
    recommendation = StageDecision.STAY
    if str(review.recommendation or "").strip().lower() == "advance":
        recommendation = StageDecision.ADVANCE
    assessment = merged.assessment.model_copy(
        update={
            "recommendation": recommendation,
            "recommendation_rationale": rationale,
            "missing_reasoning_elements": missing,
            "evidence_identified": evidence,
            "readiness_candidate": recommendation is StageDecision.ADVANCE
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

    def _invoke_payload(
        self,
        request: CoachRequest,
        specialist: str,
        *,
        review_mode: str | None = None,
        review_trigger: str | None = None,
    ) -> tuple[dict[str, Any], ModelContextPlan]:
        """Build the JSON payload and request-local context plan for one invoke.

        Always sends Converse ``messages``: planner-selected DSQL history plus
        the untrusted current-turn content. Canonical pedagogy lives in the
        AgentCore runtime. This adapter sends application runtime rules in
        ``trusted_instructions`` and ``runtime_context``. The untrusted brief
        omits duplicated ``<recent_messages>``. Derived memory appears only in
        ``<conversation_memory>`` when compression was required. A top-level
        ``prompt`` string is never used. Token budgeting still uses the full
        ordered ``composed_text`` so the split cannot overflow the window.

        The plan is returned to the caller so two notebooks sharing this
        provider instance cannot overwrite each other's conversation memory.
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
        specialist = str(specialist or "").strip().lower()
        if specialist not in ALLOWED_SPECIALISTS:
            specialist = SPECIALIST_COACHING
        payload: dict[str, Any] = {
            "phase": specialist,
            "topic": agentcore_topic_for_stage(request.current_stage),
            "output_contract": _CONTRACT_BY_SPECIALIST.get(
                specialist, _OUTPUT_CONTRACT
            ),
            "runtime_context": _runtime_context(
                request,
                specialist,
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

    def _call_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke AgentCore once and return the parsed JSON object.

        Args:
            payload: Companion InvokeAgentRuntime JSON.

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
            runtimeSessionId=_stateless_session_id(),
            payload=encoded,
            contentType="application/json",
            accept="application/json",
        )
        if not isinstance(response, Mapping):
            raise _malformed_error()
        return _payload_from_runtime_response(response)

    def _role_provider_model(self, role: str) -> tuple[str, str]:
        """Return configured provider/model ids for one role without secrets."""
        mapping = {
            "router": (settings.router_model_provider, settings.router_model_id),
            "qa": (settings.qa_model_provider, settings.qa_model_id),
            "coaching": (
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
        """Return the server-owned specialist, using Haiku only for free text.

        Explicit ``request.specialist`` is treated as already validated by
        application code or tests. HTTP overwrites browser hints to ``None``
        before this adapter runs.
        """
        requested = str(request.specialist or "").strip().lower()
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
            parsed = self._call_runtime(_router_payload(request))
            routed = RouterOutput.model_validate(parsed)
            specialist = apply_semantic_route(
                routed.specialist,
                routed.confidence,
                min_confidence=min_confidence,
            )
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

    def _apply_incremental_review(
        self, request: CoachRequest, result: ProviderAssessmentResult
    ) -> ProviderAssessmentResult:
        """Keep the Review projection current after Coaching. Cannot advance."""
        started = time.monotonic()
        model_id = self._role_provider_model("review_incremental")[1]
        payload, _plan = self._invoke_payload(
            request,
            SPECIALIST_REVIEW,
            review_mode=REVIEW_DEPTH_INCREMENTAL,
            review_trigger=REVIEW_TRIGGER_INCREMENTAL,
        )
        try:
            parsed = self._call_runtime(payload)
            review = self._parse_review_turn(parsed)
            merged = _overlay_review_fields(
                result,
                review,
                review_depth=REVIEW_DEPTH_INCREMENTAL,
                review_model=model_id or HAIKU_4_5_MODEL_ID,
                review_trigger=REVIEW_TRIGGER_INCREMENTAL,
                force_stay=True,
            )
            self._log_role_precise(
                role="review",
                started=started,
                success=True,
                extra=(
                    " review_depth=incremental review_trigger=incremental"
                ),
                model_role="review_incremental",
            )
            return merged
        except ProviderUnavailableError as error:
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=error.category,
                extra=" review_depth=incremental",
                model_role="review_incremental",
            )
            raise
        except (ValidationError, TypeError, ValueError) as error:
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category="structured_output_failure",
                extra=" review_depth=incremental",
                model_role="review_incremental",
            )
            raise _malformed_error() from error
        except Exception as error:
            translated = _translate_agentcore_error(error)
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=translated.category,
                extra=" review_depth=incremental",
                model_role="review_incremental",
            )
            raise translated from error

    def _apply_deep_review(
        self,
        request: CoachRequest,
        result: ProviderAssessmentResult,
        *,
        review_trigger: str,
        replace_response_text: bool,
    ) -> tuple[ProviderAssessmentResult, bool]:
        """Run Sonnet Deep Review. Fail closed to STAY without resetting state."""
        started = time.monotonic()
        model_id = self._role_provider_model("review_deep")[1]
        payload, _plan = self._invoke_payload(
            request,
            SPECIALIST_REVIEW,
            review_mode=REVIEW_DEPTH_DEEP,
            review_trigger=review_trigger,
        )
        extra = (
            f" review_depth=deep review_trigger={review_trigger}"
            f" coaching_turns_since_deep_review="
            f"{int(request.coaching_turns_since_deep_review)}"
            f" deep_review_interval="
            f"{bound_deep_review_interval(request.deep_review_interval_turns)}"
            " deep_review_triggered=true"
        )
        try:
            parsed = self._call_runtime(payload)
            review = self._parse_review_turn(parsed)
            merged, succeeded = _merge_deep_review(
                request,
                result,
                review,
                review_model=model_id or SONNET_4_6_MODEL_ID,
                review_trigger=review_trigger,
            )
            if replace_response_text:
                text = str(review.response_text or "").strip()
                if text:
                    merged = merged.model_copy(update={"response_text": text})
            failure_category = "" if succeeded else "wrong_stage"
            self._log_role_precise(
                role="review",
                started=started,
                success=succeeded,
                failure_category=failure_category,
                extra=extra,
                model_role="review_deep",
            )
            return merged, succeeded
        except ProviderUnavailableError as error:
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=error.category,
                extra=extra,
                model_role="review_deep",
            )
            return _stay_after_deep_review_failure(result), False
        except (ValidationError, TypeError, ValueError):
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category="structured_output_failure",
                extra=extra,
                model_role="review_deep",
            )
            return _stay_after_deep_review_failure(result), False
        except Exception as error:
            translated = _translate_agentcore_error(error)
            self._log_role_precise(
                role="review",
                started=started,
                success=False,
                failure_category=translated.category,
                extra=extra,
                model_role="review_deep",
            )
            return _stay_after_deep_review_failure(result), False

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

        Args:
            request: Server-built coaching input, including the persisted phase.

        Returns:
            Validated coaching text, assessment, and optional research coding.

        Raises:
            ProviderUnavailableError: When AgentCore cannot produce a valid turn.
        """
        for image in request.image_inputs:
            _payload_image_block(image)
        specialist = self._resolve_specialist(request)
        routed = request.model_copy(update={"specialist": specialist})
        interval = bound_deep_review_interval(request.deep_review_interval_turns)
        if specialist == SPECIALIST_QA:
            result, plan = self._invoke_specialist(routed, SPECIALIST_QA)
            return self._with_memory(
                request,
                result.model_copy(
                    update={
                        "specialist": SPECIALIST_QA,
                        "qualifying_coaching_turn": False,
                        "deep_review_succeeded": False,
                        "review_trigger": None,
                    }
                ),
                plan,
            )
        if specialist == SPECIALIST_REVIEW:
            started = time.monotonic()
            try:
                payload, plan = self._invoke_payload(
                    routed,
                    SPECIALIST_REVIEW,
                    review_mode=REVIEW_DEPTH_DEEP,
                    review_trigger="explicit",
                )
                parsed = self._call_runtime(payload)
                result = _validated_result(parsed, routed)
                self._log_role_precise(
                    role="review",
                    started=started,
                    success=True,
                    extra=" review_depth=deep review_trigger=explicit",
                    model_role="review_deep",
                )
            except ProviderUnavailableError as error:
                self._log_role_precise(
                    role="review",
                    started=started,
                    success=False,
                    failure_category=error.category,
                    extra=" review_depth=deep review_trigger=explicit",
                    model_role="review_deep",
                )
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

        result, plan = self._invoke_specialist(routed, SPECIALIST_COACHING)
        result, readiness = _coaching_without_advancement(result)
        result = self._apply_incremental_review(routed, result)
        readiness = bool(result.assessment.readiness_candidate)
        trigger = resolve_deep_review_trigger(
            specialist=SPECIALIST_COACHING,
            current_stage=routed.current_stage,
            readiness_candidate=readiness,
            coaching_turns_since_deep_review=int(
                routed.coaching_turns_since_deep_review
            ),
            interval=interval,
            qualifying_coaching_turn=True,
        )
        logger.info(
            "agentcore_invoke role=review review_depth=incremental "
            "review_trigger=incremental coaching_turns_since_deep_review=%s "
            "deep_review_interval=%s deep_review_triggered=%s",
            int(routed.coaching_turns_since_deep_review),
            interval,
            "true" if should_run_deep_review(trigger) else "false",
        )
        deep_succeeded = False
        if should_run_deep_review(trigger):
            result, deep_succeeded = self._apply_deep_review(
                routed,
                result,
                review_trigger=str(trigger),
                replace_response_text=False,
            )
        return self._with_memory(
            request,
            result.model_copy(
                update={
                    "specialist": SPECIALIST_COACHING,
                    "qualifying_coaching_turn": True,
                    "deep_review_succeeded": deep_succeeded,
                    "review_trigger": trigger,
                }
            ),
            plan,
        )

    def _invoke_specialist(
        self, request: CoachRequest, specialist: str
    ) -> tuple[ProviderAssessmentResult, ModelContextPlan]:
        """Invoke one Q&A or Coaching specialist and validate the result."""
        payload, plan = self._invoke_payload(request, specialist)
        started = time.monotonic()
        try:
            parsed = self._call_runtime(payload)
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
