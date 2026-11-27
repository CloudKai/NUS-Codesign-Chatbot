"""Authenticated browser projection over existing owner-scoped workspace services."""

import logging

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from backend.http.origin import same_configured_origin
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, Response

from backend.auth_profiles import has_streamlit_access
from backend.http.reader_sources import register_reader_sources
from backend.http.reader_artifacts import register_reader_artifacts
from backend.http.reader_canvases import register_reader_canvases
from backend.http.reader_deep_review import register_reader_deep_review
from backend.artifact_export import render_artifact_text
from backend.canvas_export import render_canvas_selection_text
from backend.project_export import (
    MAX_EXPORT_ARTIFACTS,
    MAX_EXPORT_CANVASES,
    MAX_EXPORT_MESSAGES,
    ProjectExportError,
    build_project_export,
    selected_ids,
    serialize_project_export,
)
from backend.persistence.store.operations.references import notebook_family_ids
from backend.http.reader_workspace import (
    ReaderError,
    ReaderNotebook,
    ReaderNotebookSettings,
    ReaderPreferences,
    reader_notebook_settings,
    reader_preferences,
    reader_notebook,
    reader_notebook_for_owner,
    register_reader_workspace,
)
from backend.learning_signals import learning_receipts
from backend.artifact_feedback import ArtifactFeedback
from backend.canvas_draft import CanvasDraftProposal
from backend.canvas_suggestions import CanvasSuggestion
from backend.domain import ArtifactFeedbackOrigin, CanvasContextOrigin, CitationReference, CoachRequest, CoachTurn, ProjectBriefResult, require_visible_text
from backend.learning.journey import (
    FACIONE_DIMENSIONS,
    learning_review,
    merge_checkpoint_items_into_sections,
    normalize_journey,
    selectable_stage_ids,
)
from backend.learning.resume import StageResume, project_resume
from backend.learning.recaps import MilestoneRecap
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


class ReaderBootstrap(BaseModel):
    """Initial public projections bound to the same authenticated owner.

    These independently read presentation resources are not a transactional
    workspace snapshot. No transcript, source body or model call is included.
    """

    session: ReaderSession
    listing: ReaderNotebooks
    preferences: ReaderPreferences


