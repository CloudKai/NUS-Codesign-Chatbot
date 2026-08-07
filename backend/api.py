"""FastAPI boundary for the local Co-design Chatbot demonstration."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from .application import CoachApplicationService
from .auth_routes import register_auth_routes
from .domain import (
    CoachRequest,
    CoachTurn,
    MessageCreateRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    PendingPhaseTransition,
    PreferencePatch,
    SourceSelectAllRequest,
    SourceUpdateRequest,
)
from .learning_service import LearningProgressService
from .providers import ProviderUnavailableError, configured_coach_provider
from .repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from .settings import settings
from .source_library import CourseMaterialSyncCoordinator
from .student_store import StudentStore
from .workflow import CoachWorkflow
from .workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

# Streamlit OIDC cookie names (and numeric chunks) cleared by the logout callback.
# Profile Logout / ui.auth_gate.app_logout_url() navigates here; not Cognito /logout.
_STREAMLIT_AUTH_COOKIES = ("_streamlit_user", "_streamlit_user_tokens")


class TransitionResolution(BaseModel):
    """Student decision submitted for one pending phase recommendation."""

    accepted: bool


def _expire_streamlit_auth_cookie(response: RedirectResponse, cookie_name: str) -> None:
    """Expire one Streamlit auth cookie with attributes that match how it was set.

    Streamlit signs cookies with ``HttpOnly`` and ``SameSite=Lax`` (no Secure on
    loopback). Browsers only clear those cookies when the expiry response
    repeats the same flags — see Streamlit ``starlette_auth_routes``.
    """
    response.set_cookie(
        key=cookie_name,
        value="",
        max_age=0,
        expires=0,
        path="/",
        httponly=True,
        samesite="lax",
    )


def create_app(
    store: StudentStore | None = None,
    *,
    auto_advance_stages: bool | None = None,
    workspace: WorkspaceService | None = None,
    session_service=None,
    oidc_client=None,
) -> FastAPI:
    """Create a local API application with injectable progression behavior."""
    active_store = store or StudentStore()
    workspace_service = workspace or WorkspaceService(
        active_store, CourseMaterialSyncCoordinator()
    )
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
    register_auth_routes(
        app,
        store=active_store,
        sessions=session_service,
        oidc=oidc_client,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        """Stamp every response with a request id for local observability."""
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def _value_error(error: ValueError) -> HTTPException:
        detail = str(error)
        status = 404 if "not found" in detail.lower() else 400
        return HTTPException(status_code=status, detail=detail)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        """Return a lightweight process-health response."""
        return {"status": "ok", "mode": "local"}

    @app.get("/api/v1/auth/logout/callback")
    def auth_logout_callback(request: Request) -> RedirectResponse:
        """Deprecated Streamlit-cookie clear path kept for migration only.

        Prefer ``GET/POST /api/v1/auth/logout``, which revokes the FastAPI
        application session. This legacy route still expires old Streamlit OIDC
        cookies and redirects to the signed-out gate.
        """
        target = str(settings.ui_base_url or "").rstrip("/")
        parsed = urlparse(target)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
        }
        if (
            not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not local_http)
        ):
            raise HTTPException(status_code=500, detail="Invalid configured UI URL")

        # Land on the login gate; ui.auth_gate.render_login_gate consumes signed_out.
        response = RedirectResponse(f"{target}/?signed_out=1", status_code=302)
        for cookie_name in _STREAMLIT_AUTH_COOKIES:
            _expire_streamlit_auth_cookie(response, cookie_name)
        for cookie_name in request.cookies:
            is_auth_chunk = any(
                cookie_name.startswith(f"{base}_")
                and cookie_name[len(base) + 1 :].isdigit()
                for base in _STREAMLIT_AUTH_COOKIES
            )
            if is_auth_chunk:
                _expire_streamlit_auth_cookie(response, cookie_name)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/ready")
    def ready() -> dict[str, str]:
        """Return readiness once the local database and provider config are usable."""
        try:
            active_store.get_user_preferences()
        except Exception as error:  # pragma: no cover - defensive startup guard
            raise HTTPException(
                status_code=503, detail=f"Database not ready: {error}"
            ) from error
        provider = settings.model_provider
        if provider not in {"mock", "ollama", "openai"}:
            raise HTTPException(
                status_code=503, detail=f"Unsupported MODEL_PROVIDER: {provider}"
            )
        if provider == "openai" and not settings.openai_api_key and not settings.mock_openai:
            raise HTTPException(
                status_code=503, detail="OPENAI_API_KEY is not configured"
            )
        return {
            "status": "ready",
            "mode": "local",
            "provider": provider,
        }

    @app.get("/api/v1/preferences")
    def get_preferences() -> dict[str, Any]:
        """Return local user preferences."""
        return workspace_service.get_preferences()

    @app.patch("/api/v1/preferences")
    def patch_preferences(request: PreferencePatch) -> dict[str, Any]:
        """Merge preference keys for the local user."""
        patch = request.model_dump(exclude_none=True)
        return workspace_service.update_preferences(patch)

    @app.get("/api/v1/threads")
    def list_threads(search: str = "") -> list[dict[str, Any]]:
        """List notebooks for the local student."""
        return workspace_service.list_threads(search)

    @app.post("/api/v1/threads")
    def create_thread(request: NotebookCreateRequest) -> dict[str, Any]:
        """Create a notebook with optional initial metadata."""
        try:
            return workspace_service.create_thread(
                name=request.name,
                model_id=request.model_id,
                support_mode=request.support_mode,
                assignment=request.assignment,
                metadata=request.metadata or None,
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.get("/api/v1/threads/{thread_id}")
    def get_thread(thread_id: str) -> dict[str, Any]:
        """Return one notebook."""
        thread = workspace_service.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return thread

    @app.patch("/api/v1/threads/{thread_id}")
    def update_thread(thread_id: str, request: NotebookUpdateRequest) -> dict[str, Any]:
        """Rename a notebook and/or merge metadata."""
        try:
            return workspace_service.update_thread(
                thread_id, name=request.name, metadata=request.metadata
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.delete("/api/v1/threads/{thread_id}")
    def delete_thread(thread_id: str) -> dict[str, str]:
        """Delete a notebook."""
        workspace_service.delete_thread(thread_id)
        return {"status": "deleted"}

    @app.get("/api/v1/threads/{thread_id}/messages")
    def list_messages(thread_id: str) -> list[dict[str, Any]]:
        """Return canonical chat history."""
        try:
            return workspace_service.get_messages(thread_id)
        except ValueError as error:
            raise _value_error(error) from error

    @app.post("/api/v1/threads/{thread_id}/messages")
    def create_message(thread_id: str, request: MessageCreateRequest) -> dict[str, str]:
        """Persist one message (welcome seeding and similar)."""
        try:
            message_id = workspace_service.add_message(
                thread_id,
                request.role,
                request.content,
                metadata=request.metadata,
            )
        except ValueError as error:
            raise _value_error(error) from error
        return {"id": message_id}

    @app.get("/api/v1/threads/{thread_id}/sources")
    def list_sources(
        thread_id: str, selected_only: bool = False
    ) -> list[dict[str, Any]]:
        """List notebook sources without filesystem paths."""
        try:
            return workspace_service.list_sources(
                thread_id, selected_only=selected_only
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.get("/api/v1/threads/{thread_id}/sources/{source_id}")
    def get_source(thread_id: str, source_id: str) -> dict[str, Any]:
        """Return one source without a filesystem path."""
        source = workspace_service.get_source(thread_id, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        return source

    @app.post("/api/v1/threads/{thread_id}/sources")
    async def upload_sources(
        thread_id: str,
        files: list[UploadFile] = File(...),
    ) -> list[dict[str, Any]]:
        """Upload one or more files into the notebook source library."""
        uploads: list[tuple[str, bytes, str | None]] = []
        for upload in files:
            payload = await upload.read()
            uploads.append(
                (upload.filename or "upload.bin", payload, upload.content_type)
            )
        try:
            return workspace_service.upload_sources(thread_id, uploads)
        except ValueError as error:
            raise _value_error(error) from error

    @app.patch("/api/v1/threads/{thread_id}/sources/{source_id}")
    def update_source(
        thread_id: str, source_id: str, request: SourceUpdateRequest
    ) -> dict[str, Any]:
        """Rename and/or change selection for one source."""
        try:
            if request.title is not None:
                workspace_service.rename_source(thread_id, source_id, request.title)
            if request.selected is not None:
                workspace_service.set_source_selected(
                    thread_id, source_id, request.selected
                )
            source = workspace_service.get_source(thread_id, source_id)
            if not source:
                raise ValueError("Source not found")
            return source
        except ValueError as error:
            raise _value_error(error) from error

    @app.post("/api/v1/threads/{thread_id}/sources/select-all")
    def select_all_sources(
        thread_id: str, request: SourceSelectAllRequest
    ) -> list[dict[str, Any]]:
        """Select or deselect every source in a notebook."""
        try:
            return workspace_service.set_all_sources_selected(
                thread_id, request.selected
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.delete("/api/v1/threads/{thread_id}/sources/{source_id}")
    def delete_source(thread_id: str, source_id: str) -> dict[str, str]:
        """Delete a non-locked source."""
        try:
            workspace_service.delete_source(thread_id, source_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {"status": "deleted"}

    @app.get("/api/v1/threads/{thread_id}/sources/{source_id}/content")
    def source_content(thread_id: str, source_id: str) -> Response:
        """Return source file bytes for preview or download."""
        try:
            content = workspace_service.read_source_content(thread_id, source_id)
        except ValueError as error:
            raise _value_error(error) from error
        disposition = (
            "inline; filename*=UTF-8''" + quote(content.filename)
        )
        return Response(
            content=content.data,
            media_type=content.mime,
            headers={"Content-Disposition": disposition},
        )

    @app.post("/api/v1/threads/{thread_id}/sources/backfill-legacy")
    def backfill_legacy(thread_id: str) -> dict[str, int]:
        """Import legacy message attachments into the source library."""
        try:
            created = workspace_service.backfill_legacy_sources(thread_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {"created": created}

    @app.post("/api/v1/threads/{thread_id}/sources/sync-course-materials")
    def sync_course_materials(thread_id: str) -> dict[str, Any]:
        """Synchronize lecture-note folder materials into the notebook."""
        try:
            result = workspace_service.sync_course_materials(thread_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {
            "added": result.added,
            "updated": result.updated,
            "removed": result.removed,
            "unchanged": result.unchanged,
            "skipped": result.skipped,
            "errors": list(result.errors),
        }

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
        logger.info(
            "coach_turn request thread_id=%s stage=%s sources=%s",
            request.thread_id,
            request.current_stage,
            len(request.source_ids),
        )
        if not active_store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            turn = coach_service.submit(request)
        except ProviderUnavailableError as error:
            logger.warning(
                "coach_turn provider unavailable thread_id=%s", request.thread_id
            )
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            logger.info(
                "coach_turn rejected thread_id=%s reason=%s",
                request.thread_id,
                error,
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
        logger.info(
            "coach_turn ok thread_id=%s recommendation=%s auto_advanced_to=%s",
            request.thread_id,
            turn.assessment.recommendation.value,
            turn.auto_advanced_to,
        )
        return turn

    @app.post("/api/v1/coach/turn/stream")
    def coach_turn_stream(request: CoachRequest) -> StreamingResponse:
        """Stream one coaching turn as NDJSON progress + token events."""

        def events():
            yield json.dumps(
                {
                    "event": "started",
                    "thread_id": request.thread_id,
                    "stage": request.current_stage,
                }
            ) + "\n"
            try:
                turn = coach_service.submit(request)
            except ProviderUnavailableError as error:
                yield json.dumps({"event": "error", "detail": str(error), "status": 503}) + "\n"
                return
            except ValueError as error:
                yield json.dumps({"event": "error", "detail": str(error), "status": 400}) + "\n"
                return
            graph = workflow.inspect_thread(request.thread_id) or {}
            yield json.dumps(
                {
                    "event": "graph",
                    "steps": graph.get("steps") or [],
                    "mode": graph.get("mode"),
                }
            ) + "\n"
            text = turn.response_text
            chunk_size = 32
            for index in range(0, len(text), chunk_size):
                yield json.dumps(
                    {"event": "token", "text": text[index : index + chunk_size]}
                ) + "\n"
            yield json.dumps(
                {"event": "done", "turn": turn.model_dump(mode="json")}
            ) + "\n"

        if not active_store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/v1/threads/{thread_id}/graph")
    def graph_inspection(thread_id: str) -> dict[str, Any]:
        """Return the latest inspectable coach-graph summary for a notebook."""
        if not active_store.get_thread(thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        summary = workflow.inspect_thread(thread_id)
        if not summary:
            return {"thread_id": thread_id, "steps": [], "mode": None}
        return {"thread_id": thread_id, **summary}

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
        logger.info(
            "resolve_transition thread_id=%s transition_id=%s accepted=%s",
            thread_id,
            transition_id,
            request.accepted,
        )
        try:
            return learning_service.resolve(thread_id, transition_id, request.accepted)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
