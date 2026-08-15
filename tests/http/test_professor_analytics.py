"""Deterministic coverage for the read-only professor analytics boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.persistence.factory import reset_file_storage_cache
from backend.professor_analytics.repository import ProfessorAnalyticsRepository
from backend.professor_analytics.service import ProfessorAnalyticsService
from backend.settings import settings
from backend.student_store import StudentStore


class FakeOIDC(CognitoOIDCClient):
    """No-network identity verifier used to exercise the real role boundary."""

    def __init__(self, store: StudentStore) -> None:
        super().__init__(
            CognitoAuthConfig(
                client_id="test", client_secret="secret",
                server_metadata_url="https://example.test/meta",
                redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
            ),
            store=store,
        )
        self.identities: dict[str, CognitoIdentity] = {}

    def add(self, sub: str) -> str:
        token = f"token-{sub}"
        self.identities[token] = CognitoIdentity(
            sub=sub, email=f"{sub}@example.edu", claims={"sub": sub, "email": f"{sub}@example.edu", "given_name": sub},
        )
        return token

    def verify_id_token(self, token: str) -> CognitoIdentity:
        if token not in self.identities:
            raise CognitoOIDCError("invalid")
        return self.identities[token]


def _seed_user(store: StudentStore, sub: str, role: str) -> dict:
    user = store.upsert_cognito_user(
        cognito_sub=sub, identifier=f"cognito:{sub}", email=f"{sub}@example.edu", display_name=sub.title(),
    )
    with store._connect() as connection:  # noqa: SLF001 - deterministic fixture setup
        connection.execute("UPDATE users SET role=? WHERE id=?", (role, user["id"]))
    return store.get_user_by_id(user["id"]) or {}


def _assessment(**scores: int) -> dict:
    return {"facione_scores": {key: scores.get(key, 0) for key in ("analysis", "interpretation", "inference", "evaluation", "explanation", "self_regulation")}, "current_stage": "concept_generation"}


def _seed_student_activity(store: StudentStore, *, sub: str, now: datetime, messages: int = 2) -> str:
    profile = _seed_user(store, sub, "student")
    student_store = StudentStore(Path(store.path), identifier=f"cognito:{sub}")
    thread = student_store.create_thread(name=f"{sub} notebook", model_id="mock", support_mode="critical-thinking")
    for index in range(messages):
        student_store.add_message(thread, "user", f"Student idea {index + 1}")
        student_store.add_message(thread, "assistant", "Coach reply", metadata={"assessment": _assessment(analysis=3, interpretation=2, inference=3, evaluation=2)})
    # Timestamp all active messages deterministically; earlier than 30 minutes
    # keeps the fixture as one estimated activity session.
    with store._connect() as connection:  # noqa: SLF001
        for index, row in enumerate(connection.execute("SELECT id FROM messages WHERE notebook_id=? ORDER BY created_at, id", (thread,)).fetchall()):
            stamp = (now - timedelta(minutes=(messages * 2 - index))).isoformat()
            connection.execute("UPDATE messages SET created_at=? WHERE id=?", (stamp, row["id"]))
    return str(profile["id"])


def _setup(tmp_path):
    db = tmp_path / "analytics.sqlite3"
    bootstrap = StudentStore(db, identifier="local-student")
    professor = _seed_user(bootstrap, "prof", "lecturer")
    student = _seed_student_activity(bootstrap, sub="student-a", now=datetime.now(timezone.utc), messages=2)
    oidc = FakeOIDC(bootstrap)
    return bootstrap, professor, student, oidc


def test_professor_routes_enforce_authentication_and_persisted_role(tmp_path, monkeypatch):
    """Normal students cannot retrieve class data even when calling URLs directly."""
    bootstrap, _professor, _student, oidc = _setup(tmp_path)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    assert client.get("/api/v1/professor/overview").status_code == 401
    student_token = oidc.add("student-a")
    assert client.get("/api/v1/professor/overview", cookies={settings.cognito_id_token_cookie_name: student_token}).status_code == 403
    professor_token = oidc.add("prof")
    response = client.get("/api/v1/professor/overview", cookies={settings.cognito_id_token_cookie_name: professor_token})
    assert response.status_code == 200
    assert response.json()["students"] == 1


def test_analytics_uses_active_branch_assessments_and_session_boundaries(tmp_path):
    """Aggregates exclude revision-superseded turns and split long message gaps."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    service = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap), now=datetime.now(timezone.utc)
    )
    detail = service.student_detail(student_id)
    assert detail is not None
    assert detail.student.facione_overall == 2.5
    assert detail.engagement["sessions"] == 1
    assert detail.engagement["estimated_active_minutes"] == 5
    assert detail.engagement["active_days"] == 1

    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    thread = student_store.list_threads()[0]["id"]
    original = student_store.get_messages(thread)[0]
    student_store.revise_conversation_from_user_message(thread, original["id"], "Revised thought")
    after_revision = service.student_detail(student_id)
    assert after_revision is not None
    transcript = service.conversation_transcript(student_id, thread)
    assert transcript is not None
    assert all(message["content"] != original["content"] for message in transcript.messages)


