"""Student journey readiness walk through the public reader routes (mock provider only)."""

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.learning.stages import THINKING_STAGES
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {"Origin": "https://testserver"}
ANALOGY = "Analogy transfers a relationship from a familiar setting to a new design problem."


def _done(response: Any) -> dict[str, Any]:
    """Return the saved turn from a streamed reader response."""
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["event"] == "started"
    return next(event["turn"] for event in events if event["event"] == "done")


def _guest_client(root: StudentStore, monkeypatch: MonkeyPatch, **options: Any) -> TestClient:
    """Return a client signed in through the explicit guest start route."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "ui_base_url", "https://testserver")
    client = TestClient(create_app(root, oidc_client=FakeOIDC(root), **options), base_url="https://testserver")
    assert client.post("/api/v1/auth/guest/start", headers=ORIGIN).status_code == 200
    return client


def _registered_client(root: StudentStore, monkeypatch: MonkeyPatch, **options: Any) -> TestClient:
    """Return a client signed in as the seeded registered student."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    _seed_user(root, "student", "student")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc, **options), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    return client


def _wait_for_source(client: TestClient, path: str, title: str) -> dict[str, Any]:
    """Poll the source list until a background upload becomes visible."""
    for _ in range(300):
        rows = client.get(path + "/sources").json()["sources"]
        found = next((row for row in rows if row["title"] == title), None)
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError("Upload did not become visible")


