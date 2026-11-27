"""Workspace parity verified through the authenticated public browser HTTP seam."""
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_notebook_lifecycle_export_and_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Create/rename/export/delete use existing durable notebook contracts without data loss."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'workspace.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    response = client.post('/api/v1/reader/threads', json={'name': 'Crossing study'}, headers=origin)
    assert response.status_code == 200
    notebook = response.json()['notebook']
    path = f"/api/v1/reader/threads/{notebook['id']}"
    assert client.post(f'{path}/settings', json={'name': 'Residents crossing'}, headers=origin).status_code == 200
    assert client.get('/api/v1/reader/threads').json()['notebooks'][0]['name'] == 'Residents crossing'
    export = client.get(f'{path}/transcript.txt')
    assert export.status_code == 200
    assert 'Residents crossing' in export.text
    assert export.headers['cache-control'] == 'no-store'
    assert 'attachment;' in export.headers['content-disposition']
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    assert restarted.get('/api/v1/reader/threads').json() == client.get('/api/v1/reader/threads').json()
    assert client.post(f'{path}/remove', json={'confirmed': False}, headers=origin).status_code == 422
    assert client.get(f'{path}/settings').status_code == 200
    assert client.post(f'{path}/remove', json={'confirmed': True}, headers=origin).status_code == 200
    assert client.get(f'{path}/transcript.txt').status_code == 404
    assert client.get('/api/v1/reader/threads').json()['notebooks'] == []