def test_normal_idempotency_metadata_is_not_filtered_as_internal(tmp_path):
    """Normal API turns remain visible when they carry an idempotency key."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    thread = student_store.list_threads()[0]["id"]
    student_store.add_message(
        thread, "user", "A retry-safe contribution",
        metadata={"coach_idempotency_key": "request-1"},
    )
    student_store.add_message(
        thread, "assistant", "A retry-safe response",
        metadata={
            "coach_idempotency_key": "request-1",
            "assessment": _assessment(analysis=4, evaluation=3),
        },
    )
    detail = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap), now=datetime.now(timezone.utc)
    ).student_detail(student_id)
    assert detail is not None
    assert detail.student.student_messages == 3
    assert detail.student.facione_overall == 3.5


def test_conversations_sessions_primary_assessment_and_not_started_are_truthful(tmp_path):
    """Multi-notebook metrics keep notebook scopes separate and count starts."""
    now = datetime.now(timezone.utc)
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    newer = student_store.create_thread(
        name="New discussion", model_id="mock", support_mode="critical-thinking"
    )
    student_store.add_message(newer, "user", "New problem framing")
    student_store.add_message(
        newer, "assistant", "New coaching",
        metadata={"assessment": _assessment(analysis=1, evaluation=1)},
    )
    with bootstrap._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE messages SET created_at=? WHERE notebook_id<>?",
            ((now - timedelta(hours=1)).isoformat(), newer),
        )
        newer_rows = connection.execute(
            "SELECT id, role FROM messages WHERE notebook_id=? ORDER BY created_at, id",
            (newer,),
        ).fetchall()
        for index, row in enumerate(newer_rows):
            connection.execute(
                "UPDATE messages SET created_at=? WHERE id=?",
                ((now - timedelta(minutes=2 - index)).isoformat(), row["id"]),
            )
    unstarted = _seed_user(bootstrap, "no-work", "student")
    service = ProfessorAnalyticsService(ProfessorAnalyticsRepository(bootstrap), now=now)
    overview = service.overview()
    detail = service.student_detail(student_id)
    assert detail is not None
    assert overview.total_conversations == 2
    assert detail.student.facione_overall == 1.0
    assert detail.engagement["sessions"] == 2
    assert sum(item.count for item in overview.stage_distribution) == overview.students
    assert service.student_detail(str(unstarted["id"])).student.current_stage is None


def test_no_activity_waits_for_inactivity_window(tmp_path):
    """A newly provisioned student is not immediately marked for follow-up."""
    now = datetime.now(timezone.utc)
    bootstrap, _professor, _student, _oidc = _setup(tmp_path)
    profile = _seed_user(bootstrap, "new-student", "student")
    service = ProfessorAnalyticsService(ProfessorAnalyticsRepository(bootstrap), now=now)
    row = next(item for item in service.students().students if item.id == profile["id"])
    assert not any(signal.code == "inactive" for signal in row.needs_attention)
    with bootstrap._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE users SET created_at=? WHERE id=?",
            ((now - timedelta(days=8)).isoformat(), profile["id"]),
        )
    row = next(item for item in service.students().students if item.id == profile["id"])
    assert any(signal.code == "inactive" for signal in row.needs_attention)


def test_overview_handles_missing_assessments_and_uses_one_batch_query(tmp_path):
    """No assessment becomes null, and roster size does not cause N+1 reads."""
    bootstrap, _professor, _student, _oidc = _setup(tmp_path)
    _seed_user(bootstrap, "unassessed", "student")

    class TrackingStore(StudentStore):
        connections = 0

        def _connect(self):
            type(self).connections += 1
            return super()._connect()

    tracking = TrackingStore(Path(bootstrap.path), identifier="local-student")
    TrackingStore.connections = 0
    result = ProfessorAnalyticsService(ProfessorAnalyticsRepository(tracking)).overview()
    assert result.median_facione.value == 2.5
    assert result.facione_profile["Self-Regulation"].value is None
    assert TrackingStore.connections == 1


def test_professor_endpoints_are_read_only(tmp_path, monkeypatch):
    """Analytics requests create no notebook, message, or learning-state rows."""
    bootstrap, _professor, _student, oidc = _setup(tmp_path)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    with bootstrap._connect() as connection:  # noqa: SLF001
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notebooks", "messages", "sources")
        }
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    token = oidc.add("prof")
    for path in ("overview", "students", "critical-thinking", "engagement"):
        assert client.get(f"/api/v1/professor/{path}", cookies={settings.cognito_id_token_cookie_name: token}).status_code == 200
    with bootstrap._connect() as connection:  # noqa: SLF001
        after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notebooks", "messages", "sources")
        }
    assert after == before
    reset_file_storage_cache()
