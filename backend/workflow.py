"""Local, typed critical-thinking workflow with an optional LangGraph runtime.

The workflow is deliberately provider-agnostic. A provider creates a validated
assessment; the workflow decides whether a recommendation must await student
confirmation. The application persists the completed turn and recommendation
together after provider work finishes.

When LangGraph is available, ``run`` executes the documented multi-step graph
(load → assess → recommend → format). Completed runs retain only a bounded
latest summary; durable turn recovery belongs to the transcript repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from .usage import assessed
from .domain import (
    CoachRequest,
    CoachTurn,
    EducationalAssessment,
    PendingPhaseTransition,
    ProviderAssessmentResult,
    ProvisionalResearchCoding,
    StageDecision,
)
from .coaching.workflow_navigation import (
    apply_progression_effect,
    progression_effect_for,
)
from .learning.hmw import (
    HMW_SCAFFOLD_STAGE_ID,
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
        "needs_source_retrieval": bool(provider_result.needs_source_retrieval),
        "needs_sources": bool(provider_result.needs_sources),
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


def _lecture_assessment(
    request: CoachRequest, assessment: EducationalAssessment
) -> EducationalAssessment:
    """Remove educational awards from explicit lecture help before graph guards.

    Provider prose and citations remain available; project progress and readiness
    cannot be inferred from lecture questions, even with a malformed mode choice.
    """
    if request.interaction_intent != "lecture_help":
        return assessment
    return EducationalAssessment(
        current_stage=request.current_stage,
        response_mode="qa",
        citations=assessment.citations,
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
    """Pass Reflection ADVANCE through as complete-in-place (no next stage).

    ADVANCE on Reflection means the stage purpose is met. The workflow must
    not invent a sixth phase or rewrite the recommendation to STAY; persist
    records Reflection in ``completed_stages`` while focus stays put.
    """
    del request  # Authority is request.current_stage at the call site.
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


def _is_free_mode(request: CoachRequest) -> bool:
    """Return whether the turn uses Free coaching (``response_detail=long``)."""
    return str(request.response_detail or "").strip().lower() == "long"


def _clear_hmw_scaffold_flags(
    assessment: EducationalAssessment,
) -> EducationalAssessment:
    """Clear HMW scaffold unlock markers on an assessment."""
    if (
        assessment.hmw_scaffold_ready is False
        and assessment.hmw_scaffold_guarded is False
    ):
        return assessment
    return assessment.model_copy(
        update={"hmw_scaffold_ready": False, "hmw_scaffold_guarded": False}
    )


def _promote_free_mode_advance(
    request: CoachRequest,
    assessment: EducationalAssessment,
) -> EducationalAssessment:
    """In Free mode, promote coaching STAY to ADVANCE for a usable idea.

    Free must not require HMW wording, two concepts, a full specification,
    exhaustive ethics, or a polished reflection. Empty messages, Q&A, and
    Deep Review stay STAY. Meta/status turns are handled separately via
    ``progression_effect=none`` after this helper runs.

    Args:
        request: Authoritative coach request for this turn.
        assessment: Assessment after HMW guards and formative-review STAY.

    Returns:
        The same assessment, or an ADVANCE copy when Free coaching should
        unlock Next without an artifact bar.
    """
    if not _is_free_mode(request):
        return assessment
    assessment = _clear_hmw_scaffold_flags(assessment)
    if request.current_stage == HMW_SCAFFOLD_STAGE_ID:
        return assessment
    if str(request.specialist or "").strip().lower() == "review":
        return assessment
    if str(assessment.response_mode or "").strip().lower() == "qa":
        return assessment
    if assessment.recommendation is None:
        return assessment
    if not str(request.student_message or "").strip():
        return assessment
    if assessment.recommendation is StageDecision.ADVANCE:
        return assessment
    rationale = str(assessment.recommendation_rationale or "").strip()
    return assessment.model_copy(
        update={
            "recommendation": StageDecision.ADVANCE,
            "readiness_candidate": True,
            "hmw_scaffold_ready": False,
            "hmw_scaffold_guarded": False,
            "recommendation_rationale": rationale
            or (
                "Free mode: the student shared a usable idea or draft for "
                "this stage and can press Next."
            ),
        }
    )


@dataclass
class CoachWorkflow:
    """Run one student turn and return a confirmation-gated recommendation."""

    provider: AssessmentProvider
    transitions: PhaseTransitionRepository
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
            try:
                self._ensure_graph()
            except RuntimeError as error:
                if not isinstance(error.__cause__, ImportError):
                    raise
                return self._run_sequential(request)
            return self._run_graph(request)
        except BaseException:
            self.discard_thread(request.thread_id)
            raise

    def discard_thread(self, thread_id: str) -> None:
        """Release transient results after a failed or evicted notebook run."""
        self._last_graph_state.pop(thread_id, None)
        self.release_results(thread_id)

    def release_results(self, thread_id: str) -> None:
        """Release provider handoff data while the caller holds the execution lease."""
        self._last_research_coding.pop(thread_id, None)
        self._last_conversation_memory.pop(thread_id, None)
        self._last_review_orchestration.pop(thread_id, None)

    def _remember_state(self, thread_id: str, summary: dict[str, Any]) -> None:
        """Keep at most 64 latest notebook summaries, evicting oldest first."""
        self._last_graph_state.pop(thread_id, None)
        self._last_graph_state[thread_id] = summary
        while len(self._last_graph_state) > 64:
            self._last_graph_state.pop(next(iter(self._last_graph_state)))

    def retention(self) -> dict[str, int]:
        """Report retained completed checkpoints and bounded summary count."""
        return {"completed_checkpoints": 0, "cached_threads": len(self._last_graph_state)}

    def _run_sequential(self, request: CoachRequest) -> CoachTurn:
        """Portable non-graph path used when LangGraph is unavailable."""
        provider_result = _provider_result(assessed(self.provider, request))
        response_text, assessment = provider_result
        assessment = _lecture_assessment(request, assessment)
        assessment = _normalize_terminal_assessment(request, assessment)
        assessment = _formative_review_stays(request, assessment)
        assessment = _promote_free_mode_advance(request, assessment)
        # Application-owned progression gate: After semantic assessment, before
        # PendingPhaseTransition. Meta/status/prior-review cannot open Ready.
        assessment = apply_progression_effect(
            assessment,
            progression_effect_for(
                request.student_message,
                current_stage=request.current_stage,
            ),
        )
        if assessment.current_stage != request.current_stage:
            raise ValueError("Assessment stage does not match the active journey stage")
        pending: PendingPhaseTransition | None = None
        if assessment.recommendation is StageDecision.ADVANCE:
            next_stage = _next_stage(request.current_stage)
            # Reflection ADVANCE is complete-in-place: no pending Next target.
            if next_stage is not None:
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
        self._remember_state(request.thread_id, {
            "steps": ["load_context", "assess", "recommend", "format"],
            "turn": turn.model_dump(mode="json"),
            "mode": "sequential",
        })
        self._last_research_coding[request.thread_id] = provider_result.research_coding
        self._last_conversation_memory[request.thread_id] = (
            provider_result.conversation_memory
        )
        orchestration = _review_orchestration(provider_result)
        self._last_review_orchestration[request.thread_id] = orchestration
        return turn

    def _run_graph(self, request: CoachRequest) -> CoachTurn:
        """Execute a fresh graph; persisted transcript state supplies continuity."""
        graph = self._ensure_graph()
        self._last_research_coding.pop(request.thread_id, None)
        self._last_conversation_memory.pop(request.thread_id, None)
        self._last_review_orchestration.pop(request.thread_id, None)
        try:
            result = graph.invoke(
                {
                    "request": request.model_dump(mode="json"),
                    "steps_completed": [],
                },
            )
        except Exception:
            self._last_research_coding.pop(request.thread_id, None)
            raise
        turn = CoachTurn.model_validate(result["turn"])
        self._remember_state(request.thread_id, {
            "steps": list(result.get("steps_completed") or []),
            "turn": turn.model_dump(mode="json"),
            "mode": "langgraph",
        })
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

    def peek_needs_sources(self, thread_id: str) -> bool:
        """Return whether the latest first call set ``needs_sources``.

        Does not consume orchestration flags. Used by the application-owned
        RAG fallback before persist. The provider only sets the flag when the
        request carried ``source_need_check``.
        """
        data = self._last_review_orchestration.get(thread_id) or {}
        return bool(data.get("needs_sources"))

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

    The graph has no interrupts: transcript persistence owns restart recovery.
    Avoid retaining completed request/source payloads in a redundant checkpointer.
    """
    try:
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
        provider_result = _provider_result(assessed(workflow.provider, request))
        response_text, assessment = provider_result
        assessment = _lecture_assessment(request, assessment)
        assessment = _normalize_terminal_assessment(request, assessment)
        assessment = _formative_review_stays(request, assessment)
        assessment = _promote_free_mode_advance(request, assessment)
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
        # Application-owned progression gate: AFTER HMW guard/promote (assess),
        # BEFORE PendingPhaseTransition. Same helper as sequential path.
        assessment = apply_progression_effect(
            assessment,
            progression_effect_for(
                request.student_message,
                current_stage=request.current_stage,
            ),
        )
        pending: PendingPhaseTransition | None = None
        if assessment.recommendation is StageDecision.ADVANCE:
            next_stage = _next_stage(request.current_stage)
            # Reflection ADVANCE is complete-in-place: no pending Next target.
            if next_stage is not None:
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
    return graph.compile()
