"""Deterministic API and service contracts for professor research review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.api as api_module
from backend.api import create_app
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.professor_analytics.research import (
    ProfessorResearchService,
    ResearchReviewRequest,
)
from backend.research.models import (
    ResearchAccessEvent,
    ResearchAccessEventCreate,
    ResearchAdjudication,
    ResearchAdjudicationCreate,
    ResearchEvidenceSpan,
    ResearchObservation,
    ResearchReview,
    ResearchReviewCreate,
)
from backend.settings import settings
from backend.student_store import StudentStore


def _observation(
    *,
    notebook_id: str = "notebook-1",
    student_user_id: str = "student-1",
    student_name: str = "Student One",
) -> ResearchObservation:
    """Return one fully typed automated observation."""
    return ResearchObservation(
        id="observation-1",
        notebook_id=notebook_id,
        student_user_id=student_user_id,
        student_display_name=student_name,
        user_message_id="user-message-1",
        assistant_message_id="assistant-message-1",
        conversation_revision=0,
        coding_status="coded",
        dominant_clear="explicit",
        facione_behaviors=["analysis"],
        ethics_concepts=["fairness"],
        evidence=[
            ResearchEvidenceSpan(
                start_offset=0,
                end_offset=5,
                rationale="The student explicitly identifies a constraint.",
                confidence=0.8,
            )
        ],
        coding_version="research-v1",
        prompt_version="prompt-v1",
        provider="mock",
        model_id="mock",
        coaching_profile="quick",
        phase_id="problem_identification",
        created_at="2026-08-14T01:00:00+00:00",
    )


class FakeResearchRepository:
    """In-memory typed repository that records call order for fail-closed tests."""

    def __init__(self, observation: ResearchObservation | None = None) -> None:
        self.observation = observation or _observation()
        self.audit_events: list[ResearchAccessEventCreate] = []
        self.list_calls = 0
        self.fail_audit = False
        self.reviews: list[ResearchReview] = []
        self.adjudications: list[ResearchAdjudication] = []

    def list_observations(self, **kwargs: Any) -> list[ResearchObservation]:
        self.list_calls += 1
        notebook_id = kwargs.get("notebook_id")
        return [self.observation] if not notebook_id or notebook_id == self.observation.notebook_id else []

    def get_observation(self, observation_id: str, **_kwargs: Any):
        return self.observation if observation_id == self.observation.id else None

    def append_review(self, value: ResearchReviewCreate) -> ResearchReview:
        review = ResearchReview(
            **value.model_dump(), id=f"review-{len(self.reviews) + 1}",
            created_at="2026-08-14T02:00:00+00:00",
        )
        self.reviews.append(review)
        return review

    def list_reviews(self, observation_id: str) -> list[ResearchReview]:
        return [item for item in self.reviews if item.observation_id == observation_id]

    def append_adjudication(
        self, value: ResearchAdjudicationCreate
    ) -> ResearchAdjudication:
        item = ResearchAdjudication(
            **value.model_dump(), id="adjudication-1",
            created_at="2026-08-14T03:00:00+00:00",
        )
        self.adjudications.append(item)
        return item

    def list_adjudications(self, observation_id: str) -> list[ResearchAdjudication]:
        return [item for item in self.adjudications if item.observation_id == observation_id]

    def record_access_event(
        self, value: ResearchAccessEventCreate
    ) -> ResearchAccessEvent:
        if self.fail_audit:
            raise RuntimeError("private database detail")
        self.audit_events.append(value)
        return ResearchAccessEvent(
            **value.model_dump(), id=f"audit-{len(self.audit_events)}",
            created_at="2026-08-14T01:30:00+00:00",
        )


def test_identifiable_queue_and_detail_fail_closed_before_read() -> None:
    """An audit insertion failure prevents every identifiable repository read."""
    repository = FakeResearchRepository()
    repository.fail_audit = True
    service = ProfessorResearchService(repository)

    with pytest.raises(RuntimeError, match="private database detail"):
        service.queue(
            actor_user_id="lecturer-1",
            actor_role="lecturer",
            request_id="request-1",
            coding_status=None,
            phase=None,
            search="",
            limit=25,
            offset=0,
        )
    assert repository.list_calls == 0

    with pytest.raises(RuntimeError, match="private database detail"):
        service.notebook_detail(
            "notebook-1",
            actor_user_id="lecturer-1",
            actor_role="lecturer",
            request_id="request-2",
            transcript_loader=lambda *_args: pytest.fail("transcript must not load"),
        )
    assert repository.list_calls == 0

    with pytest.raises(RuntimeError, match="private database detail"):
        service.export_csv(
            actor_user_id="lecturer-1",
            actor_role="lecturer",
            request_id="request-3",
            coding_status=None,
            phase=None,
        )
    assert repository.list_calls == 0


def test_reviewer_identity_is_server_supplied_and_csv_is_formula_safe() -> None:
    """Payloads cannot spoof staff identity and exported cells cannot execute."""
    repository = FakeResearchRepository(
        _observation(student_name="=HYPERLINK(\"https://invalid\")")
    )
    service = ProfessorResearchService(repository)
    review = service.submit_review(
        ResearchReviewRequest(
            observation_id="observation-1",
            status="confirmed",
            notes="Evidence supports the provisional code.",
        ),
        reviewer_user_id="persisted-lecturer-id",
    )
    assert review.reviewer_user_id == "persisted-lecturer-id"

    exported = service.export_csv(
        actor_user_id="persisted-lecturer-id",
        actor_role="lecturer",
        request_id="request-export",
        coding_status="coded",
        phase=None,
    )
    assert "'=HYPERLINK" in exported
    assert repository.audit_events[-1].action == "research.export"
    assert repository.audit_events[-1].request_id == "request-export"


class FakeOIDC(CognitoOIDCClient):
    """No-network verified identity source for the real professor dependency."""

    def __init__(self, store: StudentStore) -> None:
        super().__init__(
            CognitoAuthConfig(
                client_id="test",
                client_secret="secret",
                server_metadata_url="https://example.test/meta",
                redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
            ),
            store=store,
        )
        self.identities: dict[str, CognitoIdentity] = {}

    def token(self, sub: str) -> str:
        value = f"token-{sub}"
        self.identities[value] = CognitoIdentity(
            sub=sub,
            email=f"{sub}@example.edu",
            claims={"sub": sub, "email": f"{sub}@example.edu"},
        )
        return value

    def verify_id_token(self, token: str) -> CognitoIdentity:
        try:
            return self.identities[token]
        except KeyError as error:
            raise CognitoOIDCError("invalid") from error


def _staff_api(tmp_path: Path, monkeypatch):
    store = StudentStore(tmp_path / "research-api.sqlite3", identifier="local-student")
    learner_profile: dict[str, Any] = {}
    for sub, role in (("staff", "lecturer"), ("learner", "student")):
        profile = store.upsert_cognito_user(
            cognito_sub=sub,
            identifier=f"cognito:{sub}",
            email=f"{sub}@example.edu",
            display_name=sub.title(),
        )
        with store._connect() as connection:  # noqa: SLF001 - fixture role setup
            connection.execute("UPDATE users SET role=? WHERE id=?", (role, profile["id"]))
        if sub == "learner":
            learner_profile = profile
    learner_store = StudentStore(
        Path(store.path), identifier="cognito:learner"
    )
    notebook_id = learner_store.create_thread(
        name="Research notebook", model_id="mock", support_mode="critical-thinking"
    )
    learner_store.add_message(notebook_id, "user", "A student utterance")
    learner_store.add_message(notebook_id, "assistant", "A coaching response")
    oidc = FakeOIDC(store)
    repository = FakeResearchRepository(
        _observation(
            notebook_id=notebook_id,
            student_user_id=str(learner_profile["id"]),
            student_name="Learner",
        )
    )
    monkeypatch.setattr(
        api_module, "StudentStoreResearchRepository", lambda _store: repository
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    return TestClient(create_app(store, oidc_client=oidc)), oidc, repository


def test_research_api_requires_persisted_staff_role_and_sanitizes_audit_failure(
    tmp_path, monkeypatch
) -> None:
    """Students receive 403 and audit failures return a privacy-safe 503."""
    client, oidc, repository = _staff_api(tmp_path, monkeypatch)
    cookie = settings.cognito_id_token_cookie_name
    assert client.get("/api/v1/professor/research/summary").status_code == 401
    assert client.get(
        "/api/v1/professor/research/summary",
        cookies={cookie: oidc.token("learner")},
    ).status_code == 403
    staff_cookie = {cookie: oidc.token("staff")}
    summary = client.get(
        "/api/v1/professor/research/summary", cookies=staff_cookie
    )
    assert summary.status_code == 200
    summary_body = summary.json()
    assert "not grades" in summary_body["co_occurrence_note"]
    assert any(
        item["left"] == "analysis" and item["right"] == "explicit"
        for item in summary_body["co_occurrence"]
    )
    queue = client.get(
        "/api/v1/professor/research/queue?limit=1", cookies=staff_cookie
    )
    assert queue.status_code == 200
    assert queue.json()["items"][0]["observation_id"] == "observation-1"
    assert repository.audit_events[-1].actor_user_id != "learner"
    notebook_id = repository.observation.notebook_id
    detail = client.get(
        f"/api/v1/professor/research/notebooks/{notebook_id}",
        cookies=staff_cookie,
    )
    assert detail.status_code == 200
    assert detail.json()["transcript"][0]["content"] == "A student utterance"
    assert repository.audit_events[-1].action == "research.detail"
    review = client.post(
        "/api/v1/professor/research/reviews",
        cookies=staff_cookie,
        json={
            "observation_id": "observation-1",
            "status": "confirmed",
            "notes": "The evidence supports this code.",
        },
    )
    assert review.status_code == 201
    assert review.json()["reviewer_user_id"] == repository.audit_events[0].actor_user_id
    invalid_code = client.post(
        "/api/v1/professor/research/reviews",
        cookies=staff_cookie,
        json={
            "observation_id": "observation-1",
            "status": "amended",
            "coding_status": "coded",
            "dominant_clear": "invented-code",
            "notes": "This should be rejected at the typed API boundary.",
        },
    )
    assert invalid_code.status_code == 422
    exported = client.get(
        "/api/v1/professor/research/export.csv", cookies=staff_cookie
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "observation_id" in exported.text

    repository.fail_audit = True
    failed = client.get(
        "/api/v1/professor/research/queue", cookies=staff_cookie
    )
    assert failed.status_code == 503
    assert failed.json() == {
        "detail": "Professor research data is temporarily unavailable"
    }
    assert "private database detail" not in failed.text
