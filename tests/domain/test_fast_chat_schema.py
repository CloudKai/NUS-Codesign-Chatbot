"""Lightweight FastChatTurnOutput contract tests. No AWS."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agentcore_runtime.models import (
    FAST_CHAT_SCHEMA_ID,
    FastChatContractError,
    FastChatTurnOutput,
    adapt_fast_chat_turn_payload,
    parse_fast_chat_turn_output,
)
from backend.domain import EducationalAssessment, StageDecision


_TEXT = "What specifically prevents noon booking?"


def _coaching(**extra: Any) -> dict[str, Any]:
    """Return a coaching payload with optional overrides. No student secrets."""
    payload: dict[str, Any] = {
        "mode": "coaching",
        "response_text": _TEXT,
        "recommendation": "stay",
    }
    payload.update(extra)
    return payload


def _qa(**extra: Any) -> dict[str, Any]:
    """Return a Q&A payload with optional overrides."""
    payload: dict[str, Any] = {
        "mode": "qa",
        "response_text": "Week 1 covers Innovation-driven economy [S1].",
        "citations": [{"label": "S1", "title": "Week 1"}],
    }
    payload.update(extra)
    return payload


def _schema_instance(**fields: Any) -> dict[str, Any]:
    """Return a Fast Chat instance that satisfies generated ``required`` keys."""
    payload: dict[str, Any] = {
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }
    payload.update(fields)
    return payload


def _schema_allows(schema: dict[str, Any], instance: Any) -> bool:
    """Return whether ``instance`` satisfies a Fast Chat JSON Schema subset.

    Supports the keywords this model actually emits: type, properties,
    required, enum, const, anyOf, if/then, minLength. Extra instance keys
    are allowed. This is a structural checker, not a full JSON Schema suite.
    """
    if not isinstance(schema, dict):
        return False
    if "anyOf" in schema:
        return any(_schema_allows(option, instance) for option in schema["anyOf"])
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        actual = _json_type_name(instance)
        if actual not in names:
            return False
    if "const" in schema and instance != schema["const"]:
        return False
    if "enum" in schema and instance not in schema["enum"]:
        return False
    if isinstance(instance, str) and "minLength" in schema:
        if len(instance) < int(schema["minLength"]):
            return False
    if not isinstance(instance, dict):
        return True
    required = schema.get("required") or []
    if any(key not in instance for key in required):
        return False
    properties = schema.get("properties") or {}
    for key, subschema in properties.items():
        if key not in instance:
            continue
        if not _schema_allows(subschema, instance[key]):
            return False
    if_schema = schema.get("if")
    then_schema = schema.get("then")
    if if_schema is not None and then_schema is not None:
        if _schema_allows(if_schema, instance) and not _schema_allows(
            then_schema, instance
        ):
            return False
    return True


def _json_type_name(value: Any) -> str:
    """Return the JSON Schema type name for a Python value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def test_qa_null_recommendation_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(_qa(recommendation=None))
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_qa_omitted_recommendation_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(_qa())
    assert parsed.recommendation is None


def test_coaching_stay_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(_coaching(recommendation="stay"))
    assert parsed.recommendation == "stay"


def test_coaching_advance_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(_coaching(recommendation="advance"))
    assert parsed.recommendation == "advance"


def test_coaching_null_recommendation_fails_pydantic() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(recommendation=None))


def test_null_needs_source_retrieval_fails_pydantic() -> None:
    """The required retrieval flag must remain a JSON boolean, not null."""
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_qa(needs_source_retrieval=None))


def test_coaching_missing_recommendation_fails() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(
            {"mode": "coaching", "response_text": _TEXT}
        )


def test_invalid_recommendation_enum_fails() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(recommendation="maybe"))


def test_coaching_rationale_is_optional() -> None:
    parsed = FastChatTurnOutput.model_validate(_coaching())
    assert parsed.recommendation == "stay"
    assert parsed.recommendation_rationale is None


