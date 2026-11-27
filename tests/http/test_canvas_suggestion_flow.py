"""Canvas suggestion seam: bounded proposals ride the saved turn, nothing else.

Suggestions are untrusted data end to end. Only the reader dispatch resolves
their origin; legacy coach routes strip client-supplied context, and the saved
message projects the validated proposals for explicit student acceptance.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {'Origin': 'https://testserver'}


def _setup(tmp_path: Path) -> tuple[TestClient, str, str, int]:
    root = StudentStore(tmp_path / 'canvas-suggestions.sqlite3')
    _seed_user(root, 'student', 'student')
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
    ], 'edges': []})
    return client, chat, canvas['id'], int(canvas['revision'])


def test_canvas_coaching_suggestion_is_saved_and_projected(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A coaching turn about a selected node saves one bounded, revision-stamped proposal."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, canvas_id, revision = _setup(tmp_path)
    stream = client.post(f'/api/v1/reader/threads/{chat}/project/stream',
                         json={'student_message': 'What is weak about this node?',
                               'idempotency_key': 'sg-1',
                               'canvas_selection': {'canvas_id': canvas_id,
                                                    'revision': revision,
                                                    'node_ids': ['n0']}},
                         headers=ORIGIN)
    assert stream.status_code == 200
    done = [line for line in stream.text.splitlines() if '"done"' in line]
    assert done, 'stream must complete'
    event = json.loads(done[0])
    suggestions = event['turn']['canvas_suggestions']
    assert len(suggestions) == 1
    assert suggestions[0]['id'].startswith('sg-mock-')
    assert suggestions[0]['base_canvas_revision'] == revision

    page = client.get(f'/api/v1/reader/threads/{chat}/messages/page',
                      headers=ORIGIN).json()
    assistant = [m for m in page['messages'] if m['role'] == 'assistant']
    assert assistant and assistant[-1]['canvas_suggestions']
    projected = assistant[-1]['canvas_suggestions'][0]
    assert projected['kind'] == 'new_node'
    assert projected['base_canvas_revision'] == revision

    # The exact-key recovery returns the same saved suggestions.
    saved = client.get(f'/api/v1/reader/threads/{chat}/coach-turn'
                       '?idempotency_key=sg-1', headers=ORIGIN).json()
    assert saved['canvas_suggestions'][0]['id'] == projected['id']


def test_legacy_coach_routes_strip_client_canvas_injection(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Client-supplied canvas context and origin never produce suggestions."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, _canvas_id, _revision = _setup(tmp_path)
    body = {'thread_id': chat,
            'student_message': 'What is weak about this node?',
            'current_stage': 'problem_identification',
            'response_detail': 'short',
            'canvas_context': "Node 'Unsafe crossing' (problem): left turns",
            'canvas_context_origin': {'canvas_id': 'c-1', 'revision': 4},
            'idempotency_key': 'inject-1'}
    response = client.post('/api/v1/coach/turn', json=body,
                           headers=ORIGIN)
    assert response.status_code == 200
    assert response.json()['canvas_suggestions'] == []

    stream_body = dict(body, idempotency_key='inject-2')
    streamed = client.post('/api/v1/coach/turn/stream',
                           json=stream_body, headers=ORIGIN)
    assert streamed.status_code == 200
    done = [line for line in streamed.text.splitlines() if '"done"' in line]
    assert done and json.loads(done[0])['turn']['canvas_suggestions'] == []
