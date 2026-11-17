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