def test_generated_schema_is_single_object_not_union() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    assert schema.get("type") == "object"
    assert "oneOf" not in schema
    assert "anyOf" not in schema
    assert "allOf" not in schema
    assert "if" in schema
    assert "then" in schema
    then_rec = schema["then"]["properties"]["recommendation"]
    assert then_rec.get("type") == "string"
    assert then_rec.get("enum") == ["stay", "advance"]
    assert "recommendation" in schema["then"]["required"]
    assert "citations" in (schema.get("required") or [])
    assert "hmw_scaffold_ready" in (schema.get("required") or [])
    assert "needs_source_retrieval" in (schema.get("required") or [])
    assert "out_of_scope" in (schema.get("required") or [])
    citations = (schema.get("properties") or {}).get("citations") or {}
    assert citations.get("type") == "array"
    assert "null" not in str(citations.get("type"))
    assert citations.get("anyOf") is None
    assert citations.get("oneOf") is None
    hmw_ready = (schema.get("properties") or {}).get("hmw_scaffold_ready") or {}
    assert hmw_ready.get("type") == "boolean"
    assert "null" not in str(hmw_ready.get("type"))
    assert hmw_ready.get("anyOf") is None
    assert hmw_ready.get("oneOf") is None
    description = " ".join(str(hmw_ready.get("description") or "").split())
    assert "at least two of identifiable user" in description
    assert "does not prevent true" in description
    assert "not yet ready to attempt" not in description.lower()
    assert "hmw_scaffold_ready" in (schema.get("required") or [])
    needs_retrieval = (
        (schema.get("properties") or {}).get("needs_source_retrieval") or {}
    )
    assert needs_retrieval.get("type") == "boolean"
    assert "null" not in str(needs_retrieval.get("type"))
    assert needs_retrieval.get("anyOf") is None
    assert needs_retrieval.get("oneOf") is None
    out_of_scope = (schema.get("properties") or {}).get("out_of_scope") or {}
    assert out_of_scope.get("type") == "boolean"
    assert "null" not in str(out_of_scope.get("type"))


def test_generated_schema_rejects_coaching_null_and_keeps_qa_null() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    coaching_stay = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
    )
    coaching_advance = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="advance",
    )
    coaching_null = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation=None,
    )
    coaching_missing = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
    )
    qa_null = _schema_instance(
        mode="qa",
        response_text="Week 1.",
        recommendation=None,
    )
    qa_omitted = _schema_instance(mode="qa", response_text="Week 1.")
    assert _schema_allows(schema, coaching_stay)
    assert _schema_allows(schema, coaching_advance)
    assert not _schema_allows(schema, coaching_null)
    assert not _schema_allows(schema, coaching_missing)
    assert _schema_allows(schema, qa_null)
    assert _schema_allows(schema, qa_omitted)


def test_generated_schema_rejects_null_boolean_contract_fields() -> None:
    """The model-facing schema must not advertise null for required booleans."""
    schema = FastChatTurnOutput.model_json_schema()
    base = _schema_instance(mode="qa", response_text="Week 1.")
    assert not _schema_allows(schema, {**base, "hmw_scaffold_ready": None})
    assert not _schema_allows(schema, {**base, "needs_source_retrieval": None})
    assert not _schema_allows(schema, {**base, "out_of_scope": None})


