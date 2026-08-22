"""Focused coach_turn wire schema for the AgentCore harness.

This schema matches the companion application's production contract without
importing ``backend.domain``. Live-model variants already accepted by the
application (uppercase ``stay``/``advance``, object-shaped
``stage_assessment``) are coerced here so the harness can validate before
returning JSON. Invalid optional research coding is dropped; invalid
coaching assessment fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


def _stage_assessment_as_text(value: Any) -> Any:
    """Flatten live-model stage_assessment objects or lists into one string."""
    if isinstance(value, str) or value is None:
        return value
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if not isinstance(value, Mapping):
        return value
    for key in ("text", "summary", "assessment", "stage_assessment"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    parts: list[str] = []
    for key in ("strengths", "improvements", "gaps", "notes"):
        item = value.get(key)
        if isinstance(item, list):
            joined = "; ".join(
                str(entry).strip() for entry in item if str(entry).strip()
            )
            if joined:
                parts.append(f"{key}: {joined}")
        elif isinstance(item, str) and item.strip():
            parts.append(item.strip())
    return " ".join(parts).strip()


class FacioneScoresOutput(BaseModel):
    """Six Facione dimensions using 0=not started through 4=Strong."""

    model_config = ConfigDict(extra="ignore")

    analysis: int = Field(ge=0, le=4, default=0)
    interpretation: int = Field(ge=0, le=4, default=0)
    inference: int = Field(ge=0, le=4, default=0)
    evaluation: int = Field(ge=0, le=4, default=0)
    explanation: int = Field(ge=0, le=4, default=0)
    self_regulation: int = Field(ge=0, le=4, default=0)


class CitationOutput(BaseModel):
    """One [S#] citation over a selected notebook source."""

    model_config = ConfigDict(extra="ignore")

    source_id: str = ""
    label: str
    title: str = ""
    excerpt: str = ""


class AssessmentOutput(BaseModel):
    """Required educational assessment fields for one coach_turn."""

    model_config = ConfigDict(extra="ignore")

    current_stage: str
    contribution_summary: str = Field(min_length=1, max_length=2_000)
    stage_assessment: str = Field(min_length=1, max_length=4_000)
    critical_understanding_level: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    recommendation: str
    recommendation_rationale: str = Field(min_length=1, max_length=4_000)
    guidance_questions: list[str] = Field(default_factory=list, max_length=3)
    learning_summary: str = Field(min_length=1, max_length=4_000)
    citations: list[CitationOutput] = Field(default_factory=list)
    facione_scores: FacioneScoresOutput = Field(default_factory=FacioneScoresOutput)
    evidence_identified: list[str] = Field(default_factory=list)
    assumptions_identified: list[str] = Field(default_factory=list)
    missing_reasoning_elements: list[str] = Field(default_factory=list)
    working_conclusion: str = Field(default="", max_length=4_000)
    understanding_change: str = Field(default="", max_length=4_000)
    review_strengths: list[str] = Field(default_factory=list, max_length=4)
    review_improvements: list[str] = Field(default_factory=list, max_length=4)
    readiness_candidate: bool = False

    @model_validator(mode="before")
    @classmethod
    def coerce_live_provider_shapes(cls, value: Any) -> Any:
        """Accept uppercase stay/advance and object-shaped stage_assessment."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        stage = data.get("stage_assessment")
        if isinstance(stage, Mapping):
            if not data.get("review_strengths") and isinstance(
                stage.get("strengths"), list
            ):
                data["review_strengths"] = stage.get("strengths")
            if not data.get("review_improvements") and isinstance(
                stage.get("improvements"), list
            ):
                data["review_improvements"] = stage.get("improvements")
            data["stage_assessment"] = _stage_assessment_as_text(stage)
        elif isinstance(stage, list):
            data["stage_assessment"] = _stage_assessment_as_text(stage)
        recommendation = data.get("recommendation")
        if isinstance(recommendation, str):
            data["recommendation"] = recommendation.strip().lower()
        return data

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_stay_or_advance(cls, value: str) -> str:
        """Reject recommendations outside the two-value production contract."""
        cleaned = str(value or "").strip().lower()
        if cleaned not in {"stay", "advance"}:
            raise ValueError("recommendation must be stay or advance")
        return cleaned

    @field_validator("guidance_questions")
    @classmethod
    def guidance_questions_are_questions(cls, values: list[str]) -> list[str]:
        """Normalize non-empty guidance prompts while preserving model wording."""
        cleaned = [value.strip() for value in values if value and value.strip()]
        if any(not value.endswith("?") for value in cleaned):
            raise ValueError("Guidance questions must end with a question mark")
        return cleaned


class CoachTurnOutput(BaseModel):
    """Validated coach_turn object returned by the production harness."""

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    assessment: AssessmentOutput
    research_coding: dict[str, Any] | None = None

    @field_validator("research_coding", mode="before")
    @classmethod
    def invalid_research_coding_becomes_absent(cls, value: Any) -> Any:
        """Drop invalid optional research data without losing valid coaching."""
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        if "coding_status" not in value and "dominant_clear" not in value:
            return None
        return value


class QATurnOutput(BaseModel):
    """Grounded course Q&A result. Never advances the Thinking Path."""

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    citations: list[CitationOutput] = Field(default_factory=list)


# Wire marker stamped on slim Fast Chat JSON. Unknown values are ignored.
FAST_CHAT_SCHEMA_ID = "fast_chat_turn_v1"

_FAST_CHAT_REVIEW_HINT_KEYS = frozenset(
    {
        "synthesis",
        "strengths",
        "areas_to_develop",
        "readiness_candidate",
        "facione_profile",
        "readiness_evidence",
        "missing_requirements",
    }
)
_FAST_CHAT_ROUTER_HINT_KEYS = frozenset({"specialist", "rationale_category"})


class FastChatContractError(ValueError):
    """Raised when a Fast Chat wire payload cannot be adapted safely.

    ``reason`` is a stable token for logs. It must never include payload
    values, student text, or prompt content.
    """

    def __init__(self, reason: str) -> None:
        cleaned = str(reason or "unrecognized").strip() or "unrecognized"
        self.reason = cleaned[:80]
        super().__init__(self.reason)


def fast_chat_payload_shape_log(payload: Mapping[str, Any]) -> str:
    """Return a key-only Fast Chat shape diagnostic with no payload values.

    Args:
        payload: Runtime JSON object.

    Returns:
        A single log fragment naming expected schema vs received keys.
    """
    keys = sorted(str(key) for key in payload)
    schema_raw = payload.get("schema_id")
    schema_token = "absent"
    if "schema_id" in payload:
        candidate = str(schema_raw or "").strip()
        compact = candidate.replace("_", "").replace("-", "")
        if candidate and len(candidate) <= 64 and compact.isalnum() and candidate.isascii():
            schema_token = candidate
        else:
            schema_token = "present_untrusted"
    return (
        f"expected={FAST_CHAT_SCHEMA_ID} received_keys={keys} "
        f"has_mode={('mode' in payload)} has_assessment={('assessment' in payload)} "
        f"has_top_recommendation={('recommendation' in payload)} "
        f"schema_id={schema_token}"
    )


def _recommendation_token(value: Any) -> str | None:
    """Return stay/advance or None. Blank and unknown tokens stay distinct."""
    cleaned = str(value or "").strip().lower()
    if cleaned in {"", "none", "null"}:
        return None
    if cleaned in {"stay", "advance"}:
        return cleaned
    return cleaned


def adapt_fast_chat_turn_payload(value: Any) -> FastChatTurnOutput:
    """Parse slim Fast Chat JSON, or map the immediately-previous rich shape.

    The previous normal-chat wire object was nested ``CoachTurnOutput``
    (``response_text`` + ``assessment.recommendation``) or ``QATurnOutput``
    (``response_text`` + citations, no recommendation). This adapter exists so
    FastAPI can be published before the runtime without a same-millisecond
    cutover.

    A rich coaching object is mapped only when ``assessment.recommendation`` is
    exactly stay or advance. This function never invents a recommendation.
    When ``mode`` is present, the slim schema wins and extra nested
    ``assessment`` is ignored unless coaching is missing a top-level
    recommendation. Conflicting stay/advance values fail closed. Review and
    router objects without ``mode`` fail closed.

    Args:
        value: Runtime JSON object, Pydantic model, or mapping.

    Returns:
        A validated :class:`FastChatTurnOutput`.

    Raises:
        FastChatContractError: When the payload is the wrong contract or would
            require fabricating stage semantics.
        ValidationError: When the slim object is present but invalid.
    """
    if isinstance(value, FastChatTurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            value = value.model_dump(mode="json")
        except (TypeError, ValueError):
            value = value
    if not isinstance(value, Mapping):
        raise FastChatContractError("unrecognized")
    payload = dict(value)
    has_mode = "mode" in payload
    assessment = payload.get("assessment")
    has_assessment = isinstance(assessment, Mapping)
    if not has_mode and (
        _FAST_CHAT_REVIEW_HINT_KEYS.intersection(payload)
        or _FAST_CHAT_ROUTER_HINT_KEYS.intersection(payload)
    ):
        raise FastChatContractError("wrong_contract")
    if has_mode:
        mode = str(payload.get("mode") or "").strip().lower()
        if mode == "coaching" and has_assessment:
            top_rec = _recommendation_token(payload.get("recommendation"))
            nested_rec = _recommendation_token(assessment.get("recommendation"))
            if (
                top_rec in {"stay", "advance"}
                and nested_rec in {"stay", "advance"}
                and top_rec != nested_rec
            ):
                raise FastChatContractError("recommendation_conflict")
        try:
            return parse_fast_chat_turn_output(payload)
        except (ValidationError, TypeError, ValueError) as error:
            if mode != "coaching" or not has_assessment:
                raise FastChatContractError("slim_invalid") from error
            nested_rec = _recommendation_token(assessment.get("recommendation"))
            if nested_rec not in {"stay", "advance"}:
                raise FastChatContractError("legacy_recommendation_missing")
            text = payload.get("response_text")
            if not isinstance(text, str) or not text.strip():
                raise FastChatContractError("legacy_missing_text")
            citations = assessment.get("citations")
            if not isinstance(citations, list):
                citations = payload.get("citations")
            if not isinstance(citations, list):
                citations = []
            return parse_fast_chat_turn_output(
                {
                    "mode": "coaching",
                    "response_text": text,
                    "recommendation": nested_rec,
                    "recommendation_rationale": assessment.get(
                        "recommendation_rationale"
                    ),
                    "citations": citations,
                    "needs_source_retrieval": bool(
                        payload.get("needs_source_retrieval")
                    ),
                }
            )
    if has_assessment:
        rec = _recommendation_token(assessment.get("recommendation"))
        if rec not in {"stay", "advance"}:
            raise FastChatContractError("legacy_recommendation_missing")
        top = payload.get("recommendation")
        if top is not None and str(top).strip().lower() not in {"", "none", "null"}:
            top_rec = _recommendation_token(top)
            if top_rec != rec:
                raise FastChatContractError("recommendation_conflict")
        text = payload.get("response_text")
        if not isinstance(text, str) or not text.strip():
            raise FastChatContractError("legacy_missing_text")
        citations = assessment.get("citations")
        if not isinstance(citations, list):
            citations = payload.get("citations")
        if not isinstance(citations, list):
            citations = []
        return parse_fast_chat_turn_output(
            {
                "mode": "coaching",
                "response_text": text,
                "recommendation": rec,
                "recommendation_rationale": assessment.get("recommendation_rationale"),
                "citations": citations,
                "needs_source_retrieval": bool(payload.get("needs_source_retrieval")),
            }
        )
    text = payload.get("response_text")
    if not isinstance(text, str) or not text.strip():
        raise FastChatContractError("unrecognized")
    top_rec = _recommendation_token(payload.get("recommendation"))
    if top_rec is not None:
        raise FastChatContractError("recommendation_without_mode")
    citations = payload.get("citations")
    if citations is None:
        citations = []
    if not isinstance(citations, list):
        raise FastChatContractError("unrecognized")
    return parse_fast_chat_turn_output(
        {
            "mode": "qa",
            "response_text": text,
            "citations": citations,
            "needs_source_retrieval": bool(payload.get("needs_source_retrieval")),
        }
    )


_FAST_CHAT_RECOMMENDATION_ENUM = ("stay", "advance")


def _attach_fast_chat_mode_conditions(schema: dict[str, Any]) -> None:
    """Harden Fast Chat JSON Schema for coaching recommendation and citations.

    Strands 1.52.0 ``convert_pydantic_to_tool_spec`` flattens to ``type=object``
    plus ``properties`` and drops top-level ``oneOf`` / ``anyOf``. Claude tool
    ``input_schema`` also rejects top-level composition keywords. A
    discriminated-union RootModel is therefore unsafe here. Keep one object
    and express the coaching invariant with ``if`` / ``then``.

    The same flatten path marks every non-required property as
    ``type: [T, "null"]``. ``citations`` has a Python default of ``[]``, so
    Pydantic omits it from ``required`` and the model-facing spec becomes
    ``["array", "null"]``. Claude then emits ``citations: null``, which this
    model still rejects. Require an array so flatten keeps ``type: array``.
    JSON ``null`` stays invalid. Python callers may still omit the field.

    ``hmw_scaffold_ready`` is the same Boolean case: a Python default of
    ``False`` would otherwise flatten to ``["boolean", "null"]``. Require a
    boolean so the model-facing spec stays ``type: boolean``. Pydantic parse
    of omitted or malformed values still fails closed to ``False``.

    ``needs_source_retrieval`` is also required by the Fast Chat wire contract.
    Keep it as a non-null boolean in the model-facing schema; otherwise a
    nullable generated property can invite ``null``, which Pydantic rejects.

    Args:
        schema: Mutable ``model_json_schema()`` output for this class.

    Returns:
        None. Mutates ``schema`` in place.
    """
    schema["if"] = {
        "type": "object",
        "properties": {"mode": {"const": "coaching"}},
        "required": ["mode"],
    }
    schema["then"] = {
        "type": "object",
        "required": ["recommendation"],
        "properties": {
            "recommendation": {
                "type": "string",
                "enum": list(_FAST_CHAT_RECOMMENDATION_ENUM),
            }
        },
    }
    required = list(schema.get("required") or [])
    if "citations" not in required:
        required.append("citations")
    if "hmw_scaffold_ready" not in required:
        required.append("hmw_scaffold_ready")
    if "needs_source_retrieval" not in required:
        required.append("needs_source_retrieval")
    if "out_of_scope" not in required:
        required.append("out_of_scope")
    schema["required"] = required
    properties = schema.get("properties")
    citations = properties.get("citations") if isinstance(properties, dict) else None
    if isinstance(citations, dict):
        citations["type"] = "array"
        citations.pop("anyOf", None)
        citations.pop("oneOf", None)
    hmw_ready = (
        properties.get("hmw_scaffold_ready") if isinstance(properties, dict) else None
    )
    if isinstance(hmw_ready, dict):
        hmw_ready["type"] = "boolean"
        hmw_ready.pop("anyOf", None)
        hmw_ready.pop("oneOf", None)
    needs_retrieval = (
        properties.get("needs_source_retrieval") if isinstance(properties, dict) else None
    )
    if isinstance(needs_retrieval, dict):
        needs_retrieval["type"] = "boolean"
        needs_retrieval.pop("anyOf", None)
        needs_retrieval.pop("oneOf", None)
    out_of_scope = properties.get("out_of_scope") if isinstance(properties, dict) else None
    if isinstance(out_of_scope, dict):
        out_of_scope["type"] = "boolean"
        out_of_scope.pop("anyOf", None)
        out_of_scope.pop("oneOf", None)


class FastChatTurnOutput(BaseModel):
    """Lightweight one-call Coaching or Q&A result. Deep Review is separate.

    Wire shape stays a single object named ``FastChatTurnOutput``. Coaching
    requires ``recommendation`` stay or advance in both JSON Schema and
    Pydantic. Q&A still allows a null or omitted recommendation. Rationale
    remains optional.
    """

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_attach_fast_chat_mode_conditions,
    )

    mode: Literal["coaching", "qa"]
    response_text: str = Field(min_length=1)
    recommendation: Literal["stay", "advance"] | None = Field(
        default=None,
        description=(
            "stay or advance when mode is coaching; omit or null when mode is qa"
        ),
    )
    recommendation_rationale: str | None = Field(default=None, max_length=4_000)
    citations: list[CitationOutput] = Field(
        default_factory=list,
        description="Always return an array. Use [] when no citations are needed.",
    )
    hmw_scaffold_ready: bool = Field(
        default=False,
        description=(
            "Problem Identification only. Always return a boolean. Return true "
            "when at least two of identifiable user, understandable "
            "problem/context, and meaningful desired outcome are reasonably "
            "clear AND the student has not yet authored a valid working How "
            "Might We. Missing the third component, extra evidence, "
            "root-cause certainty, perfect scope, or complete consequences "
            "does not prevent true. Return false for 0–1 signals, Q&A, "
            "stages outside Problem Identification, or after a valid working "
            "How Might We."
        ),
    )
    needs_source_retrieval: bool = False
    out_of_scope: bool = Field(
        default=False,
        description=(
            "Return true only when the student's request or supplied material is "
            "clearly unrelated to CDE2300 course content and the active CDE2300 "
            "design project. Return false when relevance is plausible or uncertain."
        ),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def mode_must_be_coaching_or_qa(cls, value: str) -> str:
        """Reject modes outside the two-value fast-chat contract."""
        cleaned = str(value or "").strip().lower()
        if cleaned not in {"coaching", "qa"}:
            raise ValueError("mode must be coaching or qa")
        return cleaned

    @field_validator("recommendation", mode="before")
    @classmethod
    def recommendation_stay_advance_or_empty(cls, value: str | None) -> str | None:
        """Accept stay/advance; treat blank as absent."""
        cleaned = str(value or "").strip().lower()
        if cleaned in {"", "none", "null"}:
            return None
        if cleaned not in {"stay", "advance"}:
            raise ValueError("recommendation must be stay or advance")
        return cleaned

    @field_validator("recommendation_rationale", mode="before")
    @classmethod
    def compact_rationale(cls, value: Any) -> str | None:
        """Keep a short rationale or drop blanks."""
        cleaned = " ".join(str(value or "").split()).strip()
        return cleaned[:4_000] if cleaned else None

    @field_validator("hmw_scaffold_ready", mode="before")
    @classmethod
    def coerce_hmw_scaffold_ready(cls, value: Any) -> bool:
        """Accept only JSON true; omit, null, and malformed values are false."""
        return value is True

    @field_validator("out_of_scope", mode="before")
    @classmethod
    def coerce_out_of_scope(cls, value: Any) -> bool:
        """Accept only JSON true; malformed values fail closed to in-scope."""
        return value is True

    @model_validator(mode="after")
    def coaching_requires_recommendation(self) -> "FastChatTurnOutput":
        """Coaching must recommend stay or advance; Q&A must not.

        Q&A also forces ``hmw_scaffold_ready`` false so a course question
        cannot unlock Problem Identification UI guidance.
        """
        if self.out_of_scope:
            return self.model_copy(
                update={
                    "mode": "qa",
                    "recommendation": None,
                    "recommendation_rationale": None,
                    "citations": [],
                    "hmw_scaffold_ready": False,
                    "needs_source_retrieval": False,
                }
            )
        if self.mode == "coaching":
            if self.recommendation not in {"stay", "advance"}:
                raise ValueError("coaching mode requires recommendation stay or advance")
            return self
        return self.model_copy(
            update={
                "recommendation": None,
                "recommendation_rationale": None,
                "hmw_scaffold_ready": False,
            }
        )


class ReviewTurnOutput(BaseModel):
    """Formative Review result for incremental Haiku or deep Sonnet.

    Incremental mode keeps the Review projection current and may flag
    ``readiness_candidate``. Deep mode may recommend stay/advance. FastAPI
    still owns stage mutation. This is never a grade.
    """

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list, max_length=4)
    areas_to_develop: list[str] = Field(default_factory=list, max_length=4)
    synthesis: str = Field(min_length=1)
    citations: list[CitationOutput] = Field(default_factory=list)
    facione_profile: FacioneScoresOutput | None = None
    readiness_candidate: bool = False
    review_depth: str | None = None
    working_conclusion: str = Field(default="", max_length=4_000)
    current_stage: str | None = Field(default=None, max_length=64)
    recommendation: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    readiness_evidence: list[str] = Field(default_factory=list, max_length=8)
    missing_requirements: list[str] = Field(default_factory=list, max_length=8)
    rationale_summary: str = Field(default="", max_length=1_000)

    @model_validator(mode="before")
    @classmethod
    def coerce_live_and_judge_shapes(cls, value: Any) -> Any:
        """Fill student-facing fields from synthesis or judge-shaped output."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        rationale = str(data.get("rationale_summary") or "").strip()
        synthesis = str(data.get("synthesis") or "").strip()
        response = str(data.get("response_text") or "").strip()
        if not response:
            filled = synthesis or rationale
            if filled:
                data["response_text"] = filled
        if not synthesis and rationale:
            data["synthesis"] = rationale
        recommendation = data.get("recommendation")
        if isinstance(recommendation, str):
            cleaned = recommendation.strip().lower()
            data["recommendation"] = cleaned or None
        depth = str(data.get("review_depth") or "").strip().lower()
        data["review_depth"] = depth if depth in {"incremental", "deep"} else depth or None
        return data

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_stay_advance_or_empty(cls, value: str | None) -> str | None:
        """Accept stay/advance from Deep Review; drop empty incremental values."""
        cleaned = str(value or "").strip().lower()
        if cleaned in {"", "none", "null"}:
            return None
        if cleaned not in {"stay", "advance"}:
            raise ValueError("recommendation must be stay or advance")
        return cleaned

    @field_validator("current_stage")
    @classmethod
    def current_stage_is_compact(cls, value: str | None) -> str | None:
        """Keep an optional stage token compact for equality checks."""
        cleaned = " ".join(str(value or "").split())[:64]
        return cleaned or None

    @field_validator("readiness_evidence", "missing_requirements")
    @classmethod
    def compact_string_lists(cls, values: list[str]) -> list[str]:
        """Bound Deep Review bullet lists without keeping empty items."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = " ".join(str(item or "").split())[:400]
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        return cleaned[:8]


_THINKING_PATH_STAGE_IDS = (
    "problem_identification",
    "concept_generation",
    "design_specification",
    "deep_analysis",
    "reflection",
)
ThinkingPathStageId = Literal[
    "problem_identification",
    "concept_generation",
    "design_specification",
    "deep_analysis",
    "reflection",
]
_THINKING_PATH_STAGE_ID_SET = frozenset(_THINKING_PATH_STAGE_IDS)


def _force_schema_array(schema: dict[str, Any], field: str) -> None:
    """Require one JSON Schema field to be an array, never null."""
    required = list(schema.get("required") or [])
    if field not in required:
        required.append(field)
    schema["required"] = required
    properties = schema.get("properties")
    node = properties.get(field) if isinstance(properties, dict) else None
    if isinstance(node, dict):
        node["type"] = "array"
        node.pop("anyOf", None)
        node.pop("oneOf", None)


def _compact_message_refs(values: Any, *, limit: int = 3) -> list[str]:
    """Keep unique ephemeral ``M#`` labels; drop unknown shapes."""
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"^M([1-9][0-9]{0,3})$")
    for item in values:
        label = str(item or "").strip()
        if not pattern.fullmatch(label) or label in seen:
            continue
        seen.add(label)
        cleaned.append(label)
        if len(cleaned) >= limit:
            break
    return cleaned