def test_reader_preferences_preserve_learning_and_private_keys(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Theme and notebook response controls persist without exposing or rewriting learning fields."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'preferences.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Preferences'}, headers=origin).json()['notebook']['id']
    path = f'/api/v1/reader/threads/{thread}'
    before = client.get(f'{path}/project').json()
    response = client.post('/api/v1/reader/preferences', json={'appearance': 'Dark'}, headers=origin)
    assert response.status_code == 200
    assert response.json()['appearance'] == 'Dark'
    presentation = {
        'display_name': 'Studio student', 'reduce_motion': True,
        'default_mode': 'project', 'starter_prompts': False,
    }
    updated = client.post('/api/v1/reader/preferences', json=presentation, headers=origin)
    assert updated.status_code == 200
    assert all(updated.json()[key] == value for key, value in presentation.items())
    assert updated.json()['appearance'] == 'Dark'
    response = client.post(f'{path}/settings', json={'response_detail': 'long', 'response_language': '中文',
        'assignment': {'title': 'Accessible crossings', 'brief': 'Investigate residents needs'}}, headers=origin)
    assert response.status_code == 200
    assert response.json()['response_detail'] == 'long'
    assert response.json()['response_language'] == '中文'
    assert response.json()['assignment']['title'] == 'Accessible crossings'
    assert client.get(f'{path}/project').json() == before
    assert client.post(f'{path}/settings', json={'learning_journey': {'current_stage': 'reflection'}}, headers=origin).status_code == 422
    assert client.post('/api/v1/reader/preferences', json={'appearance': 'unknown'}, headers=origin).status_code == 422
    assert client.get('/api/v1/reader/preferences').json()['appearance'] == 'Dark'
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    assert restarted.get(f'{path}/settings').json() == client.get(f'{path}/settings').json()
    assert restarted.get('/api/v1/reader/preferences').json() == updated.json()


def test_reader_message_edit_feedback_and_exact_recovery(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Edits reuse append-only revisions and exact-key recovery; eligible feedback persists."""
    import json
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'messages.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Lecture'}, headers=origin).json()['notebook']['id']
    path = f'/api/v1/reader/threads/{thread}'
    response = client.post(f'{path}/lecture/stream', json={'student_message': 'Explain analogy', 'idempotency_key': 'original'}, headers=origin)
    assert response.status_code == 200
    assert any(event['event'] == 'done' for event in map(json.loads, response.text.splitlines()))
    page = client.get(f'{path}/messages/page').json()
    user, answer = page['messages'][-2:]
    feedback = client.post(f"{path}/messages/{answer['id']}/learning-signal", json={'kind': 'useful'}, headers=origin)
    assert feedback.status_code == 200
    assert feedback.json()['signals']['rating']['kind'] == 'useful'
    assert client.get(f'{path}/messages/page').json()['messages'][-1]['rating'] == 'useful'
    response = client.post(f"{path}/messages/{user['id']}/revise", json={'content': 'Explain analogy with a comparison', 'idempotency_key': 'revised'}, headers=origin)
    assert response.status_code == 200
    saved = client.get(f'{path}/coach-turn?idempotency_key=revised').json()
    assert saved == response.json()
    updated = client.get(f'{path}/messages/page').json()
    assert updated['conversation_revision'] > page['conversation_revision']
    assert updated['messages'][-2]['content'] == 'Explain analogy with a comparison'
    assert user['id'] not in [row['id'] for row in updated['messages']]
    assert client.post(f"{path}/messages/{user['id']}/revise", json={'content': 'Explain analogy with a comparison', 'idempotency_key': 'revised'}, headers=origin).json() == saved
    assert 'Explain analogy with a comparison' in client.get(f'{path}/transcript.txt').text


def test_reader_workspace_guards_and_existing_data(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Every added browser route rejects missing credentials, staff, foreign owners and CSRF."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'guards.sqlite3')
    for name, role in [('student', 'student'), ('other', 'student'), ('staff', 'lecturer')]:
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Existing data', model_id='mock', support_mode='critical-thinking')
    student.update_user_preferences({'appearance': 'Light', 'private_existing_key': 'preserve'})
    user = student.add_message(thread, 'user', 'My earlier reasoning')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    path = f'/api/v1/reader/threads/{thread}'
    reads = ['/api/v1/reader/preferences', f'{path}/settings', f'{path}/transcript.txt']
    writes = [('/api/v1/reader/preferences', {'appearance': 'Dark'}),
        ('/api/v1/reader/threads', {'name': 'Owned new notebook'}),
        (f'{path}/settings', {'name': 'Rename'}), (f'{path}/remove', {'confirmed': True}),
        (f'{path}/move', {'parent_notebook_id': None}),
        (f'{path}/messages/{user}/revise', {'content': 'Replacement', 'idempotency_key': 'edit-guard'}),
        (f'{path}/messages/{user}/learning-signal', {'kind': 'useful'})]
    origin = {'Origin': 'https://testserver'}
    for route in reads:
        assert client.get(route).status_code == 401
    for route, body in writes:
        assert client.post(route, json=body, headers=origin).status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('staff'))
    for route in reads:
        assert client.get(route).status_code == 403
    for route, body in writes:
        assert client.post(route, json=body, headers=origin).status_code == 403
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    for route in reads[1:]:
        assert client.get(route).status_code == 404
    for route, body in writes[2:]:
        assert client.post(route, json=body, headers=origin).status_code == 404
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    for route, body in writes:
        assert client.post(route, json=body).status_code == 403
        assert client.post(route, json=body, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.get(f'{path}/settings').json()['notebook']['name'] == 'Existing data'
    assert 'My earlier reasoning' in client.get(f'{path}/transcript.txt').text
    assert 'private_existing_key' not in client.get('/api/v1/reader/preferences').json()
    assert client.post('/api/v1/reader/preferences', json={'appearance': 'Dark'}, headers=origin).status_code == 200
    assert client.get('/api/v1/preferences').json()['private_existing_key'] == 'preserve'
    assert client.post(f'{path}/settings', json={'selected_model': 'invented'}, headers=origin).status_code == 422
    assert client.post(f'{path}/settings', json={'reasoning_effort': 'invented'}, headers=origin).status_code == 422


def test_reader_workspace_open_is_bounded_and_owner_fenced(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """One bounded open read returns page, project, bookmarks and settings without source bodies."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'workspace-open.sqlite3')
    for name, role in [('student', 'student'), ('other', 'student'), ('staff', 'lecturer')]:
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Crossing study', model_id='mock', support_mode='critical-thinking',
                                   reader_notebook=True)
    for index in range(25):
        student.add_message(thread, 'user', f'Message {index}')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    path = f'/api/v1/reader/threads/{thread}'
    starred = client.get(f'{path}/messages/page', params={'limit': 1}).json()['messages'][0]['id']
    assert client.post(f'{path}/messages/{starred}/star', json={'starred': True}, headers=origin).status_code == 200

    response = client.get(f'{path}/workspace', headers=origin)
    assert response.status_code == 200
    workspace = response.json()
    assert set(workspace) == {'owner_id', 'page', 'project', 'bookmarks', 'settings'}
    assert workspace['owner_id'] == client.get('/api/v1/reader/session', headers=origin).json()['owner_id']
    assert workspace['page']['total_count'] == 25
    assert len(workspace['page']['messages']) == 20
    assert workspace['page'] == client.get(f'{path}/messages/page').json()
    assert workspace['project']['thread_id'] == thread
    assert workspace['bookmarks']['thread_id'] == thread
    assert [item['id'] for item in workspace['bookmarks']['messages']] == [starred]
    assert workspace['settings']['notebook']['id'] == thread
    assert workspace['settings']['notebook']['kind'] == 'notebook'
    assert 'sources' not in workspace and 'transcript' not in workspace

    assert client.get('/api/v1/reader/threads/unknown/workspace', headers=origin).status_code == 404
    anonymous = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    assert anonymous.get(f'{path}/workspace', headers=origin).status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('staff'))
    assert client.get(f'{path}/workspace', headers=origin).status_code == 403
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(f'{path}/workspace', headers=origin).status_code == 404


