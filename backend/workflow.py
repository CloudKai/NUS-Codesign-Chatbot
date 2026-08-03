"""Local, typed critical-thinking workflow with an optional LangGraph runtime.

The workflow is deliberately provider-agnostic. A provider creates a validated
assessment; the workflow decides whether a recommendation must await student
confirmation and persists that recommendation through a repository port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from .domain import CoachRequest, CoachTurn, EducationalAssessment, PendingPhaseTransition, StageDecision
from .repositories import PhaseTransitionRepository
from .student_journey import THINKING_STAGES


class AssessmentProvider(Protocol):
    """Generate a validated educational assessment for one workflow request."""

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Return student-facing coaching text and a structured assessment."""


def _next_stage(stage_id: str) -> str:
    """Return the following stage, keeping the conclusion stage terminal."""
    stage_ids = [stage.id for stage in THINKING_STAGES]
    index = stage_ids.index(stage_id)
    return stage_ids[min(index + 1, len(stage_ids) - 1)]


@dataclass
class CoachWorkflow:
    """Run one student turn and persist a confirmation-gated recommendation."""

    provider: AssessmentProvider
    transitions: PhaseTransitionRepository

    def run(self, request: CoachRequest) -> CoachTurn:
        """Produce coaching output without mutating the student's current stage.

        An advance recommendation becomes a pending transition. Staying at a
        stage intentionally creates no transition record.
        """
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
        return CoachTurn(
            response_text=response_text,
            assessment=assessment,
            pending_transition=pending,
        )


def build_langgraph_workflow(workflow: CoachWorkflow):
    """Build a one-node LangGraph wrapper around the portable workflow.

    LangGraph is optional until its dependency is installed. The explicit state
    contract keeps the graph inspectable and makes checkpoints straightforward
    when the local runtime is enabled.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as error:  # pragma: no cover - exercised in local setup.
        raise RuntimeError(
            "LangGraph is not installed. Install the pinned project dependencies first."
        ) from error

    def coach_node(state: dict) -> dict:
        request = CoachRequest.model_validate(state["request"])
        return {"turn": workflow.run(request).model_dump(mode="json")}

    graph = StateGraph(dict)
    graph.add_node("coach", coach_node)
    graph.add_edge(START, "coach")
    graph.add_edge("coach", END)
    return graph.compile()
