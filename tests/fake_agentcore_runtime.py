"""Shared Fake AgentCore Runtime client for deterministic adapter tests."""

from __future__ import annotations

import json
from typing import Any


class FakeBody:
    """Minimal streaming-body stand-in used by the fake runtime client."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        """Return the whole fake response body."""
        return self._payload


def _decode_payload(raw: Any) -> dict[str, Any]:
    """Parse one InvokeAgentRuntime payload without raising on bad JSON."""
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8")
    else:
        text = str(raw or "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _review_mode(payload: dict[str, Any]) -> str:
    """Return incremental or deep from one Review invoke payload."""
    context = payload.get("runtime_context")
    mode = ""
    if isinstance(context, dict):
        mode = str(context.get("review_mode") or "").strip().lower()
    if not mode:
        mode = str(payload.get("review_mode") or "").strip().lower()
    return mode


def _payload_kind(payload: dict[str, Any]) -> str:
    """Return router, review mode, or specialist for one invoke payload."""
    contract = str(payload.get("output_contract") or "").strip().lower()
    phase = str(payload.get("phase") or "").strip().lower()
    if contract == "router_turn" or phase == "router":
        return "router"
    if contract == "stage_judge_turn" or phase == "stage_judge":
        return "review_deep"
    if phase == "review" or contract == "review_turn":
        if _review_mode(payload) == "incremental":
            return "review_incremental"
        return "review_deep"
    return "specialist"


def _looks_like_review_body(payload: dict[str, Any] | None) -> bool:
    """Return whether a specialist default payload is Formative Review JSON."""
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("assessment"), dict):
        return False
    return "synthesis" in payload or "strengths" in payload or "areas_to_develop" in payload


def _default_router_body() -> bytes:
    """Return a high-confidence coaching route so existing tests stay stable."""
    return json.dumps(
        {
            "specialist": "coaching",
            "confidence": 0.9,
            "rationale_category": "project_coaching",
        }
    ).encode("utf-8")


def _default_incremental_body() -> bytes:
    """Return a lightweight Luna Review that cannot advance the stage."""
    return json.dumps(
        {
            "response_text": "Incremental review of the latest coaching turn.",
            "strengths": ["The student named a concrete setting."],
            "areas_to_develop": ["Name who is affected at night."],
            "synthesis": "Progress is forming; this is not a grade.",
            "readiness_candidate": False,
            "review_depth": "incremental",
            "recommendation": "stay",
            "working_conclusion": "Elderly caregivers are scarce in Singapore.",
        }
    ).encode("utf-8")


def _default_deep_body(payload: dict[str, Any]) -> bytes:
    """Confirm ADVANCE with Review fields so existing transition tests pass."""
    stage = ""
    context = payload.get("runtime_context")
    if isinstance(context, dict):
        stage = str(context.get("current_stage") or "").strip()
    if not stage:
        stage = "problem_identification"
    return json.dumps(
        {
            "response_text": "Formative deep review of progress.",
            "strengths": ["The contribution named a concrete constraint."],
            "areas_to_develop": ["Name who is affected at night."],
            "synthesis": "The work is ready to advance.",
            "readiness_candidate": True,
            "review_depth": "deep",
            "current_stage": stage,
            "recommendation": "advance",
            "confidence": 0.9,
            "readiness_evidence": ["The candidate met the current-stage bar."],
            "missing_requirements": [],
            "rationale_summary": "The contribution is ready to advance.",
            "working_conclusion": "Elderly caregivers are scarce in Singapore.",
        }
    ).encode("utf-8")


def _encode_item(item: Any) -> bytes:
    """Encode a queued fake response body."""
    if isinstance(item, bytes):
        return item
    return json.dumps(item).encode("utf-8")


class FakeAgentCoreRuntime:
    """Injected bedrock-agentcore client that records InvokeAgentRuntime calls.

    Router, Incremental Review, and Deep Review invokes are answered from
    dedicated queues, or from safe defaults that do not consume the specialist
    payload queue. Existing specialist contract tests therefore keep working.
    ``judge_payload`` remains an alias for Deep Review responses.
    """

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        raw: bytes | None = None,
        payloads: list[Any] | None = None,
        router_payload: dict[str, Any] | bytes | None = None,
        router_payloads: list[Any] | None = None,
        incremental_payload: dict[str, Any] | bytes | None = None,
        incremental_payloads: list[Any] | None = None,
        deep_payload: dict[str, Any] | bytes | None = None,
        deep_payloads: list[Any] | None = None,
        judge_payload: dict[str, Any] | bytes | None = None,
        judge_payloads: list[Any] | None = None,
        content_type: str = "application/json",
        error: BaseException | None = None,
        router_error: BaseException | None = None,
        incremental_error: BaseException | None = None,
        deep_error: BaseException | None = None,
        judge_error: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = payload
        self._raw = raw
        self._queue = list(payloads) if payloads is not None else None
        self._router_payload = router_payload
        self._router_queue = list(router_payloads) if router_payloads is not None else None
        self._incremental_payload = incremental_payload
        self._incremental_queue = (
            list(incremental_payloads) if incremental_payloads is not None else None
        )
        self._deep_payload = (
            deep_payload if deep_payload is not None else judge_payload
        )
        self._deep_queue = list(
            deep_payloads if deep_payloads is not None else judge_payloads or []
        ) if (deep_payloads is not None or judge_payloads is not None) else None
        self._content_type = content_type
        self._error = error
        self._router_error = router_error
        self._incremental_error = incremental_error
        self._deep_error = deep_error if deep_error is not None else judge_error

    def _queued_response(self, queue: list[Any], label: str) -> dict[str, Any]:
        """Pop one queued body or raise when the queue is exhausted."""
        if not queue:
            raise AssertionError(f"FakeAgentCoreRuntime has no queued {label} responses left")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {
            "contentType": self._content_type,
            "response": FakeBody(_encode_item(item)),
        }

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        """Record one runtime invocation and return a fake structured response."""
        self.calls.append(kwargs)
        incoming = _decode_payload(kwargs.get("payload"))
        kind = _payload_kind(incoming)
        if kind == "router":
            if self._router_error is not None:
                raise self._router_error
            if self._router_queue is not None:
                return self._queued_response(self._router_queue, "router")
            if self._router_payload is not None:
                return {
                    "contentType": self._content_type,
                    "response": FakeBody(_encode_item(self._router_payload)),
                }
            return {
                "contentType": self._content_type,
                "response": FakeBody(_default_router_body()),
            }
        if kind == "review_incremental":
            if self._incremental_error is not None:
                raise self._incremental_error
            if self._incremental_queue is not None:
                return self._queued_response(self._incremental_queue, "incremental")
            if self._incremental_payload is not None:
                return {
                    "contentType": self._content_type,
                    "response": FakeBody(_encode_item(self._incremental_payload)),
                }
            return {
                "contentType": self._content_type,
                "response": FakeBody(_default_incremental_body()),
            }
        if kind == "review_deep":
            if self._deep_error is not None:
                raise self._deep_error
            if self._deep_queue is not None:
                return self._queued_response(self._deep_queue, "deep")
            if self._deep_payload is not None:
                return {
                    "contentType": self._content_type,
                    "response": FakeBody(_encode_item(self._deep_payload)),
                }
            if _looks_like_review_body(self._payload):
                return {
                    "contentType": self._content_type,
                    "response": FakeBody(_encode_item(self._payload)),
                }
            return {
                "contentType": self._content_type,
                "response": FakeBody(_default_deep_body(incoming)),
            }
        return self._specialist_response()

    def _specialist_response(self) -> dict[str, Any]:
        """Return the next queued specialist body or the default payload."""
        if self._queue is not None:
            if not self._queue:
                raise AssertionError("FakeAgentCoreRuntime has no queued responses left")
            item = self._queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, bytes):
                body = item
            else:
                body = json.dumps(item).encode("utf-8")
            return {"contentType": self._content_type, "response": FakeBody(body)}
        if self._error is not None:
            raise self._error
        if self._raw is not None:
            body = self._raw
        else:
            body = json.dumps(self._payload or {}).encode("utf-8")
        return {"contentType": self._content_type, "response": FakeBody(body)}
