"""Message bookmark behavior at the authenticated browser HTTP boundary."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_owner_sets_explicit_star_state_and_reads_it_back(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Both authors default unstarred; repeated desired states persist without coaching changes."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'stars.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'kind': 'chat'}, headers=origin).json()['notebook']['id']
    path = f'/api/v1/reader/threads/{thread}'
    response = client.post(f'{path}/lecture/stream', json={'student_message': 'Explain analogy', 'idempotency_key': 'original'}, headers=origin)
    assert any(event['event'] == 'done' for event in map(json.loads, response.text.splitlines()))
    before = client.get(f'{path}/messages/page').json()
    project = client.get(f'{path}/project').json()
    for message in before['messages']:
        route = f"{path}/messages/{message['id']}/star"
        for desired in (True, True, False, False, True):
            saved = client.post(route, json={'starred': desired}, headers=origin)
            assert saved.status_code == 200
            assert saved.json()['starred'] is desired
            readback = client.get(f'{path}/messages/page').json()
            assert next(row for row in readback['messages'] if row['id'] == message['id'])['starred'] is desired
    assert all(row['starred'] is False for row in before['messages'])
    assert client.get(f'{path}/project').json() == project
    assert client.get(f'{path}/messages/page').json()['conversation_revision'] == before['conversation_revision']


def test_bookmarks_are_complete_private_saved_context_and_restart_safe(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Legacy and old-page bookmarks use saved context, exclude internal rows and remain owner-scoped."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'bookmark-list.sqlite3')
    for subject in ('student', 'other'):
        _seed_user(root, subject, 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(name='History', model_id='mock', support_mode='critical-thinking')
    legacy = owner.add_message(thread, 'user', 'Legacy idea', metadata={'private': 'DO NOT EXPOSE', 'thinking_stage': ['invalid'], 'interaction_intent': {'old': True}})
    lecture = owner.add_message(thread, 'assistant', 'An explanation', metadata={
        'thinking_stage': 'concept_generation', 'interaction_intent': 'lecture_help'})
    internal = owner.add_message(thread, 'assistant', 'INTERNAL', metadata={'_internal_type': 'marker'})
    for index in range(25):
        owner.add_message(thread, 'user', f'Later idea {index}', metadata={'thinking_stage': 'reflection'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    origin = {'Origin': 'https://testserver'}
    for message in (legacy, lecture):
        assert client.post(f'{path}/messages/{message}/star', json={'starred': True}, headers=origin).status_code == 200
    response = client.get(f'{path}/bookmarks')
    assert response.status_code == 200
    bookmarks = response.json()
    assert [row['id'] for row in bookmarks['messages']] == [legacy, lecture]
    assert [(row['stage_id'], row['interaction_intent']) for row in bookmarks['messages']] == [
        (None, None), ('concept_generation', 'lecture_help')]
    assert 'DO NOT EXPOSE' not in response.text
    assert legacy not in [row['id'] for row in client.get(f'{path}/messages/page').json()['messages']]
    assert client.post(f'{path}/messages/{internal}/star', json={'starred': True}, headers=origin).status_code == 404
    assert client.post(f'{path}/messages/{legacy}/star', json={'starred': 'true'}, headers=origin).status_code == 422
    assert client.post(f'{path}/messages/{legacy}/star', json={'starred': True}).status_code == 403
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    assert restarted.get(f'{path}/bookmarks').json() == bookmarks
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(f'{path}/bookmarks').status_code == 404
    assert client.post(f'{path}/messages/{legacy}/star', json={'starred': False}, headers=origin).status_code == 404
    client.cookies.clear()
    assert client.get(f'{path}/bookmarks').status_code == 401


def test_revised_messages_need_new_stars_and_removed_originals_are_unavailable(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """An edit removes replaced bookmarks and starts its replacement unstarred."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'revisions.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'kind': 'chat'}, headers=origin).json()['notebook']['id']
    path = f'/api/v1/reader/threads/{thread}'
    response = client.post(f'{path}/lecture/stream', json={'student_message': 'Explain analogy', 'idempotency_key': 'old'}, headers=origin)
    assert any(event['event'] == 'done' for event in map(json.loads, response.text.splitlines()))
    original = client.get(f'{path}/messages/page').json()['messages']
    for row in original:
        assert client.post(f"{path}/messages/{row['id']}/star", json={'starred': True}, headers=origin).status_code == 200
    response = client.post(f"{path}/messages/{original[0]['id']}/revise", json={
        'content': 'Explain analogy with a comparison', 'idempotency_key': 'new'}, headers=origin)
    assert response.status_code == 200
    page = client.get(f'{path}/messages/page').json()
    assert all(row['starred'] is False for row in page['messages'])
    bookmarks = client.get(f'{path}/bookmarks').json()
    assert bookmarks['messages'] == []
    assert bookmarks['conversation_revision'] == page['conversation_revision']
    for row in original:
        assert client.post(f"{path}/messages/{row['id']}/star", json={'starred': True}, headers=origin).status_code == 404
    assert client.post(f'{path}/remove', json={'confirmed': True}, headers=origin).status_code == 200
    assert client.get(f'{path}/bookmarks').status_code == 404


def test_star_preserves_concurrent_ratings_transcript_and_saved_stage(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Independent message writes merge without losing receipts, new turns or frozen context."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'concurrent.sqlite3')
    _seed_user(root, 'student', 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(name='Saved context', model_id='mock', support_mode='critical-thinking')
    answer = owner.add_message(thread, 'assistant', 'Saved explanation ' + 'x' * 600, metadata={
        'thinking_stage': 'concept_generation', 'interaction_intent': 'lecture_help', 'unrelated': 'private'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    origin = {'Origin': 'https://testserver'}
    def send(suffix: str, body: dict) -> int:
        """Submit one independent public write and return its HTTP status."""
        return client.post(path + suffix, json=body, headers=origin).status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(send, f'/messages/{answer}/star', {'starred': True}),
                pool.submit(send, f'/messages/{answer}/learning-signal', {'kind': 'useful'}),
                pool.submit(send, '/lecture/stream', {'student_message': 'Explain analogy', 'idempotency_key': 'append'})]
        assert [job.result() for job in jobs] == [200, 200, 200]
    page = client.get(f'{path}/messages/page').json()
    saved = next(row for row in page['messages'] if row['id'] == answer)
    assert saved['starred'] is True and saved['rating'] == 'useful'
    assert len(page['messages']) == 3
    bookmark = client.get(f'{path}/bookmarks').json()['messages'][0]
    assert bookmark['stage_id'] == 'concept_generation'
    assert bookmark['interaction_intent'] == 'lecture_help'
    assert bookmark['preview'] == 'Saved explanation ' + 'x' * 302
    assert 'unrelated' not in bookmark


def test_only_messages_with_available_originals_can_be_bookmarked(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A hidden empty transition row cannot become a bookmark with no jump target."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'hidden.sqlite3')
    _seed_user(root, 'student', 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(name='Legacy transitions', model_id='mock', support_mode='critical-thinking')
    hidden = owner.add_message(thread, 'assistant', '', metadata={'thinking_stage': 'reflection'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    assert client.get(f'{path}/messages/page').json()['messages'] == []
    assert client.post(f'{path}/messages/{hidden}/star', json={'starred': True}, headers={'Origin': 'https://testserver'}).status_code == 404
    assert client.get(f'{path}/bookmarks').json()['messages'] == []
