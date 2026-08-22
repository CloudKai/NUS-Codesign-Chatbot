"""Deterministic coverage for the read-only professor analytics boundary."""

from __future__ import annotations

import json
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
from backend.workspace_service import WorkspaceService
from backend.source_library import add_text_source


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


_FORBIDDEN_WORKSPACE_KEYS = frozenset({
    "extractedText",
    "extracted_text",
    "path",
    "object_key",
    "local_path",
    "extracted_text_key",
})


def _assert_no_forbidden_workspace_fields(value: object, *, path: str = "workspace") -> None:
    """Recursively reject data-minimization leaks in professor workspace JSON."""
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in _FORBIDDEN_WORKSPACE_KEYS, f"{path}.{key}"
            _assert_no_forbidden_workspace_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_workspace_fields(child, path=f"{path}[{index}]")


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


def test_identifiable_professor_reads_audit_before_returning_data(tmp_path, monkeypatch):
    """Each ordinary identifiable analytics read writes an attributable event."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    headers = {"x-request-id": "analytics-read-1"}

    requests = (
        ("/api/v1/professor/overview", "professor.overview"),
        ("/api/v1/professor/students?search=student", "professor.students"),
        (f"/api/v1/professor/students/{student_id}", "professor.student_detail"),
        (
            f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}",
            "professor.transcript",
        ),
        ("/api/v1/professor/engagement", "professor.engagement"),
    )
    for path, _action in requests:
        assert client.get(path, cookies=cookies, headers=headers).status_code == 200

    with bootstrap._connect() as connection:  # noqa: SLF001 - audit assertion
        rows = connection.execute(
            "SELECT action, actor_user_id, request_id, target_user_id, notebook_id, filters_text "
            "FROM research_access_events ORDER BY created_at, id"
        ).fetchall()
    assert [row["action"] for row in rows] == [action for _, action in requests]
    assert all(row["actor_user_id"] for row in rows)
    assert all(row["request_id"] == "analytics-read-1" for row in rows)
    assert rows[1]["filters_text"] and "student" in rows[1]["filters_text"]
    assert rows[2]["target_user_id"] == student_id
    assert rows[3]["target_user_id"] == student_id
    assert rows[3]["notebook_id"] == notebook_id


def test_professor_read_fails_closed_when_access_audit_fails(tmp_path, monkeypatch):
    """An audit persistence error prevents the identifiable query."""
    bootstrap, _professor, _student_id, oidc = _setup(tmp_path)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    def fail_audit(_value):
        raise RuntimeError("audit database unavailable")

    monkeypatch.setattr(StudentStore, "record_research_access_event", fail_audit)
    monkeypatch.setattr(
        ProfessorAnalyticsRepository,
        "load_class_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("analytics read occurred before audit")
        ),
    )
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    response = client.get(
        "/api/v1/professor/overview",
        cookies={settings.cognito_id_token_cookie_name: oidc.add("prof")},
    )
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Professor analytics is temporarily unavailable"
    }


def test_selected_student_detail_uses_scoped_rows_and_compact_benchmark(tmp_path):
    """Detail does not rebuild detailed notebook rows for the whole class."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)

    class TrackingRepository(ProfessorAnalyticsRepository):
        calls: list[tuple[str, dict]] = []

        def load_student_roster_row(self, selected_id):
            self.calls.append(("profile", {"student_id": selected_id}))
            return super().load_student_roster_row(selected_id)

        def load_student_notebook_summaries(self, selected_id):
            self.calls.append(("notebooks", {"student_id": selected_id}))
            return super().load_student_notebook_summaries(selected_id)

        def load_student_activity_rows(self, selected_id):
            self.calls.append(("activity", {"student_id": selected_id}))
            return super().load_student_activity_rows(selected_id)

        def load_class_benchmark_rows(self):
            self.calls.append(("benchmark", {}))
            return super().load_class_benchmark_rows()

    repository = TrackingRepository(bootstrap)
    detail = ProfessorAnalyticsService(repository).student_detail(student_id)
    assert detail is not None
    assert repository.calls[0] == ("profile", {"student_id": student_id})
    assert ("notebooks", {"student_id": student_id}) in repository.calls
    assert ("activity", {"student_id": student_id}) in repository.calls
    assert ("benchmark", {}) in repository.calls


