"""Authenticated browser projection over existing owner-scoped workspace services."""

import logging

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, Response

from backend.auth_profiles import has_streamlit_access
from backend.http.reader_sources import register_reader_sources
from backend.http.reader_workspace import (
    ReaderNotebook,
    reader_notebook,
    reader_notebook_for_owner,
    register_reader_workspace,
)
from backend.learning_signals import learning_receipts
from backend.domain import CitationReference, CoachRequest, CoachTurn, ProjectBriefResult, require_visible_text
from backend.learning.journey import (
    FACIONE_DIMENSIONS,
    learning_review,
    merge_checkpoint_items_into_sections,
    normalize_journey,
    selectable_stage_ids,
)
from backend.learning.resume import StageResume, project_resume
from backend.learning.stages import THINKING_STAGES
from backend.owner_context import OwnerServices
from backend.operational_metrics import record_stage_transition
from backend.settings import settings
from backend.specialists.review_orchestration import (
    DEEP_REVIEW_SNAPSHOT_KEY,
    JOURNEY_STAGE_REVIEWS_KEY,
    parse_journey_stage_reviews,
)


class ReaderSession(BaseModel):
    """Nonsecret identity used to fence in-memory browser state."""

    owner_id: str
    display_name: str
    kind: Literal["guest", "registered"]


class ReaderChatSummary(BaseModel):
    """Bounded, owner-scoped preview of an active saved conversation."""

    preview: str
    activity_at: str


class ReaderNotebooks(BaseModel):
    """Owner-fenced notebook list for the read-only pilot."""

    owner_id: str
    notebooks: list[ReaderNotebook]
    chat_summaries: dict[str, ReaderChatSummary]


