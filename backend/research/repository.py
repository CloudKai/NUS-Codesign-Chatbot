"""Narrow repository port and StudentStore adapter for research persistence."""

from __future__ import annotations

from typing import Any, Protocol

from backend.student_store import StudentStore

from .models import (
    ResearchAccessEvent,
    ResearchAccessEventCreate,
    ResearchAdjudication,
    ResearchAdjudicationCreate,
    ResearchObservation,
    ResearchReview,
    ResearchReviewCreate,
)


class ResearchRepository(Protocol):
    """Read coded observations and append human/audit decisions."""

    def list_observations(
        self,
        *,
        notebook_id: str | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResearchObservation]: ...

    def get_observation(
        self, observation_id: str, *, active_only: bool = True
    ) -> ResearchObservation | None: ...

    def append_review(self, value: ResearchReviewCreate) -> ResearchReview: ...

    def list_reviews(self, observation_id: str) -> list[ResearchReview]: ...

    def append_adjudication(
        self, value: ResearchAdjudicationCreate
    ) -> ResearchAdjudication: ...

    def list_adjudications(
        self, observation_id: str
    ) -> list[ResearchAdjudication]: ...

    def record_access_event(
        self, value: ResearchAccessEventCreate
    ) -> ResearchAccessEvent: ...

    def get_system_metadata(self, key: str) -> dict[str, Any] | None: ...

    def set_system_metadata(self, key: str, value: dict[str, Any]) -> None: ...

    def research_workflow_contract_ready(self) -> bool: ...


class StudentStoreResearchRepository:
    """Typed adapter over SQLite or DSQL StudentStore research methods."""

    def __init__(self, store: StudentStore) -> None:
        self._store = store

    def list_observations(
        self,
        *,
        notebook_id: str | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResearchObservation]:
        return [
            ResearchObservation.model_validate(item)
            for item in self._store.list_research_observations(
                notebook_id=notebook_id,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        ]

    def get_observation(
        self, observation_id: str, *, active_only: bool = True
    ) -> ResearchObservation | None:
        item = self._store.get_research_observation(
            observation_id, active_only=active_only
        )
        return ResearchObservation.model_validate(item) if item else None

    def append_review(self, value: ResearchReviewCreate) -> ResearchReview:
        return ResearchReview.model_validate(
            self._store.append_research_review(value.model_dump(mode="json"))
        )

    def list_reviews(self, observation_id: str) -> list[ResearchReview]:
        return [
            ResearchReview.model_validate(item)
            for item in self._store.list_research_reviews(observation_id)
        ]

    def append_adjudication(
        self, value: ResearchAdjudicationCreate
    ) -> ResearchAdjudication:
        return ResearchAdjudication.model_validate(
            self._store.append_research_adjudication(value.model_dump(mode="json"))
        )

    def list_adjudications(
        self, observation_id: str
    ) -> list[ResearchAdjudication]:
        return [
            ResearchAdjudication.model_validate(item)
            for item in self._store.list_research_adjudications(observation_id)
        ]

    def record_access_event(
        self, value: ResearchAccessEventCreate
    ) -> ResearchAccessEvent:
        return ResearchAccessEvent.model_validate(
            self._store.record_research_access_event(value.model_dump(mode="json"))
        )

    def get_system_metadata(self, key: str) -> dict[str, Any] | None:
        return self._store.get_system_metadata(key)

    def set_system_metadata(self, key: str, value: dict[str, Any]) -> None:
        self._store.set_system_metadata(key, value)

    def research_workflow_contract_ready(self) -> bool:
        return self._store.research_workflow_contract_ready()
