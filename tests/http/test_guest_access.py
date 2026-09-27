"""Phase 3 guest API ownership tests using temporary SQLite stores."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth_oidc import CognitoIdentity, CognitoOIDCError
from backend.api_client import GuestClaimConflictError, LocalApiClient
from backend.auth_profiles import sync_authenticated_user
from backend.persistence.guest_sessions import guest_secret_digest
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.object_keys import build_extracted_text_object_key, build_upload_object_key
from backend.settings import settings
from backend.student_store import StudentStore


def test_guest_cookie_resolves_isolated_workspace_and_invalid_secret_fails_closed(
    tmp_path, monkeypatch
):
    """A validated guest sees only its notebooks; malformed credentials get 401."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    first_store = StudentStore(tmp_path / "guest-workspace.sqlite3")
    _first_owner_id, first_secret = first_store.create_guest_session()
    second_owner_id, second_secret = first_store.create_guest_session()
    first_owner = first_store.get_user_by_id(first_store.validate_guest_session(first_secret))
    second_owner = first_store.get_user_by_id(second_owner_id)
    assert first_owner is not None and second_owner is not None

    first_notebook = StudentStore(
        first_store.path, identifier=str(first_owner["identifier"])
    ).create_thread(model_id="mock", support_mode="critical-thinking")
    second_notebook = StudentStore(
        first_store.path, identifier=str(second_owner["identifier"])
    ).create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(first_store))

    client.cookies.set(settings.guest_session_cookie_name, first_secret)
    listed = client.get("/api/v1/threads")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [first_notebook]
    assert client.get("/api/v1/professor/overview").status_code == 401

    client.cookies.set(settings.guest_session_cookie_name, "invalid-secret")
    rejected = client.get("/api/v1/threads")
    assert rejected.status_code == 401
    assert second_notebook not in [item["id"] for item in listed.json()]


def test_guest_cannot_fetch_another_guests_notebook_source_or_attachment(
    tmp_path, monkeypatch
):
    """Every notebook-bound resource remains scoped to the presented guest."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    store = StudentStore(tmp_path / "guest-cross-resource.sqlite3")
    guest_a_id, guest_a_secret = store.create_guest_session()
    guest_b_id, guest_b_secret = store.create_guest_session()
    guest_a_profile = store.get_user_by_id(guest_a_id)
    guest_b_profile = store.get_user_by_id(guest_b_id)
    assert guest_a_profile is not None and guest_b_profile is not None
    guest_a = StudentStore(store.path, identifier=str(guest_a_profile["identifier"]))
    guest_b = StudentStore(store.path, identifier=str(guest_b_profile["identifier"]))
    notebook_a = guest_a.create_thread(model_id="mock", support_mode="guided")
    notebook_b = guest_b.create_thread(model_id="mock", support_mode="guided")
    guest_b.add_source(
        notebook_b,
        kind="file",
        title="private.pdf",
        mime="application/pdf",
        size=7,
        source_id="private-source",
    )
    client = TestClient(create_app(store))
    client.cookies.set(settings.guest_session_cookie_name, guest_b_secret)
    uploaded = client.post(
        f"/api/v1/threads/{notebook_b}/attachments",
        files=[("files", ("victim.pdf", b"attachment bytes", "application/pdf"))],
    )
    assert uploaded.status_code == 200
    attachment_id = uploaded.json()[0]["id"]
    guest_b.add_message(
        notebook_b,
        "user",
        "See the attached file",
        metadata={"attachments": [{"id": attachment_id}]},
    )

    client.cookies.set(settings.guest_session_cookie_name, guest_a_secret)

    assert client.get(f"/api/v1/threads/{notebook_b}").status_code == 404
    assert client.get(f"/api/v1/threads/{notebook_b}/sources").status_code == 404
    assert client.get(
        f"/api/v1/threads/{notebook_b}/sources/private-source"
    ).status_code == 404
    assert client.get(
        f"/api/v1/threads/{notebook_b}/sources/{attachment_id}/content"
    ).status_code == 404

    client.cookies.set(settings.guest_session_cookie_name, guest_b_secret)
    assert client.get(f"/api/v1/threads/{notebook_b}").status_code == 200
    assert notebook_a not in [item["id"] for item in client.get("/api/v1/threads").json()]


def test_invalid_cognito_cookie_never_downgrades_to_valid_guest(
    tmp_path, monkeypatch
):
    """A bad Cognito token remains an auth error even beside a valid guest cookie."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    store = StudentStore(tmp_path / "guest-cognito-priority.sqlite3")
    _owner_id, guest_secret = store.create_guest_session()

    class InvalidOIDC:
        def verify_id_token(self, _token: str):
            raise CognitoOIDCError("bad token")

    client = TestClient(create_app(store, oidc_client=InvalidOIDC()))
    client.cookies.set(settings.cognito_id_token_cookie_name, "invalid-cognito")
    client.cookies.set(settings.guest_session_cookie_name, guest_secret)

    assert client.get("/api/v1/threads").status_code == 401


