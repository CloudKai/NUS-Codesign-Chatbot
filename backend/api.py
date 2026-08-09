"""FastAPI boundary for the local Co-design Chatbot demonstration."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from .auth_oidc import CognitoOIDCClient
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
from .owner_context import OwnerResolver, OwnerServices
from .providers import ProviderUnavailableError
from .settings import settings
from .source_library import CourseMaterialSyncCoordinator
from .student_store import StudentStore
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
    oidc_client: CognitoOIDCClient | None = None,
) -> FastAPI:
    """Create a local API application with injectable progression behavior.

    Application CRUD/coach routes resolve the owner from a verified Cognito
    ID-token cookie. Injected *store* / *workspace* remain the local-demo and
    test default when no Cognito cookie is present (SQLite + local/memory only).
    """
    from backend.persistence.factory import (
        create_student_store,
        validate_storage_configuration,
    )

    validate_storage_configuration()
    if store is not None:
        active_store = store
    elif settings.database_provider == "dsql":
        # Production bootstrap store is for auth/OAuth helpers and readiness only.
        # It must not insert a shared local-student user row into DSQL.
        active_store = create_student_store(
            identifier="__auth_bootstrap__",
            ensure_owner=False,
        )
    else:
        active_store = create_student_store()
    course_sync = CourseMaterialSyncCoordinator()
    # Optional injected workspace is only used as the anonymous/local default.
    # Authenticated Cognito requests always receive a freshly owner-scoped
    # WorkspaceService from OwnerResolver (never the shared local-student one).
    if workspace is not None and workspace.store is not active_store:
        raise ValueError("Injected workspace must use the same store instance")
    advance = (
        settings.auto_advance_stages
        if auto_advance_stages is None
        else auto_advance_stages
    )
    oidc = oidc_client or CognitoOIDCClient(store=active_store)
    resolver = OwnerResolver(
        active_store,
        oidc=oidc,
        course_sync=course_sync,
        auto_advance_stages=bool(advance),
    )
    if workspace is not None:
        # Replace the cached default workspace with the injected instance so
        # tests that assert on a shared WorkspaceService keep working.
        cached = resolver._cache[active_store.identifier]  # noqa: SLF001
        resolver._cache[active_store.identifier] = OwnerServices(  # noqa: SLF001
            store=cached.store,
            workspace=workspace,
            coach=cached.coach,
            learning=cached.learning,
            workflow=cached.workflow,
            transitions=cached.transitions,
            identifier=cached.identifier,
            user_id=cached.user_id,
        )

    app = FastAPI(title="Co-design local API", version="0.1.0")
    register_auth_routes(
        app,
        store=active_store,
        oidc=oidc,
    )

    def current_owner(request: Request) -> OwnerServices:
        """FastAPI dependency: Cognito-verified owner or local-student default."""
        return resolver.resolve(request)

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

        Prefer ``GET/POST /api/v1/auth/logout``, which clears Cognito auth
        cookies (and best-effort revokes the refresh token). This legacy route
        still expires old Streamlit OIDC cookies and redirects to the gate.
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
            active_store.ping()
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
            "mode": (
                "production"
                if settings.database_provider == "dsql"
                or settings.file_storage_provider == "s3"
                else "local"
            ),
            "provider": provider,
            "database_provider": settings.database_provider,
            "file_storage_provider": settings.file_storage_provider,
            "course_material_sync_enabled": (
                "true" if settings.course_material_sync_enabled else "false"
            ),
        }

    @app.get("/api/v1/preferences")
    def get_preferences(owner: OwnerServices = Depends(current_owner)) -> dict[str, Any]:
        """Return preferences for the authenticated (or local demo) owner."""
        return owner.workspace.get_preferences()

    @app.patch("/api/v1/preferences")
    def patch_preferences(
        request: PreferencePatch,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Merge preference keys for the authenticated owner."""
        patch = request.model_dump(exclude_none=True)
        return owner.workspace.update_preferences(patch)

    @app.get("/api/v1/threads")
    def list_threads(
        search: str = "",
        owner: OwnerServices = Depends(current_owner),
    ) -> list[dict[str, Any]]:
        """List notebooks owned by the authenticated user."""
        return owner.workspace.list_threads(search)

    @app.post("/api/v1/threads")
    def create_thread(
        request: NotebookCreateRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Create a notebook owned by the authenticated user."""
        try:
            return owner.workspace.create_thread(
                name=request.name,
                model_id=request.model_id,
                support_mode=request.support_mode,
                assignment=request.assignment,
                metadata=request.metadata or None,
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.get("/api/v1/threads/{thread_id}")
    def get_thread(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Return one owned notebook."""
        thread = owner.workspace.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return thread

    @app.patch("/api/v1/threads/{thread_id}")
    def update_thread(
        thread_id: str,
        request: NotebookUpdateRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Rename an owned notebook and/or merge metadata."""
        try:
            return owner.workspace.update_thread(
                thread_id, name=request.name, metadata=request.metadata
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.delete("/api/v1/threads/{thread_id}")
    def delete_thread(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, str]:
        """Delete an owned notebook."""
        try:
            owner.workspace.delete_thread(thread_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {"status": "deleted"}

    @app.get("/api/v1/threads/{thread_id}/messages")
    def list_messages(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> list[dict[str, Any]]:
        """Return canonical chat history for an owned notebook."""
        try:
            return owner.workspace.get_messages(thread_id)
        except ValueError as error:
            raise _value_error(error) from error

    @app.post("/api/v1/threads/{thread_id}/messages")
    def create_message(
        thread_id: str,
        request: MessageCreateRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, str]:
        """Persist one message on an owned notebook."""
        try:
            message_id = owner.workspace.add_message(
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
        thread_id: str,
        selected_only: bool = False,
        owner: OwnerServices = Depends(current_owner),
    ) -> list[dict[str, Any]]:
        """List owned notebook sources without filesystem paths."""
        try:
            return owner.workspace.list_sources(
                thread_id, selected_only=selected_only
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.get("/api/v1/threads/{thread_id}/sources/{source_id}")
    def get_source(
        thread_id: str,
        source_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Return one owned source without a filesystem path."""
        source = owner.workspace.get_source(thread_id, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        return source

    @app.post("/api/v1/threads/{thread_id}/sources")
    async def upload_sources(
        thread_id: str,
        files: list[UploadFile] = File(...),
        owner: OwnerServices = Depends(current_owner),
    ) -> list[dict[str, Any]]:
        """Upload files into an owned notebook's source library."""
        uploads: list[tuple[str, bytes, str | None]] = []
        for upload in files:
            payload = await upload.read()
            uploads.append(
                (upload.filename or "upload.bin", payload, upload.content_type)
            )
        try:
            return owner.workspace.upload_sources(thread_id, uploads)
        except ValueError as error:
            raise _value_error(error) from error

    @app.patch("/api/v1/threads/{thread_id}/sources/{source_id}")
    def update_source(
        thread_id: str,
        source_id: str,
        request: SourceUpdateRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Rename and/or change selection for one owned source."""
        try:
            if request.title is not None:
                owner.workspace.rename_source(thread_id, source_id, request.title)
            if request.selected is not None:
                owner.workspace.set_source_selected(
                    thread_id, source_id, request.selected
                )
            source = owner.workspace.get_source(thread_id, source_id)
            if not source:
                raise ValueError("Source not found")
            return source
        except ValueError as error:
            raise _value_error(error) from error

    @app.post("/api/v1/threads/{thread_id}/sources/select-all")
    def select_all_sources(
        thread_id: str,
        request: SourceSelectAllRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> list[dict[str, Any]]:
        """Select or deselect every source in an owned notebook."""
        try:
            return owner.workspace.set_all_sources_selected(
                thread_id, request.selected
            )
        except ValueError as error:
            raise _value_error(error) from error

    @app.delete("/api/v1/threads/{thread_id}/sources/{source_id}")
    def delete_source(
        thread_id: str,
        source_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, str]:
        """Delete a non-locked owned source."""
        try:
            owner.workspace.delete_source(thread_id, source_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {"status": "deleted"}

    @app.get("/api/v1/threads/{thread_id}/sources/{source_id}/content")
    def source_content(
        thread_id: str,
        source_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> Response:
        """Return owned source file bytes for preview or download."""
        try:
            content = owner.workspace.read_source_content(thread_id, source_id)
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
    def backfill_legacy(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, int]:
        """Import legacy message attachments into the owned source library."""
        try:
            created = owner.workspace.backfill_legacy_sources(thread_id)
        except ValueError as error:
            raise _value_error(error) from error
        return {"created": created}

    @app.post("/api/v1/threads/{thread_id}/sources/sync-course-materials")
    def sync_course_materials(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Synchronize lecture-note folder materials into the owned notebook."""
        try:
            result = owner.workspace.sync_course_materials(thread_id)
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
    def learning_state(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict:
        """Return persisted notebook learning metadata for the owned thread."""
        thread = owner.store.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return dict(thread.get("metadata") or {})

    @app.get("/api/v1/threads/{thread_id}/phase-transitions/pending")
    def pending_transition(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> PendingPhaseTransition | None:
        """Return the student's unresolved stage transition recommendation."""
        if not owner.store.get_thread(thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        return owner.transitions.get_pending(thread_id)

    @app.post("/api/v1/coach/turn", response_model=CoachTurn)
    def coach_turn(
        request: CoachRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> CoachTurn:
        """Run the typed coaching workflow for an owned notebook."""
        logger.info(
            "coach_turn request thread_id=%s stage=%s sources=%s",
            request.thread_id,
            request.current_stage,
            len(request.source_ids),
        )
        if not owner.store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            turn = owner.coach.submit(request)
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
    def coach_turn_stream(
        request: CoachRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> StreamingResponse:
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
                turn = owner.coach.submit(request)
            except ProviderUnavailableError as error:
                yield json.dumps({"event": "error", "detail": str(error), "status": 503}) + "\n"
                return
            except ValueError as error:
                yield json.dumps({"event": "error", "detail": str(error), "status": 400}) + "\n"
                return
            graph = owner.workflow.inspect_thread(request.thread_id) or {}
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

        if not owner.store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/v1/threads/{thread_id}/graph")
    def graph_inspection(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict[str, Any]:
        """Return the latest inspectable coach-graph summary for a notebook."""
        if not owner.store.get_thread(thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        summary = owner.workflow.inspect_thread(thread_id)
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
        owner: OwnerServices = Depends(current_owner),
    ) -> PendingPhaseTransition:
        """Persist the student's accept/reject decision for a transition."""
        logger.info(
            "resolve_transition thread_id=%s transition_id=%s accepted=%s",
            thread_id,
            transition_id,
            request.accepted,
        )
        try:
            return owner.learning.resolve(thread_id, transition_id, request.accepted)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