def test_reader_quick_chats_are_separate_from_named_notebooks(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Classify new quick chats durably and show pre-existing conversations as chats."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "quick-chats.sqlite3")
    _seed_user(root, "student", "student")
    _seed_user(root, "other", "student")
    old_id = StudentStore(root.path, identifier="cognito:student").create_thread(
        name="New Chat", model_id="mock", support_mode="critical-thinking",
    )
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    origin = {"Origin": "https://testserver"}
    endpoint = "/api/v1/reader/threads"

    assert client.post(endpoint, json={}, headers=origin).status_code == 422
    assert client.post(endpoint, json={"kind": "chat", "name": "A name"}, headers=origin).status_code == 422
    notebook = client.post(endpoint, json={"name": "Studio project"}, headers=origin).json()["notebook"]
    quick_response = client.post(endpoint, json={"kind": "chat"}, headers=origin)
    assert quick_response.status_code == 200
    quick = quick_response.json()["notebook"]
    assert quick["name"] == "New Chat"
    assert quick["kind"] == "chat"
    assert notebook["kind"] == "notebook"
    assert quick["pinned"] is False

    path = f"{endpoint}/{quick['id']}"
    assert client.post(f"{endpoint}/{notebook['id']}/settings", json={"pinned": True}, headers=origin).status_code == 422
    assert client.post(f"{path}/settings", json={"pinned": "yes"}, headers=origin).status_code == 422
    assert client.post(f"{path}/settings", json={"pinned": True}, headers=origin).json()["notebook"]["pinned"] is True
    request = {"student_message": "What is analogy?", "idempotency_key": "quick-chat-turn"}
    response = client.post(path + "/lecture/stream", json=request, headers=origin)
    assert response.status_code == 200
    assert '"event": "done"' in response.text

    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    page = restarted.get(path + "/messages/page").json()
    assert page["notebook"]["kind"] == "chat"
    assert page["notebook"]["pinned"] is True
    assert page["messages"][0]["content"] == "What is analogy?"
    entries = {item["id"]: item for item in restarted.get(endpoint).json()["notebooks"]}
    assert entries[old_id]["kind"] == "chat"
    assert entries[quick["id"]] == page["notebook"]
    assert restarted.post(f"{path}/settings", json={"pinned": False}, headers=origin).json()["notebook"]["pinned"] is False

    restarted.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("other"))
    assert restarted.get(endpoint).json()["notebooks"] == []
    assert restarted.get(path + "/messages/page").status_code == 404