def test_multiple_notebooks_detail_lists_all_but_transcript_scopes_one(tmp_path):
    """Selecting notebook B never hydrates notebook A's transcript content."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_a = student_store.list_threads()[0]["id"]
    notebook_b = student_store.create_thread(
        name="Notebook B", model_id="mock", support_mode="critical-thinking"
    )
    student_store.add_message(notebook_b, "user", "Only notebook B")
    detail = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).student_detail(student_id)
    assert detail is not None
    assert {item["id"] for item in detail.notebooks} == {notebook_a, notebook_b}
    transcript = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).conversation_transcript(student_id, notebook_b)
    assert transcript is not None
    assert any(message["content"] == "Only notebook B" for message in transcript.messages)
    assert all(message["content"] != "Student idea 1" for message in transcript.messages)


def test_transcript_projection_includes_safe_message_attachment_metadata(tmp_path):
    """Transcript attachment descriptors stay message-associated and path-free."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    attachment = WorkspaceService(student_store).upload_attachments(
        notebook_id, [("private.txt", b"private", "text/plain")]
    )[0]
    student_store.add_message(
        notebook_id,
        "user",
        "Here is my private file.",
        metadata={"attachments": [attachment], "attachment_source_ids": [attachment["id"]]},
    )
    transcript = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).conversation_transcript(student_id, notebook_id)
    assert transcript is not None
    descriptor = transcript.messages[-1]["attachments"][0]
    assert descriptor["title"] == "private.txt"
    assert "path" not in descriptor
    assert "object_key" not in descriptor


def test_transcript_normalizes_and_authorizes_current_citation_refs(tmp_path):
    """Current dict source refs and legacy ids are safe, notebook-scoped citations."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    source = add_text_source(student_store, notebook_id, "Lecture source", "Evidence")
    with bootstrap._connect() as connection:  # noqa: SLF001
        assistant = connection.execute(
            "SELECT id FROM messages WHERE notebook_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1",
            (notebook_id,),
        ).fetchone()
        connection.execute(
            "UPDATE messages SET cited_source_ids_text=? WHERE id=?",
            (
                json.dumps([
                    {"id": source["id"], "label": "S1", "title": "Lecture source"},
                    {"id": "foreign-source", "label": "S9", "title": "Private"},
                    "legacy-source",
                ]),
                assistant["id"],
            ),
        )
    transcript = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).conversation_transcript(student_id, notebook_id)
    assert transcript is not None
    citations = transcript.messages[-1]["citations"]
    assert citations == [{"id": source["id"], "label": "S1", "title": "Lecture source"}]


def test_professor_attachment_route_requires_message_association(tmp_path, monkeypatch):
    """Lecturers can open only the selected student's message attachment."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    attachment = WorkspaceService(student_store).upload_attachments(
        notebook_id, [("private.txt", b"private", "text/plain")]
    )[0]
    student_store.add_message(
        notebook_id,
        "user",
        "Attached.",
        metadata={"attachments": [attachment]},
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    token = oidc.add("prof")
    cookies = {settings.cognito_id_token_cookie_name: token}
    response = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/attachments/{attachment['id']}",
        cookies=cookies,
    )
    assert response.status_code == 200
    assert response.content == b"private"
    with bootstrap._connect() as connection:  # noqa: SLF001 - audit assertion
        audit = connection.execute(
            "SELECT action, target_user_id, notebook_id, metadata_text FROM research_access_events "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    assert audit["action"] == "professor.attachment"
    assert audit["target_user_id"] == student_id
    assert audit["notebook_id"] == notebook_id
    assert attachment["id"] in audit["metadata_text"]
    ordinary = add_text_source(student_store, notebook_id, "Reusable source", "Not an attachment")
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/attachments/{ordinary['id']}",
        cookies=cookies,
    ).status_code == 404
    other_student_id = _seed_student_activity(
        bootstrap, sub="student-b", now=datetime.now(timezone.utc), messages=1
    )
    other_notebook_id = StudentStore(
        Path(bootstrap.path), identifier="cognito:student-b"
    ).list_threads()[0]["id"]
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{other_notebook_id}/attachments/{attachment['id']}",
        cookies=cookies,
    ).status_code == 404
    assert client.get(
        f"/api/v1/professor/students/{other_student_id}/conversations/{notebook_id}/attachments/{attachment['id']}",
        cookies=cookies,
    ).status_code == 404
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/attachments/not-related",
        cookies=cookies,
    ).status_code == 404


