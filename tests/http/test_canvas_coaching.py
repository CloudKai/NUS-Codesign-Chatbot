"""Canvas selection coaching: server-resolved context with stale/foreign/unknown guards."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {'Origin': 'https://testserver'}


def _setup(tmp_path: Path) -> tuple[TestClient, FakeOIDC, StudentStore, str, str, int]:
    root = StudentStore(tmp_path / 'canvas-coach.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    notebook = client.post('/api/v1/reader/threads', json={'name': 'Design notebook'},
                           headers=ORIGIN).json()['notebook']['id']
    chat = client.post('/api/v1/reader/threads',
                       json={'kind': 'chat', 'parent_notebook_id': notebook},
                       headers=ORIGIN).json()['notebook']['id']
    student = StudentStore(root.path, identifier='cognito:student')
    canvas = student.create_canvas(notebook, 'Concept map', {'nodes': [
        {'id': 'n0', 'kind': 'problem', 'title': 'Unsafe crossing', 'description': 'left turns',
         'x': 0, 'y': 0},
        {'id': 'n1', 'kind': 'stakeholder', 'title': 'Students', 'x': 200, 'y': 100},
    ], 'edges': [
        {'id': 'e0', 'source': 'n0', 'target': 'n1', 'relation': 'addresses'},
    ]})
    return client, oidc, root, chat, canvas['id'], int(canvas['revision'])


def test_canvas_selection_streams_with_server_resolved_context(tmp_path: Path,
                                                               monkeypatch: MonkeyPatch) -> None:
    """A valid selection streams through the existing coach lifecycle."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, _oidc, _root, chat, canvas_id, revision = _setup(tmp_path)
    response = client.post(f'/api/v1/reader/threads/{chat}/project/stream',
                           json={'student_message': 'What is weak about this node?',
                                 'idempotency_key': 'canvas-1',
                                 'canvas_selection': {'canvas_id': canvas_id,
                                                      'revision': revision,
                                                      'node_ids': ['n0']}},
                           headers=ORIGIN)
    assert response.status_code == 200
    assert 'started' in response.text


def test_canvas_selection_guards_fail_closed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stale revisions, foreign canvases and unknown nodes never reach the coach."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, oidc, root, chat, canvas_id, revision = _setup(tmp_path)
    base = f'/api/v1/reader/threads/{chat}/project/stream'

    def post(selection: dict[str, object], key: str) -> object:
        return client.post(base, json={'student_message': 'What about this?',
                                       'idempotency_key': key,
                                       'canvas_selection': selection}, headers=ORIGIN)

    # Stale revision: the student had not seen the current snapshot.
    stale = post({'canvas_id': canvas_id, 'revision': revision + 4, 'node_ids': ['n0']}, 'stale-1')
    assert stale.status_code == 409
    # Unknown node ids fail closed.
    unknown = post({'canvas_id': canvas_id, 'revision': revision, 'node_ids': ['missing']}, 'unknown-1')
    assert unknown.status_code == 422
    # A canvas outside this notebook family is invisible.
    other = StudentStore(root.path, identifier='cognito:other')
    other_thread = other.create_thread(name='Other', model_id='mock', support_mode='critical-thinking')
    foreign_canvas = other.create_canvas(other_thread, 'Other map', {'nodes': [], 'edges': []})
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    foreign_owner = client.post(base, json={'student_message': 'hi', 'idempotency_key': 'foreign-1',
                                            'canvas_selection': {'canvas_id': canvas_id,
                                                                 'revision': revision,
                                                                 'node_ids': ['n0']}},
                                headers=ORIGIN)
    assert foreign_owner.status_code == 404
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    foreign_family = post({'canvas_id': foreign_canvas['id'], 'revision': 1, 'node_ids': ['n0']},
                          'foreign-2')
    assert foreign_family.status_code == 404
