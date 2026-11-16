"""React lecture and recovery contracts through the authenticated public HTTP API."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_lecture_is_grounded_saved_and_exactly_recoverable(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Public lecture dispatch shares saved semantics and cannot award project progress."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "conversation.sqlite3")
    _seed_user(root, "student", "student")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(name="Lecture questions", model_id="mock", support_mode="critical-thinking")
    source = add_text_source(student, thread, "Analogy notes", "Analogy transfers a relationship from a familiar setting to a new design problem.")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    path = f"/api/v1/reader/threads/{thread}"
    request = {"student_message": "What is analogy?", "idempotency_key": "reader-lecture"}
    response = client.post(f"{path}/lecture/stream", json=request, headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["event"] == "started"
    assert events[0]["idempotency_key"] == "reader-lecture"
    kinds = [event["event"] for event in events]
    assert kinds.index("reply_ready") < kinds.index("done")
    turn = next(event["turn"] for event in events if event["event"] == "done")
    assert turn["assessment"]["response_mode"] == "qa"
    assert turn["assessment"]["recommendation"] is None
    assert turn["pending_transition"] is None
    assert "Analogy transfers" in turn["response_text"]
    assert turn["assessment"]["citations"][0]["source_id"] == source["id"]
    assert client.get(f"{path}/coach-turn?idempotency_key=unrelated").json() is None
    assert client.get(f"{path}/coach-turn?idempotency_key=reader-lecture").json() == turn
    replay = client.post(f"{path}/lecture/stream", json=request, headers={"Origin": "https://testserver"})
    assert any(event.get("turn") == turn for event in map(json.loads, replay.text.splitlines()))
    page = client.get(f"{path}/messages/page").json()
    assert page["total_count"] == 2
    assert page["messages"][-1]["citations"][0]["source_id"] == source["id"]
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    assert restarted.get(f"{path}/coach-turn?idempotency_key=reader-lecture").json() == turn


def test_reader_citation_opens_only_saved_owned_evidence(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Evidence follows the saved citation mapping, never an arbitrary source URL."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "citations.sqlite3")
    _seed_user(root, "student", "student")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(student, thread, "Analogy notes", "Analogy transfers relationships between designs.")
    uncited = add_text_source(student, thread, "Other notes", "Uncited confidential note.")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    path = f"/api/v1/reader/threads/{thread}"
    client.post(f"{path}/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "citation-turn"}, headers={"Origin": "https://testserver"})
    message = client.get(f"{path}/messages/page").json()["messages"][-1]
    url = f"{path}/messages/{message['id']}/citations/{source['id']}/content"
    evidence = client.get(url)
    assert evidence.status_code == 200
    assert evidence.content == b"Analogy transfers relationships between designs."
    assert evidence.headers["cache-control"] == "no-store"
    assert evidence.headers["x-content-type-options"] == "nosniff"
    assert evidence.headers["content-disposition"].startswith("attachment;")
    assert client.get(url.replace(source['id'], uncited['id'])).status_code == 404
    assert client.get(url.replace(message['id'], "missing-message")).status_code == 404


def test_reader_writes_require_credentials_origin_student_and_owned_notebook(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Browser generation cannot fall through anonymous mode or accept forged intent."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "guards.sqlite3")
    for name, role in (("student", "student"), ("other", "student"), ("staff", "lecturer")):
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    path = f"/api/v1/reader/threads/{thread}"
    payload = {"student_message": "What is analogy?", "idempotency_key": "guarded-turn"}
    origin = {"Origin": "https://testserver"}
    assert client.post(f"{path}/lecture/stream", json=payload, headers=origin).status_code == 401
    assert client.get(f"{path}/coach-turn?idempotency_key=guarded-turn").status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    for headers in ({}, {"Origin": "https://evil.test"}, {**origin, "Sec-Fetch-Site": "cross-site"}):
        assert client.post(f"{path}/lecture/stream", json=payload, headers=headers).status_code == 403
    for field, value in (("interaction_intent", "project_coaching"), ("current_stage", "reflection")):
        assert client.post(f"{path}/lecture/stream", json={**payload, field: value}, headers=origin).status_code == 422
    for identity, status in (("other", 404), ("staff", 403)):
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add(identity))
        assert client.post(f"{path}/lecture/stream", json=payload, headers=origin).status_code == status
        assert client.get(f"{path}/coach-turn?idempotency_key=guarded-turn").status_code == status
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    assert client.get(f"{path}/messages/page").json()["total_count"] == 0


def test_reader_failed_save_never_recovers_preview(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A storage failure clears preview authority and returns no durable recovery result."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "failure.sqlite3")
    _seed_user(root, "student", "student")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))

    def unavailable_storage(*args: object, **kwargs: object) -> None:
        """Simulate a storage outage at the existing durable write boundary."""
        raise OSError("private storage failure details")

    monkeypatch.setattr(StudentStore, "persist_coach_turn", unavailable_storage)
    path = f"/api/v1/reader/threads/{thread}"
    response = client.post(f"{path}/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "failed-save"}, headers={"Origin": "https://testserver"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(event["event"] == "reply_ready" for event in events)
    assert events[-1]["event"] == "error"
    assert all(event["event"] != "done" for event in events)
    assert "private storage" not in response.text
    assert client.get(f"{path}/coach-turn?idempotency_key=failed-save").json() is None
    assert client.get(f"{path}/messages/page").json()["total_count"] == 0


def test_reader_evidence_respects_superseded_messages_and_owner(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A citation loses access when its answer is superseded and never crosses owners."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "active-evidence.sqlite3")
    for name, role in (("student", "student"), ("other", "student"), ("staff", "lecturer")):
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(student, thread, "Analogy", "Analogy transfers relationships between designs.")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    path = f"/api/v1/reader/threads/{thread}"
    client.post(f"{path}/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "active-answer"}, headers={"Origin": "https://testserver"})
    messages = client.get(f"{path}/messages/page").json()["messages"]
    citation = messages[-1]["citations"][0]
    url = f"{path}/messages/{messages[-1]['id']}/citations/{citation['source_id']}/content"
    for identity, status in (("other", 404), ("staff", 403)):
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add(identity))
        assert client.get(url).status_code == status
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    assert client.get(url).status_code == 200
    revised = client.post(f"/api/v1/threads/{thread}/messages/{messages[0]['id']}/revise", json={"content": "Explain analogy again.", "idempotency_key": "revised-answer"})
    assert revised.status_code == 200
    assert client.get(url).status_code == 404