def _attach_deep_review_stage_feedback_schema(schema: dict[str, Any]) -> None:
    """Keep stage-feedback bullet lists as arrays after Strands flatten."""
    _force_schema_array(schema, "strengths")
    _force_schema_array(schema, "areas_to_develop")
    _force_schema_array(schema, "supporting_message_refs")


def _attach_deep_review_turn_schema(schema: dict[str, Any]) -> None:
    """Keep new Deep Review collection fields required, non-null arrays.

    ``ReviewTurnOutput`` remains deliberately permissive for historical
    incremental/legacy payloads. This hook is applied only to the new Deep
    Review structured-output contract used by the runtime.
    """
    for field in (
        "strengths",
        "areas_to_develop",
        "readiness_evidence",
        "missing_requirements",
    ):
        _force_schema_array(schema, field)
    _force_schema_array(schema, "stage_reviews")


def _compact_review_bullets(values: Any, *, limit: int = 8) -> list[str]:
    """Normalize Deep Review bullet lists without keeping empty items."""
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = " ".join(str(item or "").split())[:400]
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


class DeepReviewStageFeedback(BaseModel):
    """Stage-attributed Deep Review strengths and areas.

    Incremental Review does not use this object. Empty arrays mean the stage
    was represented in the frozen conversation but has no item of that kind.
    """

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_attach_deep_review_stage_feedback_schema,
    )

    stage_id: ThinkingPathStageId
    strengths: list[str] = Field(
        max_length=8,
        description="Always return an array. Use [] when this stage has no strengths.",
    )
    areas_to_develop: list[str] = Field(
        max_length=8,
        description=(
            "Always return an array. Use [] when this stage has no areas to develop."
        ),
    )
    supporting_message_refs: list[str] = Field(
        max_length=3,
        description=(
            "Always return an array of ephemeral M# labels from this request "
            "that support this stage's strengths or areas. Prefer student "
            "messages. Use [] when there is no specific original-message anchor. "
            "Do not invent labels or database identifiers."
        ),
    )

    @field_validator("strengths", "areas_to_develop", mode="before")
    @classmethod
    def coerce_bullet_arrays(cls, value: Any) -> list[str]:
        """Require arrays for new Deep Review stage feedback."""
        if not isinstance(value, list):
            raise ValueError("Deep Review stage feedback fields must be arrays")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("Deep Review stage feedback items must be strings")
        return _compact_review_bullets(value)

    @field_validator("supporting_message_refs", mode="before")
    @classmethod
    def coerce_supporting_message_refs(cls, value: Any) -> list[str]:
        """Require an array of ephemeral refs for new Deep Review output."""
        if not isinstance(value, list):
            raise ValueError("supporting_message_refs must be an array")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("supporting_message_refs items must be strings")
        return _compact_message_refs(value)