def test_enabled_guest_mode_fails_closed_without_guest_cookie(tmp_path, monkeypatch):
    """Flag-on signed-out requests cannot fall through to local-student data."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    store = StudentStore(tmp_path / "guest-missing-cookie.sqlite3")
    client = TestClient(create_app(store))

    assert client.get("/api/v1/threads").status_code == 401


def test_logout_revokes_and_expires_presented_guest_cookie(tmp_path, monkeypatch):
    """Only an explicit same-origin POST revokes a guest credential."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    store = StudentStore(tmp_path / "guest-logout.sqlite3")
    _owner_id, secret = store.create_guest_session()
    client = TestClient(create_app(store), follow_redirects=False)
    client.cookies.set(settings.guest_session_cookie_name, secret)

    cross_site_get = client.get("/api/v1/auth/logout")
    assert store.validate_guest_session(secret) is not None
    assert not any(
        item.startswith(f"{settings.guest_session_cookie_name}=")
        for item in cross_site_get.headers.get_list("set-cookie")
    )

    cross_origin_post = client.post(
        "/api/v1/auth/logout", headers={"Origin": "https://attacker.example"}
    )
    assert store.validate_guest_session(secret) is not None
    assert not any(
        item.startswith(f"{settings.guest_session_cookie_name}=")
        for item in cross_origin_post.headers.get_list("set-cookie")
    )

    response = client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://testserver"}
    )

    assert response.status_code == 302
    assert store.validate_guest_session(secret) is None
    cookie = next(
        item
        for item in response.headers.get_list("set-cookie")
        if item.startswith(f"{settings.guest_session_cookie_name}=")
    )
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_cognito_logout_preserves_unclaimed_guest_cookie_and_owner(tmp_path, monkeypatch):
    """A Cognito session with a guest cookie must not revoke unclaimed guest work."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://chat.example.edu")
    monkeypatch.setattr(settings, "api_base_url", "http://internal-api:8000")
    store = StudentStore(tmp_path / "guest-preserved-on-cognito-logout.sqlite3")
    _owner_id, secret = store.create_guest_session()
    client = TestClient(create_app(store), follow_redirects=False)
    client.cookies.set(settings.guest_session_cookie_name, secret)
    client.cookies.set(settings.cognito_id_token_cookie_name, "active-cognito")

    response = client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://testserver"}
    )

    assert response.status_code == 302
    assert store.validate_guest_session(secret) is not None
    assert not any(
        item.startswith(f"{settings.guest_session_cookie_name}=")
        for item in response.headers.get_list("set-cookie")
    )


def test_verified_cognito_owner_wins_over_guest_cookie(tmp_path, monkeypatch):
    """A verified Cognito subject remains the authoritative request owner."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    store = StudentStore(tmp_path / "cognito-guest-priority.sqlite3")
    _guest_owner_id, guest_secret = store.create_guest_session()
    identity = CognitoIdentity(
        sub="verified-student",
        email="verified-student@example.edu",
        claims={
            "sub": "verified-student",
            "email": "verified-student@example.edu",
            "given_name": "Verified",
        },
    )
    cognito_profile = sync_authenticated_user(identity.claims, store=store)
    cognito_store = StudentStore(store.path, identifier=cognito_profile.store_identifier)
    cognito_notebook = cognito_store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return identity

    client = TestClient(create_app(store, oidc_client=ValidOIDC()))
    client.cookies.set(settings.cognito_id_token_cookie_name, "verified-cognito")
    client.cookies.set(settings.guest_session_cookie_name, guest_secret)

    listed = client.get("/api/v1/threads")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [cognito_notebook]