class ReaderMessage(BaseModel):
    """Visible saved message without private assessment or storage metadata."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationReference] = Field(default_factory=list)
    starred: bool = False
    feedback_available: bool = False
    rating: Literal["useful", "not_useful"] | None = None


class ReaderStar(BaseModel):
    """Explicit desired bookmark state; no transcript or stage authority."""

    model_config = ConfigDict(extra="forbid")
    starred: bool = Field(strict=True)


class ReaderBookmark(BaseModel):
    """Bounded preview with authoritative saved stage and mode for one bookmark."""

    id: str
    role: Literal["user", "assistant"]
    preview: str
    stage_id: str | None
    interaction_intent: Literal["lecture_help", "project_coaching"] | None


class ReaderBookmarks(BaseModel):
    """All active bookmarks, independent of the currently loaded transcript page."""

    owner_id: str
    thread_id: str
    conversation_revision: int
    messages: list[ReaderBookmark]


class ReaderPage(BaseModel):
    """Chronological transcript page fenced to owner, notebook, and revision."""

    owner_id: str
    notebook: ReaderNotebook
    messages: list[ReaderMessage]
    next_cursor: str | None
    total_count: int
    conversation_revision: int


class LectureRequest(BaseModel):
    """Bounded lecture input; source, stage and model authority remain on the server."""

    model_config = ConfigDict(extra="forbid")
    student_message: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    attachment_source_ids: list[str] = Field(default_factory=list, max_length=5)
    _visible_message = field_validator("student_message")(require_visible_text)


class ReaderStage(StageResume):
    """Canonical stage artifact with server-projected navigation availability."""

    id: str
    label: str
    selectable: bool


class ReaderPending(BaseModel):
    """Visible recommendation without private assessment or research metadata."""

    id: str
    from_stage: str
    to_stage: str
    rationale: str


class ReaderReviewFeedback(BaseModel):
    """Saved formative feedback grouped by the stage it addresses."""

    stage_id: str
    items: list[str]


class ReaderFacioneScore(BaseModel):
    """A rubric dimension and its saved score, when assessed."""

    dimension: str
    score: int | None = Field(ge=1, le=4)


class ReaderBriefRequest(BaseModel):
    """Only explicit retry intent is accepted; all summary inputs are server-owned."""

    model_config = ConfigDict(extra="forbid")
    retry: StrictBool = False


class ReaderReview(BaseModel):
    """Student-facing review projected from saved conversation assessments."""

    project_brief: ProjectBriefResult
    summary: str
    strengths: list[ReaderReviewFeedback]
    improvements: list[ReaderReviewFeedback]
    facione_scores: list[ReaderFacioneScore]


class ReaderProject(BaseModel):
    """Owner-fenced saved project work and canonical pending action."""

    owner_id: str
    thread_id: str
    current_stage: str
    stages: list[ReaderStage]
    pending: ReaderPending | None
    review: ReaderReview


class ReaderDecision(BaseModel):
    """Explicit decision for one saved recommendation; additional authority is forbidden."""

    model_config = ConfigDict(extra="forbid")
    accepted: bool = Field(strict=True)


class ReaderSelection(BaseModel):
    """Requested focus; the application enforces the canonical unlock policy."""

    model_config = ConfigDict(extra="forbid")
    stage_id: str = Field(min_length=1, max_length=64)


def _message(row: dict[str, Any]) -> ReaderMessage:
    """Project saved citations only, keeping research and storage fields private."""
    metadata = row.get("metadata")
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    values = assessment.get("citations") if isinstance(assessment, dict) else None
    citations = []
    for value in values if isinstance(values, list) and row["role"] == "assistant" else []:
        try:
            citations.append(CitationReference.model_validate(value))
        except ValueError:
            continue
    meta = metadata if isinstance(metadata, dict) else {}
    return ReaderMessage(
        id=row["id"], role=row["role"], content=row["content"], citations=citations,
        feedback_available=row['role'] == 'assistant' and meta.get('interaction_intent') == 'lecture_help' and not row.get('is_error'),
        starred=meta.get("starred") is True,
        rating=(learning_receipts(meta.get('learning_signals')).get('rating') or {}).get('kind'),
    )


class ReaderStopTurn(BaseModel):
    """Identify the exact streamed turn to stop in an owned chat."""

    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def register_notebook_reader(
    app: FastAPI, resolve_owner: Callable[[Request], OwnerServices],
    stream_turn: Callable[[CoachRequest, Request, OwnerServices], StreamingResponse],
    revise: Callable[[str, str, str, str, Request, OwnerServices], CoachTurn],
    revise_stream: Callable[[str, str, str, str, Request, OwnerServices], StreamingResponse],
    stop_turn: Callable[[OwnerServices, str, str], str],
) -> None:
    """Register bounded student conversation routes; never use the anonymous local demo owner."""

    def reader_owner(request: Request) -> OwnerServices:
        """Require credentials and delegate verification to the existing resolver."""
        credential = str(request.cookies.get(settings.cognito_id_token_cookie_name) or "").strip()
        guest = settings.guest_access_enabled and str(request.cookies.get(settings.guest_session_cookie_name) or "").strip()
        if not credential and not guest:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Same-origin request required")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings.public_api_base_url.rstrip("/"):
            raise HTTPException(status_code=403, detail="Same-origin request required")
        if request.method == "POST" and not origin:
            raise HTTPException(status_code=403, detail="Same-origin request required")
        owner = resolve_owner(request)
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        if profile.get("role", "student") != "student":
            raise HTTPException(status_code=403, detail="Open the lecturer workspace in Streamlit")
        return owner

    register_reader_sources(app, reader_owner)
    register_reader_workspace(app, reader_owner, revise, revise_stream)

    @app.post("/api/v1/reader/threads/{thread_id}/coach-turn/stop")
    def stop_coach_turn(
        thread_id: str, request: ReaderStopTurn, owner: OwnerServices = Depends(reader_owner),
    ) -> dict[str, str]:
        """Request cancellation without creating or replaying a coach turn."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"status": stop_turn(owner, thread_id, request.idempotency_key)}

    @app.get("/api/v1/reader/session", response_model=ReaderSession)
    def session(owner: OwnerServices = Depends(reader_owner)) -> ReaderSession:
        """Return the verified owner without tokens or private profile fields."""
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        return ReaderSession(
            owner_id=owner.user_id,
            display_name=str(profile.get("display_name") or "Student"),
            kind="guest" if owner.identifier.startswith("guest:") else "registered",
        )

    @app.get("/api/v1/reader/threads", response_model=ReaderNotebooks)
    def notebooks(owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebooks:
        """List owned notebooks without changing or migrating their data."""
        rows = owner.workspace.list_threads()
        entries = [reader_notebook(row) for row in rows]
        notebook_ids = {entry.id for entry in entries if entry.kind == "notebook"}
        for entry in entries:
            if entry.parent_notebook_id not in notebook_ids:
                entry.parent_notebook_id = None
        summaries = {
            entry.id: ReaderChatSummary(
                preview=" ".join(str(row.get("latestUserMessage") or "")[:640].split())[:160],
                activity_at=str(row.get("lastMessageAt") or row.get("createdAt") or ""),
            )
            for entry, row in zip(entries, rows, strict=True)
            if entry.kind == "chat" or int(row.get("messageCount") or 0) > 0
        }
        return ReaderNotebooks(owner_id=owner.user_id, notebooks=entries, chat_summaries=summaries)

    @app.get("/api/v1/reader/threads/{thread_id}/messages/page", response_model=ReaderPage)
    def messages(
        thread_id: str,
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderPage:
        """Read active saved history using existing revision-bound pagination."""
        notebook = owner.workspace.get_thread(thread_id)
        if notebook is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            page = owner.workspace.get_message_page(thread_id, limit=limit, cursor=cursor)
        except ValueError as error:
            status = int(getattr(error, "status_code", 400))
            raise HTTPException(status_code=status, detail="History changed. Reopen the notebook.") from error
        return ReaderPage(
            owner_id=owner.user_id, notebook=reader_notebook_for_owner(notebook, owner),
            messages=[_message(row) for row in page["messages"]],
            next_cursor=page["next_cursor"], total_count=page["total_count"],
            conversation_revision=page["conversation_revision"],
        )

    @app.get("/api/v1/reader/threads/{thread_id}/bookmarks", response_model=ReaderBookmarks)
    def bookmarks(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderBookmarks:
        """Project only owned active stars; never infer context from the live stage."""
        try:
            revision, rows = owner.workspace.get_message_bookmarks(thread_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Notebook not found") from error
        entries = []
        stage_ids = {stage.id for stage in THINKING_STAGES}
        for row in rows:
            meta = row.get("metadata") or {}
            if meta.get("starred") is not True or meta.get("kind") or meta.get("_internal_type"):
                continue
            stage = meta.get("thinking_stage")
            intent = meta.get("interaction_intent")
            entries.append(ReaderBookmark(
                id=row["id"], role=row["role"], preview=row["content"][:320],
                stage_id=stage if isinstance(stage, str) and stage in stage_ids else None,
                interaction_intent=intent if isinstance(intent, str) and intent in {"lecture_help", "project_coaching"} else None,
            ))
        return ReaderBookmarks(
            owner_id=owner.user_id, thread_id=thread_id,
            conversation_revision=revision, messages=entries,
        )

    @app.post("/api/v1/reader/threads/{thread_id}/messages/{message_id}/star", response_model=ReaderStar)
    def star_message(
        thread_id: str, message_id: str, payload: ReaderStar,
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderStar:
        """Set an owned active message's star without starting a coaching turn."""
        try:
            starred = owner.workspace.set_message_star(thread_id, message_id, payload.starred)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Message not found") from error
        return ReaderStar(starred=starred)

    @app.post("/api/v1/reader/threads/{thread_id}/project/brief", response_model=ProjectBriefResult)
    def project_brief(thread_id: str, payload: ReaderBriefRequest, http_request: Request, owner: OwnerServices = Depends(reader_owner)) -> ProjectBriefResult:
        """Generate or reuse a whole-chat brief; accept no browser-supplied history or instructions."""
        from backend.providers import ProviderUnavailableError
        from backend.rate_limit import RateLimitExceeded
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        logging.getLogger("backend.api").info(
            "project_brief request_id=%s thread_id=%s",
            getattr(http_request.state, "request_id", "unknown"), thread_id,
        )
        try:
            return owner.coach.project_brief.generate(thread_id, retry=payload.retry)
        except ValueError as error:
            raise HTTPException(status_code=503, detail="The whole-chat summary could not be generated.") from error
        except RuntimeError as error:
            if isinstance(error, ProviderUnavailableError):
                raise HTTPException(status_code=503, detail="Project summary unavailable. Try again.") from error
            raise HTTPException(status_code=409, detail="Chat changed. Refresh before trying again.") from error
        except RateLimitExceeded as error:
            raise HTTPException(status_code=429, detail="Please wait before updating your summary.") from error

    @app.get("/api/v1/reader/threads/{thread_id}/project", response_model=ReaderProject)
    def project(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderProject:
        """Read canonical artifacts and navigation without invoking a provider or writing data."""
        thread = owner.workspace.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        metadata = thread.get("metadata") or {}
        journey = normalize_journey(metadata.get("learning_journey"))
        messages = owner.store.get_messages(thread_id)
        resume = project_resume(metadata, messages)
        snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
        checkpoints = parse_journey_stage_reviews(metadata.get(JOURNEY_STAGE_REVIEWS_KEY))
        review = learning_review(
            messages,
            journey,
            deep_review_snapshot=snapshot if isinstance(snapshot, dict) else None,
            journey_stage_reviews=checkpoints,
        )
        selectable = selectable_stage_ids(journey) if settings.student_stage_selection else ()
        pending = owner.learning.get_pending(thread_id)
        return ReaderProject(
            owner_id=owner.user_id, thread_id=thread_id, current_stage=resume.current_stage,
            stages=[ReaderStage(
                **view.model_dump(), id=stage.id, label=stage.label, selectable=stage.id in selectable,
            ) for stage, view in zip(THINKING_STAGES, resume.stages, strict=True)],
            pending=ReaderPending(
                id=pending.id, from_stage=pending.from_stage, to_stage=pending.to_stage,
                rationale=pending.assessment.recommendation_rationale,
            ) if pending else None,
            review=ReaderReview(
                project_brief=owner.coach.project_brief.read(thread_id),
                summary=review["saved_summary"] or str(metadata.get("learning_summary") or "").strip(),
                strengths=merge_checkpoint_items_into_sections(
                    review["strength_sections"], checkpoints, field="strengths",
                ),
                improvements=merge_checkpoint_items_into_sections(
                    review["improvement_sections"], checkpoints, field="areas_to_revisit",
                ),
                facione_scores=[
                    ReaderFacioneScore(dimension=label, score=review["facione_scores"][key] or None)
                    for key, label in FACIONE_DIMENSIONS
                ],
            ),
        )

    @app.post("/api/v1/reader/threads/{thread_id}/project/resolve/{transition_id}", response_model=ReaderProject)
    def project_resolve(
        thread_id: str, transition_id: str, payload: ReaderDecision,
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderProject:
        """Apply the shared atomic decision; stale/duplicate requests require canonical rereading."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            owner.learning.resolve(thread_id, transition_id, payload.accepted)
        except ValueError as error:
            raise HTTPException(status_code=409, detail="Project changed. Refresh saved project work.") from error
        record_stage_transition(outcome="accepted" if payload.accepted else "rejected")
        return project(thread_id, owner)

    @app.post("/api/v1/reader/threads/{thread_id}/project/select-stage", response_model=ReaderProject)
    def project_select(
        thread_id: str, payload: ReaderSelection, owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderProject:
        """Select only application-authorized stages without awarding completion in the browser."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            owner.learning.select_stage(thread_id, payload.stage_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail="Stage unavailable. Refresh saved project work.") from error
        record_stage_transition(outcome="selected")
        return project(thread_id, owner)

    @app.post("/api/v1/reader/threads/{thread_id}/lecture/stream")
    def lecture_stream(
        thread_id: str, payload: LectureRequest, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Reuse the shared dispatch/preview/save lifecycle with server-owned lecture intent."""
        return dispatch(thread_id, payload, request, owner, "lecture_help")

    @app.post("/api/v1/reader/threads/{thread_id}/project/stream")
    def project_stream(
        thread_id: str, payload: LectureRequest, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Coach student-authored project work through the same saved-turn lifecycle."""
        return dispatch(thread_id, payload, request, owner, "project_coaching")

    def dispatch(
        thread_id: str, payload: LectureRequest, request: Request, owner: OwnerServices,
        intent: Literal["lecture_help", "project_coaching"],
    ) -> StreamingResponse:
        """Build the shared request from authoritative saved stage and response detail."""
        thread = owner.workspace.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        if len(set(payload.attachment_source_ids)) != len(payload.attachment_source_ids):
            raise HTTPException(status_code=422, detail="Attachment IDs must be distinct")
        journey = normalize_journey((thread.get("metadata") or {}).get("learning_journey"))
        coach_request = CoachRequest(
            thread_id=thread_id, student_message=payload.student_message,
            idempotency_key=payload.idempotency_key, interaction_intent=intent,
            current_stage=journey["current_stage"], response_detail=journey["response_detail"],
            attachment_source_ids=payload.attachment_source_ids,
        )
        coach_request._reader_english = True
        return stream_turn(coach_request, request, owner)

    @app.get("/api/v1/reader/threads/{thread_id}/coach-turn", response_model=CoachTurn | None)
    def saved_turn(
        thread_id: str, idempotency_key: str = Query(min_length=1, max_length=128),
        owner: OwnerServices = Depends(reader_owner),
    ) -> CoachTurn | None:
        """Reconcile by the exact saved identity without starting or replaying generation."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return owner.coach.completed_turn(thread_id, idempotency_key)

    @app.get("/api/v1/reader/threads/{thread_id}/messages/{message_id}/citations/{source_id}/content")
    def cited_content(
        thread_id: str, message_id: str, source_id: str,
        owner: OwnerServices = Depends(reader_owner),
    ) -> Response:
        """Download only evidence mapped to an active saved answer in this notebook."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        row = owner.workspace.get_active_message(thread_id, message_id)
        if row is not None and row["role"] != "assistant":
            row = None
        if row is None or not any(citation.source_id == source_id for citation in _message(row).citations):
            raise HTTPException(status_code=404, detail="Saved citation not found")
        try:
            content = owner.workspace.read_source_content(thread_id, source_id)
        except ValueError:
            try:
                content = owner.workspace.read_library_source(source_id)
            except ValueError as error:
                raise HTTPException(status_code=404, detail="Source unavailable") from error
        return Response(content.data, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(content.filename, safe=""),
            "X-Content-Type-Options": "nosniff",
        })

    def streamlit_allowed(request: Request) -> bool:
        """Check verified Cognito identity and reload its persisted access profile."""
        if not str(request.cookies.get(settings.cognito_id_token_cookie_name) or "").strip():
            return False
        try:
            owner = resolve_owner(request)
        except HTTPException as error:
            if error.status_code == 401:
                return False
            raise
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        return has_streamlit_access(profile, settings.streamlit_access_subjects)

    @app.get("/api/v1/auth/streamlit-access", include_in_schema=False)
    def streamlit_access(request: Request) -> Response:
        """Authorize the proxy's Streamlit requests and WebSocket handshakes."""
        headers = {"Cache-Control": "no-store", "Vary": "Cookie"}
        if not streamlit_allowed(request):
            raise HTTPException(status_code=403, detail="Streamlit access required", headers=headers)
        return Response(status_code=204, headers=headers)

    @app.get("/", include_in_schema=False)
    @app.get("/pilot/", include_in_schema=False)
    def browser_home(request: Request) -> Response:
        """Choose the default workspace from the verified browser identity."""
        headers = {"Cache-Control": "no-store", "Vary": "Cookie"}
        if streamlit_allowed(request):
            query = request.url.query
            target = f"/streamlit/?{query}" if query else "/streamlit/"
            return RedirectResponse(target, status_code=302, headers=headers)
        if (
            not request.cookies.get(settings.cognito_id_token_cookie_name)
            and request.cookies.get(settings.cognito_session_hint_cookie_name)
            and "auth_refreshed" not in request.query_params
        ):
            return RedirectResponse("/api/v1/auth/refresh", status_code=302, headers=headers)
        response = pilot_asset("index.html")
        response.headers["Vary"] = "Cookie"
        return response

    @app.get("/pilot/{asset_path:path}", include_in_schema=False)
    def pilot_asset(asset_path: str) -> FileResponse:
        """Serve built public assets only; missing builds never break Streamlit startup."""
        root = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        relative = asset_path or "index.html"
        root = root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(status_code=404, detail="Not found")
        allowed_suffixes = {".html", ".js", ".css", ".svg", ".ico", ".ttf", ".txt"}
        design_assets = {"favicon.png", "fonts/inter-latin-wght-normal.woff2"}
        if path.suffix not in allowed_suffixes and path.relative_to(root).as_posix() not in design_assets:
            raise HTTPException(status_code=404, detail="Not found")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        })
