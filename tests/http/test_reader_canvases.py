"""Design canvas routes: ownership, restart persistence, stale-save conflicts and validation."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {'Origin': 'https://testserver'}


def _client(tmp_path: Path, name: str) -> tuple[TestClient, FakeOIDC, StudentStore]:
    root = StudentStore(tmp_path / f'{name}.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    return client, oidc, root


def _graph() -> dict[str, object]:
    return {'nodes': [
        {'id': 'n0', 'kind': 'problem', 'title': 'Crossing problem', 'description': 'unsafe left turns',
         'x': 0.0, 'y': 0.0},
        {'id': 'n1', 'kind': 'stakeholder', 'title': 'Students', 'description': '', 'x': 200.0, 'y': 100.0},
    ], 'edges': [
        {'id': 'e0', 'source': 'n0', 'target': 'n1', 'relation': 'addresses',
         'explanation': 'students cross here daily'},
    ]}


def test_canvas_deletion_preserves_unavailable_evidence_links(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """Delete the confirmed revision and its history while retaining inbound provenance."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, oidc, root = _client(tmp_path, 'delete-canvas')
    thread_id = client.post('/api/v1/reader/threads', json={'name': 'Design notebook'},
                            headers=ORIGIN).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread_id}'
    canvas = client.post(f'{base}/canvases', json={'title': 'Concept map', 'graph': _graph()},
                         headers=ORIGIN).json()
    path = f"{base}/canvases/{canvas['id']}"
    reference = {'kind': 'canvas_node', 'canvas_id': canvas['id'], 'id': 'n0'}
    artifact = client.post(f'{base}/artifacts', headers=ORIGIN, json={
        'title': 'Evidence notes', 'kind': 'notes', 'document': {'type': 'doc', 'content': []},
        'references': [reference],
    }).json()
    assert artifact['references'][0]['available'] is True
    linked_graph = _graph()
    linked_graph['nodes'][0]['references'] = [reference]
    linked = client.post(f'{base}/canvases', headers=ORIGIN, json={
        'title': 'Linked map', 'graph': linked_graph,
    }).json()
    updated = client.put(path, json={'title': 'Updated map', 'revision': 1, 'graph': _graph()},
                         headers=ORIGIN).json()
    assert updated['revision'] == 2
    assert client.post(f'{path}/delete', json={'revision': 2, 'confirmed': False},
                       headers=ORIGIN).status_code == 422
    assert client.post(f'{path}/delete', json={'revision': 1, 'confirmed': True},
                       headers=ORIGIN).status_code == 409
    assert client.get(f'{path}/versions/1').status_code == 200
    deleted = client.post(f'{path}/delete', json={'revision': 2, 'confirmed': True}, headers=ORIGIN)
    assert deleted.status_code == 200
    assert deleted.json()['id'] == canvas['id']

    reopened = TestClient(create_app(StudentStore(root.path), oidc_client=oidc),
                          base_url='https://testserver')
    reopened.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    assert reopened.get(path).status_code == 404
    assert reopened.get(f'{path}/versions/1').status_code == 404
    assert [item['id'] for item in reopened.get(f'{base}/canvases').json()['canvases']] == [linked['id']]
    resolved = reopened.get(f"{base}/artifacts/{artifact['id']}").json()['references'][0]
    assert all(resolved[key] == value for key, value in reference.items())
    assert resolved['available'] is False and resolved['title'] is None
    updated_link = reopened.put(f"{base}/canvases/{linked['id']}", headers=ORIGIN, json={
        'title': 'Linked map, edited', 'graph': linked_graph, 'revision': 1,
    })
    assert updated_link.status_code == 200
    assert updated_link.json()['graph']['nodes'][0]['references'] == [reference]