def test_guest_claim_requires_preview_confirmation_and_transfers_verified_files(
    tmp_path, monkeypatch
):
    """Cognito alone leaves guest data; confirmation copies files and preserves IDs."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "api_base_url", "http://internal-api:8000")
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    store = StudentStore(
        tmp_path / "guest-claim-api.sqlite3", identifier="local-student"
    )
    guest_user_id, guest_secret = store.create_guest_session()
    guest_profile = store.get_user_by_id(guest_user_id)
    assert guest_profile
    guest = StudentStore(store.path, identifier=guest_profile["identifier"])
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    from backend.research.models import (
        ResearchAccessEventCreate,
        ResearchAdjudicationCreate,
        ResearchEvidenceSpan,
        ResearchObservationCreate,
        ResearchReviewCreate,
    )
    from backend.research.repository import StudentStoreResearchRepository
    from backend.professor_analytics.repository import ProfessorAnalyticsRepository
    from backend.professor_analytics.service import ProfessorAnalyticsService
    from backend.professor_analytics.guest_identity import guest_public_id

    stage = str((guest.get_thread(notebook_id) or {}).get("metadata", {}).get("thinking_stage"))
    message_id, assistant_id = guest.persist_coach_turn(
        notebook_id,
        expected_stage=stage,
        expected_conversation_revision=0,
        user_content="Keep my analysis",
        user_metadata={"thinking_stage": stage},
        assistant_content="Consider the evidence.",
        assistant_metadata={},
        summary_metadata={},
        research_observation=ResearchObservationCreate(
            coding_status="coded",
            coding_version="research-v1",
            prompt_version="prompt-v1",
            provider="mock",
            model_id="mock",
            coaching_profile="quick",
            phase_id=stage,
            dominant_clear="explicit",
            evidence=[
                ResearchEvidenceSpan(
                    start_offset=0,
                    end_offset=4,
                    rationale="Guest evidence",
                    confidence=0.8,
                )
            ],
        ),
    )
    observation = StudentStoreResearchRepository(guest).list_observations()[0]
    review = guest.append_research_review(
        ResearchReviewCreate(
            observation_id=observation.id,
            reviewer_user_id=guest_user_id,
            status="confirmed",
        )
    )
    guest.append_research_adjudication(
        ResearchAdjudicationCreate(
            observation_id=observation.id,
            adjudicator_user_id=guest_user_id,
            decision="confirmed",
            referenced_review_ids=[review["id"]],
        )
    )
    guest.record_research_access_event(
        ResearchAccessEventCreate(
            actor_user_id=guest_user_id,
            action="research.detail",
            scope="notebook",
            request_id="historical-guest-audit",
            target_user_id=guest_user_id,
            notebook_id=notebook_id,
        )
    )
    with guest._connect() as connection:
        research_rows_before = {
            table: [tuple(row) for row in connection.execute(
                f"SELECT * FROM {table} WHERE "
                + ("id=?" if table == "research_observations" else "observation_id=?"),
                (observation.id,),
            )]
            for table in ("research_observations", "research_reviews", "research_adjudications")
        }
        audit_before = tuple(connection.execute(
            "SELECT actor_user_id, target_user_id, notebook_id FROM research_access_events "
            "WHERE request_id='historical-guest-audit'"
        ).fetchone())
    source_id = "claim-source"
    raw_key = build_upload_object_key(
        user_id=guest_user_id, notebook_id=notebook_id, source_id=source_id,
        filename="brief.pdf",
    )
    extracted_key = build_extracted_text_object_key(
        user_id=guest_user_id, notebook_id=notebook_id, source_id=source_id,
    )
    storage = MemoryFileStorage()
    storage.put_bytes(key=raw_key, data=b"private upload")
    storage.put_bytes(key=extracted_key, data=b"extracted evidence")
    with guest._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "object_key, extracted_text_key, metadata_text, created_at, updated_at) "
            "VALUES (?, ?, 'file', 'brief.pdf', 'application/pdf', ?, ?, ?, ?, 'now', 'now')",
            (source_id, notebook_id, len(b"private upload"), raw_key, extracted_key,
             '{"storage_provider":"memory","object_key":"' + raw_key + '",'
             '"local_path":"threads/' + notebook_id + '/uploads/brief.pdf"}'),
        )
    identity = CognitoIdentity(
        sub="guest-claim-student", email="claim@example.edu",
        claims={"sub": "guest-claim-student", "email": "claim@example.edu", "given_name": "Claim"},
    )
    account_profile = sync_authenticated_user(identity.claims, store=store)
    account = StudentStore(store.path, identifier=account_profile.store_identifier)
    account.update_user_preferences({"theme": "keep"})
    with account._connect() as connection:
        account_preferences_before = connection.execute(
            "SELECT preferences_text, role FROM users WHERE id=?", (account.owner_id,)
        ).fetchone()

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return identity

    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: storage)
    session = TestClient(
        create_app(store, oidc_client=ValidOIDC()), base_url="http://internal-api:8000"
    )
    api_client = LocalApiClient(
        settings.api_base_url,
        session=session,
        cookie_provider=lambda: {
            settings.cognito_id_token_cookie_name: "verified-cognito",
            settings.guest_session_cookie_name: guest_secret,
        },
    )
    preview = api_client.guest_claim_preview()
    assert preview["account"]["email"] == "claim@example.edu"
    assert preview["notebooks"][0]["title"]
    assert preview["notebooks"][0]["files"] == ["brief.pdf"]
    assert session.get(
        "/api/v1/threads", cookies=api_client.auth_cookies_snapshot()
    ).json() == []

    stale_operation_id = preview["operation_id"]
    guest.add_message(notebook_id, "user", "New work after the preview")
    with pytest.raises(GuestClaimConflictError, match="Refresh the preview"):
        api_client.confirm_guest_claim(stale_operation_id)
    assert store.validate_guest_session(guest_secret) == guest_user_id
    preview = api_client.guest_claim_preview()
    operation_id = preview["operation_id"]
    # A process interruption after fencing can be abandoned by the same owner.
    pending = store.begin_guest_claim(
        secret=guest_secret, target_user_id=account.owner_id,
        operation_id=operation_id,
    )
    assert pending is not None
    assert api_client.cancel_guest_claim(operation_id) == {"released": True}
    assert store.validate_guest_session(guest_secret) == guest_user_id
    result = api_client.confirm_guest_claim(operation_id)
    assert result["notebook_ids"] == [notebook_id]
    assert [item["id"] for item in session.get(
        "/api/v1/threads", cookies=api_client.auth_cookies_snapshot()
    ).json()] == [notebook_id]
    with account._connect() as connection:
        preserved = {
            table: [tuple(row) for row in connection.execute(
                f"SELECT * FROM {table} WHERE "
                + ("id=?" if table == "research_observations" else "observation_id=?"),
                (observation.id,),
            )]
            for table in ("research_observations", "research_reviews", "research_adjudications")
        }
        audit_row = tuple(connection.execute(
            "SELECT actor_user_id, target_user_id, notebook_id FROM research_access_events "
            "WHERE request_id='historical-guest-audit'"
        ).fetchone())
        assert audit_row == audit_before
    assert preserved == research_rows_before
    lecturer_profile = store.upsert_cognito_user(
        cognito_sub="guest-claim-reviewer",
        identifier="cognito:guest-claim-reviewer",
        email="reviewer@example.edu",
        display_name="Reviewer",
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE users SET role='lecturer' WHERE id=?",
            (lecturer_profile["id"],),
        )
    account.append_research_review(
        ResearchReviewCreate(
            observation_id=observation.id,
            reviewer_user_id=str(lecturer_profile["id"]),
            status="confirmed",
        )
    )
    lecturer_identity = CognitoIdentity(
        sub="guest-claim-reviewer",
        email="reviewer@example.edu",
        claims={
            "sub": "guest-claim-reviewer",
            "email": "reviewer@example.edu",
            "given_name": "Reviewer",
        },
    )

    class LecturerOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return lecturer_identity

    lecturer_client = TestClient(create_app(store, oidc_client=LecturerOIDC()))
    detail_response = lecturer_client.get(
        f"/api/v1/professor/research/notebooks/{notebook_id}",
        cookies={settings.cognito_id_token_cookie_name: "verified-reviewer"},
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert guest_user_id not in detail_response.text
    assert detail["observations"][0]["evidence"][0]["rationale"] == "Guest evidence"
    review_actor_ids = {
        item["reviewer_user_id"] for item in detail["observations"][0]["reviews"]
    }
    assert guest_public_id(guest_user_id) in review_actor_ids
    assert str(lecturer_profile["id"]) in review_actor_ids
    assert detail["observations"][0]["adjudications"][0]["adjudicator_user_id"] == (
        guest_public_id(guest_user_id)
    )
    public_students = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(store)
    ).students().students
    assert sum(item.id == account.owner_id for item in public_students) == 1
    assert all(item.id != guest_user_id for item in public_students)
    public_overview = ProfessorAnalyticsService(
        ProfessorAnalyticsRepository(store)
    ).overview()
    assert public_overview.students == 1
    assert ProfessorAnalyticsRepository(store).resolve_public_student_id(
        guest_public_id(guest_user_id)
    ) is None
    queue = StudentStoreResearchRepository(account).list_observations()
    assert len(queue) == 1
    assert queue[0].student_user_id == account.owner_id
    assert store.validate_guest_session(guest_secret) is None
    account_source = account.get_source(notebook_id, source_id, include_extracted_text=False)
    assert account_source["object_key"] == raw_key.replace(guest_user_id, account.owner_id)
    assert account_source["metadata"]["local_path"] == (
        f"threads/{notebook_id}/uploads/brief.pdf"
    )
    assert storage.get_bytes(account_source["object_key"]) == b"private upload"
    assert account.get_messages(notebook_id)[0]["id"] == message_id
    with account._connect() as connection:
        account_preferences_after = connection.execute(
            "SELECT preferences_text, role FROM users WHERE id=?", (account.owner_id,)
        ).fetchone()
    assert tuple(account_preferences_after) == tuple(account_preferences_before)
    replay = api_client.confirm_guest_claim(operation_id)
    assert replay["notebook_ids"] == [notebook_id]
    recovery = api_client.guest_claim_preview()
    assert recovery["already_claimed"] is True
    assert recovery["notebook_ids"] == [notebook_id]


def test_guest_claim_copy_failure_releases_fence_and_allows_safe_retry(
    tmp_path, monkeypatch
):
    """A failed private-object copy keeps guest ownership and permits retry."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "api_base_url", "http://internal-api:8000")

    class FailsOneCopy(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.fail_copy = True
            self.guest_prefix = ""

        def put_bytes(self, *, key: str, data: bytes) -> None:
            if key.startswith("users/") and not key.startswith(self.guest_prefix) and self.fail_copy:
                self.fail_copy = False
                raise OSError("temporary copy failure")
            super().put_bytes(key=key, data=data)

    storage = FailsOneCopy()
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: storage)
    store = StudentStore(tmp_path / "guest-claim-copy-retry.sqlite3")
    guest_user_id, secret = store.create_guest_session()
    storage.guest_prefix = f"users/{guest_user_id}/"
    guest_profile = store.get_user_by_id(guest_user_id)
    assert guest_profile is not None
    guest = StudentStore(store.path, identifier=str(guest_profile["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    identity = CognitoIdentity(
        sub="copy-retry-account",
        email="copy-retry@example.edu",
        claims={"sub": "copy-retry-account", "email": "copy-retry@example.edu"},
    )
    account_profile = sync_authenticated_user(identity.claims, store=store)
    account = StudentStore(store.path, identifier=account_profile.store_identifier)
    raw_key = build_upload_object_key(
        user_id=guest_user_id,
        notebook_id=notebook_id,
        source_id="retry-source",
        filename="brief.pdf",
    )
    storage.put_bytes(key=raw_key, data=b"private bytes")

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return identity

    client = TestClient(create_app(store, oidc_client=ValidOIDC()))
    cookies = {
        settings.cognito_id_token_cookie_name: "verified-cognito",
        settings.guest_session_cookie_name: secret,
    }
    preview = client.post(
        "/api/v1/auth/guest/claim/preview",
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    ).json()
    payload = {"confirmed": True, "operation_id": preview["operation_id"]}

    failed = client.post(
        "/api/v1/auth/guest/claim/confirm",
        json=payload,
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert failed.status_code == 409
    assert store.validate_guest_session(secret) == guest_user_id
    assert [item["id"] for item in guest.list_threads()] == [notebook_id]
    assert account.list_threads() == []

    retried = client.post(
        "/api/v1/auth/guest/claim/confirm",
        json=payload,
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert retried.status_code == 200
    assert retried.json()["notebook_ids"] == [notebook_id]
    assert store.validate_guest_session(secret) is None
    assert [item["id"] for item in account.list_threads()] == [notebook_id]
    assert storage.get_bytes(raw_key.replace(guest_user_id, account.owner_id)) == b"private bytes"


def test_guest_claim_commit_failure_preserves_refs_and_allows_same_operation_retry(
    tmp_path, monkeypatch
):
    """An ownership transaction failure preserves guest access and source keys."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "api_base_url", "http://internal-api:8000")
    storage = MemoryFileStorage()
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: storage)
    store = StudentStore(tmp_path / "guest-claim-commit-retry.sqlite3")
    guest_user_id, secret = store.create_guest_session()
    guest_profile = store.get_user_by_id(guest_user_id)
    assert guest_profile is not None
    guest = StudentStore(store.path, identifier=str(guest_profile["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    identity = CognitoIdentity(
        sub="commit-retry-account",
        email="commit-retry@example.edu",
        claims={"sub": "commit-retry-account", "email": "commit-retry@example.edu"},
    )
    account_profile = sync_authenticated_user(identity.claims, store=store)
    account = StudentStore(store.path, identifier=account_profile.store_identifier)
    raw_key = build_upload_object_key(
        user_id=guest_user_id,
        notebook_id=notebook_id,
        source_id="commit-source",
        filename="brief.pdf",
    )
    storage.put_bytes(key=raw_key, data=b"source bytes")
    with guest._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "object_key, metadata_text, created_at, updated_at) "
            "VALUES ('commit-source', ?, 'file', 'brief.pdf', 'application/pdf', ?, ?, '{}', 'now', 'now')",
            (notebook_id, len(b"source bytes"), raw_key),
        )

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return identity

    transfer = store.guest_claim_transfer
    transfer_calls = 0

    def fail_one_commit(**kwargs):
        nonlocal transfer_calls
        transfer_calls += 1
        if transfer_calls == 2:
            raise RuntimeError("temporary ownership transaction failure")
        return transfer(**kwargs)

    monkeypatch.setattr(store, "guest_claim_transfer", fail_one_commit)
    client = TestClient(create_app(store, oidc_client=ValidOIDC()))
    cookies = {
        settings.cognito_id_token_cookie_name: "verified-cognito",
        settings.guest_session_cookie_name: secret,
    }
    preview = client.post(
        "/api/v1/auth/guest/claim/preview",
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    ).json()
    payload = {"confirmed": True, "operation_id": preview["operation_id"]}

    failed = client.post(
        "/api/v1/auth/guest/claim/confirm",
        json=payload,
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert failed.status_code == 409
    assert store.validate_guest_session(secret) == guest_user_id
    assert [item["id"] for item in guest.list_threads()] == [notebook_id]
    assert account.list_threads() == []
    source_before = guest.get_source(notebook_id, "commit-source", include_extracted_text=False)
    assert source_before["object_key"] == raw_key
    assert storage.get_bytes(raw_key) == b"source bytes"

    retried = client.post(
        "/api/v1/auth/guest/claim/confirm",
        json=payload,
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert retried.status_code == 200
    assert store.validate_guest_session(secret) is None
    assert [item["id"] for item in account.list_threads()] == [notebook_id]
    source_after = account.get_source(notebook_id, "commit-source", include_extracted_text=False)
    assert source_after["object_key"] == raw_key.replace(guest_user_id, account.owner_id)


def test_guest_claim_cleanup_failure_keeps_account_commit_and_retry_cleans(
    tmp_path, monkeypatch
):
    """Post-commit cleanup failure preserves account access and recovers safely."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "api_base_url", "http://internal-api:8000")

    class FailsOneDelete(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.fail_delete = True
            self.guest_prefix = ""

        def delete_prefix(self, prefix: str) -> int:
            if prefix == self.guest_prefix and self.fail_delete:
                self.fail_delete = False
                raise OSError("temporary cleanup failure")
            return super().delete_prefix(prefix)

    storage = FailsOneDelete()
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: storage)
    store = StudentStore(tmp_path / "guest-claim-cleanup-retry.sqlite3")
    guest_user_id, secret = store.create_guest_session()
    storage.guest_prefix = f"users/{guest_user_id}/"
    guest_profile = store.get_user_by_id(guest_user_id)
    assert guest_profile is not None
    guest = StudentStore(store.path, identifier=str(guest_profile["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    storage.guest_prefix = f"users/{guest_user_id}/notebooks/{notebook_id}/"
    identity = CognitoIdentity(
        sub="cleanup-retry-account",
        email="cleanup-retry@example.edu",
        claims={"sub": "cleanup-retry-account", "email": "cleanup-retry@example.edu"},
    )
    account_profile = sync_authenticated_user(identity.claims, store=store)
    account = StudentStore(store.path, identifier=account_profile.store_identifier)
    raw_key = build_upload_object_key(
        user_id=guest_user_id,
        notebook_id=notebook_id,
        source_id="cleanup-source",
        filename="brief.pdf",
    )
    storage.put_bytes(key=raw_key, data=b"private bytes")

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return identity

    client = TestClient(create_app(store, oidc_client=ValidOIDC()))
    cookies = {
        settings.cognito_id_token_cookie_name: "verified-cognito",
        settings.guest_session_cookie_name: secret,
    }
    preview = client.post(
        "/api/v1/auth/guest/claim/preview",
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    ).json()
    response = client.post(
        "/api/v1/auth/guest/claim/confirm",
        json={"confirmed": True, "operation_id": preview["operation_id"]},
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["notebook_ids"] == [notebook_id]
    assert store.validate_guest_session(secret) is None
    assert [item["id"] for item in account.list_threads()] == [notebook_id]
    assert storage.exists(raw_key)

    recovery = client.post(
        "/api/v1/auth/guest/claim/preview",
        cookies=cookies,
        headers={"Origin": "http://testserver"},
    )
    assert recovery.status_code == 200
    assert recovery.json()["already_claimed"] is True
    assert not storage.exists(raw_key)
    assert [item["id"] for item in account.list_threads()] == [notebook_id]


def test_guest_ui_explains_automatic_transfer_after_sign_in() -> None:
    """Guest profile describes automatic transfer without manual claim controls."""
    from pathlib import Path

    profile_source = Path("ui/profile.py").read_text(encoding="utf-8")
    assert "add your guest notebooks " in profile_source
    assert "to your account automatically" in profile_source
    assert "Review guest workspace" not in profile_source
    assert "Transfer guest workspace" not in profile_source


def test_guest_renew_sets_http_only_400_day_cookie_and_slides_expiry(
    tmp_path, monkeypatch
):
    """Browser renewal validates the secret and slides its persisted expiry."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    store = StudentStore(tmp_path / "guest-renew-api.sqlite3")
    _owner_id, secret = store.create_guest_session()
    with store._connect() as connection:  # noqa: SLF001
        before = connection.execute(
            "SELECT expires_at FROM guest_sessions WHERE token_digest=?",
            (guest_secret_digest(secret),),
        ).fetchone()["expires_at"]
    client = TestClient(create_app(store))
    client.cookies.set(settings.guest_session_cookie_name, secret)

    response = client.post(
        "/api/v1/auth/guest/renew", headers={"Origin": "http://testserver"}
    )

    assert response.status_code == 200
    assert response.json() == {"renewed": True}
    assert secret not in response.text
    cookie = response.headers["set-cookie"]
    assert f"{settings.guest_session_cookie_name}={secret}" in cookie
    assert "Max-Age=34560000" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert store.validate_guest_session(secret) is not None
    with store._connect() as connection:  # noqa: SLF001
        after = connection.execute(
            "SELECT expires_at FROM guest_sessions WHERE token_digest=?",
            (guest_secret_digest(secret),),
        ).fetchone()["expires_at"]
    assert after > before


def test_guest_renew_rejects_cross_origin_and_disabled_flag_without_store_lookup(
    tmp_path, monkeypatch
):
    """Renewal is same-origin, and flag-off requests never query guest storage."""
    store = StudentStore(tmp_path / "guest-renew-guard.sqlite3")
    _owner_id, secret = store.create_guest_session()
    client = TestClient(create_app(store))
    client.cookies.set(settings.guest_session_cookie_name, secret)
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://chat.example.edu")

    cross_origin = client.post(
        "/api/v1/auth/guest/renew", headers={"Origin": "https://evil.example"}
    )
    assert cross_origin.status_code == 403

    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("guest storage queried while feature flag is disabled")

    monkeypatch.setattr(store, "validate_guest_session", unexpected_lookup)
    monkeypatch.setattr(settings, "guest_access_enabled", False)
    disabled = client.post(
        "/api/v1/auth/guest/renew", headers={"Origin": "https://chat.example.edu"}
    )
    assert disabled.status_code == 404
    # The existing local API fallback remains available and does not inspect the
    # dormant guest cookie or guest table.
    assert client.get("/api/v1/threads").status_code == 200


def test_guest_start_is_explicit_same_origin_and_reuses_cookie(tmp_path, monkeypatch):
    """Only the start action creates a guest; secrets are issued as HttpOnly cookies."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    store = StudentStore(tmp_path / "guest-start.sqlite3")
    client = TestClient(create_app(store), base_url="https://testserver")
    headers = {"Origin": "https://testserver"}

    started = client.post("/api/v1/auth/guest/start", headers=headers)
    assert started.status_code == 200
    payload = started.json()
    secret = client.cookies.get(settings.guest_session_cookie_name)
    assert payload["started"] is True
    assert payload["guest_id"].startswith("guest:")
    assert secret and secret not in started.text
    cookie = started.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    original_owner = store.validate_guest_session(secret)

    reused = client.post("/api/v1/auth/guest/start", headers=headers)
    assert reused.status_code == 200
    assert reused.json()["guest_id"] == payload["guest_id"]
    assert store.validate_guest_session(secret) == original_owner


def test_cookie_loss_and_explicit_guest_start_create_distinct_owner(
    tmp_path, monkeypatch
):
    """Explicit start after cookie loss creates a new isolated guest identity."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    store = StudentStore(tmp_path / "guest-cookie-loss.sqlite3")
    client = TestClient(create_app(store), base_url="https://testserver")
    headers = {"Origin": "https://testserver"}

    first = client.post("/api/v1/auth/guest/start", headers=headers)
    first_secret = client.cookies.get(settings.guest_session_cookie_name)
    assert first.status_code == 200 and first_secret
    first_owner_id = store.validate_guest_session(first_secret)
    assert first_owner_id
    first_owner = store.get_user_by_id(first_owner_id)
    assert first_owner is not None
    first_notebook = StudentStore(
        store.path, identifier=str(first_owner["identifier"])
    ).create_thread(model_id="mock", support_mode="guided")

    client.cookies.delete(settings.guest_session_cookie_name)
    second = client.post("/api/v1/auth/guest/start", headers=headers)
    second_secret = client.cookies.get(settings.guest_session_cookie_name)
    assert second.status_code == 200 and second_secret
    second_owner_id = store.validate_guest_session(second_secret)
    assert second_owner_id and second_owner_id != first_owner_id
    second_owner = store.get_user_by_id(second_owner_id)
    assert second_owner is not None
    second_guest = StudentStore(
        store.path, identifier=str(second_owner["identifier"])
    )
    assert second_guest.list_threads() == []
    assert StudentStore(
        store.path, identifier=str(first_owner["identifier"])
    ).get_thread(first_notebook) is not None


def test_guest_flag_off_then_on_preserves_unexpired_workspace_without_resolution(
    tmp_path, monkeypatch
):
    """Flag-off guest routes skip guest lookup and re-enable restores the workspace."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    store = StudentStore(tmp_path / "guest-flag-rollback.sqlite3")
    owner_id, secret = store.create_guest_session()
    profile = store.get_user_by_id(owner_id)
    assert profile is not None
    guest = StudentStore(store.path, identifier=str(profile["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    client = TestClient(create_app(store), base_url="https://testserver")
    client.cookies.set(settings.guest_session_cookie_name, secret)
    assert client.get("/api/v1/threads").json()[0]["id"] == notebook_id

    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("guest owner resolution ran with guest mode disabled")

    monkeypatch.setattr(store, "validate_guest_session", unexpected_lookup)
    monkeypatch.setattr(settings, "guest_access_enabled", False)
    headers = {"Origin": "https://testserver"}
    assert client.post("/api/v1/auth/guest/probe", headers=headers).status_code == 404
    assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 404
    assert client.post("/api/v1/auth/guest/renew", headers=headers).status_code == 404

    monkeypatch.setattr(store, "validate_guest_session", StudentStore.validate_guest_session.__get__(store))
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    assert client.get("/api/v1/threads").json()[0]["id"] == notebook_id
    assert guest.get_thread(notebook_id) is not None


def test_guest_start_checks_flag_origin_and_cognito_precedence(tmp_path, monkeypatch):
    """Disabled, cross-origin, and Cognito-owned start requests do not create guests."""
    store = StudentStore(tmp_path / "guest-start-guards.sqlite3")
    client = TestClient(create_app(store))
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "guest_access_enabled", False)
    disabled = client.post(
        "/api/v1/auth/guest/start", headers={"Origin": "http://testserver"}
    )
    assert disabled.status_code == 404
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    cross_origin = client.post(
        "/api/v1/auth/guest/start", headers={"Origin": "https://attacker.example"}
    )
    assert cross_origin.status_code == 403

    class ValidOIDC:
        def verify_id_token(self, _token: str) -> CognitoIdentity:
            return CognitoIdentity(
                sub="cognito-start-priority",
                email=None,
                claims={"sub": "cognito-start-priority"},
            )

    cognito_client = TestClient(create_app(store, oidc_client=ValidOIDC()))
    cognito_client.cookies.set(settings.cognito_id_token_cookie_name, "valid")
    rejected = cognito_client.post(
        "/api/v1/auth/guest/start", headers={"Origin": "http://testserver"}
    )
    assert rejected.status_code == 409
    assert store.list_threads() == []


def test_guest_probe_is_safe_and_local_api_client_forwards_browser_cookie(
    tmp_path, monkeypatch
):
    """Probe returns only a verified owner ID and the typed client forwards the guest cookie."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "http://testserver")
    monkeypatch.setattr(settings, "api_base_url", "http://testserver")
    store = StudentStore(tmp_path / "guest-probe.sqlite3")
    owner_id, secret = store.create_guest_session()
    expected_guest_id = str(store.get_user_by_id(owner_id)["identifier"])
    session = TestClient(create_app(store))
    api_client = LocalApiClient(
        "http://testserver",
        session=session,
        cookie_provider=lambda: {settings.guest_session_cookie_name: secret},
    )
    result = api_client.guest_session_probe()
    assert result == {"authenticated": True, "guest_id": expected_guest_id}
    assert secret not in str(result)
    assert api_client._http.cookies.get(settings.guest_session_cookie_name) is None

    monkeypatch.setattr(settings, "guest_access_enabled", False)
    assert api_client.guest_session_probe() is None
