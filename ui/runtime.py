"""Cached runtime resources shared across Streamlit UI modules.

``store`` is a workspace facade: when ``USE_LOCAL_API`` is enabled it calls the
typed FastAPI client; otherwise it uses ``WorkspaceService`` in-process. Either
path avoids panel modules importing SQLite or reading source files from disk.
Student turns go through ``submit_coach_turn`` / ``stream_coach_turn_events``
(API or in-process ``CoachApplicationService``), not ``StudentChatEngine``.
"""

from __future__ import annotations

from typing import Any, Iterator

import streamlit as st

from backend.api_client import LocalApiClient
from backend.application import CoachApplicationService
from backend.domain import (
    CoachRequest,
    CoachTurn,
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
from backend.workspace_service import SourceContent, WorkspaceService


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
        auto_advance_stages=bool(getattr(settings, "auto_advance_stages", False)),
    )
    return store, service, coach, learning


def owner_identifier() -> str:
    """Return the active StudentStore owner identifier for this browser session."""
    return str(st.session_state.get("_auth_store_identifier") or "local-student")


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

    return LocalApiClient(
        str(getattr(settings, "api_base_url", "http://127.0.0.1:8000")),
        cookie_provider=_id_cookie,
    )


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


def stream_coach_turn_events(request: CoachRequest) -> Iterator[dict[str, Any]]:
    """Yield progress/token/done events for one coaching turn.

    Uses the NDJSON streaming API when ``USE_LOCAL_API`` is enabled; otherwise
    runs the in-process coach service and emits a compact token stream.
    """
    if local_api_enabled():
        yield from local_api_client().stream_coach_turn(request)
        return
    _, _, coach, _ = _resolve_resources()
    yield {
        "event": "started",
        "thread_id": request.thread_id,
        "stage": request.current_stage,
    }
    turn = coach.submit(request)
    text = turn.response_text
    chunk_size = 32
    for index in range(0, len(text), chunk_size):
        yield {"event": "token", "text": text[index : index + chunk_size]}
    yield {"event": "done", "turn": turn.model_dump(mode="json")}


class WorkspaceFacade:
    """UI persistence facade over the typed API or in-process workspace service."""

    def _service(self) -> WorkspaceService:
        _, service, _, _ = _resolve_resources()
        return service

    def _backend_store(self) -> StudentStore:
        store, _, _, _ = _resolve_resources()
        return store

    def get_user_preferences(self) -> dict[str, Any]:
        """Return local user preferences."""
        if local_api_enabled():
            return local_api_client().get_preferences()
        return self._service().get_preferences()

    def update_user_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys."""
        if local_api_enabled():
            local_api_client().update_preferences(patch)
            return
        self._service().update_preferences(patch)

    def list_threads(self, search: str = "", folder_id: str | None = None) -> list[dict]:
        """List notebooks (folder filter retained for store compatibility; unused)."""
        del folder_id
        if local_api_enabled():
            return local_api_client().list_threads(search)
        return self._service().list_threads(search)

    def get_thread(self, thread_id: str) -> dict | None:
        """Return one notebook."""
        if local_api_enabled():
            return local_api_client().get_thread(thread_id)
        return self._service().get_thread(thread_id)

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
            return str(thread["id"])
        thread = self._service().create_thread(
            name=name,
            model_id=model_id,
            support_mode=support_mode,
            assignment=assignment,
        )
        return str(thread["id"])

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
            return
        self._service().update_thread(thread_id, name=name, metadata=metadata)

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook."""
        if local_api_enabled():
            local_api_client().delete_thread(thread_id)
            return
        self._service().delete_thread(thread_id)

    def get_messages(self, thread_id: str) -> list[dict]:
        """Return chat history."""
        if local_api_enabled():
            return local_api_client().get_messages(thread_id)
        return self._service().get_messages(thread_id)

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
            return local_api_client().add_message(
                thread_id,
                MessageCreateRequest(
                    role=role, content=content, metadata=metadata or {}
                ),
            )
        return self._service().add_message(
            thread_id, role, content, metadata=metadata
        )

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict]:
        """List notebook sources without filesystem paths."""
        if local_api_enabled():
            return local_api_client().list_sources(
                thread_id, selected_only=selected_only
            )
        return self._service().list_sources(thread_id, selected_only=selected_only)

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
            return
        self._service().set_source_selected(thread_id, source_id, selected)

    def set_all_sources_selected(self, thread_id: str, selected: bool) -> None:
        """Select or deselect every source."""
        if local_api_enabled():
            local_api_client().select_all_sources(thread_id, selected)
            return
        self._service().set_all_sources_selected(thread_id, selected)

    def rename_source(self, thread_id: str, source_id: str, title: str) -> None:
        """Rename a non-locked source."""
        if local_api_enabled():
            local_api_client().update_source(
                thread_id, source_id, SourceUpdateRequest(title=title)
            )
            return
        self._service().rename_source(thread_id, source_id, title)

    def delete_source(
        self, thread_id: str, source_id: str, *, force: bool = False
    ) -> None:
        """Delete a source."""
        del force
        if local_api_enabled():
            local_api_client().delete_source(thread_id, source_id)
            return
        self._service().delete_source(thread_id, source_id)

    def upload_sources(
        self,
        thread_id: str,
        uploads: list[tuple[str, bytes, str | None]],
        *,
        origin: str = "source_panel",
    ) -> list[dict]:
        """Upload files into the source library."""
        if local_api_enabled():
            return local_api_client().upload_sources(thread_id, uploads)
        return self._service().upload_sources(thread_id, uploads, origin=origin)

    def get_source_content(self, thread_id: str, source_id: str) -> SourceContent:
        """Read source bytes for preview/download."""
        if local_api_enabled():
            return local_api_client().get_source_content(thread_id, source_id)
        return self._service().read_source_content(thread_id, source_id)

    def backfill_legacy_sources(self, thread_id: str) -> int:
        """Import legacy message attachments."""
        if local_api_enabled():
            return local_api_client().backfill_legacy_sources(thread_id)
        return self._service().backfill_legacy_sources(thread_id)

    def pending_transition(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved stage recommendation for the owned notebook."""
        if local_api_enabled():
            return local_api_client().pending_transition(thread_id)
        _, _, _, learning = _resolve_resources()
        return learning.get_pending(thread_id)

    def resolve_transition(
        self,
        thread_id: str,
        transition_id: str,
        *,
        accepted: bool,
    ) -> PendingPhaseTransition:
        """Persist the student's decision through the active application path."""
        if local_api_enabled():
            return local_api_client().resolve_transition(
                thread_id,
                transition_id,
                accepted,
            )
        _, _, _, learning = _resolve_resources()
        return learning.resolve(thread_id, transition_id, accepted)

    def request_course_material_sync(self, thread_id: str):
        """Start or join course-material sync for the active notebook.

        API-mode sessions (including Cognito) sync through FastAPI so ownership
        stays on the authenticated application user.
        """
        if local_api_enabled():
            api_base = str(getattr(settings, "api_base_url", "http://127.0.0.1:8000"))

            def _sync_via_api() -> LectureNotesSyncResult:
                payload = local_api_client().sync_course_materials(thread_id)
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


store = WorkspaceFacade()


def rerun() -> None:
    st.rerun()