def test_out_of_scope_normalizes_to_non_mutating_qa() -> None:
    """A scope boundary cannot cite, advance, or unlock HMW guidance."""
    parsed = FastChatTurnOutput.model_validate(
        _coaching(
            recommendation="advance",
            citations=[{"label": "S1", "title": "Unrelated file"}],
            hmw_scaffold_ready=True,
            needs_source_retrieval=True,
            out_of_scope=True,
        )
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None
    assert parsed.citations == []
    assert parsed.hmw_scaffold_ready is False
    assert parsed.needs_source_retrieval is False


def test_out_of_scope_missing_or_malformed_is_in_scope() -> None:
    """Older runtimes and malformed flags fail closed to normal handling."""
    assert FastChatTurnOutput.model_validate(_qa()).out_of_scope is False
    assert FastChatTurnOutput.model_validate(_qa(out_of_scope="true")).out_of_scope is False


def test_coaching_schema_requires_stay_or_advance_and_omits_assessment() -> None:
    parsed = parse_fast_chat_turn_output(
        {
            "mode": "coaching",
            "response_text": "What specifically prevents noon booking?",
            "recommendation": "stay",
            "recommendation_rationale": "The booking mechanism is still unproven.",
            "citations": [],
            "needs_source_retrieval": False,
        }
    )
    dumped = parsed.model_dump(mode="json")
    assert "assessment" not in FastChatTurnOutput.model_fields
    assert "assessment" not in dumped
    assert "facione_scores" not in dumped
    assert "research_coding" not in dumped
    assert "review_strengths" not in dumped


def test_qa_schema_drops_recommendation() -> None:
    parsed = FastChatTurnOutput.model_validate(
        {
            "mode": "qa",
            "response_text": "Week 1 covers Innovation-driven economy [S1].",
            "recommendation": "stay",
            "recommendation_rationale": "ignore me",
            "citations": [{"label": "S1", "title": "Week 1"}],
        }
    )
    assert parsed.recommendation is None
    assert parsed.recommendation_rationale is None


def test_coaching_without_recommendation_fails() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(
            {"mode": "coaching", "response_text": "Hello"}
        )


def test_legacy_full_assessment_still_parses() -> None:
    assessment = EducationalAssessment.model_validate(
        {
            "current_stage": "problem_identification",
            "contribution_summary": "The student compared two constraints.",
            "stage_assessment": "Usable starting point.",
            "critical_understanding_level": "Developing",
            "confidence": 0.7,
            "recommendation": "STAY",
            "recommendation_rationale": "More evidence is needed.",
            "guidance_questions": ["What trade-off still needs evidence?"],
            "learning_summary": "The student is developing the problem.",
            "working_conclusion": "Evening rooms are scarce.",
            "review_strengths": ["Named a setting"],
            "review_improvements": ["Name who is affected"],
            "facione_scores": {"analysis": 2, "evaluation": 1},
            "research_coding": {"ignored": True},
        }
    )
    assert assessment.recommendation is StageDecision.STAY
    assert assessment.facione_scores.analysis == 2
    assert assessment.review_strengths == ["Named a setting"]


def test_fast_chat_persisted_mapping_omits_review_fields() -> None:
    slim = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        recommendation_rationale="More evidence is needed.",
        response_mode="coaching",
    ).persisted_mapping()
    assert slim["response_mode"] == "coaching"
    assert slim["recommendation"] == "stay"
    assert "hmw_scaffold_ready" not in slim
    assert "facione_scores" not in slim
    assert "review_strengths" not in slim
    assert "working_conclusion" not in slim
    assert "research_coding" not in slim


def _legacy_coach_turn(*, recommendation: str = "stay") -> dict:
    """Return the immediately-previous nested coach_turn wire shape."""
    return {
        "response_text": "What specifically prevents noon booking?",
        "assessment": {
            "current_stage": "problem_identification",
            "contribution_summary": "The student compared two constraints.",
            "stage_assessment": "Usable starting point.",
            "critical_understanding_level": "Developing",
            "confidence": 0.7,
            "recommendation": recommendation,
            "recommendation_rationale": "The booking mechanism is still unproven.",
            "guidance_questions": ["What trade-off still needs evidence?"],
            "learning_summary": "The student is developing the problem.",
            "citations": [],
            "facione_scores": {"analysis": 2, "evaluation": 1},
        },
        "research_coding": None,
    }


def test_adapt_slim_fast_chat_payload() -> None:
    parsed = adapt_fast_chat_turn_payload(
        _schema_instance(
            mode="coaching",
            response_text="What specifically prevents noon booking?",
            recommendation="stay",
            schema_id=FAST_CHAT_SCHEMA_ID,
        )
    )
    assert parsed.mode == "coaching"
    assert parsed.recommendation == "stay"


def test_adapt_wire_payload_missing_required_fields_fails() -> None:
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload({"mode": "qa", "response_text": "Week 1."})
    assert raised.value.reason == "slim_invalid"