class ReaderMessage(BaseModel):
    """Visible saved message without private assessment or storage metadata."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    interaction_intent: Literal["lecture_help", "improve_design", "project_coaching"] | None = None
    citations: list[CitationReference] = Field(default_factory=list)
    # Bounded untrusted canvas proposals saved with this answer. They render as
    # preview cards only; acceptance is the student's explicit canvas save.
    canvas_suggestions: list[CanvasSuggestion] = Field(default_factory=list)
    # At most one before/after artifact feedback pair, same acceptance rules.
    artifact_feedback: list[ArtifactFeedback] = Field(default_factory=list)
    # One reviewable synthesized draft for an explicit draft request. It is
    # untrusted data: nothing is created until the student confirms, and the
    # confirmation always makes a new artifact.
    canvas_draft: CanvasDraftProposal | None = None
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
    interaction_intent: Literal["lecture_help", "improve_design", "project_coaching"] | None


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


class ReaderCanvasSelection(BaseModel):
    """Server-resolved canvas selection: identity and revision, never node content.

    ``purpose`` distinguishes discussing the selection from explicitly
    requesting a synthesized artifact draft; the server decides which purpose
    a request carries.
    """

    model_config = ConfigDict(extra="forbid")
    canvas_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(strict=True, ge=1)
    node_ids: list[str] = Field(min_length=1, max_length=5)
    purpose: Literal["discuss", "draft"] = "discuss"


class ReaderArtifactSelection(BaseModel):
    """Server-resolved artifact feedback selection: identity, revision, never text.

    ``paragraph`` indexes the saved document's top-level blocks; None asks for
    the whole bounded document text. The saved text is resolved server-side.
    """

    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(strict=True, ge=1)
    paragraph: int | None = Field(default=None, ge=0, le=10_000)


class LectureRequest(BaseModel):
    """Bounded lecture input; source, stage and model authority remain on the server."""

    model_config = ConfigDict(extra="forbid")
    student_message: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    attachment_source_ids: list[str] = Field(default_factory=list, max_length=5)
    canvas_selection: ReaderCanvasSelection | None = None
    artifact_selection: ReaderArtifactSelection | None = None
    _visible_message = field_validator("student_message")(require_visible_text)


def _resolve_canvas_selection(
    thread_id: str, selection: ReaderCanvasSelection | None, owner: OwnerServices,
) -> tuple[str, CanvasContextOrigin | None]:
    """Resolve the authorized saved node text for one canvas selection, or ''.

    The canvas must belong to the thread's notebook family and match the seen
    revision (409 stale); unknown nodes fail 422. The returned text comes only
    from the stored canonical graph — bounded server-side, never from the body.
    The paired origin records the resolved snapshot identity so canvas
    suggestions can carry the base revision the coach reasoned about.
    """
    if selection is None:
        return "", None
    canvas = owner.store.get_canvas(selection.canvas_id)
    with owner.store._connect() as connection:
        family = notebook_family_ids(connection, thread_id, owner.user_id)
    if canvas is None or canvas['thread_id'] not in family:
        raise HTTPException(status_code=404, detail="Canvas not found")
    if int(canvas['revision']) != int(selection.revision):
        raise HTTPException(status_code=409, detail="Canvas changed. Reopen it before asking.")
    graph = canvas['graph']
    known = {str(node.get('id')) for node in graph.get('nodes') or []}
    unknown = [node_id for node_id in selection.node_ids if node_id not in known]
    if unknown:
        raise HTTPException(status_code=422, detail="Unknown canvas node")
    return (
        render_canvas_selection_text(graph, selection.node_ids),
        CanvasContextOrigin(canvas_id=selection.canvas_id, revision=int(selection.revision),
                            node_ids=list(selection.node_ids)[:5]),
    )


def _artifact_block_text(document: dict[str, Any], paragraph: int | None) -> str:
    """Resolve the bounded saved text for one artifact feedback selection.

    ``paragraph`` indexes the document's top-level blocks; ``None`` selects the
    whole bounded plaintext. Returns '' for an empty selection. Raises
    ``LookupError`` when the paragraph index is out of range.
    """
    if paragraph is None:
        return render_artifact_text(document)[:4_000]
    blocks = [block for block in document.get('content') or [] if isinstance(block, dict)]
    if paragraph >= len(blocks):
        raise LookupError('paragraph')
    block = blocks[paragraph]
    if str(block.get('type') or '') in {'paragraph', 'heading', 'codeBlock'}:
        return render_artifact_text({'type': 'doc', 'content': [block]})[:4_000]
    # Structured blocks (lists, etc.) resolve to their nested readable text.
    return render_artifact_text({'type': 'doc', 'content': [block]})[:4_000]


def _resolve_artifact_feedback(
    thread_id: str, selection: ReaderArtifactSelection | None, owner: OwnerServices,
) -> tuple[str, ArtifactFeedbackOrigin | None]:
    """Resolve the authorized saved artifact text for one feedback selection, or ''.

    The artifact must belong to the thread's notebook family and match the seen
    revision (409 stale); out-of-range paragraphs fail 422. The returned text
    comes only from the stored canonical document — bounded server-side, never
    from the request body.
    """
    if selection is None:
        return "", None
    artifact = owner.store.get_artifact(selection.artifact_id)
    with owner.store._connect() as connection:
        family = notebook_family_ids(connection, thread_id, owner.user_id)
    if artifact is None or artifact['thread_id'] not in family:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if int(artifact['revision']) != int(selection.revision):
        raise HTTPException(status_code=409, detail="Document changed. Reopen it before asking.")
    try:
        text = _artifact_block_text(artifact['document'], selection.paragraph)
    except LookupError:
        raise HTTPException(status_code=422, detail="Unknown document paragraph") from None
    return (
        f"Selected {'passage' if selection.paragraph is not None else 'draft'} from your "
        f"saved artifact '{artifact['title']}':\n{text}",
        ArtifactFeedbackOrigin(
            artifact_id=selection.artifact_id, revision=int(selection.revision),
            paragraph=selection.paragraph, original_text=text,
        ),
    )


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
    # Persisted confirmed-milestone recaps: read-only history that never
    # completes or advances a stage; malformed saved entries are dropped.
    recaps: list[MilestoneRecap] = Field(default_factory=list)


class ReaderThreadWorkspace(BaseModel):
    """One owner-consistent bounded open read for the student workspace.

    These independently read projections are not a transactional snapshot. No
    transcript beyond the first page, uploaded source body or version history
    is included; bounded counts inside each projection are the availability
    indicators until typed source resources own them.
    """

    owner_id: str
    page: ReaderPage
    project: ReaderProject
    bookmarks: ReaderBookmarks
    settings: ReaderNotebookSettings


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
    meta = metadata if isinstance(metadata, dict) else {}
    values = meta.get("citations")
    if not isinstance(values, list):
        assessment = meta.get("assessment")
        values = assessment.get("citations") if isinstance(assessment, dict) else None
    citations = []
    for value in values if isinstance(values, list) and row["role"] == "assistant" else []:
        try:
            citations.append(CitationReference.model_validate(value))
        except ValueError:
            continue
    saved_suggestions: list[CanvasSuggestion] = []
    saved_feedback: list[ArtifactFeedback] = []
    if row["role"] == "assistant":
        for raw in meta.get("canvas_suggestions") or []:
            try:
                saved_suggestions.append(CanvasSuggestion.model_validate(raw))
            except (TypeError, ValueError):
                continue
        for raw in meta.get("artifact_feedback") or []:
            try:
                saved_feedback.append(ArtifactFeedback.model_validate(raw))
            except (TypeError, ValueError):
                continue
        raw_draft = meta.get("canvas_draft")
        if isinstance(raw_draft, dict):
            try:
                saved_draft: CanvasDraftProposal | None = CanvasDraftProposal.model_validate(raw_draft)
            except (TypeError, ValueError):
                saved_draft = None
        else:
            saved_draft = None
    else:
        saved_draft = None
    intent = meta.get("interaction_intent")
    return ReaderMessage(
        id=row["id"], role=row["role"], content=row["content"], citations=citations,
        interaction_intent=intent if intent in ("lecture_help", "improve_design", "project_coaching") else None,
        canvas_suggestions=saved_suggestions[:5],
        artifact_feedback=saved_feedback[:1],
        canvas_draft=saved_draft,
        feedback_available=row['role'] == 'assistant' and meta.get('interaction_intent') in {'lecture_help', 'improve_design'} and not row.get('is_error'),
        starred=meta.get("starred") is True,
        rating=(learning_receipts(meta.get('learning_signals')).get('rating') or {}).get('kind'),
    )


def reader_page_view(thread_id: str, owner: OwnerServices, limit: int = 20,
                     cursor: str | None = None) -> ReaderPage:
    """Read one revision-bound transcript page with the shared pagination authority."""
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


def reader_bookmarks_view(thread_id: str, owner: OwnerServices) -> ReaderBookmarks:
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
            interaction_intent=intent if isinstance(intent, str) and intent in {"lecture_help", "improve_design", "project_coaching"} else None,
        ))
    return ReaderBookmarks(
        owner_id=owner.user_id, thread_id=thread_id,
        conversation_revision=revision, messages=entries,
    )


def reader_project_view(thread_id: str, owner: OwnerServices) -> ReaderProject:
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
    recaps: list[MilestoneRecap] = []
    for raw in metadata.get("milestone_recaps") or []:
        try:
            recaps.append(MilestoneRecap.model_validate(raw))
        except (TypeError, ValueError):
            continue
    return ReaderProject(
        owner_id=owner.user_id, thread_id=thread_id, current_stage=resume.current_stage,
        recaps=recaps[:10],
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
        if origin and not same_configured_origin(
            origin, settings.public_api_base_url, settings.api_base_url,
        ):
            raise HTTPException(status_code=403, detail="Same-origin request required")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not origin:
            raise HTTPException(status_code=403, detail="Same-origin request required")
        owner = resolve_owner(request)
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        if profile.get("role", "student") != "student":
            raise HTTPException(status_code=403, detail="Open the lecturer workspace in Streamlit")
        return owner

    register_reader_sources(app, reader_owner)
    register_reader_artifacts(app, reader_owner)
    register_reader_canvases(app, reader_owner)
    register_reader_deep_review(app, reader_owner)
    register_reader_workspace(app, reader_owner, revise, revise_stream)

    @app.post("/api/v1/reader/threads/{thread_id}/coach-turn/stop")
    def stop_coach_turn(
        thread_id: str, request: ReaderStopTurn, owner: OwnerServices = Depends(reader_owner),
    ) -> dict[str, str]:
        """Request cancellation without creating or replaying a coach turn."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"status": stop_turn(owner, thread_id, request.idempotency_key)}

    @app.get("/api/v1/reader/session", response_model=ReaderSession, operation_id="readerSession",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}})
    def session(owner: OwnerServices = Depends(reader_owner)) -> ReaderSession:
        """Return the verified owner without tokens or private profile fields."""
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        return ReaderSession(
            owner_id=owner.user_id,
            display_name=str(profile.get("display_name") or "Student"),
            kind="guest" if owner.identifier.startswith("guest:") else "registered",
        )

    @app.get("/api/v1/reader/threads", response_model=ReaderNotebooks, operation_id="readerNotebooks",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}})
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

    @app.get("/api/v1/reader/bootstrap", response_model=ReaderBootstrap, operation_id="readerBootstrap",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}})
    def bootstrap(owner: OwnerServices = Depends(reader_owner)) -> ReaderBootstrap:
        """Load initial projections with one authentication and existing bulk list read."""
        return ReaderBootstrap(session=session(owner), listing=notebooks(owner),
                               preferences=reader_preferences(owner))

    @app.get("/api/v1/reader/threads/{thread_id}/messages/page", response_model=ReaderPage,
             operation_id="readerMessages", responses={code: {"model": ReaderError} for code in (400, 401, 403, 404, 409)})
    def messages(
        thread_id: str,
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderPage:
        """Read active saved history using existing revision-bound pagination."""
        return reader_page_view(thread_id, owner, limit=limit, cursor=cursor)

    @app.get("/api/v1/reader/threads/{thread_id}/workspace", response_model=ReaderThreadWorkspace,
             operation_id="readerThreadWorkspace",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def workspace(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderThreadWorkspace:
        """Load one bounded owner-consistent open read; not a transactional snapshot."""
        return ReaderThreadWorkspace(
            owner_id=owner.user_id,
            page=reader_page_view(thread_id, owner),
            project=reader_project_view(thread_id, owner),
            bookmarks=reader_bookmarks_view(thread_id, owner),
            settings=reader_notebook_settings(thread_id, owner),
        )

    @app.get("/api/v1/reader/threads/{thread_id}/bookmarks", response_model=ReaderBookmarks,
             operation_id="readerBookmarks",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def bookmarks(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderBookmarks:
        """Project only owned active stars; never infer context from the live stage."""
        return reader_bookmarks_view(thread_id, owner)

    @app.post("/api/v1/reader/threads/{thread_id}/messages/{message_id}/star", response_model=ReaderStar,
              operation_id="readerStar",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
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

    @app.post("/api/v1/reader/threads/{thread_id}/project/brief", response_model=ProjectBriefResult,
              operation_id="readerProjectBrief",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                         409: {"model": ReaderError}, 429: {"model": ReaderError}, 503: {"model": ReaderError}})
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

    @app.get("/api/v1/reader/threads/{thread_id}/project", response_model=ReaderProject,
             operation_id="readerProject",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def project(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderProject:
        """Read canonical artifacts and navigation without invoking a provider or writing data."""
        return reader_project_view(thread_id, owner)

    @app.get("/api/v1/reader/threads/{thread_id}/project/export", include_in_schema=False)
    def project_export(thread_id: str,
                       artifacts: str = Query("", max_length=2048),
                       canvases: str = Query("", max_length=2048),
                       owner: OwnerServices = Depends(reader_owner)) -> Response:
        """Download the selected project export as an inert structured attachment.

        Like the artifact, canvas and transcript exports, this stays a documented
        download outside the JSON browser contract: same-origin enforced,
        nosniff attachment with a sanitized filename and no caching. The envelope
        is assembled server-side from saved, owner-checked rows only, bounded in
        item count and serialized size, and reuses the same student-facing
        project projection the browser already reads — no rendering service.
        """
        thread = owner.workspace.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            artifact_ids = selected_ids(artifacts, limit=MAX_EXPORT_ARTIFACTS)
            canvas_ids = selected_ids(canvases, limit=MAX_EXPORT_CANVASES)
        except ProjectExportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        artifact_rows = []
        for artifact_id in artifact_ids:
            row = owner.store.get_artifact(artifact_id)
            if row is None or row["thread_id"] != thread_id:
                raise HTTPException(status_code=404, detail="Artifact not found")
            artifact_rows.append(row)
        canvas_rows = []
        for canvas_id in canvas_ids:
            row = owner.store.get_canvas(canvas_id)
            if row is None or row["thread_id"] != thread_id:
                raise HTTPException(status_code=404, detail="Canvas not found")
            canvas_rows.append(row)
        with owner.store._connect() as connection:
            family = notebook_family_ids(connection, thread_id, owner.user_id)
        conversation: list[dict[str, Any]] = []
        for family_id in family:
            family_thread = owner.workspace.get_thread(family_id)
            if family_thread is None:
                continue
            chat_title = str(family_thread.get("name") or "").strip() or "Untitled chat"
            # Bounded read: at most MAX_EXPORT_MESSAGES newest messages per
            # family chat (keyset pages), then the export-wide cap below.
            # Never load an unbounded history here.
            collected: list[dict[str, Any]] = []
            cursor: str | None = None
            while len(collected) < MAX_EXPORT_MESSAGES:
                page = owner.store.get_messages_page(
                    family_id, limit=min(100, MAX_EXPORT_MESSAGES - len(collected)),
                    cursor=cursor)
                batch = page.get("messages", [])
                collected.extend(batch)
                cursor = page.get("next_cursor")
                if not batch or not cursor:
                    break
            conversation.extend(
                {**message, "chat_title": chat_title} for message in collected)
        conversation.sort(key=lambda message: str(message.get("created_at") or ""))
        try:
            envelope = build_project_export(
                title=str(thread.get("name") or "").strip() or "Untitled notebook",
                project=reader_project_view(thread_id, owner).model_dump(),
                messages=conversation,
                artifacts=artifact_rows, canvases=canvas_rows,
            )
            body = serialize_project_export(envelope)
        except ProjectExportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        safe_title = ''.join(character for character in thread["name"]
                             if character.isalnum() or character in (' ', '-', '_')).strip() \
            or 'project'
        return Response(body, media_type="application/json", headers={
            'Content-Disposition':
                f"attachment; filename*=UTF-8''{quote(f'{safe_title}-project.json', safe='')}",
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store',
        })

    @app.post("/api/v1/reader/threads/{thread_id}/project/resolve/{transition_id}", response_model=ReaderProject,
              operation_id="readerProjectResolve",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                         409: {"model": ReaderError}})
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

    @app.post("/api/v1/reader/threads/{thread_id}/project/select-stage", response_model=ReaderProject,
              operation_id="readerProjectSelect",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                         409: {"model": ReaderError}})
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

    @app.post("/api/v1/reader/threads/{thread_id}/improve/stream")
    def improve_stream(
        thread_id: str, payload: LectureRequest, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Stream and save freeform feedback with server-owned Improve intent."""
        return dispatch(thread_id, payload, request, owner, "improve_design")

    @app.post("/api/v1/reader/threads/{thread_id}/project/stream")
    def project_stream(
        thread_id: str, payload: LectureRequest, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Coach student-authored project work through the same saved-turn lifecycle."""
        return dispatch(thread_id, payload, request, owner, "project_coaching")

    def dispatch(
        thread_id: str, payload: LectureRequest, request: Request, owner: OwnerServices,
        intent: Literal["lecture_help", "improve_design", "project_coaching"],
    ) -> StreamingResponse:
        """Build the shared request from authoritative saved stage and response detail."""
        thread = owner.workspace.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        if len(set(payload.attachment_source_ids)) != len(payload.attachment_source_ids):
            raise HTTPException(status_code=422, detail="Attachment IDs must be distinct")
        journey = normalize_journey((thread.get("metadata") or {}).get("learning_journey"))
        canvas_text, canvas_origin = _resolve_canvas_selection(
            thread_id, payload.canvas_selection, owner
        )
        artifact_text, artifact_origin = _resolve_artifact_feedback(
            thread_id, payload.artifact_selection, owner
        )
        coach_request = CoachRequest(
            thread_id=thread_id, student_message=payload.student_message,
            idempotency_key=payload.idempotency_key, interaction_intent=intent,
            current_stage=journey["current_stage"], response_detail=journey["response_detail"],
            attachment_source_ids=payload.attachment_source_ids,
            canvas_context=canvas_text,
            canvas_context_origin=canvas_origin,
            canvas_selection_purpose=(
                payload.canvas_selection.purpose if payload.canvas_selection else None
            ),
            artifact_context=artifact_text,
            artifact_feedback_origin=artifact_origin,
        )
        coach_request._reader_english = True
        coach_request._context_server_resolved = True
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
        return browser_view(request)

    @app.get("/library", include_in_schema=False)
    @app.get("/search", include_in_schema=False)
    @app.get("/settings", include_in_schema=False)
    @app.get("/chats/{thread_id}", include_in_schema=False)
    @app.get("/notebooks/{folder_id}", include_in_schema=False)
    @app.get("/notebooks/{folder_id}/artifacts/{artifact_id}", include_in_schema=False)
    @app.get("/notebooks/{folder_id}/canvases/{canvas_id}", include_in_schema=False)
    @app.get("/pilot/library", include_in_schema=False)
    @app.get("/pilot/search", include_in_schema=False)
    @app.get("/pilot/settings", include_in_schema=False)
    @app.get("/pilot/chats/{thread_id}", include_in_schema=False)
    @app.get("/pilot/notebooks/{folder_id}", include_in_schema=False)
    @app.get("/pilot/notebooks/{folder_id}/artifacts/{artifact_id}", include_in_schema=False)
    @app.get("/pilot/notebooks/{folder_id}/canvases/{canvas_id}", include_in_schema=False)
    def browser_view(request: Request) -> Response:
        """Serve the recognized student view shell; the SPA carries no private data."""
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
