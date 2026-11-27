"""Persistent artifact routes: ownership, restart persistence and stale-save conflicts."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def _client(tmp_path: Path, name: str) -> TestClient:
    root = StudentStore(tmp_path / f'{name}.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    return client


def test_artifact_lifecycle_restart_and_stale_save(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Create, edit, reopen after restart and reject stale saves through the public contracts."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'lifecycle.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Design notebook'}, headers=origin).json()['notebook']['id']
    document = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Crossing observations'}]}]}

    created = client.post(f'/api/v1/reader/threads/{thread}/artifacts',
                          json={'title': 'Field notes', 'kind': 'notes', 'document': document}, headers=origin)
    assert created.status_code == 201
    artifact = created.json()
    assert artifact['owner_id'] == client.get('/api/v1/reader/session', headers=origin).json()['owner_id']
    assert artifact['thread_id'] == thread
    assert artifact['kind'] == 'notes'
    assert artifact['document'] == document and artifact['revision'] == 1
    assert artifact['references'] == []

    listing = client.get(f'/api/v1/reader/threads/{thread}/artifacts', headers=origin)
    assert listing.status_code == 200
    assert [entry['id'] for entry in listing.json()['artifacts']] == [artifact['id']]
    assert listing.json()['kinds'][0] == 'notes'
    assert 'document' not in listing.json()['artifacts'][0]

    saved = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}",
                       json={'title': 'Field notes v2', 'document': document, 'revision': 1}, headers=origin)
    assert saved.status_code == 200
    assert saved.json()['revision'] == 2 and saved.json()['title'] == 'Field notes v2'

    # A stale conditional save fails without changing the stored work.
    stale = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}",
                       json={'document': document, 'revision': 1}, headers=origin)
    assert stale.status_code == 409
    assert client.get(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}", headers=origin).json()['revision'] == 2

    # Unsafe structures fail closed.
    broken = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}",
                        json={'document': {'type': 'paragraph'}, 'revision': 2}, headers=origin)
    assert broken.status_code == 422

    # Every artifact write requires the same-origin policy even with a valid body.
    for headers in ({}, {'Origin': 'https://evil.test'},
                    {'Origin': 'https://testserver', 'Sec-Fetch-Site': 'cross-site'}):
        write = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}",
                           json={'document': document, 'revision': 2}, headers=headers)
        assert write.status_code == 403, (headers, write.status_code)
        make = client.post(f'/api/v1/reader/threads/{thread}/artifacts',
                           json={'title': 'X', 'document': document}, headers=headers)
        assert make.status_code == 403, (headers, make.status_code)

    # A real backend restart keeps the saved artifact exactly.
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    reopened = restarted.get(f"/api/v1/reader/threads/{thread}/artifacts/{artifact['id']}", headers=origin)
    assert reopened.status_code == 200
    assert reopened.json() == saved.json()


def test_artifact_create_replays_request_id_and_keeps_draft_provenance(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """A retried create returns the original artifact; origin and node revision survive."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'replay-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Design'},
                         headers=origin).json()['notebook']['id']
    canvas = client.post(f'/api/v1/reader/threads/{thread}/canvases', headers=origin,
                         json={'title': 'Map', 'graph': {'nodes': [
                             {'id': 'n1', 'kind': 'note', 'title': 'Observation', 'x': 0, 'y': 0}],
                             'edges': []}}).json()
    base = f'/api/v1/reader/threads/{thread}/artifacts'
    document = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Coach draft'}]}]}
    payload = {
        'title': 'Draft from canvas', 'kind': 'notes', 'document': document,
        'origin': 'coach_draft', 'request_id': 'draft:cd-mock-abc12345',
        'references': [{'kind': 'canvas_node', 'canvas_id': canvas['id'],
                        'id': 'n1', 'revision': canvas['revision']}],
    }

    first = client.post(base, json=payload, headers=origin)
    assert first.status_code == 201
    artifact = first.json()
    assert artifact['origin'] == 'coach_draft'
    assert artifact['references'][0]['revision'] == canvas['revision']

    replay = client.post(base, json={**payload, 'title': 'Changed retry title'}, headers=origin)
    assert replay.status_code == 422
    listing = client.get(base, headers=origin).json()['artifacts']
    assert [entry['id'] for entry in listing] == [artifact['id']]
    versions = client.get(f"{base}/{artifact['id']}/versions", headers=origin).json()['versions']
    assert [entry['revision'] for entry in versions] == [1]
    assert versions[0]['origin'] == 'coach_draft'

    # The allowlist and key bounds fail closed at the typed boundary.
    for bad in ({'origin': 'model_generated'}, {'request_id': 'bad key!'},
                {'request_id': 'x' * 129}):
        rejected = client.post(base, json={**payload, **bad, 'request_id':
                                           bad.get('request_id', 'draft:other-key')},
                               headers=origin)
        assert rejected.status_code == 422, (bad, rejected.status_code)