def test_professor_workspace_returns_read_only_payload(tmp_path, monkeypatch):
    """Workspace bundles transcript, library sources, and learning projections."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    library_source = WorkspaceService(student_store).upload_sources(
        notebook_id, [("lecture.txt", b"Evidence", "text/plain")]
    )[0]
    attachment = WorkspaceService(student_store).upload_attachments(
        notebook_id, [("private.txt", b"private", "text/plain")]
    )[0]
    student_store.add_message(
        notebook_id,
        "user",
        "Attached.",
        metadata={"attachments": [attachment]},
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    token = oidc.add("prof")
    cookies = {settings.cognito_id_token_cookie_name: token}
    response = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/workspace",
        cookies=cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["notebook"]["id"] == notebook_id
    assert payload["transcript"]["messages"]
    source_ids = {item["id"] for item in payload["sources"]}
    assert library_source["id"] in source_ids
    assert attachment["id"] not in source_ids
    for source in payload["sources"]:
        assert set(source) <= {
            "id",
            "title",
            "kind",
            "mime",
            "size",
            "group",
            "selected",
            "origin",
            "locked",
            "has_file",
        }
    assert "journey" in payload["learning"]
    assert "hmw_scaffold" in payload["learning"]
    assert "review" in payload["learning"]
    _assert_no_forbidden_workspace_fields(payload)
    with bootstrap._connect() as connection:  # noqa: SLF001
        audit = connection.execute(
            "SELECT action FROM research_access_events ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    assert audit["action"] == "professor.workspace"


def test_professor_workspace_enforces_ownership_and_role(tmp_path, monkeypatch):
    """Workspace and library source routes reject cross-student and student callers."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    library_source = WorkspaceService(student_store).upload_sources(
        notebook_id, [("lecture.txt", b"Evidence", "text/plain")]
    )[0]
    other_student_id = _seed_student_activity(
        bootstrap, sub="student-b", now=datetime.now(timezone.utc), messages=1
    )
    other_notebook_id = StudentStore(
        Path(bootstrap.path), identifier="cognito:student-b"
    ).list_threads()[0]["id"]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    professor_token = oidc.add("prof")
    student_token = oidc.add("student-a")
    professor_cookies = {settings.cognito_id_token_cookie_name: professor_token}
    student_cookies = {settings.cognito_id_token_cookie_name: student_token}
    workspace_url = (
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/workspace"
    )
    source_url = (
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}"
        f"/sources/{library_source['id']}"
    )
    assert client.get(workspace_url, cookies=student_cookies).status_code == 403
    assert client.get(source_url, cookies=student_cookies).status_code == 403
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{other_notebook_id}/workspace",
        cookies=professor_cookies,
    ).status_code == 404
    assert client.get(
        f"/api/v1/professor/students/{other_student_id}/conversations/{notebook_id}/workspace",
        cookies=professor_cookies,
    ).status_code == 404
    source_response = client.get(source_url, cookies=professor_cookies)
    assert source_response.status_code == 200
    assert source_response.content
    attachment = WorkspaceService(student_store).upload_attachments(
        notebook_id, [("private.txt", b"private", "text/plain")]
    )[0]
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources/{attachment['id']}",
        cookies=professor_cookies,
    ).status_code == 404


def test_student_roster_sql_is_dsql_portable():
    """Roster SQL must not use SQLite-only NOT-integer predicates."""
    from backend.persistence.dsql_connection import adapt_sqlite_sql
    from backend.professor_analytics.repository import _STUDENT_ROSTER_SQL

    sql = _STUDENT_ROSTER_SQL.lower()
    assert "not message_is_error" not in sql
    assert "not am.message_is_error" not in sql
    assert "coalesce(message_is_error, 0) = 0" in sql
    adapted = adapt_sqlite_sql(_STUDENT_ROSTER_SQL)
    assert adapted.count("%s") == 0