def test_reader_moves_chat_without_changing_its_saved_work(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Persist moves for owned chats and recover orphaned chats when a notebook is deleted."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "move-chat.sqlite3")
    for subject in ("student", "other"):
        _seed_user(root, subject, "student")
    student = StudentStore(root.path, identifier="cognito:student")
    other = StudentStore(root.path, identifier="cognito:other")
    defaults = {"model_id": "mock", "support_mode": "critical-thinking"}
    chat = student.create_thread(quick_chat=True, **defaults)
    first = student.create_thread(name="First notebook", reader_notebook=True, **defaults)
    second = student.create_thread(name="Second notebook", reader_notebook=True, **defaults)
    foreign = other.create_thread(name="Private notebook", reader_notebook=True, **defaults)
    student.add_message(chat, "user", "Why are quiet study rooms hard to find?")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    endpoint = "/api/v1/reader/threads"
    path = f"{endpoint}/{chat}"
    origin = {"Origin": "https://testserver"}
    before = client.get(f"{path}/messages/page").json()
    project_before = client.get(f"{path}/project").json()
    assert before["notebook"]["parent_notebook_id"] is None
    assert client.post(f"{path}/move", json={}, headers=origin).status_code == 422
    for invalid in (foreign, chat):
        assert client.post(f"{path}/move", json={"parent_notebook_id": invalid}, headers=origin).status_code == 404
    assert client.post(f"{endpoint}/{first}/move", json={"parent_notebook_id": second}, headers=origin).status_code == 422

    for destination in (first, second, None, first, first):
        moved = client.post(f"{path}/move", json={"parent_notebook_id": destination}, headers=origin)
        assert moved.status_code == 200
        assert moved.json()["notebook"] == {**before["notebook"], "parent_notebook_id": destination}
        assert client.get(f"{path}/project").json() == project_before
        assert client.get(f"{path}/messages/page").json() == {**before, "notebook": moved.json()["notebook"]}

    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    entries = {entry["id"]: entry for entry in restarted.get(endpoint).json()["notebooks"]}
    assert entries[chat]["parent_notebook_id"] == first
    assert restarted.post(f"{endpoint}/{first}/remove", json={"confirmed": True}, headers=origin).status_code == 200
    entries = {entry["id"]: entry for entry in restarted.get(endpoint).json()["notebooks"]}
    assert entries[chat] == before["notebook"]
    assert restarted.get(f"{path}/messages/page").json() == before


def test_reader_folder_chats_use_existing_history_and_owner_scoped_summaries(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """Create directly in a notebook while preserving the root conversation ID and recency."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    root = StudentStore(tmp_path / "folders.sqlite3")
    for subject in ("student", "other"):
        _seed_user(root, subject, "student")
    other = StudentStore(root.path, identifier="cognito:other")
    foreign = other.create_thread(name="Other folder", model_id="mock", support_mode="critical-thinking", reader_notebook=True)
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    endpoint = "/api/v1/reader/threads"
    origin = {"Origin": "https://testserver"}
    folder = client.post(endpoint, json={"name": "Research"}, headers=origin).json()["notebook"]["id"]
    assert folder not in client.get(endpoint).json()["chat_summaries"]
    assert client.post(endpoint, json={"kind": "chat", "parent_notebook_id": foreign}, headers=origin).status_code == 404
    assert client.post(endpoint, json={"name": "Bad", "parent_notebook_id": folder}, headers=origin).status_code == 422
    response = client.post(endpoint, json={"kind": "chat", "parent_notebook_id": folder}, headers=origin)
    assert response.status_code == 200
    child = response.json()["notebook"]
    assert child["parent_notebook_id"] == folder
    assert client.post(endpoint, json={"kind": "chat", "parent_notebook_id": child["id"]}, headers=origin).status_code == 404

    student = StudentStore(root.path, identifier="cognito:student")
    original_message = student.add_message(folder, "user", "Original discussion\nabout crossing design")
    original_page = client.get(f"{endpoint}/{folder}/messages/page").json()
    student.add_message(child["id"], "user", "The new conversation " * 40)
    summaries = client.get(endpoint).json()["chat_summaries"]
    assert summaries[folder]["preview"] == "Original discussion about crossing design"
    assert 0 < len(summaries[child["id"]]["preview"]) <= 160
    assert summaries[child["id"]]["activity_at"] >= summaries[folder]["activity_at"]
    assert client.post(f"{endpoint}/{folder}/settings", json={"name": "Renamed notebook"}, headers=origin).status_code == 200
    assert client.get(endpoint).json()["chat_summaries"] == summaries
    assert client.get(f"{endpoint}/{folder}/messages/page").json()["messages"] == original_page["messages"]
    assert original_page["messages"][0]["id"] == original_message

    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    assert restarted.get(endpoint).json() == client.get(endpoint).json()
    restarted.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("other"))
    assert restarted.get(endpoint).json()["chat_summaries"] == {}