def test_adapt_full_wire_payload_passes() -> None:
    parsed = adapt_fast_chat_turn_payload(
        _schema_instance(
            mode="qa",
            response_text="Week 1 covers Innovation-driven economy [S1].",
            citations=[{"label": "S1", "title": "Week 1"}],
        )
    )
    assert parsed.mode == "qa"
    assert parsed.citations


def test_adapt_legacy_coach_turn_keeps_assessment_recommendation() -> None:
    parsed = adapt_fast_chat_turn_payload(_legacy_coach_turn(recommendation="advance"))
    assert parsed.mode == "coaching"
    assert parsed.recommendation == "advance"


def test_adapt_legacy_qa_turn_does_not_invent_recommendation() -> None:
    parsed = adapt_fast_chat_turn_payload(
        {
            "response_text": "Week 1 covers Innovation-driven economy [S1].",
            "citations": [{"label": "S1"}],
        }
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_adapt_legacy_missing_recommendation_fails() -> None:
    payload = _legacy_coach_turn(recommendation="maybe")
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(payload)
    assert raised.value.reason == "legacy_recommendation_missing"


def test_adapt_recommendation_without_mode_fails() -> None:
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(
            {
                "response_text": "What specifically prevents noon booking?",
                "recommendation": "advance",
            }
        )
    assert raised.value.reason == "recommendation_without_mode"


def test_adapt_qa_mode_ignores_nested_assessment_advance() -> None:
    parsed = adapt_fast_chat_turn_payload(
        _schema_instance(
            mode="qa",
            response_text="The lecture names stakeholders.",
            assessment=_legacy_coach_turn(recommendation="advance")["assessment"],
        )
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_adapt_conflicting_recommendations_fail() -> None:
    payload = _legacy_coach_turn(recommendation="advance")
    payload["mode"] = "coaching"
    payload["recommendation"] = "stay"
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(payload)
    assert raised.value.reason == "recommendation_conflict"


def test_adapt_malformed_payload_fails_closed() -> None:
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload({"foo": 1})
    assert raised.value.reason == "unrecognized"
    with pytest.raises(FastChatContractError) as raised_review:
        adapt_fast_chat_turn_payload(
            {
                "response_text": "Formative review.",
                "synthesis": "Progress is forming.",
                "strengths": ["Named a setting"],
            }
        )
    assert raised_review.value.reason == "wrong_contract"


def test_coaching_omitted_citations_default_to_empty_list() -> None:
    parsed = FastChatTurnOutput.model_validate(_coaching())
    assert parsed.citations == []


def test_coaching_empty_citations_are_valid() -> None:
    parsed = FastChatTurnOutput.model_validate(_coaching(citations=[]))
    assert parsed.citations == []


def test_coaching_null_citations_fail_pydantic() -> None:
    with pytest.raises(ValidationError) as raised:
        FastChatTurnOutput.model_validate(_coaching(citations=None))
    assert "citations" in str(raised.value)


def test_coaching_string_citations_fail_pydantic() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(citations="S1"))


def test_coaching_object_citations_fail_pydantic() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(citations={}))


def test_coaching_numeric_citations_fail_pydantic() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(citations=123))


def test_coaching_malformed_citation_item_fails_pydantic() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(_coaching(citations=[{"wrong": "shape"}]))


def test_coaching_valid_citation_list_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(
        _coaching(citations=[{"label": "S1", "title": "Week 1"}])
    )
    assert parsed.citations[0].label == "S1"
    assert parsed.citations[0].title == "Week 1"


def test_qa_omitted_citations_default_to_empty_list() -> None:
    parsed = FastChatTurnOutput.model_validate(
        {"mode": "qa", "response_text": "Week 1 covers innovation."}
    )
    assert parsed.mode == "qa"
    assert parsed.citations == []


def test_qa_empty_citations_are_valid() -> None:
    parsed = FastChatTurnOutput.model_validate(
        {"mode": "qa", "response_text": "Week 1 covers innovation.", "citations": []}
    )
    assert parsed.citations == []


def test_qa_null_citations_fail_pydantic() -> None:
    with pytest.raises(ValidationError) as raised:
        FastChatTurnOutput.model_validate(
            {
                "mode": "qa",
                "response_text": "Week 1 covers innovation.",
                "citations": None,
            }
        )
    assert "citations" in str(raised.value)