class DeepReviewTurnOutput(ReviewTurnOutput):
    """Deep Review result with whole-conversation and per-stage feedback.

    Holistic fields stay on the parent: synthesis, Facione, working
    conclusion, readiness, and missing requirements. ``stage_reviews`` is
    the student-facing Strengths / Areas projection. Incremental Review
    keeps :class:`ReviewTurnOutput` and must not emit this object.
    """

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_attach_deep_review_turn_schema,
    )

    # These fields are required by the new Deep Review wire contract.  Keep
    # the defaults on ReviewTurnOutput for incremental and v24 compatibility,
    # but do not let a missing or flattened top-level array become an empty
    # Deep Review result.
    strengths: list[str] = Field(
        max_length=4,
        description="Always return an array. Use [] when there are no strengths.",
    )
    areas_to_develop: list[str] = Field(
        max_length=4,
        description=(
            "Always return an array. Use [] when there are no areas to develop."
        ),
    )
    readiness_evidence: list[str] = Field(
        max_length=8,
        description=(
            "Always return an array. Use [] when there is no readiness evidence."
        ),
    )
    missing_requirements: list[str] = Field(
        max_length=8,
        description=(
            "Always return an array. Use [] when there are no missing requirements."
        ),
    )

    stage_reviews: list[DeepReviewStageFeedback] = Field(
        description=(
            "Always return an array. Include only Thinking Path stages with "
            "conversation evidence. Use [] when no stage-specific items exist."
        ),
    )

    @field_validator(
        "strengths",
        "areas_to_develop",
        "readiness_evidence",
        "missing_requirements",
        mode="before",
    )
    @classmethod
    def require_top_level_string_arrays(cls, value: Any) -> Any:
        """Reject missing-shape Deep Review arrays before Pydantic coercion."""
        if not isinstance(value, list):
            raise ValueError("Deep Review top-level fields must be arrays")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("Deep Review top-level array items must be strings")
        return value

    @model_validator(mode="before")
    @classmethod
    def filter_unknown_stage_ids(cls, value: Any) -> Any:
        """Keep unknown stage ids out without weakening array validation.

        Missing ``stage_reviews`` is intentionally left missing so direct
        validation remains strict. The compatibility parser adds ``[]`` only
        for an explicitly identified legacy payload.
        """
        if not isinstance(value, dict) or "stage_reviews" not in value:
            return value
        raw = value["stage_reviews"]
        if not isinstance(raw, list):
            return value
        if any(not isinstance(item, dict) for item in raw):
            raise ValueError("stage_reviews items must be objects")
        data = dict(value)
        data["stage_reviews"] = [
            item
            for item in raw
            if str(item.get("stage_id") or "").strip()
            in _THINKING_PATH_STAGE_ID_SET
        ]
        return data

    @model_validator(mode="after")
    def compact_stage_reviews(self) -> "DeepReviewTurnOutput":
        """Merge duplicate stage ids, drop empty entries, keep path order."""
        merged: dict[str, DeepReviewStageFeedback] = {}
        for item in self.stage_reviews:
            existing = merged.get(item.stage_id)
            if existing is None:
                merged[item.stage_id] = item
                continue
            merged[item.stage_id] = item.model_copy(
                update={
                    "strengths": _compact_review_bullets(
                        [*existing.strengths, *item.strengths]
                    ),
                    "areas_to_develop": _compact_review_bullets(
                        [*existing.areas_to_develop, *item.areas_to_develop]
                    ),
                    "supporting_message_refs": _compact_message_refs(
                        [
                            *existing.supporting_message_refs,
                            *item.supporting_message_refs,
                        ]
                    ),
                }
            )
        kept: list[DeepReviewStageFeedback] = []
        for stage_id in _THINKING_PATH_STAGE_IDS:
            item = merged.get(stage_id)
            if item is None:
                continue
            if not item.strengths and not item.areas_to_develop:
                continue
            kept.append(item)
        if kept == list(self.stage_reviews):
            return self
        return self.model_copy(update={"stage_reviews": kept})