def test_sign_in_state_for_guest_and_registered_students(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guest start and registered sign-in each yield a student session; /auth/me is Cognito-only."""
    guest = _guest_client(StudentStore(tmp_path / "guest.sqlite3"), monkeypatch)
    session = guest.get("/api/v1/reader/session")
    assert session.status_code == 200
    assert session.json()["kind"] == "guest"
    assert guest.get("/api/v1/auth/me").status_code == 401
    registered = _registered_client(StudentStore(tmp_path / "registered.sqlite3"), monkeypatch)
    me = registered.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "student"
    assert "token" not in me.text.lower()
    assert registered.get("/api/v1/reader/session").json()["kind"] == "registered"


def test_guest_lecture_help_cites_notes_and_survives_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A new chat answers a lecture question with [S#] citations whose content opens."""
    root = StudentStore(tmp_path / "lecture.sqlite3")
    client = _guest_client(root, monkeypatch)
    with client:
        chat = client.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
        path = f"/api/v1/reader/threads/{chat}"
        uploaded = client.post(path + "/uploads", files={"files": ("analogy.txt", ANALOGY.encode(), "text/plain")}, headers=ORIGIN)
        assert uploaded.status_code == 202
        source = _wait_for_source(client, path, "analogy.txt")
        turn = _done(client.post(path + "/lecture/stream", json={
            "student_message": "What is analogy?", "idempotency_key": "lecture-1",
        }, headers=ORIGIN))
        assert turn["assessment"]["response_mode"] == "qa"
        assert turn["pending_transition"] is None
        assert "[S1]" in turn["response_text"]
        assert [item["source_id"] for item in turn["assessment"]["citations"]] == [source["id"]]
        message = client.get(path + "/messages/page").json()["messages"][-1]
        assert message["citations"][0]["source_id"] == source["id"]
        content = client.get(path + f"/messages/{message['id']}/citations/{source['id']}/content")
        assert content.status_code == 200
        assert ANALOGY.encode() in content.content
        restarted = TestClient(create_app(StudentStore(root.path), oidc_client=FakeOIDC(root)), base_url="https://testserver")
        restarted.cookies.update(client.cookies)
        again = restarted.get(path + "/messages/page").json()
        assert again["messages"][-1]["citations"] == message["citations"]
        assert again["total_count"] == 2


def test_five_stage_journey_with_move_on_and_stay_here(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Every Thinking Path stage needs an explicit decision; Review fills in and restart keeps it all."""
    root = StudentStore(tmp_path / "journey.sqlite3")
    client = _registered_client(root, monkeypatch, auto_advance_stages=False)
    thread = client.post("/api/v1/reader/threads", json={"name": "Crossings"}, headers=ORIGIN).json()["notebook"]["id"]
    path = f"/api/v1/reader/threads/{thread}"
    stage_ids = [stage.id for stage in THINKING_STAGES]
    assert len(stage_ids) == 5
    turns = 0

    def coach(stage: str, text: str) -> dict[str, Any]:
        nonlocal turns
        turns += 1
        view = client.get(path + "/project").json()
        assert view["current_stage"] == stage
        return _done(client.post(path + "/project/stream", json={
            "student_message": text, "idempotency_key": f"coach-{turns}",
        }, headers=ORIGIN))

    for index, stage in enumerate(stage_ids):
        first = coach(stage, f"Older residents struggle to cross safely, stage {index} first idea.")
        if first["pending_transition"] is None:
            second = coach(stage, f"Older residents need more time at the crossing, stage {index} detail.")
            pending = second["pending_transition"]
        else:
            pending = first["pending_transition"]
        if index == len(stage_ids) - 1:
            # The last stage has nowhere to go: no move is proposed, and its own coaching turns complete it.
            assert pending is None
            break
        assert pending is not None
        view = client.get(path + "/project").json()
        assert view["pending"]["id"] == pending["id"]
        assert view["current_stage"] == stage
        assert not view["stages"][index]["completed"]
        stay = client.post(path + f"/project/resolve/{pending['id']}", json={"accepted": False}, headers=ORIGIN)
        assert stay.status_code == 200
        assert stay.json()["current_stage"] == stage
        assert stay.json()["pending"] is None
        assert not stay.json()["stages"][index]["completed"]
        again = coach(stage, f"Older residents also need a refuge island, stage {index} revision.")
        assert again["pending_transition"] is not None
        moved = client.post(path + f"/project/resolve/{again['pending_transition']['id']}", json={"accepted": True}, headers=ORIGIN)
        assert moved.status_code == 200
        assert moved.json()["current_stage"] == stage_ids[index + 1]
        assert moved.json()["stages"][index]["completed"]
    view = client.get(path + "/project").json()
    assert view["current_stage"] == "reflection"
    assert [stage["completed"] for stage in view["stages"]] == [True] * 5
    review = view["review"]
    assert review["summary"]
    assert any(section["items"] for section in review["strengths"])
    assert any(section["items"] for section in review["improvements"])
    assert [item["dimension"] for item in review["facione_scores"]] == [
        "Analysis", "Interpretation", "Inference", "Evaluation", "Explanation", "Self-Regulation",
    ]
    assert any(item["score"] for item in review["facione_scores"])
    for _ in range(300):  # The stage checkpoint for the last stage is saved by a background job.
        view = client.get(path + "/project").json()
        if any(section["stage_id"] == "reflection" and section["items"] for section in view["review"]["strengths"]):
            break
        time.sleep(0.01)
    oidc = FakeOIDC(root)
    oidc.add("student")
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc, auto_advance_stages=False), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    assert restarted.get(path + "/project").json() == view
    restored = restarted.get(path + "/messages/page?limit=100").json()
    assert restored["total_count"] == turns * 2


def test_source_upload_select_remove_and_attachment_flow(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Upload, deselect, reselect and remove a source, and use a composer attachment once."""
    root = StudentStore(tmp_path / "sources.sqlite3")
    client = _guest_client(root, monkeypatch)
    with client:
        thread = client.post("/api/v1/reader/threads", json={"name": "Sources"}, headers=ORIGIN).json()["notebook"]["id"]
        path = f"/api/v1/reader/threads/{thread}"
        assert client.post(path + "/uploads", files={"files": ("notes.txt", ANALOGY.encode(), "text/plain")}, headers=ORIGIN).status_code == 202
        source = _wait_for_source(client, path, "notes.txt")
        assert source["selected"]
        assert client.post(path + f"/sources/{source['id']}/select", json={"selected": False}, headers=ORIGIN).status_code == 200
        off = _done(client.post(path + "/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "off"}, headers=ORIGIN))
        assert off["assessment"]["citations"] == []
        assert client.post(path + f"/sources/{source['id']}/select", json={"selected": True}, headers=ORIGIN).status_code == 200
        on = _done(client.post(path + "/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "on"}, headers=ORIGIN))
        assert [item["source_id"] for item in on["assessment"]["citations"]] == [source["id"]]
        attachment = client.post(path + "/attachments", files={"files": ("extra.txt", b"Empathy mapping records what users say, think, do and feel.", "text/plain")}, headers=ORIGIN)
        assert attachment.status_code == 200, attachment.text
        attached = attachment.json()[0]["id"]
        turn = _done(client.post(path + "/lecture/stream", json={
            "student_message": "Summarise the attached file.", "idempotency_key": "attached", "attachment_source_ids": [attached],
        }, headers=ORIGIN))
        assert attached in {item["source_id"] for item in turn["assessment"]["citations"]}
        assert attached not in {row["id"] for row in client.get(path + "/sources").json()["sources"]}
        assert client.post(path + f"/sources/{source['id']}/remove", headers=ORIGIN).status_code == 200
        assert source["id"] not in {row["id"] for row in client.get(path + "/sources").json()["sources"]}
        gone = _done(client.post(path + "/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "gone"}, headers=ORIGIN))
        assert gone["assessment"]["citations"] == []


def test_edit_and_retry_replace_the_answer_and_keep_one_branch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Editing a question replaces the old pair; retrying the same key returns the saved answer."""
    root = StudentStore(tmp_path / "revise.sqlite3")
    client = _guest_client(root, monkeypatch)
    thread = client.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    path = f"/api/v1/reader/threads/{thread}"
    _done(client.post(path + "/lecture/stream", json={"student_message": "What is analogy?", "idempotency_key": "q1"}, headers=ORIGIN))
    user, old_answer = client.get(path + "/messages/page").json()["messages"][-2:]
    edit = {"content": "What is analogy in design?", "idempotency_key": "q1-edit"}
    revised = client.post(path + f"/messages/{user['id']}/revise", json=edit, headers=ORIGIN)
    assert revised.status_code == 200, revised.text
    assert revised.json()["assessment"]["response_mode"] == "qa"
    assert revised.json()["response_text"] != ""
    retry = client.post(path + f"/messages/{user['id']}/revise", json=edit, headers=ORIGIN)
    assert retry.status_code == 200
    assert retry.json() == revised.json()
    page = client.get(path + "/messages/page").json()
    assert [row["content"] for row in page["messages"] if row["role"] == "user"] == ["What is analogy in design?"]
    assert page["total_count"] == 2
    assert old_answer["id"] not in [row["id"] for row in page["messages"]]
    # A retried send with a fresh key after the edit adds exactly one new question and answer.
    _done(client.post(path + "/lecture/stream", json={"student_message": "Explain it again.", "idempotency_key": "q2"}, headers=ORIGIN))
    assert client.get(path + "/messages/page").json()["total_count"] == 4
    # Replaying the same key saves nothing new.
    _done(client.post(path + "/lecture/stream", json={"student_message": "Explain it again.", "idempotency_key": "q2"}, headers=ORIGIN))
    assert client.get(path + "/messages/page").json()["total_count"] == 4

