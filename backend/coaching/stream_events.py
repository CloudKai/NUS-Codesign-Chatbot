"""Validated transport contracts for coach streams and saved graph inspection."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.domain import CoachTurn


class StartedEvent(BaseModel):
    """Acknowledge worker dispatch with the exact recovery identity."""

    event: Literal["started"] = "started"
    thread_id: str
    stage: str
    idempotency_key: str | None


class StatusEvent(BaseModel):
    """Report an actual execution phase without student content."""

    event: Literal["status"] = "status"
    phase: Literal["retrieving", "thinking", "saving"]
    label: str


class ReplyEvent(BaseModel):
    """Carry a validated but unsaved, ephemeral reply preview."""

    event: Literal["reply_ready"] = "reply_ready"
    text: str = Field(min_length=1)


class SavedEvent(BaseModel):
    """Acknowledge a durably saved coaching turn."""

    event: Literal["done"] = "done"
    turn: CoachTurn


class ErrorEvent(BaseModel):
    """Terminate a failed stream with a safe status and retry information."""

    event: Literal["error"] = "error"
    detail: str
    status: int
    category: str | None = None
    retry_after: int | None = Field(default=None, ge=1)


class GraphEvent(BaseModel):
    """Report completed workflow steps after saving."""

    event: Literal["graph"] = "graph"
    steps: list[str]
    mode: str | None


CoachStreamEvent = Annotated[
    StartedEvent | StatusEvent | ReplyEvent | SavedEvent | ErrorEvent | GraphEvent,
    Field(discriminator="event"),
]
COACH_EVENT_ADAPTER: TypeAdapter[CoachStreamEvent] = TypeAdapter(CoachStreamEvent)


class GraphRetention(BaseModel):
    """Bounded runtime retention counters, excluding the durable transcript."""

    model_config = ConfigDict(extra="forbid")
    completed_checkpoints: int = Field(ge=0)
    cached_threads: int = Field(ge=0, le=64)


class GraphSummary(BaseModel):
    """Expose saved workflow output and bounded runtime retention per notebook."""

    thread_id: str
    steps: list[str]
    mode: str | None
    turn: CoachTurn | None = None
    retention: GraphRetention
