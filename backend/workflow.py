"""Local, typed critical-thinking workflow with an optional LangGraph runtime.

The workflow is deliberately provider-agnostic. A provider creates a validated
assessment; the workflow decides whether a recommendation must await student
confirmation and persists that recommendation through a repository port.

When LangGraph is available, ``run`` executes the documented multi-step graph
(load → assess → recommend → format) with an in-memory checkpointer so graph
state can be inspected per thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from .domain import (
    CoachRequest,
    CoachTurn,
    EducationalAssessment,
    PendingPhaseTransition,
    StageDecision,
)
from .repositories import PhaseTransitionRepository
from .student_journey import THINKING_STAGES


class AssessmentProvider(Protocol):
    """Generate a validated educational assessment for one workflow request."""

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Return student-facing coaching text and a structured assessment."""


def _next_stage(stage_id: str) -> str:
    """Return the following stage, keeping the conclusion stage terminal."""
    stage_ids = [stage.id for stage in THINKING_STAGES]
    try:
        index = stage_ids.index(stage_id)
    except ValueError as error:
        raise ValueError(f"Unknown Thinking Path stage: {stage_id}") from error
    return stage_ids[min(index + 1, len(stage_ids) - 1)]


@dataclass
class CoachWorkflow:
    """Run one student turn and persist a confirmation-gated recommendation."""

    provider: AssessmentProvider
    transitions: PhaseTransitionRepository
    _checkpointer: Any = field(default=None, init=False, repr=False)
    _graph: Any = field(default=None, init=False, repr=False)
    _last_graph_state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def run(self, request: CoachRequest) -> CoachTurn:
        """Produce coaching output without mutating the student's current stage.

        Prefers the multi-step LangGraph path when LangGraph is installed; falls
        back to the portable sequential implementation otherwise.
        """
        try:
            return self._run_graph(request)
        except RuntimeError:
            return self._run_sequential(request)

    def _run_sequential(self, request: CoachRequest) -> CoachTurn:
        """Portable non-graph path used when LangGraph is unavailable."""
        response_text, assessment = self.provider.assess(request)
        if assessment.current_stage != request.current_stage:
            raise ValueError("Assessment stage does not match the active journey stage")
        pending: PendingPhaseTransition | None = None
        if assessment.recommendation is StageDecision.ADVANCE:
            pending = PendingPhaseTransition(
                id=str(uuid4()),
                thread_id=request.thread_id,
                from_stage=request.current_stage,
                to_stage=_next_stage(request.current_stage),
                assessment=assessment,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            pending = self.transitions.create(pending)
        turn = CoachTurn(
            response_text=response_text,
            assessment=assessment,
            pending_transition=pending,
        )
        self._last_graph_state[request.thread_id] = {
            "steps": ["load_context", "assess", "recommend", "format"],
            "turn": turn.model_dump(mode="json"),
            "mode": "sequential",
        }
        return turn

    def _run_graph(self, request: CoachRequest) -> CoachTurn:
        """Execute the multi-step LangGraph workflow with a durable checkpointer."""
        graph = self._ensure_graph()
        config = {
            "configurable": {
                "thread_id": request.thread_id,
                "checkpoint_ns": "coach",
            }
        }
        result = graph.invoke(
            {
                "request": request.model_dump(mode="json"),
                "steps_completed": [],
            },
            config=config,
        )
        turn = CoachTurn.model_validate(result["turn"])
        self._last_graph_state[request.thread_id] = {
            "steps": list(result.get("steps_completed") or []),
            "turn": turn.model_dump(mode="json"),
            "mode": "langgraph",
            "checkpoint": {
                "thread_id": request.thread_id,
                "checkpoint_ns": "coach",
            },
        }
        return turn

    def inspect_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return the latest inspectable graph summary for a notebook."""
        return self._last_graph_state.get(thread_id)

    def _ensure_graph(self):
        """Build and cache the multi-step LangGraph runtime once."""
        if self._graph is not None:
            return self._graph
        self._graph = build_langgraph_workflow(self)
        return self._graph


def build_langgraph_workflow(workflow: CoachWorkflow):
    """Build the documented multi-step LangGraph coach workflow.

    Steps:
      load_context → assess → recommend → format

    Uses an in-memory checkpointer so local demos can inspect per-thread state
    without AWS. Does not create six agents.
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, START, StateGraph
    except ImportError as error:  # pragma: no cover - exercised in local setup.
        raise RuntimeError(
            "LangGraph is not installed. Install the pinned project dependencies first."
        ) from error

    def load_context(state: dict) -> dict:
        request = CoachRequest.model_validate(state["request"])
        steps = list(state.get("steps_completed") or [])
        steps.append("load_context")
        return {
            "request": request.model_dump(mode="json"),
            "thread_id": request.thread_id,
            "current_stage": request.current_stage,
            "steps_completed": steps,
        }

    def assess(state: dict) -> dict:
        request = CoachRequest.model_validate(state["request"])
        response_text, assessment = workflow.provider.assess(request)
        if assessment.current_stage != request.current_stage:
            raise ValueError(
                "Assessment stage does not match the active journey stage"
            )
        steps = list(state.get("steps_completed") or [])
        steps.append("assess")
        return {
            "request": request.model_dump(mode="json"),
            "response_text": response_text,
            "assessment": assessment.model_dump(mode="json"),
            "steps_completed": steps,
        }

    def recommend(state: dict) -> dict:
        request = CoachRequest.model_validate(state["request"])
        assessment = EducationalAssessment.model_validate(state["assessment"])
        pending: PendingPhaseTransition | None = None
        if assessment.recommendation is StageDecision.ADVANCE:
            pending = PendingPhaseTransition(
                id=str(uuid4()),
                thread_id=request.thread_id,
                from_stage=request.current_stage,
                to_stage=_next_stage(request.current_stage),
                assessment=assessment,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            pending = workflow.transitions.create(pending)
        steps = list(state.get("steps_completed") or [])
        steps.append("recommend")
        return {
            "request": request.model_dump(mode="json"),
            "response_text": state.get("response_text"),
            "assessment": assessment.model_dump(mode="json"),
            "pending_transition": (
                pending.model_dump(mode="json") if pending else None
            ),
            "steps_completed": steps,
        }

    def format_output(state: dict) -> dict:
        assessment = EducationalAssessment.model_validate(state["assessment"])
        pending_raw = state.get("pending_transition")
        pending = (
            PendingPhaseTransition.model_validate(pending_raw)
            if pending_raw
            else None
        )
        turn = CoachTurn(
            response_text=str(state.get("response_text") or ""),
            assessment=assessment,
            pending_transition=pending,
        )
        steps = list(state.get("steps_completed") or [])
        steps.append("format")
        return {
            "request": state.get("request"),
            "turn": turn.model_dump(mode="json"),
            "steps_completed": steps,
        }

    graph = StateGraph(dict)
    graph.add_node("load_context", load_context)
    graph.add_node("assess", assess)
    graph.add_node("recommend", recommend)
    graph.add_node("format", format_output)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "assess")
    graph.add_edge("assess", "recommend")
    graph.add_edge("recommend", "format")
    graph.add_edge("format", END)
    checkpointer = MemorySaver()
    workflow._checkpointer = checkpointer
    return graph.compile(checkpointer=checkpointer)
