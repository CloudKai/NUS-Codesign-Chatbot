"""Canvas suggestion acceptance persists through the public reader contract."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {'Origin': 'https://testserver'}


def _client(tmp_path: Path, name: str) -> TestClient:
    root = StudentStore(tmp_path / f'{name}.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    return client


def _graph(accepted: list[str] | None = None) -> dict[str, object]:
    graph: dict[str, object] = {'nodes': [
        {'id': 'n0', 'kind': 'problem', 'title': 'Crossing problem',
         'description': 'unsafe left turns', 'x': 0.0, 'y': 0.0},
    ], 'edges': []}
    if accepted is not None:
        graph['accepted_suggestion_ids'] = accepted
    return graph


def test_canvas_save_persists_an_accepted_suggestion_id(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """The accepted id survives the save and a second read sees it exactly once."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client = _client(tmp_path, 'suggestion-accept')
    thread = client.post(
        '/api/v1/reader/threads', json={'name': 'Design notebook'}, headers=ORIGIN,
    ).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/canvases'
    canvas = client.post(
        base, json={'title': 'Concept map', 'graph': _graph()}, headers=ORIGIN,
    ).json()

    accepted = _graph(['sg-mock-abc12345'])
    accepted['nodes'].append({
        'id': 'n1', 'kind': 'concept', 'title': 'Protected crossing',
        'description': 'Grade-separated crossing', 'x': 60.0, 'y': 60.0,
    })
    saved = client.put(
        f"{base}/{canvas['id']}",
        json={'graph': accepted, 'revision': canvas['revision']},
        headers=ORIGIN,
    )
    assert saved.status_code == 200
    assert saved.json()['graph']['accepted_suggestion_ids'] == ['sg-mock-abc12345']

    reopened = client.get(f"{base}/{canvas['id']}", headers=ORIGIN)
    assert reopened.status_code == 200
    assert reopened.json()['graph']['accepted_suggestion_ids'] == ['sg-mock-abc12345']
    assert reopened.json()['revision'] == 2


def test_canvas_save_rejects_oversized_accepted_suggestion_lists(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """More than the bounded number of accepted ids fails closed with a typed 422."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client = _client(tmp_path, 'suggestion-oversized')
    thread = client.post(
        '/api/v1/reader/threads', json={'name': 'Design notebook'}, headers=ORIGIN,
    ).json()['notebook']['id']
    base = f'/api/v1/reader/threads/{thread}/canvases'
    canvas = client.post(
        base, json={'title': 'Concept map', 'graph': _graph()}, headers=ORIGIN,
    ).json()

    oversized = _graph([f'sg-{index}' for index in range(1_001)])
    rejected = client.put(
        f"{base}/{canvas['id']}",
        json={'graph': oversized, 'revision': canvas['revision']},
        headers=ORIGIN,
    )
    assert rejected.status_code == 422
    assert 'too many accepted suggestion ids' in rejected.json()['detail']
    assert client.get(f"{base}/{canvas['id']}", headers=ORIGIN).json()['revision'] == 1