def test_qa_valid_citation_list_passes_pydantic() -> None:
    parsed = FastChatTurnOutput.model_validate(_qa())
    assert parsed.citations[0].label == "S1"


def test_generated_schema_rejects_citations_null_and_requires_array() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    coaching_empty = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
    )
    coaching_null = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
        citations=None,
    )
    coaching_omitted = {
        "mode": "coaching",
        "response_text": _TEXT,
        "recommendation": "stay",
        "hmw_scaffold_ready": False,
    }
    coaching_string = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
        citations="S1",
    )
    qa_valid = _schema_instance(
        mode="qa",
        response_text="Week 1.",
        citations=[{"label": "S1"}],
    )
    qa_null = _schema_instance(mode="qa", response_text="Week 1.", citations=None)
    assert _schema_allows(schema, coaching_empty)
    assert not _schema_allows(schema, coaching_null)
    assert not _schema_allows(schema, coaching_omitted)
    assert not _schema_allows(schema, coaching_string)
    assert _schema_allows(schema, qa_valid)
    assert not _schema_allows(schema, qa_null)


def test_hmw_scaffold_ready_omitted_or_null_defaults_false() -> None:
    """Old Fast Chat payloads without the field must still parse."""
    omitted = parse_fast_chat_turn_output(
        {
            "mode": "coaching",
            "response_text": _TEXT,
            "recommendation": "stay",
            "citations": [],
        }
    )
    assert omitted.hmw_scaffold_ready is False
    nullish = parse_fast_chat_turn_output(
        {
            "mode": "coaching",
            "response_text": _TEXT,
            "recommendation": "stay",
            "citations": [],
            "hmw_scaffold_ready": None,
        }
    )
    assert nullish.hmw_scaffold_ready is False
    malformed = parse_fast_chat_turn_output(
        {
            "mode": "coaching",
            "response_text": _TEXT,
            "recommendation": "stay",
            "citations": [],
            "hmw_scaffold_ready": "true",
        }
    )
    assert malformed.hmw_scaffold_ready is False


def test_qa_forces_hmw_scaffold_ready_false() -> None:
    """Q&A cannot unlock How Might We readiness."""
    parsed = parse_fast_chat_turn_output(
        _qa(hmw_scaffold_ready=True, recommendation="advance")
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None
    assert parsed.hmw_scaffold_ready is False


def test_coaching_hmw_scaffold_ready_true_does_not_imply_advance() -> None:
    """Readiness to formulate is independent of stay/advance."""
    parsed = parse_fast_chat_turn_output(
        _coaching(hmw_scaffold_ready=True, recommendation="stay", citations=[])
    )
    assert parsed.hmw_scaffold_ready is True
    assert parsed.recommendation == "stay"


def test_generated_schema_rejects_hmw_scaffold_ready_null() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    valid = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
        hmw_scaffold_ready=True,
    )
    omitted = {
        "mode": "coaching",
        "response_text": _TEXT,
        "recommendation": "stay",
        "citations": [],
    }
    nullish = _schema_instance(
        mode="coaching",
        response_text=_TEXT,
        recommendation="stay",
        hmw_scaffold_ready=None,
    )
    assert _schema_allows(schema, valid)
    assert not _schema_allows(schema, omitted)
    assert not _schema_allows(schema, nullish)


def test_persisted_mapping_keeps_hmw_scaffold_ready_only_when_true() -> None:
    slim_false = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        response_mode="coaching",
        hmw_scaffold_ready=False,
    ).persisted_mapping()
    assert "hmw_scaffold_ready" not in slim_false
    slim_true = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        response_mode="coaching",
        hmw_scaffold_ready=True,
    ).persisted_mapping()
    assert slim_true["hmw_scaffold_ready"] is True
    old = EducationalAssessment.model_validate(
        {
            "current_stage": "problem_identification",
            "response_mode": "coaching",
            "recommendation": "stay",
        }
    )
    assert old.hmw_scaffold_ready is False
