"""Content-free generation accounting events for offline operator reconciliation.

Events distinguish application calls from unknown SDK/model retries. Logs are
an exportable ledger, not an invoice or an exactly-once durable billing store.
No transcript, source, identity, credential or exception text enters this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.coaching.cancellation import check_turn_cancelled
from backend.domain import CoachRequest, EducationalAssessment, ProviderAssessmentResult

if TYPE_CHECKING:
    from backend.workflow import AssessmentProvider
    from backend.generation_admission import GenerationAdmission

AssessmentResult = ProviderAssessmentResult | tuple[str, EducationalAssessment]


class CheckpointProvider(Protocol):
    """Optional provider port for a completed-stage formative checkpoint."""

    def assess_stage_checkpoint(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Return a typed checkpoint without changing the student's active stage."""


logger = logging.getLogger("co_design.usage")


class GenerationUsage(BaseModel):
    """One application-visible provider call; missing billing meters stay null."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    event: Literal["generation_usage"] = "generation_usage"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operation_id: str
    kind: Literal["chat", "deep_review", "stage_checkpoint", "project_brief"]
    provider: Literal["mock", "openai", "bedrock", "agentcore", "unknown"]
    model: str = "unknown"
    role: str = "unknown"
    region: str = "unknown"
    success: bool = False
    input_tokens: int | None = Field(default=None, ge=0, le=10**15)
    output_tokens: int | None = Field(default=None, ge=0, le=10**15)
    cache_read_tokens: int | None = Field(default=None, ge=0, le=10**15)
    cache_write_tokens: int | None = Field(default=None, ge=0, le=10**15)
    model_calls: int | None = Field(default=None, ge=0, le=10**15)
    sdk_retries: int | None = Field(default=None, ge=0, le=10**15)


@dataclass
class UsageOperation:
    """Request-local counters; retains no content or raw notebook identifier."""

    kind: Literal["chat", "deep_review", "stage_checkpoint", "project_brief"]
    session_key: str
    admission: GenerationAdmission | None = None
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    attempts: int = 0
    success: bool = False
    answer_delivered: bool = False
    replayed: bool = False
    _token: Token[UsageOperation | None] | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> Self:
        """Bind this operation without intercepting application exceptions."""
        self._token = _current.set(self)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        """Emit counters and restore context without altering exception tracebacks."""
        try:
            _emit({
                "event": "operation_usage", "event_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation_id": self.operation_id, "kind": self.kind,
                "session_key": self.session_key, "success": self.success,
                "answer_delivered": self.answer_delivered,
                "replayed": self.replayed, "generation_attempts": self.attempts,
                "useful_answer": None,
            })
        finally:
            if self._token is not None:
                _current.reset(self._token)
                self._token = None


_current: ContextVar[UsageOperation | None] = ContextVar("usage_operation", default=None)


def _emit(payload: dict[str, Any]) -> None:
    """Write a typed, caller-owned event to the configured operational stream."""
    logger.info("%s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


def usage_operation(
    kind: Literal["chat", "deep_review", "stage_checkpoint", "project_brief"], thread_id: str,
    *, admission: GenerationAdmission | None = None,
) -> UsageOperation:
    """Count one operation and restore its caller context, including on failure.

    The session proxy is one high-entropy notebook UUID per UTC day, hashed;
    it is not an authenticated person or a measured browser/learning session.
    """
    day = datetime.now(timezone.utc).date().isoformat()
    session = hashlib.sha256(f"{day}:{thread_id}".encode()).hexdigest()[:32]
    return UsageOperation(kind=kind, session_key=session, admission=admission)


def usage_correlation() -> dict[str, str]:
    """Return content-free operation and hashed notebook/day log correlation."""
    operation = _current.get()
    if operation is None:
        return {"operation_id": "operator", "thread_key": "operator"}
    return {"operation_id": operation.operation_id, "thread_key": operation.session_key}


def mark_replayed() -> None:
    """Exclude a recovered idempotent response from newly delivered answers."""
    operation = _current.get()
    if operation is not None:
        operation.replayed = True


def safe_identifier(value: object) -> str:
    """Accept only bounded provider/model labels, never arbitrary payload text."""
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:/+-]{1,160}", value) else "unknown"


def generation_call(
    provider: Literal["mock", "openai", "bedrock", "agentcore", "unknown"],
    model: str, role: str, *, region: str = "unknown",
) -> _GenerationScope:
    """Emit a generation attempt even when invocation or response parsing fails.

    Callers set only returned numeric usage. Missing/hidden retries are null,
    never inferred from latency, estimates, or a successful final response.
    """
    operation = _current.get()
    meter = GenerationUsage(
        operation_id=operation.operation_id if operation else str(uuid4()),
        kind=operation.kind if operation else "chat",
        provider=provider, model=safe_identifier(model), role=safe_identifier(role),
        region=safe_identifier(region),
    )
    return _GenerationScope(meter, operation)


@dataclass
class _GenerationScope:
    """A call meter whose exit preserves frozen provider/application exceptions."""

    meter: GenerationUsage
    operation: UsageOperation | None
    reservation: str | None = None

    def __enter__(self) -> GenerationUsage:
        """Count the application attempt and expose its nullable numeric meters."""
        check_turn_cancelled()
        if self.operation is not None:
            if self.operation.admission is not None:
                self.reservation = self.operation.admission.acquire()
            self.operation.attempts += 1
        return self.meter

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        """Record the outcome without suppressing or rewriting an exception."""
        # Generator context managers write __traceback__, which frozen errors forbid.
        self.meter.success = exc_type is None
        if self.reservation and self.operation and self.operation.admission:
            self.operation.admission.settle(self.reservation, self.meter)
        _emit(self.meter.model_dump(mode="json"))


def assessed(provider: AssessmentProvider, request: CoachRequest, *, checkpoint: bool = False) -> AssessmentResult:
    """Call the provider port with fallback meters for mock/uninstrumented adapters.

    Adapters with per-call metering own their own attempts; fallback records one
    logical assessment and explicitly leaves unavailable model usage unknown.
    """
    call = cast(CheckpointProvider, provider).assess_stage_checkpoint if checkpoint else provider.assess
    if getattr(provider, "usage_metered", False):
        return call(request)
    provider_name = getattr(provider, "usage_provider", "unknown")
    role = "stage_checkpoint" if checkpoint else ("review_deep" if request.specialist == "review" else "fast_chat")
    with generation_call(provider_name, "mock" if provider_name == "mock" else "unknown", role) as meter:
        if provider_name == "mock":
            meter.input_tokens = meter.output_tokens = 0
            meter.cache_read_tokens = meter.cache_write_tokens = 0
            meter.model_calls = meter.sdk_retries = 0
        return call(request)


def copy_usage(meter: GenerationUsage, values: dict[str, Any], names: dict[str, str]) -> None:
    """Copy only supplied nonnegative integer meters from an adapter response."""
    for source, destination in names.items():
        value = values.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**15:
            setattr(meter, destination, value)