def test_student_roster_projection_is_one_row_per_student(tmp_path):
    """Roster SQL returns compact student aggregates without message bodies."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    rows = ProfessorAnalyticsRepository(bootstrap).load_student_roster()
    assert rows
    for row in rows:
        assert "message_content" not in row
        assert "messages" not in row
    assert sum(1 for row in rows if str(row["user_id"]) == student_id) == 1
    service_rows = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).students().students
    assert len(service_rows) == len(rows)


def test_professor_workspace_chat_reflects_active_branch_revision(tmp_path, monkeypatch):
    """Workspace chat includes revised user turns and drops superseded suffixes."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    original = student_store.get_messages(notebook_id)[0]
    student_store.revise_conversation_from_user_message(
        notebook_id, original["id"], "Revised workspace thought"
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    payload = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/workspace",
        cookies=cookies,
    ).json()
    contents = [message["content"] for message in payload["transcript"]["messages"]]
    assert "Revised workspace thought" in contents
    assert original["content"] not in contents


def test_professor_library_source_rejects_other_notebook_scope(tmp_path, monkeypatch):
    """A library source uploaded to notebook B cannot be read via notebook A."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_a = student_store.list_threads()[0]["id"]
    notebook_b = student_store.create_thread(
        name="Notebook B", model_id="mock", support_mode="critical-thinking"
    )
    library_source = WorkspaceService(student_store).upload_sources(
        notebook_b, [("other.txt", b"scoped", "text/plain")]
    )[0]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_a}"
        f"/sources/{library_source['id']}",
        cookies=cookies,
    ).status_code == 404


def test_professor_attachment_route_rejects_superseded_only_association(tmp_path, monkeypatch):
    """Attachments referenced only on superseded turns stay unavailable."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    attachment = WorkspaceService(student_store).upload_attachments(
        notebook_id, [("private.txt", b"private", "text/plain")]
    )[0]
    student_store.add_message(
        notebook_id,
        "user",
        "Attached on superseded turn.",
        metadata={"attachments": [attachment]},
    )
    original = student_store.get_messages(notebook_id)[0]
    student_store.revise_conversation_from_user_message(
        notebook_id, original["id"], "Revision without attachment"
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    assert client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}"
        f"/attachments/{attachment['id']}",
        cookies=cookies,
    ).status_code == 404


def test_professor_workspace_includes_virtual_course_source(tmp_path, monkeypatch):
    """Virtual course sources appear in workspace lists and can be opened."""
    from backend.source_library import virtual_course_source_id

    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    object_key = "course/lectureNotes/week1.pdf"
    virtual_id = virtual_course_source_id(object_key)
    virtual_source = {
        "id": virtual_id,
        "title": "Week 1 lecture",
        "kind": "file",
        "mime": "application/pdf",
        "size": 1200,
        "selected": True,
        "path": "/secret/local.pdf",
        "extractedText": "secret",
        "metadata": {
            "virtual_course_source": True,
            "course_material_group": "Lecture Notes",
            "shared_course_object": True,
            "origin": "lecture_notes_folder",
            "locked_source": True,
            "object_key": object_key,
        },
    }

    uploaded = WorkspaceService(student_store).upload_sources(
        notebook_id, [("lecture.txt", b"Evidence", "text/plain")]
    )
    library_sources = uploaded

    def _visible_sources(_store, _notebook_id, *, include_extracted_text=False):
        return [*library_sources, virtual_source]

    monkeypatch.setattr(
        "backend.sources.library.list_visible_sources",
        _visible_sources,
    )
    monkeypatch.setattr(
        "backend.professor_analytics.repository.get_visible_source",
        lambda _store, _notebook_id, source_id, **kwargs: virtual_source
        if source_id == virtual_id
        else next((item for item in library_sources if item["id"] == source_id), None),
    )

    def _read_bytes(source):
        if str(source.get("id")) == virtual_id:
            return b"virtual-bytes"
        from backend.source_library import read_source_bytes as original_read

        return original_read(source)

    monkeypatch.setattr("backend.http.app.read_source_bytes", _read_bytes)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    workspace = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/workspace",
        cookies=cookies,
    )
    assert workspace.status_code == 200
    payload = workspace.json()
    virtual = next(item for item in payload["sources"] if item["id"] == virtual_id)
    assert virtual["group"] == "Lecture Notes"
    assert virtual["locked"] is True
    _assert_no_forbidden_workspace_fields(payload)
    source_response = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources/{virtual_id}",
        cookies=cookies,
    )
    assert source_response.status_code == 200
    assert source_response.content == b"virtual-bytes"


