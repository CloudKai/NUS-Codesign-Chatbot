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
    greeting = client.post(f"{path}/lecture/stream", json={
        "student_message": "hi", "idempotency_key": "reader-lecture-greeting",
    }, headers={"Origin": "https://testserver"})
    greeted = [json.loads(line) for line in greeting.text.splitlines()][-1]["turn"]
    assert greeted["response_text"] == "Hi! What CDE2300 lecture, reading, or course concept would you like help with?"
    assert greeted["assessment"]["response_mode"] == "qa"
    assert greeted["pending_transition"] is None
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


def test_reader_revision_streams_reply_then_saves_and_replays_once(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """An owned streamed edit retains append-only revision and exact-key recovery."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    from backend.workflow import CoachWorkflow

    observed_languages: list[str] = []
    original_run = CoachWorkflow.run

    def observe_language(workflow, request):
        observed_languages.append(request.response_language)
        return original_run(workflow, request)

    monkeypatch.setattr(CoachWorkflow, 'run', observe_language)
    root = StudentStore(tmp_path / 'stream-edit.sqlite3')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    student.update_thread(thread, metadata={"response_language": "Bahasa Melayu"})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    base = f'/api/v1/reader/threads/{thread}'
    headers = {'Origin': 'https://testserver', 'X-Coach-Reply-Deltas': '1'}
    seed = client.post(base + '/project/stream', json={'student_message': 'Residents need safer crossings.', 'idempotency_key': 'seed'}, headers=headers)
    assert seed.status_code == 200
    messages = client.get(base + '/messages/page').json()['messages']
    path = base + f"/messages/{messages[0]['id']}/revise/stream"
    payload = {'content': 'Older residents need longer crossing times near the market.', 'idempotency_key': 'edit-stream'}
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/x-ndjson')
    events = [json.loads(line) for line in response.text.splitlines()]
    kinds = [item['event'] for item in events]
    assert kinds[0] == 'started' and kinds[-1] == 'done'
    assert kinds.index('reply_delta') < kinds.index('reply_ready') < kinds.index('done')
    saved = client.get(base + '/messages/page').json()
    assert len(saved['messages']) == 2
    assert saved['messages'][0]['content'] == payload['content']
    assert client.get(base + '/coach-turn?idempotency_key=edit-stream').json() == events[-1]['turn']
    replay = client.post(path, json=payload, headers=headers)
    replay_events = [json.loads(line) for line in replay.text.splitlines()]
    assert replay_events[-1] == events[-1]
    assert not any(item['event'] == 'reply_delta' for item in replay_events)
    assert client.get(base + '/messages/page').json() == saved

    assert observed_languages == ['English', 'English']
    assert student.get_thread(thread)['metadata']['response_language'] == 'Bahasa Melayu'


def test_reader_stop_is_owner_scoped_and_prevents_saving(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stop an in-flight turn, leave the transcript intact, and allow an explicit retry."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from backend.coaching.progress import emit_coach_reply_delta
    from backend.workflow import CoachWorkflow

    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "coach_stream_reply_deltas_enabled", True)
    root = StudentStore(tmp_path / "cancel.sqlite3")
    for subject in ("student", "other"):
        _seed_user(root, subject, "student")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    oidc = FakeOIDC(root)
    app = create_app(root, oidc_client=oidc)
    client = TestClient(app, base_url="https://testserver")
    foreign = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    foreign.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("other"))
    path = f"/api/v1/reader/threads/{thread}"
    origin = {"Origin": "https://testserver", "X-Coach-Reply-Deltas": "1"}
    request = {"student_message": "Older residents need safer crossings near the market.", "idempotency_key": "stop-test"}
    key = {"idempotency_key": request["idempotency_key"]}
    running, release = Event(), Event()
    original_run = CoachWorkflow.run

    def paused_run(workflow, model_request):
        if not release.is_set():
            emit_coach_reply_delta("Unfinished preview")
            running.set()
            assert release.wait(10)
        return original_run(workflow, model_request)

    monkeypatch.setattr(CoachWorkflow, "run", paused_run)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(client.post, f"{path}/project/stream", json=request, headers=origin)
        try:
            assert running.wait(10)
            assert foreign.post(f"{path}/coach-turn/stop", json=key, headers=origin).status_code == 404
            assert client.post(f"{path}/coach-turn/stop", json=key, headers=origin).json() == {"status": "stopping"}
        finally:
            release.set()
        response = result.result(timeout=10)
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-2]["event"] == "reply_discard"
    assert events[-1]["category"] == "cancelled"
    assert client.get(f"{path}/messages/page").json()["total_count"] == 0
    assert client.get(f"{path}/coach-turn", params=key).json() is None
    assert '"event": "done"' in client.post(f"{path}/project/stream", json=request, headers=origin).text
    assert client.post(f"{path}/coach-turn/stop", json=key, headers=origin).json() == {"status": "finished"}
    assert client.get(f"{path}/messages/page").json()["total_count"] == 2


def test_reader_stop_keeps_reply_when_saving_already_started(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stop cannot withdraw a reply that has won the save race."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "stop-saving.sqlite3")
    _seed_user(root, "student", "student")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(model_id="mock", support_mode="critical-thinking")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    path = f"/api/v1/reader/threads/{thread}"
    origin = {"Origin": "https://testserver"}
    request = {"student_message": "Older residents need safer crossings.", "idempotency_key": "stop-saving"}
    saving, release = Event(), Event()
    persist = StudentStore.persist_coach_turn

    def paused_save(store, *args, **kwargs):
        saving.set()
        assert release.wait(10)
        return persist(store, *args, **kwargs)

    monkeypatch.setattr(StudentStore, "persist_coach_turn", paused_save)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(client.post, f"{path}/project/stream", json=request, headers=origin)
        try:
            assert saving.wait(10)
            response = client.post(f"{path}/coach-turn/stop", json={"idempotency_key": "stop-saving"}, headers=origin)
            assert response.json() == {"status": "saving"}
        finally:
            release.set()
        assert '"event": "done"' in result.result(timeout=10).text
    assert client.get(f"{path}/messages/page").json()["total_count"] == 2