def test_canvas_lifecycle_restart_and_stale_save(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Create, edit, reopen after restart and reject stale saves through the public contracts."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, _oidc, root = _client(tmp_path, 'lifecycle')
    thread = client.post('/api/v1/reader/threads', json={'name': 'Design notebook'},
                         headers=ORIGIN).json()['notebook']['id']
    graph = _graph()

    created = client.post(f'/api/v1/reader/threads/{thread}/canvases',
                          json={'title': 'Concept map', 'graph': graph}, headers=ORIGIN)
    assert created.status_code == 201
    canvas = created.json()
    assert canvas['owner_id'] == client.get('/api/v1/reader/session', headers=ORIGIN).json()['owner_id']
    assert canvas['thread_id'] == thread
    assert canvas['graph'] == graph and canvas['revision'] == 1

    listing = client.get(f'/api/v1/reader/threads/{thread}/canvases', headers=ORIGIN)
    assert listing.status_code == 200
    assert [entry['id'] for entry in listing.json()['canvases']] == [canvas['id']]
    assert 'graph' not in listing.json()['canvases'][0]
    assert listing.json()['stages'][0] == 'problem_identification'

    # An optional Thinking Path association saves and reopens exactly.
    staged = dict(graph['nodes'][0], stage='problem_identification')
    staged_graph = {'nodes': [staged, dict(graph['nodes'][1], description='')], 'edges': []}
    saved_staged = client.put(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                              json={'graph': staged_graph, 'revision': 1}, headers=ORIGIN)
    assert saved_staged.status_code == 200
    assert saved_staged.json()['graph'] == staged_graph

    saved = client.put(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                       json={'title': 'Concept map v2', 'graph': graph, 'revision': 2},
                       headers=ORIGIN)
    assert saved.status_code == 200
    assert saved.json()['revision'] == 3 and saved.json()['title'] == 'Concept map v2'

    # A stale conditional save fails without changing the stored work.
    stale = client.put(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                       json={'graph': graph, 'revision': 2}, headers=ORIGIN)
    assert stale.status_code == 409
    assert client.get(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                      headers=ORIGIN).json()['revision'] == 3

    # Invalid graphs fail closed with a typed 422.
    broken = client.put(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                        json={'graph': {'nodes': [
                            {'id': 'n0', 'kind': 'invented', 'title': 'A', 'x': 0, 'y': 0}],
                            'edges': []}, 'revision': 3}, headers=ORIGIN)
    assert broken.status_code == 422

    # Every canvas write requires the same-origin policy even with a valid body.
    for headers in ({}, {'Origin': 'https://evil.test'},
                    {'Origin': 'https://testserver', 'Sec-Fetch-Site': 'cross-site'}):
        write = client.put(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                           json={'graph': graph, 'revision': 2}, headers=headers)
        assert write.status_code == 403, (headers, write.status_code)
        make = client.post(f'/api/v1/reader/threads/{thread}/canvases',
                           json={'title': 'X', 'graph': {'nodes': [], 'edges': []}},
                           headers=headers)
        assert make.status_code == 403, (headers, make.status_code)

    # A real backend restart keeps the saved canvas exactly.
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=_oidc),
                           base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    reopened = restarted.get(f"/api/v1/reader/threads/{thread}/canvases/{canvas['id']}",
                             headers=ORIGIN)
    assert reopened.status_code == 200
    assert reopened.json() == saved.json()


