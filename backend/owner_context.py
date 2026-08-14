"""Resolve the authenticated notebook owner for FastAPI application requests.

Production application traffic must never trust a client-supplied ``user_id``.
Ownership is derived only from a verified Cognito ID-token cookie (``sub`` →
application user → owner-scoped ``StudentStore``). Local/mock demos without
Cognito may fall back to the process default ``local-student`` store.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from backend.application import CoachApplicationService
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.auth_profiles import store_identifier_for_sub, sync_authenticated_user
from backend.bedrock_retrieve import configured_context_retriever
from backend.learning_service import LearningProgressService
from backend.persistence.factory import create_student_store
from backend.providers import configured_coach_provider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.source_library import CourseMaterialSyncCoordinator
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from backend.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OwnerServices:
    """Owner-scoped application services for one authenticated (or local) user."""

    store: StudentStore
    workspace: WorkspaceService
    coach: CoachApplicationService
    learning: LearningProgressService
    workflow: CoachWorkflow
    transitions: SQLitePhaseTransitionRepository
    identifier: str
    user_id: str


class OwnerResolver:
    """Build and cache owner-scoped services from Cognito cookies or local default."""

    def __init__(
        self,
        default_store: StudentStore,
        *,
        oidc: CognitoOIDCClient,
        course_sync: CourseMaterialSyncCoordinator,
        auto_advance_stages: bool,
    ) -> None:
        self._default_store = default_store
        self._oidc = oidc
        self._course_sync = course_sync
        self._auto_advance_stages = auto_advance_stages
        self._cache: dict[str, OwnerServices] = {}
        self._lock = threading.Lock()
        # Seed cache with the process default (local-student / injected test store).
        self._cache[default_store.identifier] = self._build_services(default_store)

    @property
    def default_store(self) -> StudentStore:
        """Return the bootstrap/default store used by auth and local demo paths."""
        return self._default_store

    def resolve(self, request: Request) -> OwnerServices:
        """Return owner-scoped services for *request*.

        Verified Cognito ``sub`` always wins. Client headers/query parameters such
        as ``user_id`` / ``X-User-Id`` are intentionally ignored.
        """
        # Defense in depth: never consult spoofable identity inputs.
        _ignore_client_identity(request)

        id_token = str(
            request.cookies.get(settings.cognito_id_token_cookie_name) or ""
        ).strip()
        if id_token:
            try:
                identity = self._oidc.verify_id_token(id_token)
            except CognitoOIDCError as error:
                logger.info("Rejected application request with invalid ID token")
                raise HTTPException(
                    status_code=401, detail="Not authenticated"
                ) from error
            return self._services_for_identity(identity)

        if self.requires_authenticated_owner():
            raise HTTPException(status_code=401, detail="Not authenticated")
        return self._cached(self._default_store.identifier)

    def requires_authenticated_owner(self) -> bool:
        """Return whether anonymous ``local-student`` fallback is forbidden.

        Aurora DSQL and student-upload S3 deployments must never share one
        production owner. Local SQLite + local/memory files keep the demo path.
        """
        return settings.database_provider == "dsql" or (
            settings.file_storage_provider == "s3"
        )

    def _services_for_identity(self, identity: CognitoIdentity) -> OwnerServices:
        """Map a verified Cognito identity onto an owner-scoped store."""
        identifier = store_identifier_for_sub(identity.sub)
        with self._lock:
            cached = self._cache.get(identifier)
            if cached is not None:
                return cached

        # Prefer lookup on the shared DB via the bootstrap store; sync when new.
        user = self._default_store.get_user_by_cognito_sub(identity.sub)
        if user is None:
            profile = sync_authenticated_user(
                identity.claims, store=self._default_store
            )
            user_id = profile.user_id
        else:
            user_id = str(user.get("id") or "")

        store = self._store_for_identifier(identifier)
        services = self._build_services(store, user_id=user_id)
        with self._lock:
            self._cache[identifier] = services
        return services

    def _store_for_identifier(self, identifier: str) -> StudentStore:
        """Return a StudentStore bound to *identifier*, sharing the default DB."""
        if identifier == self._default_store.identifier:
            return self._default_store
        path = getattr(self._default_store, "path", None)
        if isinstance(path, Path) and path is not None:
            return create_student_store(path=path, identifier=identifier)
        # DSQL / pathless: each identifier gets its own owner-scoped adapter.
        return create_student_store(identifier=identifier)

    def _build_services(
        self,
        store: StudentStore,
        *,
        user_id: str | None = None,
    ) -> OwnerServices:
        """Wire application services against one owner-scoped store."""
        workspace = WorkspaceService(store, self._course_sync)
        notebooks = SQLiteNotebookRepository(store)
        transitions = SQLitePhaseTransitionRepository(store)
        workflow = CoachWorkflow(configured_coach_provider(), transitions)
        learning = LearningProgressService(store, notebooks, transitions)
        coach = CoachApplicationService(
            store,
            notebooks,
            workflow,
            learning,
            auto_advance_stages=self._auto_advance_stages
            and not settings.student_stage_selection,
            retriever=configured_context_retriever(),
        )
        resolved_user_id = str(user_id or getattr(store, "owner_id", "") or "")
        return OwnerServices(
            store=store,
            workspace=workspace,
            coach=coach,
            learning=learning,
            workflow=workflow,
            transitions=transitions,
            identifier=str(store.identifier),
            user_id=resolved_user_id,
        )

    def _cached(self, identifier: str) -> OwnerServices:
        with self._lock:
            return self._cache[identifier]


def _ignore_client_identity(request: Request) -> None:
    """Document that client-supplied identity inputs are never trusted.

    Values are read only so static analysis and tests can prove they are not
    used for ownership decisions.
    """
    _unused: list[Any] = [
        request.headers.get("x-user-id"),
        request.headers.get("x-owner-id"),
        request.query_params.get("user_id"),
        request.query_params.get("owner_id"),
        request.query_params.get("identifier"),
    ]
    del _unused