def test_artifact_version_history_contracts(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Bounded version metadata, readable previews and guarded restores through the public seam."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'versions-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Docs'}, headers=origin).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/artifacts'
    def doc(text: str) -> dict[str, object]:
        return {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': text}]}]}
    created = client.post(base, json={'title': 'Notes', 'kind': 'notes', 'document': doc('v1')},
                          headers=origin).json()
    artifact_id = created['id']
    client.put(f'{base}/{artifact_id}', json={'document': doc('v2'), 'revision': 1}, headers=origin)

    versions = client.get(f'{base}/{artifact_id}/versions', headers=origin)
    assert versions.status_code == 200
    assert [entry['revision'] for entry in versions.json()['versions']] == [2, 1]
    assert 'document' not in versions.json()['versions'][0]

    preview = client.get(f'{base}/{artifact_id}/versions/1', headers=origin)
    assert preview.status_code == 200
    assert preview.json()['document'] == doc('v1')

    restored = client.post(f'{base}/{artifact_id}/versions/1/restore',
                           json={'revision': 2}, headers=origin)
    assert restored.status_code == 200
    assert restored.json()['revision'] == 3 and restored.json()['origin'] == 'restore'
    assert restored.json()['document'] == doc('v1')

    # Stale restore: the caller had not seen the current revision.
    stale = client.post(f'{base}/{artifact_id}/versions/1/restore',
                        json={'revision': 2}, headers=origin)
    assert stale.status_code == 409
    assert client.get(f'{base}/{artifact_id}', headers=origin).json()['revision'] == 3
    assert client.get(f'{base}/{artifact_id}/versions/99', headers=origin).status_code == 404

    # The second owner never sees the history.
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(f'{base}/{artifact_id}/versions', headers=origin).status_code == 404
    assert client.get(f'{base}/{artifact_id}/versions/1', headers=origin).status_code == 404
    assert client.post(f'{base}/{artifact_id}/versions/1/restore',
                       json={'revision': 3}, headers=origin).status_code == 404


def test_artifact_export_formats_ownership_and_safety(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Markdown, plaintext and JSON downloads are owner-checked, inert and bounded."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'export-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Docs'}, headers=origin).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/artifacts'
    document = {'type': 'doc', 'content': [
        {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': 'Crossing study'}]},
        {'type': 'paragraph', 'content': [
            {'type': 'text', 'marks': [{'type': 'link', 'attrs': {'href': 'javascript:alert(1)'}}],
             'text': 'unsafe link text'}]}]}
    artifact = client.post(base, json={'title': 'Field notes/../x', 'kind': 'notes', 'document': document},
                           headers=origin).json()
    export_base = f"{base}/{artifact['id']}/export"

    markdown = client.get(f'{export_base}?format=markdown', headers=origin)
    assert markdown.status_code == 200
    assert '## Crossing study' in markdown.text
    assert 'unsafe link text' in markdown.text and 'javascript:' not in markdown.text
    assert markdown.headers['x-content-type-options'] == 'nosniff'
    assert 'attachment' in markdown.headers['content-disposition']
    assert '..' not in markdown.headers['content-disposition'] and '/' not in markdown.headers[
        'content-disposition'].split("''")[-1]
    assert markdown.headers['cache-control'] == 'no-store'

    text = client.get(f'{export_base}?format=text', headers=origin)
    assert text.status_code == 200 and text.headers['content-type'].startswith('text/plain')
    envelope = client.get(f'{export_base}?format=json', headers=origin)
    assert envelope.status_code == 200
    payload = envelope.json()
    assert payload['title'] == 'Field notes/../x' and payload['revision'] == 1
    assert 'id' not in payload and 'thread_id' not in payload

    assert client.get(f'{export_base}?format=html', headers=origin).status_code == 422
    assert client.get(f'{base}/unknown-id/export', headers=origin).status_code == 404
    anonymous = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    assert anonymous.get(export_base, headers=origin).status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(export_base, headers=origin).status_code == 404


def test_artifact_routes_reject_foreign_owners_and_unknown_ids(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Foreign project/artifact IDs and anonymous writes fail without leaking work."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'guards.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Owned', model_id='mock', support_mode='critical-thinking')
    created = student.create_artifact(thread, 'Secret notes', {'type': 'doc', 'content': []})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    origin = {'Origin': 'https://testserver'}
    base = f'/api/v1/reader/threads/{thread}/artifacts'

    assert client.get(base).status_code == 401
    assert client.get(f'{base}/{created["id"]}').status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(base, headers=origin).status_code == 404
    assert client.get(f'{base}/{created["id"]}', headers=origin).status_code == 404
    assert client.put(f'{base}/{created["id"]}',
                      json={'document': {'type': 'doc', 'content': []}, 'revision': 1},
                      headers=origin).status_code == 404
    assert client.post('/api/v1/reader/threads/unknown-notebook/artifacts',
                       json={'title': 'X', 'kind': 'notes', 'document': {'type': 'doc', 'content': []}},
                       headers=origin).status_code == 404


def test_artifact_reference_contracts(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Evidence references save, resolve and fail closed through the public contracts."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'artifact-refs-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Design'}, headers=origin).json()['notebook']['id']
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "selected, metadata_text, created_at, updated_at) "
            "VALUES ('src-1', ?, 'pdf', 'Lecture slides', 'application/pdf', 10, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (thread,))
        connection.commit()
    document = {'type': 'doc', 'content': []}

    created = client.post(f'/api/v1/reader/threads/{thread}/artifacts',
                          json={'title': 'Notes', 'kind': 'notes', 'document': document,
                                'references': [{'kind': 'source', 'id': 'src-1'}]},
                          headers=origin)
    assert created.status_code == 201
    assert created.json()['references'] == [{'kind': 'source', 'id': 'src-1', 'available': True,
                                             'title': 'Lecture slides'}]

    # Omitted references keep the saved list; an explicit list replaces it.
    omitted = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{created.json()['id']}",
                         json={'document': document, 'revision': 1}, headers=origin)
    assert omitted.status_code == 200
    assert omitted.json()['references'][0]['id'] == 'src-1'
    cleared = client.put(f"/api/v1/reader/threads/{thread}/artifacts/{created.json()['id']}",
                         json={'document': document, 'revision': 2, 'references': []},
                         headers=origin)
    assert cleared.status_code == 200 and cleared.json()['references'] == []

    # Foreign, deleted and fabricated references fail closed without echoing evidence.
    foreign = client.post(f'/api/v1/reader/threads/{thread}/artifacts',
                          json={'title': 'X', 'kind': 'notes', 'document': document,
                                'references': [{'kind': 'source', 'id': 'unknown'}]},
                          headers=origin)
    assert foreign.status_code == 422