def test_professor_student_store_preserves_pathless_provider(
    tmp_path, monkeypatch
) -> None:
    """Lecturer reads must not force SQLite via Path(None) on DSQL-shaped stores."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    captured: dict[str, object] = {}

    class PathlessAnalyticsStore:
        """Analytics repository view with ``path is None`` like production DSQL."""

        path = None

        def __init__(self, inner: StudentStore) -> None:
            self._inner = inner

        def get_user_by_id(self, user_id: str):
            return self._inner.get_user_by_id(user_id)

    def _create_student_store(*, path=None, identifier="local-student", **kwargs):
        captured["path"] = path
        captured["identifier"] = identifier
        captured["ensure_owner"] = kwargs.get("ensure_owner")
        captured["ensure_user_called"] = False
        store = StudentStore(
            tmp_path / "owner.sqlite3",
            identifier=identifier,
            ensure_owner=bool(kwargs.get("ensure_owner", True)),
        )
        store.path = None

        def _tracked_ensure_user() -> str:
            captured["ensure_user_called"] = True
            raise AssertionError("_ensure_user must not run for lecturer reads")

        store._ensure_user = _tracked_ensure_user  # noqa: SLF001
        return store

    monkeypatch.setattr(
        "backend.professor_analytics.repository.create_student_store",
        _create_student_store,
    )
    repository = ProfessorAnalyticsRepository(PathlessAnalyticsStore(bootstrap))
    store = repository.student_store(student_id)
    assert captured["path"] is None
    assert captured["ensure_owner"] is False
    assert captured["ensure_user_called"] is False
    assert store is not None
    assert getattr(store, "path", "missing") is None
    assert store.owner_id == student_id


def test_professor_workspace_keeps_virtual_course_citations(tmp_path, monkeypatch):
    """Shared Lecture Notes citations stay visible in lecturer workspace chat."""
    from backend.source_library import virtual_course_source_id

    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    object_key = "course/lectureNotes/week1.pdf"
    virtual_id = virtual_course_source_id(object_key)
    virtual_source = {
        "id": virtual_id,
        "title": "Week 1 lecture",
        "kind": "file",
        "mime": "application/pdf",
        "size": 1200,
        "selected": True,
        "metadata": {
            "virtual_course_source": True,
            "course_material_group": "Lecture Notes",
            "shared_course_object": True,
            "origin": "lecture_notes_folder",
            "locked_source": True,
            "object_key": object_key,
        },
    }
    student_store.add_message(
        notebook_id,
        "assistant",
        "Coach cites the lecture.",
        metadata={
            "source_refs": [
                {"id": virtual_id, "label": "S1", "title": "Week 1 lecture"},
                {"id": "random-virtual-looking-id", "label": "S9", "title": "Foreign"},
            ]
        },
    )

    def _visible_sources(_store, _notebook_id, *, include_extracted_text=False):
        return [virtual_source]

    monkeypatch.setattr("backend.sources.library.list_visible_sources", _visible_sources)
    service = ProfessorAnalyticsService(ProfessorAnalyticsRepository(bootstrap))
    workspace = service.notebook_workspace(student_id, notebook_id)
    assert workspace is not None
    coach_messages = [
        message
        for message in workspace.transcript.messages
        if message.get("role") == "assistant"
    ]
    citations = coach_messages[-1]["citations"]
    assert citations == [
        {"id": virtual_id, "label": "S1", "title": "Week 1 lecture"}
    ]


def test_professor_citation_auth_rejects_other_notebook_source(tmp_path):
    """Personal sources from another notebook are not authorized citations."""
    bootstrap, _professor, student_id, _oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_a = student_store.list_threads()[0]["id"]
    notebook_b = student_store.create_thread(
        name="Notebook B", model_id="mock", support_mode="critical-thinking"
    )
    foreign_source = add_text_source(student_store, notebook_b, "Other notebook", "Evidence")
    student_store.add_message(
        notebook_a,
        "assistant",
        "Coach reply",
        metadata={
            "source_refs": [
                {"id": foreign_source["id"], "label": "S2", "title": "Other notebook"}
            ]
        },
    )
    workspace = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(bootstrap)
    ).notebook_workspace(student_id, notebook_a)
    assert workspace is not None
    citations = workspace.transcript.messages[-1]["citations"]
    assert citations == []


def test_professor_tab_routes_enforce_auth_and_ownership(tmp_path, monkeypatch):
    """New tab-scoped routes reject students, foreign notebooks, and unauthenticated callers."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    other_student_id = _seed_student_activity(
        bootstrap, sub="student-b", now=datetime.now(timezone.utc), messages=1
    )
    other_notebook_id = StudentStore(
        Path(bootstrap.path), identifier="cognito:student-b"
    ).list_threads()[0]["id"]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    professor_cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    student_cookies = {settings.cognito_id_token_cookie_name: oidc.add("student-a")}
    routes = (
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/messages",
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources",
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/journey",
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/review",
    )
    for route in routes:
        assert client.get(route).status_code == 401
        assert client.get(route, cookies=student_cookies).status_code == 403
        assert client.get(route, cookies=professor_cookies).status_code == 200
        assert client.get(
            route.replace(student_id, other_student_id),
            cookies=professor_cookies,
        ).status_code == 404
        assert client.get(
            route.replace(notebook_id, other_notebook_id),
            cookies=professor_cookies,
        ).status_code == 404