def test_canvas_version_history_contracts(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Bounded version metadata, readable previews and guarded restores through the public seam."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'canvas-versions-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Maps'}, headers=origin).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/canvases'
    def graph(text: str) -> dict[str, object]:
        return {'nodes': [{'id': 'n0', 'kind': 'note', 'title': text, 'description': '', 'x': 0, 'y': 0}],
                'edges': []}
    created = client.post(base, json={'title': 'Map', 'graph': graph('v1')}, headers=origin).json()
    canvas_id = created['id']
    client.put(f'{base}/{canvas_id}', json={'graph': graph('v2'), 'revision': 1}, headers=origin)

    versions = client.get(f'{base}/{canvas_id}/versions', headers=origin)
    assert versions.status_code == 200
    assert [entry['revision'] for entry in versions.json()['versions']] == [2, 1]
    assert 'graph' not in versions.json()['versions'][0]

    preview = client.get(f'{base}/{canvas_id}/versions/1', headers=origin)
    assert preview.status_code == 200
    assert preview.json()['graph'] == graph('v1')

    restored = client.post(f'{base}/{canvas_id}/versions/1/restore',
                           json={'revision': 2}, headers=origin)
    assert restored.status_code == 200
    assert restored.json()['revision'] == 3 and restored.json()['origin'] == 'restore'
    assert restored.json()['graph'] == graph('v1')

    # Stale restore: the caller had not seen the current revision.
    stale = client.post(f'{base}/{canvas_id}/versions/1/restore',
                        json={'revision': 2}, headers=origin)
    assert stale.status_code == 409
    assert client.get(f'{base}/{canvas_id}', headers=origin).json()['revision'] == 3
    assert client.get(f'{base}/{canvas_id}/versions/99', headers=origin).status_code == 404

    # The second owner never sees the history.
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(f'{base}/{canvas_id}/versions', headers=origin).status_code == 404
    assert client.get(f'{base}/{canvas_id}/versions/1', headers=origin).status_code == 404
    assert client.post(f'{base}/{canvas_id}/versions/1/restore',
                       json={'revision': 3}, headers=origin).status_code == 404


def test_canvas_export_formats_ownership_and_safety(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """JSON, outline and SVG downloads are owner-checked, inert and bounded."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'canvas-export-api.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    origin = {'Origin': 'https://testserver'}
    thread = client.post('/api/v1/reader/threads', json={'name': 'Maps'}, headers=origin).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/canvases'
    graph = {'nodes': [
        {'id': 'n1', 'kind': 'problem', 'title': 'Unsafe <crossing>', 'description': '',
         'stage': 'problem_identification', 'x': 0, 'y': 0},
        {'id': 'n2', 'kind': 'stakeholder', 'title': 'Students', 'description': '',
         'x': 800, 'y': 600},
    ], 'edges': [
        {'id': 'e1', 'source': 'n1', 'target': 'n2', 'relation': 'addresses', 'explanation': ''},
    ]}
    canvas = client.post(base, json={'title': 'Crossing/../map', 'graph': graph},
                         headers=origin).json()
    export_base = f"{base}/{canvas['id']}/export"

    envelope = client.get(f'{export_base}?format=json', headers=origin)
    assert envelope.status_code == 200
    payload = envelope.json()
    assert payload['title'] == 'Crossing/../map' and payload['revision'] == 1
    assert 'id' not in payload and 'thread_id' not in payload

    outline = client.get(f'{export_base}?format=outline', headers=origin)
    assert outline.status_code == 200 and outline.headers['content-type'].startswith('text/plain')
    assert 'Unsafe <crossing>' in outline.text and 'n1' not in outline.text

    svg = client.get(f'{export_base}?format=svg', headers=origin)
    assert svg.status_code == 200
    assert svg.headers['content-type'].startswith('image/svg+xml')
    assert 'Students' in svg.text and 'Unsafe &lt;crossing&gt;' in svg.text
    assert '<crossing>' not in svg.text

    for response in (envelope, outline, svg):
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'attachment' in response.headers['content-disposition']
        assert '..' not in response.headers['content-disposition'] and '/' not in \
            response.headers['content-disposition'].split("''")[-1]
        assert response.headers['cache-control'] == 'no-store'

    assert client.get(f'{export_base}?format=html', headers=origin).status_code == 422
    assert client.get(f'{base}/unknown-id/export', headers=origin).status_code == 404
    anonymous = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    assert anonymous.get(export_base, headers=origin).status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(export_base, headers=origin).status_code == 404


def test_canvas_routes_reject_foreign_owners_and_unknown_ids(tmp_path: Path,
                                                             monkeypatch: MonkeyPatch) -> None:
    """Foreign project/canvas IDs and anonymous writes fail without leaking work."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    _client(tmp_path, 'guards')
    root = StudentStore(tmp_path / 'guards.sqlite3')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Owned', model_id='mock', support_mode='critical-thinking')
    created = student.create_canvas(thread, 'Secret map', {'nodes': [], 'edges': []})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    base = f'/api/v1/reader/threads/{thread}/canvases'

    assert client.get(base).status_code == 401
    assert client.get(f"{base}/{created['id']}").status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.get(base, headers=ORIGIN).status_code == 404
    assert client.get(f"{base}/{created['id']}", headers=ORIGIN).status_code == 404
    assert client.put(f"{base}/{created['id']}",
                      json={'graph': {'nodes': [], 'edges': []}, 'revision': 1},
                      headers=ORIGIN).status_code == 404
    assert client.post('/api/v1/reader/threads/unknown-notebook/canvases',
                       json={'title': 'X', 'graph': {'nodes': [], 'edges': []}},
                       headers=ORIGIN).status_code == 404