class RouterOutput(BaseModel):
    """Strict specialist classification. Never a stage or authorization decision."""

    model_config = ConfigDict(extra="ignore")

    specialist: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_category: str | None = None

    @field_validator("specialist")
    @classmethod
    def specialist_must_be_supported(cls, value: str) -> str:
        """Accept only the three FastAPI-owned specialists."""
        cleaned = str(value or "").strip().lower()
        if cleaned not in {"qa", "coaching", "review"}:
            raise ValueError("specialist must be qa, coaching, or review")
        return cleaned

    @field_validator("rationale_category")
    @classmethod
    def rationale_category_must_be_known(cls, value: str | None) -> str | None:
        """Drop unknown category labels. Do not store free-text rationale."""
        cleaned = str(value or "").strip().lower()
        if cleaned in {"", "none", "null"}:
            return None
        if cleaned not in {
            "course_information",
            "project_coaching",
            "formative_review",
        }:
            return None
        return cleaned


class StageJudgeOutput(BaseModel):
    """Sonnet readiness classification. FastAPI still owns stage mutation."""

    model_config = ConfigDict(extra="ignore")

    current_stage: str = Field(min_length=1, max_length=64)
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    readiness_evidence: list[str] = Field(default_factory=list, max_length=8)
    missing_requirements: list[str] = Field(default_factory=list, max_length=8)
    rationale_summary: str = Field(min_length=1, max_length=1_000)

    @field_validator("current_stage")
    @classmethod
    def current_stage_is_compact(cls, value: str) -> str:
        """Keep the judge's stage token compact for equality checks."""
        cleaned = " ".join(str(value or "").split())[:64]
        if not cleaned:
            raise ValueError("current_stage is required")
        return cleaned

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_stay_or_advance(cls, value: str) -> str:
        """Reject recommendations outside stay/advance."""
        cleaned = str(value or "").strip().lower()
        if cleaned not in {"stay", "advance"}:
            raise ValueError("recommendation must be stay or advance")
        return cleaned

    @field_validator("readiness_evidence", "missing_requirements")
    @classmethod
    def compact_string_lists(cls, values: list[str]) -> list[str]:
        """Bound judge bullet lists without keeping empty items."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = " ".join(str(item or "").split())[:400]
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        return cleaned[:8]


def parse_coach_turn_output(value: Any) -> CoachTurnOutput:
    """Validate one coach_turn payload or raise ``ValidationError``.

    Args:
        value: A Pydantic model, mapping, or JSON-compatible object.

    Returns:
        A validated :class:`CoachTurnOutput`.

    Raises:
        ValidationError: When coaching fields are missing or invalid.
    """
    if isinstance(value, CoachTurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return CoachTurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return CoachTurnOutput.model_validate(value)
    return CoachTurnOutput.model_validate(value)


def parse_qa_turn_output(value: Any) -> QATurnOutput:
    """Validate one Q&A payload or raise ``ValidationError``."""
    if isinstance(value, QATurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return QATurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return QATurnOutput.model_validate(value)
    return QATurnOutput.model_validate(value)


def parse_fast_chat_turn_output(value: Any) -> FastChatTurnOutput:
    """Validate one fast-chat payload or raise ``ValidationError``."""
    if isinstance(value, FastChatTurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return FastChatTurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return FastChatTurnOutput.model_validate(value)
    return FastChatTurnOutput.model_validate(value)


def parse_review_turn_output(
    value: Any,
    *,
    allow_legacy: bool = False,
) -> ReviewTurnOutput:
    """Validate one Review payload or raise ``ValidationError``.

    New Deep Review payloads use the strict stage-aware contract. The
    application compatibility boundary may pass ``allow_legacy=True`` for
    v24 payloads that have ``review_depth=deep`` but no ``stage_reviews``;
    the runtime leaves that flag false so malformed new output triggers
    bounded recovery.
    """
    if isinstance(value, DeepReviewTurnOutput):
        return value
    if isinstance(value, ReviewTurnOutput):
        return value
    payload = value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            payload = value.model_dump(mode="json")
        except (TypeError, ValidationError):
            payload = value
    data = payload if isinstance(payload, dict) else None
    if data is not None and (
        "stage_reviews" in data
        or str(data.get("review_depth") or "").strip().lower() == "deep"
    ):
        if (
            allow_legacy
            and
            "stage_reviews" not in data
            and str(data.get("review_depth") or "").strip().lower() == "deep"
        ):
            # Keep the old flat payload as the legacy model. Do not turn it
            # into a new stage-aware empty result, which would change review
            # projection semantics.
            return ReviewTurnOutput.model_validate(data)
        return DeepReviewTurnOutput.model_validate(data)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return ReviewTurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return ReviewTurnOutput.model_validate(value)
    return ReviewTurnOutput.model_validate(value)


def parse_router_output(value: Any) -> RouterOutput:
    """Validate one router payload or raise ``ValidationError``."""
    if isinstance(value, RouterOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return RouterOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return RouterOutput.model_validate(value)
    return RouterOutput.model_validate(value)


def parse_stage_judge_output(value: Any) -> StageJudgeOutput:
    """Validate one stage-judge payload or raise ``ValidationError``."""
    if isinstance(value, StageJudgeOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return StageJudgeOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return StageJudgeOutput.model_validate(value)
    return StageJudgeOutput.model_validate(value)
