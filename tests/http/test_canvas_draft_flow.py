"""Canvas-to-artifact draft seam: explicit synthesis requests produce reviewable drafts.

Only `purpose: "draft"` selection requests synthesize; discussion never does.
Drafts persist with the saved answer, project onto reader messages, and carry
the contributing node ids and base canvas revision for the student's explicit
confirmation. A client-supplied purpose or node list is never authoritative.
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
    root = StudentStore(tmp_path / 'canvas-draft.sqlite3')
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
        {'id': 'n1', 'kind': 'stakeholder', 'title': 'Students', 'x': 200, 'y': 100},
    ], 'edges': []})
    return client, chat, canvas['id'], int(canvas['revision'])


def test_draft_request_produces_reviewable_draft_with_node_provenance(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An explicit draft request synthesizes one stamped, node-attributed proposal."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, canvas_id, revision = _setup(tmp_path)
    stream = client.post(f'/api/v1/reader/threads/{chat}/project/stream',
                         json={'student_message': 'Draft a problem brief from these nodes.',
                               'idempotency_key': 'cd-1',
                               'canvas_selection': {'canvas_id': canvas_id,
                                                    'revision': revision,
                                                    'node_ids': ['n0', 'n1'],
                                                    'purpose': 'draft'}},
                         headers=ORIGIN)
    assert stream.status_code == 200
    done = [line for line in stream.text.splitlines() if '"done"' in line]
    assert done, 'stream must complete'
    draft = json.loads(done[0])['turn']['canvas_draft']
    assert draft is not None
    assert draft['base_canvas_id'] == canvas_id
    assert draft['base_canvas_revision'] == revision
    assert draft['node_ids'] == ['n0', 'n1']
    assert draft['provenance'] == 'coach'
    assert draft['draft_text'].strip()

    page = client.get(f'/api/v1/reader/threads/{chat}/messages/page',
                      headers=ORIGIN).json()
    assistant = [m for m in page['messages'] if m['role'] == 'assistant']
    assert assistant and assistant[-1]['canvas_draft']
    assert assistant[-1]['canvas_draft']['id'] == draft['id']

    saved = client.get(f'/api/v1/reader/threads/{chat}/coach-turn'
                       '?idempotency_key=cd-1', headers=ORIGIN).json()
    assert saved['canvas_draft']['id'] == draft['id']


def test_discussion_request_never_synthesizes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The default discussion purpose produces no draft even over the same nodes."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, canvas_id, revision = _setup(tmp_path)
    stream = client.post(f'/api/v1/reader/threads/{chat}/project/stream',
                         json={'student_message': 'What is weak about these nodes?',
                               'idempotency_key': 'cd-2',
                               'canvas_selection': {'canvas_id': canvas_id,
                                                    'revision': revision,
                                                    'node_ids': ['n0', 'n1']}},
                         headers=ORIGIN)
    assert stream.status_code == 200
    done = [line for line in stream.text.splitlines() if '"done"' in line]
    assert json.loads(done[0])['turn']['canvas_draft'] is None


def test_client_supplied_draft_fields_are_never_authoritative(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Legacy coach routes strip client canvas purpose; node ids come from the server."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, _canvas_id, _revision = _setup(tmp_path)
    body = {'thread_id': chat,
            'student_message': 'Draft a problem brief from these nodes.',
            'current_stage': 'problem_identification',
            'response_detail': 'short',
            'canvas_context': "Node 'Unsafe crossing' (problem): left turns",
            'canvas_context_origin': {'canvas_id': 'c-1', 'revision': 6,
                                      'node_ids': ['n0', 'n1']},
            'canvas_selection_purpose': 'draft',
            'idempotency_key': 'cd-inject'}
    response = client.post('/api/v1/coach/turn', json=body, headers=ORIGIN)
    assert response.status_code == 200
    assert response.json()['canvas_draft'] is None