def test_professor_messages_pagination_and_cursor(tmp_path, monkeypatch):
    """Messages endpoint paginates newest-first and rejects malformed cursors."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    for index in range(40):
        student_store.add_message(notebook_id, "user", f"Turn {index}")
    messages = student_store.get_messages(notebook_id)
    last = messages[-1]
    original_content = str(last["content"])
    student_store.revise_conversation_from_user_message(
        notebook_id, last["id"], "Revised last turn"
    )
    assert len(student_store.get_messages(notebook_id)) > 30
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    base = f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/messages"
    first = client.get(base, cookies=cookies)
    assert first.status_code == 200
    payload = first.json()
    assert len(payload["messages"]) <= 30
    assert payload["next_cursor"]
    assert all("extracted_text" not in message for message in payload["messages"])
    assert all(message["content"] != original_content for message in payload["messages"])
    first_ids = {message["id"] for message in payload["messages"]}
    first_oldest = payload["messages"][0]["created_at"]
    second = client.get(
        base, cookies=cookies, params={"cursor": payload["next_cursor"]}
    )
    assert second.status_code == 200
    older_page = second.json()["messages"]
    assert older_page
    assert not first_ids & {message["id"] for message in older_page}
    assert older_page[-1]["created_at"] <= first_oldest
    assert all(message["content"] != original_content for message in older_page)
    clamped = client.get(base, cookies=cookies, params={"limit": 1_000_000}).json()
    assert len(clamped["messages"]) <= 50
    assert client.get(base, cookies=cookies, params={"cursor": "not-valid"}).status_code == 400


def test_professor_sources_list_has_no_forbidden_fields(tmp_path, monkeypatch):
    """Source list responses remain allow-listed and path-free."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    WorkspaceService(student_store).upload_sources(
        notebook_id, [("lecture.txt", b"Evidence", "text/plain")]
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    response = client.get(
        f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources",
        cookies=cookies,
    )
    assert response.status_code == 200
    _assert_no_forbidden_workspace_fields(response.json())


def test_professor_tab_routes_record_audit_actions(tmp_path, monkeypatch):
    """Tab-scoped reads write attributable audit events."""
    bootstrap, _professor, student_id, oidc = _setup(tmp_path)
    student_store = StudentStore(Path(bootstrap.path), identifier="cognito:student-a")
    notebook_id = student_store.list_threads()[0]["id"]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    cookies = {settings.cognito_id_token_cookie_name: oidc.add("prof")}
    requests = (
        (f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/messages", "professor.transcript"),
        (f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources", "professor.sources"),
        (f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/journey", "professor.journey"),
        (f"/api/v1/professor/students/{student_id}/conversations/{notebook_id}/review", "professor.review"),
    )
    for path, _action in requests:
        assert client.get(path, cookies=cookies).status_code == 200
    with bootstrap._connect() as connection:  # noqa: SLF001
        rows = connection.execute(
            "SELECT action FROM research_access_events ORDER BY created_at, id"
        ).fetchall()
    assert [row["action"] for row in rows][-4:] == [action for _, action in requests]
