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
from .learning.hmw import HMW_SCAFFOLD_STAGE_ID, student_hmw_candidate_present
from .repositories import PhaseTransitionRepository
from .student_journey import THINKING_STAGES


class AssessmentProvider(Protocol):
    """Generate a validated educational assessment for one workflow request."""

    def assess(
        self, request: CoachRequest
    ) -> ProviderAssessmentResult | tuple[str, EducationalAssessment]:
        """Return one provider result; legacy two-item adapters remain accepted."""


_PI_HMW_GUARD_RESPONSE = (
    "**Problem identification**\n\n"
    "Let's keep refining the problem before moving on. Please draft your own "
    "How Might We question naming the opportunity, who it is for, and the "
    "outcome you want. What framing would you like to try?"
)


def _review_orchestration(
    provider_result: ProviderAssessmentResult,
) -> dict[str, Any]:
    """Return persistence flags for the periodic Deep Review counter."""
    return {
        "specialist": str(provider_result.specialist or "coaching"),
        "qualifying_coaching_turn": bool(provider_result.qualifying_coaching_turn),
        "deep_review_succeeded": bool(provider_result.deep_review_succeeded),
        "review_trigger": provider_result.review_trigger,
        "needs_source_retrieval": bool(provider_result.needs_source_retrieval),
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


def _formative_review_stays(
    request: CoachRequest, assessment: EducationalAssessment
) -> EducationalAssessment:
    """Keep Deep Review formative so FastAPI remains stage authority.

    Args:
        request: Authoritative coach request. ``specialist=review`` is
            server-stamped only.
        assessment: Provider assessment, which may still mention ADVANCE as
            readiness information.

    Returns:
        The same assessment, or a STAY copy when this turn is Deep Review.
    """
    if str(request.specialist or "").strip().lower() != "review":
        return assessment
    if assessment.recommendation is StageDecision.STAY:
        return assessment
    return assessment.model_copy(update={"recommendation": StageDecision.STAY})


def _require_student_hmw_for_problem_identification_advance(
    request: CoachRequest, assessment: EducationalAssessment
) -> EducationalAssessment:
    """Block Problem Identification ADVANCE without a student HMW attempt.

    Haiku still judges HMW quality. This guard only checks whether the
    current active user contribution looks like a student-authored How
    Might We candidate. System copy, sources, Coach examples, Q&A, and
    Deep Review cannot satisfy it.

    Args:
        request: Authoritative coach request for this turn.
        assessment: Provider assessment, which may recommend ADVANCE.

    Returns:
        The same assessment, or a STAY copy when Problem Identification
        ADVANCE lacks a student HMW candidate.
    """
    # This is application-owned metadata; never carry a provider-supplied
    # guarded marker into the persisted assessment.
    assessment = assessment.model_copy(update={"hmw_scaffold_guarded": False})
    if request.current_stage != HMW_SCAFFOLD_STAGE_ID:
        return assessment
    if assessment.recommendation is not StageDecision.ADVANCE:
        return assessment
    if str(assessment.response_mode or "").strip().lower() == "qa":
        return assessment
    if student_hmw_candidate_present(request.student_message):
        return assessment.model_copy(update={"hmw_scaffold_guarded": False})
    rationale = str(assessment.recommendation_rationale or "").strip()
    # A revision intentionally starts a fresh active branch. Do not carry the
    # scaffold visibility marker onto that replacement when the superseded
    # branch contained a completed HMW; the active projection must not
    # resurrect stale completion/visibility. A subsequent fresh Coaching turn
    # can unlock or guard the scaffold again from its own assessment.
    scaffold_guarded = not bool(str(request.revise_user_message_id or "").strip())
    return assessment.model_copy(
        update={
            "recommendation": StageDecision.STAY,
            "readiness_candidate": False,
            "hmw_scaffold_ready": False,
            # A server-rejected advance is itself the authoritative signal that
            # the student needs the construction scaffold. Keep that
            # application-owned visibility marker separate from model readiness:
            # the persisted assessment remains STAY/not-ready while the active
            # branch can safely render the scaffold even when the provider
            # returned hmw_scaffold_ready=false.
            "hmw_scaffold_guarded": scaffold_guarded,
            "recommendation_rationale": rationale
            or (
                "Problem Identification advances only after a student-authored "
                "How Might We attempt."
            ),
        }
    )


def _hmw_guard_applies(
    request: CoachRequest,
    assessment: EducationalAssessment,
    *,
    needs_source_retrieval: bool = False,
) -> bool:
    """Return whether the server rejected this PI ADVANCE recommendation."""
    return (
        request.current_stage == HMW_SCAFFOLD_STAGE_ID
        and assessment.recommendation is StageDecision.ADVANCE
        and str(assessment.response_mode or "").strip().lower() != "qa"
        and not student_hmw_candidate_present(request.student_message)
        # Let the existing application-owned RAG fallback run first. The
        # final retrieval-backed pass is still normalized below, with no
        # additional retrieval caused by the HMW guard itself.
        and not (needs_source_retrieval and not request.retrieval_required)
    )


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
        assessment = _formative_review_stays(request, assessment)
        hmw_guarded = _hmw_guard_applies(
            request,
            assessment,
            needs_source_retrieval=provider_result.needs_source_retrieval,
        )
        assessment = _require_student_hmw_for_problem_identification_advance(
            request, assessment
        )
        if hmw_guarded:
            response_text = _PI_HMW_GUARD_RESPONSE
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
        orchestration = _review_orchestration(provider_result)
        if hmw_guarded:
            orchestration.update(
                {"hmw_guarded": True, "needs_source_retrieval": False}
            )
        self._last_review_orchestration[request.thread_id] = orchestration
        return turn

    def _run_graph(self, request: CoachRequest) -> CoachTurn:
        """Execute the multi-step LangGraph workflow with a durable checkpointer."""
        graph = self._ensure_graph()
        # Unique namespace per run so a RAG fallback retry cannot resume the
        # first Haiku graph checkpoint for the same notebook thread_id.
        run_ns = f"coach-{uuid4().hex}"
        config = {
            "configurable": {
                "thread_id": request.thread_id,
                "checkpoint_ns": run_ns,
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
                "checkpoint_ns": run_ns,
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

    def peek_needs_source_retrieval(self, thread_id: str) -> bool:
        """Return whether the latest provider result asked for source evidence.

        Does not consume orchestration flags. Used by the application-owned
        RAG fallback before persist.
        """
        data = self._last_review_orchestration.get(thread_id) or {}
        return bool(data.get("needs_source_retrieval"))

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
        assessment = _formative_review_stays(request, assessment)
        hmw_guarded = _hmw_guard_applies(
            request,
            assessment,
            needs_source_retrieval=provider_result.needs_source_retrieval,
        )
        assessment = _require_student_hmw_for_problem_identification_advance(
            request, assessment
        )
        if hmw_guarded:
            response_text = _PI_HMW_GUARD_RESPONSE
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
        orchestration = _review_orchestration(provider_result)
        if hmw_guarded:
            orchestration.update(
                {"hmw_guarded": True, "needs_source_retrieval": False}
            )
        workflow._last_review_orchestration[request.thread_id] = orchestration
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
