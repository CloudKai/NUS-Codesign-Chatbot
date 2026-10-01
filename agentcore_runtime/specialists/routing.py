"""Deterministic specialist phase selection inside the AgentCore runtime.

Unknown phases fall closed to coaching with no tools. They must never fall
through to Q&A, which historically attached Knowledge Base tools in the POC.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PHASE_QA = "qa"
PHASE_COACHING = "coaching"
PHASE_REVIEW = "review"
PHASE_ROUTER = "router"
PHASE_FAST_CHAT = "fast_chat"
REVIEW_MODE_INCREMENTAL = "incremental"
REVIEW_MODE_DEEP = "deep"
ALLOWED_PHASES = frozenset({PHASE_QA, PHASE_COACHING, PHASE_REVIEW})
SPECIALIST_PHASES = ALLOWED_PHASES
STRUCTURED_CONTRACTS = frozenset(
    {
        "coach_turn",
        "qa_turn",
        "review_turn",
        "router_turn",
        "fast_chat_turn",
    }
)


def normalize_phase(value: Any) -> str:
    """Return a known specialist phase.

    Args:
        value: Payload ``phase`` or equivalent.

    Returns:
        ``qa``, ``coaching``, or ``review``. ``scoring`` and leftover
        ``stage_judge`` map to ``review``. Any other value becomes ``coaching``.
    """
    cleaned = str(value or "").strip().lower()
    if cleaned in {"scoring", "stage_judge"}:
        return PHASE_REVIEW
    if cleaned in ALLOWED_PHASES:
        return cleaned
    return PHASE_COACHING


def payload_phase(payload: Mapping[str, Any] | None) -> str:
    """Return the specialist phase from one invoke payload."""
    if not isinstance(payload, Mapping):
        return PHASE_COACHING
    return normalize_phase(payload.get("phase"))


def payload_output_contract(payload: Mapping[str, Any] | None) -> str:
    """Return the structured output contract from one invoke payload."""
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("output_contract") or "").strip().lower()


def payload_review_mode(payload: Mapping[str, Any] | None) -> str:
    """Return incremental or deep Review mode from one invoke payload.

    Explicit Review and leftover ``stage_judge`` payloads are deep. Incremental
    mode must be stamped by FastAPI.

    Args:
        payload: Companion InvokeAgentRuntime JSON.

    Returns:
        ``incremental`` or ``deep``. Unknown review invokes default to deep.
    """
    if not isinstance(payload, Mapping):
        return REVIEW_MODE_DEEP
    raw_phase = str(payload.get("phase") or "").strip().lower()
    contract = payload_output_contract(payload)
    if raw_phase == "stage_judge" or contract == "stage_judge_turn":
        return REVIEW_MODE_DEEP
    context = payload.get("runtime_context")
    raw_mode = ""
    if isinstance(context, Mapping):
        raw_mode = str(context.get("review_mode") or "").strip().lower()
    if not raw_mode:
        raw_mode = str(payload.get("review_mode") or "").strip().lower()
    if raw_mode == REVIEW_MODE_INCREMENTAL:
        return REVIEW_MODE_INCREMENTAL
    return REVIEW_MODE_DEEP


def invoke_kind(payload: Mapping[str, Any] | None) -> str:
    """Return which runtime entry to use for one payload.

    Args:
        payload: Companion InvokeAgentRuntime JSON.

    Returns:
        ``fast_chat``, ``router``, ``specialist``, or ``unsupported``.
    """
    contract = payload_output_contract(payload)
    raw_phase = ""
    if isinstance(payload, Mapping):
        raw_phase = str(payload.get("phase") or "").strip().lower()
    if contract == "fast_chat_turn" or raw_phase == PHASE_FAST_CHAT:
        return PHASE_FAST_CHAT
    if contract == "router_turn" or raw_phase == PHASE_ROUTER:
        return PHASE_ROUTER
    if raw_phase == "stage_judge" or contract == "stage_judge_turn":
        return "specialist"
    if contract in {"coach_turn", "qa_turn", "review_turn"} or raw_phase in SPECIALIST_PHASES:
        return "specialist"
    return "unsupported"
