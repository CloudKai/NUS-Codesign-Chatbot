"""Artifact feedback seam: bounded before/after proposals ride the saved turn.

Only the reader dispatch resolves artifact text server-side; legacy coach
routes strip client-supplied context, stale revisions fail 409, foreign
artifacts fail 404 and out-of-range paragraphs fail 422.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch, mark

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {'Origin': 'https://testserver'}

DOC = {'type': 'doc', 'content': [
    {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'The crossing feels unsafe.'}]},
    {'type': 'paragraph', 'content': [{'type': 'text',
        'text': 'Older pedestrians rush the final seconds at the school crossing.'}]},
]}


def _setup(tmp_path: Path) -> tuple[TestClient, str, str, int]:
    root = StudentStore(tmp_path / 'artifact-feedback.sqlite3')
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
    artifact = student.create_artifact(notebook, 'Unsafe crossing notes', DOC, kind='notes')
    return client, chat, artifact['id'], int(artifact['revision'])


@mark.parametrize("mode", ["project", "improve"])
def test_paragraph_feedback_is_saved_and_projected(
    tmp_path: Path, monkeypatch: MonkeyPatch, mode: str,
) -> None:
    """A coaching turn about one paragraph saves one stamped before/after pair."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, artifact_id, revision = _setup(tmp_path)
    stream = client.post(f'/api/v1/reader/threads/{chat}/{mode}/stream',
                         json={'student_message': 'How can this paragraph be stronger?',
                               'idempotency_key': 'af-1',
                               'artifact_selection': {'artifact_id': artifact_id,
                                                      'revision': revision,
                                                      'paragraph': 1}},
                         headers=ORIGIN)
    assert stream.status_code == 200
    done = [line for line in stream.text.splitlines() if '"done"' in line]
    assert done, 'stream must complete'
    proposals = json.loads(done[0])['turn']['artifact_feedback']
    assert len(proposals) == 1
    assert proposals[0]['base_artifact_id'] == artifact_id
    assert proposals[0]['base_artifact_revision'] == revision
    assert proposals[0]['paragraph'] == 1
    assert proposals[0]['original_text'].startswith('Older pedestrians')

    page = client.get(f'/api/v1/reader/threads/{chat}/messages/page',
                      headers=ORIGIN).json()
    assistant = [m for m in page['messages'] if m['role'] == 'assistant']
    assert assistant and assistant[-1]['artifact_feedback']
    assert assistant[-1]['artifact_feedback'][0]['id'] == proposals[0]['id']

    saved = client.get(f'/api/v1/reader/threads/{chat}/coach-turn'
                       '?idempotency_key=af-1', headers=ORIGIN).json()
    assert saved['artifact_feedback'][0]['id'] == proposals[0]['id']


def test_whole_document_selection_resolves_the_bounded_draft(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A whole-artifact request resolves the full bounded text with no paragraph."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, artifact_id, revision = _setup(tmp_path)
    stream = client.post(f'/api/v1/reader/threads/{chat}/project/stream',
                         json={'student_message': 'What is missing overall?',
                               'idempotency_key': 'af-2',
                               'artifact_selection': {'artifact_id': artifact_id,
                                                      'revision': revision,
                                                      'paragraph': None}},
                         headers=ORIGIN)
    assert stream.status_code == 200
    done = [line for line in stream.text.splitlines() if '"done"' in line]
    proposals = json.loads(done[0])['turn']['artifact_feedback']
    assert len(proposals) == 1
    assert proposals[0]['paragraph'] is None
    assert 'Older pedestrians' in proposals[0]['original_text']


def test_artifact_feedback_guards_fail_closed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stale revisions, foreign artifacts and unknown paragraphs never reach the coach."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, oidc, root, chat, artifact_id, revision = _setup_guarded(tmp_path)
    base = f'/api/v1/reader/threads/{chat}/project/stream'

    def post(selection: dict[str, object], key: str) -> object:
        return client.post(base, json={'student_message': 'Improve this?',
                                       'idempotency_key': key,
                                       'artifact_selection': selection}, headers=ORIGIN)

    stale = post({'artifact_id': artifact_id, 'revision': revision + 3, 'paragraph': None}, 'stale-1')
    assert stale.status_code == 409
    out_of_range = post({'artifact_id': artifact_id, 'revision': revision, 'paragraph': 9}, 'range-1')
    assert out_of_range.status_code == 422
    other = StudentStore(root.path, identifier='cognito:other')
    other_thread = other.create_thread(name='Other', model_id='mock', support_mode='critical-thinking')
    foreign_artifact = other.create_artifact(other_thread, 'Other draft', DOC, kind='notes')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    foreign_owner = client.post(base, json={'student_message': 'hi', 'idempotency_key': 'foreign-1',
                                            'artifact_selection': {'artifact_id': artifact_id,
                                                                   'revision': revision,
                                                                   'paragraph': None}},
                                headers=ORIGIN)
    assert foreign_owner.status_code == 404
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    foreign_family = post({'artifact_id': foreign_artifact['id'], 'revision': 1,
                           'paragraph': None}, 'foreign-2')
    assert foreign_family.status_code == 404


def _setup_guarded(tmp_path: Path) -> tuple[TestClient, FakeOIDC, StudentStore, str, str, int]:
    root = StudentStore(tmp_path / 'artifact-feedback-guarded.sqlite3')
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
    artifact = student.create_artifact(notebook, 'Unsafe crossing notes', DOC, kind='notes')
    return client, oidc, root, chat, artifact['id'], int(artifact['revision'])


def test_legacy_coach_routes_strip_client_artifact_injection(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Client-supplied artifact context and origin never produce feedback."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, chat, _artifact_id, _revision = _setup(tmp_path)
    body = {'thread_id': chat,
            'student_message': 'How can this paragraph be stronger?',
            'current_stage': 'problem_identification',
            'response_detail': 'short',
            'artifact_context': 'The crossing feels unsafe.',
            'artifact_feedback_origin': {'artifact_id': 'art-1', 'revision': 4,
                                         'paragraph': 0, 'original_text': 'The crossing feels unsafe.'},
            'idempotency_key': 'inject-1'}
    response = client.post('/api/v1/coach/turn', json=body, headers=ORIGIN)
    assert response.status_code == 200
    assert response.json()['artifact_feedback'] == []

    streamed = client.post('/api/v1/coach/turn/stream',
                           json=dict(body, idempotency_key='inject-2'), headers=ORIGIN)
    assert streamed.status_code == 200
    done = [line for line in streamed.text.splitlines() if '"done"' in line]
    assert done and json.loads(done[0])['turn']['artifact_feedback'] == []
