"""FastAPI boundary for the local Co-design Chatbot demonstration."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .application import CoachApplicationService
from .domain import CoachRequest, CoachTurn, PendingPhaseTransition
from .learning_service import LearningProgressService
from .providers import configured_coach_provider
from .repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from .settings import settings
from .student_store import StudentStore
from .workflow import CoachWorkflow


class TransitionResolution(BaseModel):
    """Student decision submitted for one pending phase recommendation."""

    accepted: bool


def create_app(
    store: StudentStore | None = None,
    *,
    auto_advance_stages: bool | None = None,
) -> FastAPI:
    """Create a local API application with injectable progression behavior."""
    active_store = store or StudentStore()
    notebooks = SQLiteNotebookRepository(active_store)
    transitions = SQLitePhaseTransitionRepository(active_store)
    workflow = CoachWorkflow(configured_coach_provider(), transitions)
    learning_service = LearningProgressService(active_store, notebooks, transitions)
    coach_service = CoachApplicationService(
        active_store,
        notebooks,
        workflow,
        learning_service,
        auto_advance_stages=(
            settings.auto_advance_stages
            if auto_advance_stages is None
            else auto_advance_stages
        ),
    )
    app = FastAPI(title="Co-design local API", version="0.1.0")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        """Return a lightweight process-health response."""
        return {"status": "ok", "mode": "local"}

    @app.get("/api/v1/threads/{thread_id}/learning-state")
    def learning_state(thread_id: str) -> dict:
        """Return persisted notebook learning metadata for the owned thread."""
        thread = active_store.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return dict(thread.get("metadata") or {})

    @app.get("/api/v1/threads/{thread_id}/phase-transitions/pending")
    def pending_transition(thread_id: str) -> PendingPhaseTransition | None:
        """Return the student's unresolved stage transition recommendation."""
        if not active_store.get_thread(thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        return transitions.get_pending(thread_id)

    @app.post("/api/v1/coach/turn", response_model=CoachTurn)
    def coach_turn(request: CoachRequest) -> CoachTurn:
        """Run the local typed coaching workflow for an existing notebook."""
        if not active_store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            return coach_service.submit(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post(
        "/api/v1/threads/{thread_id}/phase-transitions/{transition_id}/resolve",
        response_model=PendingPhaseTransition,
    )
    def resolve_transition(
        thread_id: str,
        transition_id: str,
        request: TransitionResolution,
    ) -> PendingPhaseTransition:
        """Persist the student's accept/reject decision for a transition."""
        try:
            return learning_service.resolve(thread_id, transition_id, request.accepted)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
