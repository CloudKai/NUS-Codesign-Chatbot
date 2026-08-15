"""FastAPI application composition for the Co-design Chatbot."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from backend.auth_oidc import CognitoOIDCClient
from backend.auth_profiles import PROTECTED_ROLES
from backend.auth_routes import register_auth_routes
from backend.domain import (
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
from backend.owner_context import OwnerResolver, OwnerServices
from backend.operational_metrics import (
    record_coach_turn,
    record_http_request,
    record_stage_transition,
    started_at,
)
from backend.providers import (
    ProviderUnavailableError,
    provider_error_category,
    provider_unavailable_outcome,
)
from backend.rate_limit import RateLimitExceeded
from backend.settings import settings, validate_production_configuration
from backend.source_library import CourseMaterialSyncCoordinator
from backend.student_store import (
    CoachIdempotencyConflictError,
    CoachRequestInProgressError,
    CoachRequestLeaseLostError,
    ConversationRevisionConflictError,
    StudentStore,
)
from backend.workspace_service import WorkspaceService
from backend.professor_analytics.models import (
    ConversationTranscriptResponse,
    CriticalThinkingResponse,
    EngagementResponse,
    OverviewResponse,
    StudentDetailResponse,
    StudentsResponse,
)
from backend.professor_analytics.repository import (
    ProfessorAnalyticsRepository,
    ProfessorAnalyticsUnavailable,
)
from backend.professor_analytics.service import ProfessorAnalyticsService
from backend.professor_analytics.research import (
    ProfessorResearchService,
    ResearchAdjudicationRequest,
    ResearchNotebookDetailResponse,
    ResearchQueueResponse,
    ResearchReviewRequest,
    ResearchSummaryResponse,
)
from backend.research.models import ResearchAdjudication, ResearchReview

logger = logging.getLogger("backend.api")


def _provider_unavailable_detail(error: ProviderUnavailableError) -> dict[str, str]:
    """Return a structured 503 body with a category-only message."""
    return {
        "message": str(error),
        "category": provider_error_category(error),
    }


# Streamlit OIDC cookie names (and numeric chunks) cleared by the logout callback.
# Profile Logout / ui.auth_gate.app_logout_url() navigates here; not Cognito /logout.
_STREAMLIT_AUTH_COOKIES = ("_streamlit_user", "_streamlit_user_tokens")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _request_id_from_header(value: str | None) -> str:
    """Return a bounded correlation ID or replace untrusted input with a UUID."""
    candidate = str(value or "")
    return candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())


class TransitionResolution(BaseModel):
    """Student decision submitted for one pending phase recommendation."""

    accepted: bool


class StageSelectionRequest(BaseModel):
    """Student-chosen Thinking Path stage for free selection mode."""

    stage_id: str = Field(min_length=1, max_length=64)


class MessageReviseRequest(BaseModel):
    """Edit a prior user message via append-only revision and regenerate the coach."""

    content: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    model_id: str | None = None
    reasoning_effort: str | None = None
    response_detail: str | None = Field(default=None, pattern="^(short|long)$")
    response_language: str | None = Field(default=None, min_length=1, max_length=50)


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
        get_file_storage,
        validate_storage_configuration,
    )

    validate_storage_configuration()
    validate_production_configuration()
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
        settings.effective_auto_advance_stages
        if auto_advance_stages is None
        else bool(auto_advance_stages) and not settings.student_stage_selection
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

    app = FastAPI(
        title="Co-design local API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    register_auth_routes(
        app,
        store=active_store,
        oidc=oidc,
    )

    def current_owner(request: Request) -> OwnerServices:
        """FastAPI dependency: Cognito-verified owner or local-student default."""
        return resolver.resolve(request)

    def current_professor(
        request: Request,
        owner: OwnerServices = Depends(current_owner),
    ) -> OwnerServices:
        """Require a verified, persisted lecturer/admin role for analytics.

        This is intentionally separate from navigation visibility: a student
        who calls a professor URL directly receives 403.  Role claims are not
        trusted; the application reloads the database profile after Cognito
        verification so staff access can be revoked without waiting for token
        expiry.
        """
        if not str(request.cookies.get(settings.cognito_id_token_cookie_name) or "").strip():
            raise HTTPException(status_code=401, detail="Not authenticated")
        profile = owner.store.get_user_by_id(owner.user_id)
        role = str((profile or {}).get("role") or "student").strip().lower()
        if role not in PROTECTED_ROLES:
            raise HTTPException(status_code=403, detail="Professor access required")
        return owner

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        """Stamp responses and emit privacy-safe latency/status telemetry."""
        request_id = _request_id_from_header(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = started_at()
        try:
            response = await call_next(request)
        except Exception:
            route = getattr(request.scope.get("route"), "path", None) or "<unmatched>"
            record_http_request(
                method=request.method,
                route=route,
                status_code=500,
                started=started,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        route = getattr(request.scope.get("route"), "path", None) or "<unmatched>"
        record_http_request(
            method=request.method,
            route=route,
            status_code=response.status_code,
            started=started,
        )
        return response

    @app.exception_handler(ProfessorAnalyticsUnavailable)
    async def professor_analytics_unavailable(
        request: Request, _error: ProfessorAnalyticsUnavailable
    ) -> JSONResponse:
        """Return a privacy-safe temporary failure without driver or SQL detail."""
        logger.warning(
            "Professor analytics snapshot unavailable request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Professor analytics is temporarily unavailable"},
        )

    def _value_error(error: ValueError) -> HTTPException:
        detail = str(error)
        status = 404 if "not found" in detail.lower() else 400
        return HTTPException(status_code=status, detail=detail)

    def _with_idempotency_header(
        coach_request: CoachRequest,
        http_request: Request,
    ) -> CoachRequest:
        """Merge the standard retry header into the typed request body."""
        header_key = http_request.headers.get("idempotency-key")
        if header_key is None:
            return coach_request
        if (
            coach_request.idempotency_key
            and coach_request.idempotency_key != header_key
        ):
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key header does not match the request body",
            )
        try:
            return CoachRequest.model_validate(
                {
                    **coach_request.model_dump(mode="json"),
                    "idempotency_key": header_key,
                }
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key header is invalid",
            ) from error

    def _rate_limit_http_error(error: RateLimitExceeded) -> HTTPException:
        """Build a 429 response with Retry-After for coach rate limits."""
        return HTTPException(
            status_code=429,
            detail=error.detail,
            headers={"Retry-After": str(max(1, int(error.retry_after_seconds)))},
        )

    def _selected_source_count(owner: OwnerServices, thread_id: str) -> int:
        """Return the notebook's selected-source count for aggregate metrics.

        Streamlit leaves ``CoachRequest.source_ids`` empty so the application
        service can load the authoritative selection. Metrics must therefore
        read the store, not the client payload, or every UI turn looks
        ungrounded.
        """
        try:
            return len(owner.store.list_sources(thread_id, selected_only=True))
        except Exception:
            return 0

    def _emit_coach_metric(
        *,
        outcome: str,
        selected_source_count: int,
        turn: CoachTurn | None = None,
    ) -> None:
        """Record one privacy-safe coach metric for success or failure paths."""
        if turn is None:
            record_coach_turn(
                provider=settings.model_provider,
                outcome=outcome,
                selected_source_count=selected_source_count,
            )
            return
        record_coach_turn(
            provider=settings.model_provider,
            outcome=outcome,
            selected_source_count=selected_source_count,
            citation_count=len(turn.assessment.citations),
            recommendation=turn.assessment.recommendation.value,
            transition_outcome=(
                "auto_advanced"
                if turn.auto_advanced_to
                else ("pending" if turn.pending_transition else "none")
            ),
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        """Return a lightweight process-health response.

        ``mode`` reflects ``APP_ENV`` only (no secrets, no dependency checks).
        Use ``/api/v1/ready`` for production fail-closed readiness.
        """
        env = (settings.app_env or "").strip().lower() or "development"
        mode = "production" if env == "production" else "local"
        return {"status": "ok", "mode": mode}

    def _professor_service(owner: OwnerServices) -> ProfessorAnalyticsService:
        """Build a read-only analytics service for one authorised request."""
        return ProfessorAnalyticsService(ProfessorAnalyticsRepository(owner.store))

    def _research_service(owner: OwnerServices) -> ProfessorResearchService:
        """Build the research application service over its narrow repository."""
        from backend import api as api_facade

        repository_cls = api_facade.StudentStoreResearchRepository
        return ProfessorResearchService(repository_cls(owner.store))

    def _professor_role(owner: OwnerServices) -> str:
        """Reload the already-authorised persisted staff role for audit context."""
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        return str(profile.get("role") or "student").strip().lower()

    def _research_unavailable(request: Request) -> HTTPException:
        """Log only correlation context and return a privacy-safe 503."""
        logger.warning(
            "Professor research operation unavailable request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return HTTPException(
            status_code=503,
            detail="Professor research data is temporarily unavailable",
        )

    @app.get("/api/v1/professor/overview", response_model=OverviewResponse)
    def professor_overview(
        owner: OwnerServices = Depends(current_professor),
    ) -> OverviewResponse:
        """Return a compact class snapshot for teaching staff only."""
        return _professor_service(owner).overview()

    @app.get("/api/v1/professor/students", response_model=StudentsResponse)
    def professor_students(
        search: str = "",
        stage: str | None = None,
        attention_only: bool = False,
        min_score: float | None = None,
        max_score: float | None = None,
        owner: OwnerServices = Depends(current_professor),
    ) -> StudentsResponse:
        """List privacy-minimised student rows with safe server-side filters."""
        return _professor_service(owner).students(
            search=search,
            stage=stage,
            attention_only=attention_only,
            min_score=min_score,
            max_score=max_score,
        )

    @app.get(
        "/api/v1/professor/students/{student_id}",
        response_model=StudentDetailResponse,
    )
    def professor_student_detail(
        student_id: str,
        owner: OwnerServices = Depends(current_professor),
    ) -> StudentDetailResponse:
        """Return one student's active learning journey and authorised transcript."""
        detail = _professor_service(owner).student_detail(student_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Student not found")
        return detail

    @app.get(
        "/api/v1/professor/students/{student_id}/conversations/{notebook_id}",
        response_model=ConversationTranscriptResponse,
    )
    def professor_conversation_transcript(
        student_id: str,
        notebook_id: str,
        owner: OwnerServices = Depends(current_professor),
    ) -> ConversationTranscriptResponse:
        """Return one selected student's active notebook transcript only."""
        transcript = _professor_service(owner).conversation_transcript(
            student_id, notebook_id
        )
        if transcript is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return transcript

    @app.get(
        "/api/v1/professor/critical-thinking",
        response_model=CriticalThinkingResponse,
    )
    def professor_critical_thinking(
        owner: OwnerServices = Depends(current_professor),
    ) -> CriticalThinkingResponse:
        """Return current, non-causal Facione assessment aggregates."""
        return _professor_service(owner).critical_thinking()

    @app.get(
        "/api/v1/professor/engagement",
        response_model=EngagementResponse,
    )
    def professor_engagement(
        owner: OwnerServices = Depends(current_professor),
    ) -> EngagementResponse:
        """Return usage/session analytics, kept distinct from performance."""
        return _professor_service(owner).engagement()

    @app.get(
        "/api/v1/professor/research/summary",
        response_model=ResearchSummaryResponse,
    )
    def professor_research_summary(
        request: Request,
        owner: OwnerServices = Depends(current_professor),
    ) -> ResearchSummaryResponse:
        """Return aggregate research-coding counts without identities."""
        try:
            return _research_service(owner).summary()
        except Exception as error:
            raise _research_unavailable(request) from error

    @app.get(
        "/api/v1/professor/research/queue",
        response_model=ResearchQueueResponse,
    )
    def professor_research_queue(
        request: Request,
        coding_status: str | None = Query(default=None, max_length=16),
        phase: str | None = Query(default=None, max_length=80),
        search: str = Query(default="", max_length=120),
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10_000),
        owner: OwnerServices = Depends(current_professor),
    ) -> ResearchQueueResponse:
        """Return an audited, filtered page of identifiable observations."""
        try:
            return _research_service(owner).queue(
                actor_user_id=owner.user_id,
                actor_role=_professor_role(owner),
                request_id=str(getattr(request.state, "request_id", "unknown")),
                coding_status=coding_status,
                phase=phase,
                search=search,
                limit=limit,
                offset=offset,
            )
        except ValueError as error:
            raise _value_error(error) from error
        except Exception as error:
            raise _research_unavailable(request) from error

    @app.get(
        "/api/v1/professor/research/notebooks/{notebook_id}",
        response_model=ResearchNotebookDetailResponse,
    )
    def professor_research_notebook(
        notebook_id: str,
        request: Request,
        observation_limit: int = Query(default=100, ge=1, le=100),
        observation_offset: int = Query(default=0, ge=0, le=10_000),
        owner: OwnerServices = Depends(current_professor),
    ) -> ResearchNotebookDetailResponse:
        """Return one audited transcript with automated and human coding."""
        try:
            detail = _research_service(owner).notebook_detail(
                notebook_id,
                actor_user_id=owner.user_id,
                actor_role=_professor_role(owner),
                request_id=str(getattr(request.state, "request_id", "unknown")),
                transcript_loader=_professor_service(owner).conversation_transcript,
                observation_limit=observation_limit,
                observation_offset=observation_offset,
            )
        except Exception as error:
            raise _research_unavailable(request) from error
        if detail is None:
            raise HTTPException(status_code=404, detail="Research notebook not found")
        return detail

    @app.post(
        "/api/v1/professor/research/reviews",
        response_model=ResearchReview,
        status_code=201,
    )
    def professor_research_review(
        payload: ResearchReviewRequest,
        request: Request,
        owner: OwnerServices = Depends(current_professor),
    ) -> ResearchReview:
        """Append a review with reviewer identity derived from authentication."""
        try:
            return _research_service(owner).submit_review(
                payload, reviewer_user_id=owner.user_id
            )
        except ValueError as error:
            raise _value_error(error) from error
        except Exception as error:
            raise _research_unavailable(request) from error

    @app.post(
        "/api/v1/professor/research/adjudications",
        response_model=ResearchAdjudication,
        status_code=201,
    )
    def professor_research_adjudication(
        payload: ResearchAdjudicationRequest,
        request: Request,
        owner: OwnerServices = Depends(current_professor),
    ) -> ResearchAdjudication:
        """Append an adjudication with server-derived staff identity."""
        try:
            return _research_service(owner).submit_adjudication(
                payload, adjudicator_user_id=owner.user_id
            )
        except ValueError as error:
            raise _value_error(error) from error
        except Exception as error:
            raise _research_unavailable(request) from error

    @app.get("/api/v1/professor/research/export.csv")
    def professor_research_export(
        request: Request,
        coding_status: str | None = Query(default=None, max_length=16),
        phase: str | None = Query(default=None, max_length=80),
        owner: OwnerServices = Depends(current_professor),
    ) -> Response:
        """Return an audited, formula-safe CSV export of active observations."""
        try:
            content = _research_service(owner).export_csv(
                actor_user_id=owner.user_id,
                actor_role=_professor_role(owner),
                request_id=str(getattr(request.state, "request_id", "unknown")),
                coding_status=coding_status,
                phase=phase,
            )
        except ValueError as error:
            raise _value_error(error) from error
        except Exception as error:
            raise _research_unavailable(request) from error
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="research-observations.csv"',
                "X-Content-Type-Options": "nosniff",
            },
        )

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
        """Return readiness once dependencies and production config are usable."""
        # Dual-gate: explicit APP_ENV=production plus legacy dsql/s3 inference so
        # existing readiness probes keep Cognito HTTPS checks during cutover.
        production_mode = (
            settings.is_production
            or settings.database_provider == "dsql"
            or settings.file_storage_provider == "s3"
        )
        try:
            validate_production_configuration()
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        try:
            active_store.ping()
        except Exception as error:  # pragma: no cover - defensive startup guard
            logger.warning("Database readiness check failed")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Database not ready"
                    if production_mode
                    else f"Database not ready: {error}"
                ),
            ) from error
        try:
            get_file_storage().ping()
        except Exception as error:  # pragma: no cover - defensive startup guard
            logger.warning("File storage readiness check failed")
            raise HTTPException(
                status_code=503,
                detail=(
                    "File storage not ready"
                    if production_mode
                    else f"File storage not ready: {error}"
                ),
            ) from error
        provider = settings.model_provider
        if provider not in {"mock", "openai", "bedrock", "agentcore"}:
            raise HTTPException(
                status_code=503, detail=f"Unsupported MODEL_PROVIDER: {provider}"
            )
        if provider == "openai" and not settings.openai_api_key and not settings.mock_openai:
            raise HTTPException(
                status_code=503, detail="OPENAI_API_KEY is not configured"
            )
        if provider == "bedrock" and not settings.bedrock_model_id:
            raise HTTPException(
                status_code=503, detail="BEDROCK_MODEL_ID is not configured"
            )
        if provider == "agentcore" and not settings.resolved_agentcore_runtime_arn:
            raise HTTPException(
                status_code=503, detail="AGENTCORE_RUNTIME_ARN is not configured"
            )
        if production_mode:
            try:
                # Preserve the historical backend.api monkeypatch seam while
                # the implementation is owned by this extracted module.
                from backend import api as api_facade

                api_facade.validate_cognito_readiness(require_https=True)
            except ValueError as error:
                # Validation never does OIDC discovery and error text is
                # category-only, so readiness cannot disclose auth secrets.
                raise HTTPException(status_code=503, detail=str(error)) from error
            except Exception as error:  # pragma: no cover - defensive config guard
                logger.warning("Cognito readiness validation failed", exc_info=True)
                raise HTTPException(
                    status_code=503,
                    detail="Cognito authentication configuration is unavailable",
                ) from error
        return {
            "status": "ready",
            "mode": "production" if production_mode else "local",
            "app_env": settings.app_env,
            "provider": provider,
            "database_provider": settings.database_provider,
            "file_storage_provider": settings.file_storage_provider,
            "course_material_sync_enabled": (
                "true" if settings.course_material_sync_enabled else "false"
            ),
            "cognito_configured": "true" if production_mode else "not_required",
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
                metadata=request.metadata.model_dump(exclude_none=True) or None,
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
                thread_id,
                name=request.name,
                metadata=(
                    request.metadata.model_dump(exclude_none=True)
                    if request.metadata is not None
                    else None
                ),
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

    @app.get("/api/v1/threads/{thread_id}/transcript.txt")
    def download_transcript(
        thread_id: str,
        owner: OwnerServices = Depends(current_owner),
    ) -> Response:
        """Return a student-readable .txt projection of persisted messages."""
        try:
            transcript = owner.workspace.export_transcript(thread_id)
        except ValueError as error:
            raise _value_error(error) from error
        disposition = "attachment; filename*=UTF-8''" + quote(transcript.filename)
        return Response(
            content=transcript.data,
            media_type=transcript.mime,
            headers={"Content-Disposition": disposition},
        )

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
                metadata=request.metadata.model_dump(),
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
        if len(files) > settings.max_files:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Upload at most {settings.max_files} files per message."
                ),
            )
        max_bytes = max(1, int(settings.max_file_size_mb)) * 1024 * 1024
        uploads: list[tuple[str, bytes, str | None]] = []
        for upload in files:
            # Read at most one byte past the limit so oversized bodies are rejected
            # without buffering an arbitrary upload into memory.
            payload = await upload.read(max_bytes + 1)
            name = upload.filename or "upload.bin"
            if len(payload) > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{name} exceeds the {settings.max_file_size_mb} MB limit."
                    ),
                )
            uploads.append((name, payload, upload.content_type))
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

    @app.post("/api/v1/threads/{thread_id}/learning-state/select-stage")
    def select_learning_stage(
        thread_id: str,
        request: StageSelectionRequest,
        owner: OwnerServices = Depends(current_owner),
    ) -> dict:
        """Move the owned notebook to a student-chosen Thinking Path stage.

        Requires ``STUDENT_STAGE_SELECTION=true``. Returns updated notebook
        metadata including ``learning_journey``.
        """
        try:
            metadata = owner.learning.select_stage(thread_id, request.stage_id)
        except ValueError as error:
            message = str(error)
            status = 404 if "not found" in message.lower() else 400
            raise HTTPException(status_code=status, detail=message) from error
        record_stage_transition(outcome="selected")
        return dict(metadata or {})

    @app.post(
        "/api/v1/threads/{thread_id}/messages/{message_id}/revise",
        response_model=CoachTurn,
    )
    def revise_user_message(
        thread_id: str,
        message_id: str,
        request: MessageReviseRequest,
        http_request: Request,
        owner: OwnerServices = Depends(current_owner),
    ) -> CoachTurn:
        """Revise an owned user message via append-only supersede, then coach again.

        Uses a new idempotency key. Conversation revision is server-owned.
        Historical revision snapshots are not exposed on this student route.
        """
        if not owner.store.get_thread(thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        selected_source_count = _selected_source_count(owner, thread_id)
        try:
            turn = owner.coach.revise_and_resubmit(
                thread_id,
                message_id,
                request.content,
                idempotency_key=request.idempotency_key,
                model_id=request.model_id,
                reasoning_effort=request.reasoning_effort,
                response_detail=request.response_detail,
                response_language=request.response_language,
            )
        except RateLimitExceeded as error:
            raise _rate_limit_http_error(error) from error
        except CoachIdempotencyConflictError as error:
            _emit_coach_metric(
                outcome="idempotency_conflict",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ConversationRevisionConflictError as error:
            _emit_coach_metric(
                outcome="revision_conflict",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (CoachRequestInProgressError, CoachRequestLeaseLostError) as error:
            _emit_coach_metric(
                outcome="idempotency_in_progress",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ProviderUnavailableError as error:
            _emit_coach_metric(
                outcome=provider_unavailable_outcome(error),
                selected_source_count=selected_source_count,
            )
            raise HTTPException(
                status_code=503, detail=_provider_unavailable_detail(error)
            ) from error
        except ValueError as error:
            message = str(error)
            status = 404 if "not found" in message.lower() else 400
            _emit_coach_metric(
                outcome="rejected",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=status, detail=message) from error
        _emit_coach_metric(
            outcome="ok",
            selected_source_count=selected_source_count,
            turn=turn,
        )
        return turn

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
        http_request: Request,
        owner: OwnerServices = Depends(current_owner),
    ) -> CoachTurn:
        """Run the typed coaching workflow for an owned notebook."""
        request = _with_idempotency_header(request, http_request)
        if not owner.store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        selected_source_count = _selected_source_count(owner, request.thread_id)
        request_id = str(getattr(http_request.state, "request_id", None) or "-")
        logger.info(
            "coach_turn request request_id=%s stage=%s sources=%s",
            request_id,
            request.current_stage,
            selected_source_count,
        )
        try:
            # Rate limits apply inside CoachApplicationService only when a new
            # provider execution is claimed, so same-key waiters can converge.
            turn = owner.coach.submit(request)
        except RateLimitExceeded as error:
            raise _rate_limit_http_error(error) from error
        except CoachIdempotencyConflictError as error:
            _emit_coach_metric(
                outcome="idempotency_conflict",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ConversationRevisionConflictError as error:
            _emit_coach_metric(
                outcome="revision_conflict",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (CoachRequestInProgressError, CoachRequestLeaseLostError) as error:
            _emit_coach_metric(
                outcome="idempotency_in_progress",
                selected_source_count=selected_source_count,
            )
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ProviderUnavailableError as error:
            _emit_coach_metric(
                outcome=provider_unavailable_outcome(error),
                selected_source_count=selected_source_count,
            )
            logger.warning(
                "coach_turn provider unavailable request_id=%s", request_id
            )
            raise HTTPException(
                status_code=503, detail=_provider_unavailable_detail(error)
            ) from error
        except ValueError as error:
            _emit_coach_metric(
                outcome="rejected",
                selected_source_count=selected_source_count,
            )
            logger.info(
                "coach_turn rejected request_id=%s", request_id
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception:
            _emit_coach_metric(
                outcome="failed",
                selected_source_count=selected_source_count,
            )
            raise
        logger.info(
            "coach_turn ok request_id=%s recommendation=%s auto_advanced=%s",
            request_id,
            turn.assessment.recommendation.value,
            bool(turn.auto_advanced_to),
        )
        _emit_coach_metric(
            outcome="ok",
            selected_source_count=selected_source_count,
            turn=turn,
        )
        return turn

    @app.post("/api/v1/coach/turn/stream")
    def coach_turn_stream(
        request: CoachRequest,
        http_request: Request,
        owner: OwnerServices = Depends(current_owner),
    ) -> StreamingResponse:
        """Stream one coaching turn as NDJSON progress + token events."""

        request = _with_idempotency_header(request, http_request)
        if not owner.store.get_thread(request.thread_id):
            raise HTTPException(status_code=404, detail="Notebook not found")
        selected_source_count = _selected_source_count(owner, request.thread_id)

        def events():
            yield json.dumps(
                {
                    "event": "started",
                    "stage": request.current_stage,
                }
            ) + "\n"
            # Signal UI before the long provider submit so students see a
            # thinking state instead of a blank assistant bubble.
            yield json.dumps(
                {"event": "status", "phase": "thinking"}
            ) + "\n"
            try:
                turn = owner.coach.submit(request)
            except RateLimitExceeded as error:
                yield json.dumps(
                    {
                        "event": "error",
                        "detail": error.detail,
                        "status": 429,
                        "retry_after": max(1, int(error.retry_after_seconds)),
                    }
                ) + "\n"
                return
            except CoachIdempotencyConflictError as error:
                _emit_coach_metric(
                    outcome="idempotency_conflict",
                    selected_source_count=selected_source_count,
                )
                yield json.dumps(
                    {"event": "error", "detail": str(error), "status": 409}
                ) + "\n"
                return
            except ConversationRevisionConflictError as error:
                _emit_coach_metric(
                    outcome="revision_conflict",
                    selected_source_count=selected_source_count,
                )
                yield json.dumps(
                    {"event": "error", "detail": str(error), "status": 409}
                ) + "\n"
                return
            except (CoachRequestInProgressError, CoachRequestLeaseLostError) as error:
                _emit_coach_metric(
                    outcome="idempotency_in_progress",
                    selected_source_count=selected_source_count,
                )
                yield json.dumps(
                    {"event": "error", "detail": str(error), "status": 409}
                ) + "\n"
                return
            except ProviderUnavailableError as error:
                _emit_coach_metric(
                    outcome=provider_unavailable_outcome(error),
                    selected_source_count=selected_source_count,
                )
                yield json.dumps(
                    {
                        "event": "error",
                        "detail": str(error),
                        "status": 503,
                        "category": provider_error_category(error),
                    }
                ) + "\n"
                return
            except ValueError as error:
                _emit_coach_metric(
                    outcome="rejected",
                    selected_source_count=selected_source_count,
                )
                yield json.dumps(
                    {"event": "error", "detail": str(error), "status": 400}
                ) + "\n"
                return
            except Exception:
                _emit_coach_metric(
                    outcome="failed",
                    selected_source_count=selected_source_count,
                )
                raise
            _emit_coach_metric(
                outcome="ok",
                selected_source_count=selected_source_count,
                turn=turn,
            )
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
                    {
                        "event": "token",
                        "text": text[index : index + chunk_size],
                    }
                ) + "\n"
            yield json.dumps(
                {"event": "done", "turn": turn.model_dump(mode="json")}
            ) + "\n"

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
            "resolve_transition accepted=%s",
            request.accepted,
        )
        try:
            resolved = owner.learning.resolve(
                thread_id, transition_id, request.accepted
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        record_stage_transition(
            outcome="accepted" if request.accepted else "rejected"
        )
        return resolved

    return app


app = create_app()
