"""Cached runtime resources shared across Streamlit UI modules.

``store`` is a workspace facade: when ``USE_LOCAL_API`` is enabled it calls the
typed FastAPI client; otherwise it uses ``WorkspaceService`` in-process. Either
path avoids panel modules importing SQLite or reading source files from disk.
Student turns go through ``submit_coach_turn`` / ``stream_coach_turn_events``
(API or in-process ``CoachApplicationService``), not ``StudentChatEngine``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Iterator, TypeVar

import httpx
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from backend.api_client import LocalApiClient
from ui.run_memo import invalidate_memo, memoized
from backend.application import CoachApplicationService
from backend.coaching.progress import PROGRESS_LABELS
from backend.domain import (
    CoachRequest,
    CoachTurn,
    DeepReviewJob,
    MessageCreateRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    PendingPhaseTransition,
    SourceUpdateRequest,
)
from backend.learning_service import LearningProgressService
from backend.providers import configured_coach_provider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.source_library import CourseMaterialSyncCoordinator, LectureNotesSyncResult
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from backend.workspace_service import SourceContent, TranscriptExport, WorkspaceService


_T = TypeVar("_T")
_ui_perf_logger = logging.getLogger("co_design.ui_perf")


class _NonPersistentCookies(httpx.Cookies):
    """Cookie jar that never stores ``Set-Cookie`` values from responses.

    ``local_api_client()`` is process-wide. Auth still forwards the current
    browser ID cookie on each request via ``cookie_provider``; persisting
    response cookies on the shared client would mix sessions across students.
    """

    def extract_cookies(self, response: httpx.Response) -> None:
        """Ignore ``Set-Cookie`` headers so the shared jar stays empty."""
        del response
        return


def _memo_read(key: tuple[Any, ...], loader: Callable[[], _T]) -> _T:
    """Return a run-scoped cached workspace read."""
    return memoized(key, loader)


def _forget_reads(*prefixes: tuple[Any, ...]) -> None:
    """Drop run-scoped reads that match ``prefixes`` (or all, if empty)."""
    invalidate_memo(*prefixes)


@st.cache_resource
def resources(
    identifier: str = "local-student",
) -> tuple[
    StudentStore,
    WorkspaceService,
    CoachApplicationService,
    LearningProgressService,
]:
    """Create the shared store, workspace service, and coaching application service."""
    from backend.persistence.factory import create_student_store

    store = create_student_store(identifier=identifier)
    service = WorkspaceService(store, CourseMaterialSyncCoordinator())
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(configured_coach_provider(), transitions)
    learning = LearningProgressService(store, notebooks, transitions)
    coach = CoachApplicationService(
        store,
        notebooks,
        workflow,
        learning,
        auto_advance_stages=bool(
            getattr(settings, "effective_auto_advance_stages", False)
        ),
    )
    return store, service, coach, learning


def owner_identifier() -> str:
    """Return the active StudentStore owner identifier for this browser session.

    Cognito sessions bind ``cognito:{sub}`` before any store use. The
    unauthenticated demo owner ``local-student`` cannot equal that prefixed
    form, so the two cache keys cannot collide.
    """
    bound = str(st.session_state.get("_auth_store_identifier") or "").strip()
    if bound:
        return bound
    cognito_sub = str(st.session_state.get("_auth_bound_sub") or "").strip()
    if cognito_sub:
        repaired = f"cognito:{cognito_sub}"
        bind_owner_identifier(repaired)
        return repaired
    return "local-student"


def bind_owner_identifier(identifier: str) -> None:
    """Bind this browser session to a Cognito-scoped store cache key."""
    cleaned = str(identifier or "").strip() or "local-student"
    st.session_state["_auth_store_identifier"] = cleaned


def _resolve_resources() -> tuple[
    StudentStore,
    WorkspaceService,
    CoachApplicationService,
    LearningProgressService,
]:
    """Return store/service/coach, refreshing if hot-reload left a stale class."""
    store, service, coach, learning = resources(owner_identifier())
    if not hasattr(store, "get_user_preferences") or not hasattr(
        store, "update_user_preferences"
    ):
        resources.clear()
        store, service, coach, learning = resources(owner_identifier())
    if getattr(store, "identifier", None) != owner_identifier():
        resources.clear()
        store, service, coach, learning = resources(owner_identifier())
    return store, service, coach, learning


@st.cache_resource
def course_material_sync() -> CourseMaterialSyncCoordinator:
    """Share background source imports across Streamlit reruns and refreshes."""
    return CourseMaterialSyncCoordinator()


@st.cache_resource
def local_api_client() -> LocalApiClient:
    """Create the typed client used when the optional local API mode is enabled.

    Forwards the short-lived Cognito ID-token cookie on each request so FastAPI
    can resolve the authenticated owner. The refresh cookie never reaches
    Streamlit and is not forwarded here.
    """

    def _id_cookie() -> dict[str, str]:
        try:
            from ui.auth_gate import _cookie_value
        except Exception:
            return {}
        token = _cookie_value(str(settings.cognito_id_token_cookie_name))
        if not token:
            return {}
        return {str(settings.cognito_id_token_cookie_name): token}

    timeout_seconds = 120.0
    client = LocalApiClient(
        str(getattr(settings, "api_base_url", "http://127.0.0.1:8000")),
        timeout_seconds=timeout_seconds,
        cookie_provider=_id_cookie,
    )
    http = getattr(client, "_http", None)
    if isinstance(http, httpx.Client):
        # Client.cookies.setter wraps values in a generic Cookies jar and
        # would re-enable Set-Cookie persistence. Assign the private jar.
        http._cookies = _NonPersistentCookies()
    return client


def local_api_enabled() -> bool:
    """Return whether Streamlit should call FastAPI for application traffic.

    Cognito-authenticated students and the local ``local-student`` demo both use
    the API when ``USE_LOCAL_API`` is enabled. FastAPI resolves the owner from
    the verified Cognito ID cookie (or falls back to local-student for demos).
    """
    return bool(getattr(settings, "use_local_api", False))


def submit_coach_turn(request: CoachRequest) -> CoachTurn:
    """Run one student coaching turn via the local API or in-process service."""
    if local_api_enabled():
        return local_api_client().coach_turn(request)
    _, _, coach, _ = _resolve_resources()
    return coach.submit(request)


def start_deep_review(
    thread_id: str, *, idempotency_key: str | None = None
) -> DeepReviewJob:
    """Enqueue one server-owned explicit Deep Review via API or in-process service."""
    if local_api_enabled():
        return local_api_client().start_deep_review(
            thread_id, idempotency_key=idempotency_key
        )
    _, _, coach, _ = _resolve_resources()
    return coach.enqueue_deep_review(thread_id, idempotency_key=idempotency_key)


def get_deep_review_job(thread_id: str) -> DeepReviewJob | None:
    """Return the owner-scoped Deep Review job, or ``None`` when none exists."""
    if local_api_enabled():
        try:
            return local_api_client().get_deep_review(thread_id)
        except httpx.HTTPStatusError as error:
            if error.response is not None and error.response.status_code == 404:
                return None
            raise
    _, _, coach, _ = _resolve_resources()
    try:
        return coach.get_deep_review_job(thread_id)
    except ValueError:
        return None


def stream_coach_turn_events(request: CoachRequest) -> Iterator[dict[str, Any]]:
    """Yield progress and done events for one coaching turn.

    Uses the NDJSON streaming API when ``USE_LOCAL_API`` is enabled; otherwise
    runs the in-process coach service and emits the same progress phases.
    This helper does not invent token slices from a completed reply.
    A UUID ``X-Request-ID`` correlates Streamlit, FastAPI, and TIMING lines.
    """
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        if local_api_enabled():
            yield from local_api_client().stream_coach_turn(
                request, request_id=request_id
            )
            return
        _, _, coach, _ = _resolve_resources()
        yield {
            "event": "started",
            "thread_id": request.thread_id,
            "stage": request.current_stage,
        }
        bus: queue.SimpleQueue[dict[str, Any] | BaseException | None] = queue.SimpleQueue()

        def _progress(phase: str) -> None:
            bus.put(
                {
                    "event": "status",
                    "phase": phase,
                    "label": PROGRESS_LABELS.get(phase, ""),
                }
            )

        def _worker() -> None:
            try:
                completed = coach.submit(request, progress=_progress)
                bus.put({"event": "done", "turn": completed.model_dump(mode="json")})
            except BaseException as error:
                bus.put(error)
            finally:
                bus.put(None)

        worker = threading.Thread(target=_worker, name="in-process-coach-stream", daemon=True)
        worker.start()
        try:
            while True:
                item = bus.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            worker.join(timeout=1.0)
    finally:
        elapsed_ms = round(max(0.0, (time.perf_counter() - started) * 1000.0), 1)
        _ui_perf_logger.info(
            "UI TIMING request_id=%s stream_ms=%.1f",
            request_id,
            elapsed_ms,
        )


class WorkspaceFacade:
    """UI persistence facade over the typed API or in-process workspace service."""

    def _service(self) -> WorkspaceService:
        _, service, _, _ = _resolve_resources()
        return service

    def _backend_store(self) -> StudentStore:
        store, _, _, _ = _resolve_resources()
        return store

    def forget_run_reads(self, thread_id: str | None = None) -> None:
        """Drop memoized notebook reads after a coach or workspace mutation.

        Args:
            thread_id: When set, drop only that notebook's thread, messages,
                sources, pending-transition, and backfill entries. When omitted,
                clear the entire run memo.
        """
        if not thread_id:
            _forget_reads()
            return
        _forget_reads(
            ("get_thread", thread_id),
            ("get_messages", thread_id),
            ("list_sources", thread_id),
            ("pending_transition", thread_id),
            ("backfill_legacy_sources", thread_id),
            ("request_course_material_sync", thread_id),
        )

    def forget_source_reads(self, thread_id: str) -> None:
        """Drop the source-list memo after the run added or removed library rows.

        Args:
            thread_id: Notebook whose source list is now stale.
        """
        _forget_reads(
            ("list_sources", thread_id),
            ("backfill_legacy_sources", thread_id),
        )

    def forget_turn_reads(self, thread_id: str) -> None:
        """Drop thread, messages, and pending-transition memos after a coach turn.

        Source list, backfill, and course-sync memos stay valid: a completed
        turn does not add library rows, and the Sources panel often renders
        after chat in the same script run.
        """
        _forget_reads(
            ("get_thread", thread_id),
            ("get_messages", thread_id),
            ("pending_transition", thread_id),
        )

    def get_user_preferences(self) -> dict[str, Any]:
        """Return local user preferences."""

        def load() -> dict[str, Any]:
            if local_api_enabled():
                return local_api_client().get_preferences()
            return self._service().get_preferences()

        return _memo_read(("get_user_preferences",), load)

    def update_user_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys."""
        if local_api_enabled():
            local_api_client().update_preferences(patch)
        else:
            self._service().update_preferences(patch)
        _forget_reads(("get_user_preferences",))

    def list_threads(self, search: str = "", folder_id: str | None = None) -> list[dict]:
        """List notebooks (folder filter retained for store compatibility; unused)."""
        del folder_id

        def load() -> list[dict]:
            if local_api_enabled():
                return local_api_client().list_threads(search)
            return self._service().list_threads(search)

        return _memo_read(("list_threads", search), load)

    def get_thread(self, thread_id: str) -> dict | None:
        """Return one notebook."""

        def load() -> dict | None:
            if local_api_enabled():
                return local_api_client().get_thread(thread_id)
            return self._service().get_thread(thread_id)

        return _memo_read(("get_thread", thread_id), load)

    def create_thread(
        self,
        *,
        name: str = "New assignment chat",
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
    ) -> str:
        """Create a notebook and return its id."""
        if local_api_enabled():
            thread = local_api_client().create_thread(
                NotebookCreateRequest(
                    name=name,
                    model_id=model_id,
                    support_mode=support_mode,
                    assignment=assignment or {},
                )
            )
            thread_id = str(thread["id"])
        else:
            thread = self._service().create_thread(
                name=name,
                model_id=model_id,
                support_mode=support_mode,
                assignment=assignment,
            )
            thread_id = str(thread["id"])
        _forget_reads(("list_threads",))
        return thread_id

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Rename a notebook and/or merge metadata."""
        if local_api_enabled():
            local_api_client().update_thread(
                thread_id, NotebookUpdateRequest(name=name, metadata=metadata)
            )
        else:
            self._service().update_thread(thread_id, name=name, metadata=metadata)
        _forget_reads(("get_thread", thread_id), ("list_threads",))

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook."""
        if local_api_enabled():
            local_api_client().delete_thread(thread_id)
        else:
            self._service().delete_thread(thread_id)
        self.forget_run_reads(thread_id)
        _forget_reads(("list_threads",))

    def get_messages(self, thread_id: str) -> list[dict]:
        """Return chat history."""

        def load() -> list[dict]:
            if local_api_enabled():
                return local_api_client().get_messages(thread_id)
            return self._service().get_messages(thread_id)

        return _memo_read(("get_messages", thread_id), load)

    def download_transcript(self, thread_id: str) -> TranscriptExport:
        """Return a ``.txt`` transcript projected from persisted messages."""
        if local_api_enabled():
            return local_api_client().download_transcript(thread_id)
        return self._service().export_transcript(thread_id)

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        model_id: str | None = None,
        message_id: str | None = None,
        is_error: bool = False,
    ) -> str:
        """Persist one chat message."""
        del model_id, message_id, is_error
        if local_api_enabled():
            added = local_api_client().add_message(
                thread_id,
                MessageCreateRequest(
                    role=role, content=content, metadata=metadata or {}
                ),
            )
        else:
            added = self._service().add_message(
                thread_id, role, content, metadata=metadata
            )
        _forget_reads(("get_messages", thread_id), ("get_thread", thread_id))
        return added

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict]:
        """List notebook sources without filesystem paths."""

        def load() -> list[dict]:
            if local_api_enabled():
                return local_api_client().list_sources(
                    thread_id, selected_only=selected_only
                )
            return self._service().list_sources(
                thread_id, selected_only=selected_only
            )

        return _memo_read(("list_sources", thread_id, selected_only), load)

    def get_source(self, thread_id: str, source_id: str) -> dict | None:
        """Return one source without a filesystem path."""
        if local_api_enabled():
            return local_api_client().get_source(thread_id, source_id)
        return self._service().get_source(thread_id, source_id)

    def set_source_selected(
        self, thread_id: str, source_id: str, selected: bool
    ) -> None:
        """Toggle one source selection flag."""
        if local_api_enabled():
            local_api_client().update_source(
                thread_id, source_id, SourceUpdateRequest(selected=selected)
            )
        else:
            self._service().set_source_selected(thread_id, source_id, selected)
        _forget_reads(("list_sources", thread_id))

    def set_all_sources_selected(self, thread_id: str, selected: bool) -> None:
        """Select or deselect every source."""
        if local_api_enabled():
            local_api_client().select_all_sources(thread_id, selected)
        else:
            self._service().set_all_sources_selected(thread_id, selected)
        _forget_reads(("list_sources", thread_id))

    def rename_source(self, thread_id: str, source_id: str, title: str) -> None:
        """Rename a non-locked source."""
        if local_api_enabled():
            local_api_client().update_source(
                thread_id, source_id, SourceUpdateRequest(title=title)
            )
        else:
            self._service().rename_source(thread_id, source_id, title)
        _forget_reads(("list_sources", thread_id))

    def delete_source(
        self, thread_id: str, source_id: str, *, force: bool = False
    ) -> None:
        """Delete a source."""
        del force
        if local_api_enabled():
            local_api_client().delete_source(thread_id, source_id)
        else:
            self._service().delete_source(thread_id, source_id)
        _forget_reads(("list_sources", thread_id))

    def upload_sources(
        self,
        thread_id: str,
        uploads: list[tuple[str, bytes, str | None]],
        *,
        origin: str = "source_panel",
    ) -> list[dict]:
        """Upload files into the source library."""
        if local_api_enabled():
            added = local_api_client().upload_sources(thread_id, uploads)
        else:
            added = self._service().upload_sources(
                thread_id, uploads, origin=origin
            )
        _forget_reads(("list_sources", thread_id), ("get_thread", thread_id))
        return added

    def get_source_content(self, thread_id: str, source_id: str) -> SourceContent:
        """Read source bytes for preview/download."""
        if local_api_enabled():
            return local_api_client().get_source_content(thread_id, source_id)
        return self._service().read_source_content(thread_id, source_id)

    def backfill_legacy_sources(self, thread_id: str) -> int:
        """Import legacy message attachments."""

        def load() -> int:
            if local_api_enabled():
                added = local_api_client().backfill_legacy_sources(thread_id)
            else:
                added = self._service().backfill_legacy_sources(thread_id)
            if added:
                _forget_reads(("list_sources", thread_id), ("get_messages", thread_id))
            return added

        return _memo_read(("backfill_legacy_sources", thread_id), load)

    def pending_transition(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved stage recommendation for the owned notebook."""

        def load() -> PendingPhaseTransition | None:
            if local_api_enabled():
                return local_api_client().pending_transition(thread_id)
            _, _, _, learning = _resolve_resources()
            return learning.get_pending(thread_id)

        return _memo_read(("pending_transition", thread_id), load)

    def resolve_transition(
        self,
        thread_id: str,
        transition_id: str,
        *,
        accepted: bool,
    ) -> PendingPhaseTransition:
        """Persist the student's decision through the active application path."""
        if local_api_enabled():
            resolved = local_api_client().resolve_transition(
                thread_id,
                transition_id,
                accepted,
            )
        else:
            _, _, _, learning = _resolve_resources()
            resolved = learning.resolve(thread_id, transition_id, accepted)
        self.forget_run_reads(thread_id)
        return resolved

    def select_stage(self, thread_id: str, stage_id: str) -> dict:
        """Move the notebook to a student-chosen Thinking Path stage."""
        if local_api_enabled():
            metadata = local_api_client().select_stage(thread_id, stage_id)
        else:
            _, _, _, learning = _resolve_resources()
            metadata = learning.select_stage(thread_id, stage_id)
        self.forget_run_reads(thread_id)
        return metadata

    def revise_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        idempotency_key: str,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        response_detail: str | None = None,
        response_language: str | None = None,
    ) -> CoachTurn:
        """Revise a user message through the FastAPI or in-process coach path."""
        if local_api_enabled():
            turn = local_api_client().revise_message(
                thread_id,
                message_id,
                content,
                idempotency_key=idempotency_key,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                response_detail=response_detail,
                response_language=response_language,
            )
        else:
            _, _, coach, _ = _resolve_resources()
            turn = coach.revise_and_resubmit(
                thread_id,
                message_id,
                content,
                idempotency_key=idempotency_key,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                response_detail=response_detail,
                response_language=response_language,
            )
        self.forget_run_reads(thread_id)
        return turn

    def request_course_material_sync(self, thread_id: str):
        """Start or join course-material sync for the active notebook.

        API-mode sessions (including Cognito) sync through FastAPI so ownership
        stays on the authenticated application user.
        """

        def load():
            if local_api_enabled():
                api_base = str(
                    getattr(settings, "api_base_url", "http://127.0.0.1:8000")
                )
                client = local_api_client()
                # Streamlit's cookie context is script-thread local. Capture the
                # short-lived ID cookie before handing work to the sync executor;
                # reading it inside that worker resolves the fallback owner and
                # causes an endless authenticated-notebook 404 retry loop.
                auth_cookies = client.auth_cookie_snapshot()

                def _sync_via_api() -> LectureNotesSyncResult:
                    payload = client.sync_course_materials(
                        thread_id,
                        auth_cookies=auth_cookies,
                    )
                    errors = payload.get("errors") or []
                    return LectureNotesSyncResult(
                        added=int(payload.get("added") or 0),
                        updated=int(payload.get("updated") or 0),
                        removed=int(payload.get("removed") or 0),
                        unchanged=int(payload.get("unchanged") or 0),
                        skipped=int(payload.get("skipped") or 0),
                        errors=tuple(str(item) for item in errors),
                    )

                return course_material_sync().request_api(
                    api_base,
                    thread_id,
                    _sync_via_api,
                )
            return course_material_sync().request(self._backend_store(), thread_id)

        return _memo_read(("request_course_material_sync", thread_id), load)


