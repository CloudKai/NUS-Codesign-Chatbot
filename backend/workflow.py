"""Local, typed critical-thinking workflow with an optional LangGraph runtime.

The workflow is deliberately provider-agnostic. A provider creates a validated
assessment; the workflow decides whether a recommendation must await student
confirmation. The application persists the completed turn and recommendation
together after provider work finishes.

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
    ProviderAssessmentResult,
    ProvisionalResearchCoding,
    StageDecision,
)
from .repositories import PhaseTransitionRepository
from .student_journey import THINKING_STAGES


class AssessmentProvider(Protocol):
    """Generate a validated educational assessment for one workflow request."""

    def assess(
        self, request: CoachRequest
    ) -> ProviderAssessmentResult | tuple[str, EducationalAssessment]:
        """Return one provider result; legacy two-item adapters remain accepted."""


def _review_orchestration(
    provider_result: ProviderAssessmentResult,
) -> dict[str, Any]:
    """Return persistence flags for the periodic Deep Review counter."""
    return {
        "specialist": str(provider_result.specialist or "coaching"),
        "qualifying_coaching_turn": bool(provider_result.qualifying_coaching_turn),
        "deep_review_succeeded": bool(provider_result.deep_review_succeeded),
        "review_trigger": provider_result.review_trigger,
    }


def _provider_result(
    value: ProviderAssessmentResult | tuple[str, EducationalAssessment],
) -> ProviderAssessmentResult:
    """Normalize the internal provider result without making another model call."""
    if isinstance(value, ProviderAssessmentResult):
        return value
    response_text, assessment = value
    return ProviderAssessmentResult(
        response_text=response_text,
        assessment=assessment,
    )


def _next_stage(stage_id: str) -> str | None:
    """Return the following stage, or ``None`` for terminal Reflection."""
    stage_ids = [stage.id for stage in THINKING_STAGES]
    try:
        index = stage_ids.index(stage_id)
    except ValueError as error:
        raise ValueError(f"Unknown Thinking Path stage: {stage_id}") from error
    if index == len(stage_ids) - 1:
        return None
    return stage_ids[index + 1]


def _normalize_terminal_assessment(
    request: CoachRequest, assessment: EducationalAssessment
) -> EducationalAssessment:
    """Prevent a provider from recommending advancement beyond Reflection."""
    if (
        request.current_stage == THINKING_STAGES[-1].id
        and assessment.recommendation is StageDecision.ADVANCE
    ):
        return assessment.model_copy(
            update={
                "recommendation": StageDecision.STAY,
                "recommendation_rationale": (
                    "Reflection is the terminal Thinking Path stage; the student's "
                    "work remains here for final calibration or completion."
                ),
            }
        )
    return assessment


@dataclass
class CoachWorkflow:
    """Run one student turn and return a confirmation-gated recommendation."""

    provider: AssessmentProvider
    transitions: PhaseTransitionRepository
    _checkpointer: Any = field(default=None, init=False, repr=False)
    _graph: Any = field(default=None, init=False, repr=False)
    _last_graph_state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_research_coding: dict[str, ProvisionalResearchCoding | None] = field(
        default_factory=dict, init=False, repr=False
    )
    _last_conversation_memory: dict[str, dict[str, Any] | None] = field(
        default_factory=dict, init=False, repr=False
    )
    _last_review_orchestration: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def provider_id(self) -> str:
        """Return the actual injected provider identifier for provenance."""
        explicit = str(getattr(self.provider, "provider_id", "") or "").strip()
        if explicit:
            return explicit
        return type(self.provider).__name__.removesuffix("CoachProvider").lower()

    def model_id_for(self, request: CoachRequest) -> str:
        """Return the actual injected provider model used for this request."""
        resolver = getattr(self.provider, "model_id_for", None)
        if callable(resolver):
            resolved = str(resolver(request) or "").strip()
            if resolved:
                return resolved
        return str(request.model_id or "unknown").strip() or "unknown"

    def run(self, request: CoachRequest) -> CoachTurn:
        """Produce coaching output without mutating the student's current stage.

        Prefers the multi-step LangGraph path when LangGraph is installed; falls
        back to the portable sequential implementation otherwise.
        """
        try:
            self._ensure_graph()
        except RuntimeError as error:
            if not isinstance(error.__cause__, ImportError):
                raise
            return self._run_sequential(request)
        return self._run_graph(request)

    def _run_sequential(self, request: CoachRequest) -> CoachTurn:
        """Portable non-graph path used when LangGraph is unavailable."""
        provider_result = _provider_result(self.provider.assess(request))
        response_text, assessment = provider_result
        assessment = _normalize_terminal_assessment(request, assessment)
        if assessment.current_stage != request.current_stage:
            raise ValueError("Assessment stage does not match the active journey stage")
        pending: PendingPhaseTransition | None = None
        if assessment.recommendation is StageDecision.ADVANCE:
            next_stage = _next_stage(request.current_stage)
            if next_stage is None:
                raise ValueError("Reflection cannot advance to another stage")
            pending = PendingPhaseTransition(
                id=str(uuid4()),
                thread_id=request.thread_id,
                from_stage=request.current_stage,
                to_stage=next_stage,
                assessment=assessment,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
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
        self._last_research_coding[request.thread_id] = provider_result.research_coding
        self._last_conversation_memory[request.thread_id] = (
            provider_result.conversation_memory
        )
        self._last_review_orchestration[request.thread_id] = _review_orchestration(
            provider_result
        )
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
        self._last_research_coding.pop(request.thread_id, None)
        self._last_conversation_memory.pop(request.thread_id, None)
        self._last_review_orchestration.pop(request.thread_id, None)
        try:
            result = graph.invoke(
                {
                    "request": request.model_dump(mode="json"),
                    "steps_completed": [],
                },
                config=config,
            )
        except Exception:
            self._last_research_coding.pop(request.thread_id, None)
            raise
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

    def provisional_research_coding(
        self, thread_id: str
    ) -> ProvisionalResearchCoding | None:
        """Return the latest internal coding result without changing CoachTurn."""
        return self._last_research_coding.get(thread_id)

    def take_provisional_research_coding(
        self, thread_id: str
    ) -> ProvisionalResearchCoding | None:
        """Consume transient coding after its provider quotes become offsets."""
        return self._last_research_coding.pop(thread_id, None)

    def take_conversation_memory(self, thread_id: str) -> dict[str, Any] | None:
        """Consume derived conversation memory after the provider turn.

        Returns:
            The derived memory dict to persist, or ``None`` to clear a stale
            projection after a conversation revision.
        """
        return self._last_conversation_memory.pop(thread_id, None)

    def take_review_orchestration(self, thread_id: str) -> dict[str, Any]:
        """Consume Review orchestration flags after a provider turn.

        Returns:
            Qualifying-coaching and Deep Review success flags used to persist
            the periodic counter. Missing extras default closed (no increment,
            no reset).
        """
        return dict(self._last_review_orchestration.pop(thread_id, {}) or {})

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
    without AWS. Does not create five agents.
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
        provider_result = _provider_result(workflow.provider.assess(request))
        response_text, assessment = provider_result
        assessment = _normalize_terminal_assessment(request, assessment)
        if assessment.current_stage != request.current_stage:
            raise ValueError(
                "Assessment stage does not match the active journey stage"
            )
        steps = list(state.get("steps_completed") or [])
        steps.append("assess")
        workflow._last_research_coding[request.thread_id] = (
            provider_result.research_coding
        )
        workflow._last_conversation_memory[request.thread_id] = (
            provider_result.conversation_memory
        )
        workflow._last_review_orchestration[request.thread_id] = _review_orchestration(
            provider_result
        )
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
            next_stage = _next_stage(request.current_stage)
            if next_stage is None:
                raise ValueError("Reflection cannot advance to another stage")
            pending = PendingPhaseTransition(
                id=str(uuid4()),
                thread_id=request.thread_id,
                from_stage=request.current_stage,
                to_stage=next_stage,
                assessment=assessment,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
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