store = WorkspaceFacade()

# Fragment ticks from a prior script may not see in-flight session_state.
# Session ids let Sources/Deep Review skip ``rerun_app()`` in the same process.
_streaming_session_ids: set[str] = set()


def _script_session_id() -> str:
    """Return the current Streamlit session id, or empty when no script context."""
    ctx = get_script_run_ctx(suppress_warning=True)
    if ctx is None:
        return ""
    return str(getattr(ctx, "session_id", "") or "")


def rerun_app() -> None:
    """Request a full Streamlit script rerun (notebook/auth/coach/layout changes)."""
    st.rerun()


def rerun_fragment() -> None:
    """Request a fragment-scoped rerun for panel-local UI updates."""
    st.rerun(scope="fragment")


def set_coach_turn_streaming(active: bool) -> None:
    """Record whether this session is blocked in a coach send or revise.

    Writes ``_coach_turn_streaming`` and an in-process set keyed by Streamlit
    session id so a Sources ``run_every`` fragment from a prior script can
    still skip ``rerun_app()`` while ``handle_prompt`` holds the main run.

    Args:
        active: True while the send/revise call is in flight.
    """
    flagged = bool(active)
    st.session_state["_coach_turn_streaming"] = flagged
    session_id = _script_session_id()
    if not session_id:
        return
    if flagged:
        _streaming_session_ids.add(session_id)
    else:
        _streaming_session_ids.discard(session_id)


def coach_turn_is_streaming() -> bool:
    """Return whether a coach send or revise is blocking this script run.

    Sources and Deep Review fragments must not call ``rerun_app()`` while this
    is true; a full remount during ``handle_prompt`` stacks a second workspace.
    True if session state or the in-process session-id set says streaming.
    """
    if st.session_state.get("_coach_turn_streaming"):
        return True
    session_id = _script_session_id()
    return bool(session_id and session_id in _streaming_session_ids)
