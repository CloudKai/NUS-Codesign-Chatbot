"""Selected project export: bounded, owner-checked assembly from saved work only."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.project_export import MAX_EXPORT_ARTIFACTS, MAX_EXPORT_MESSAGES
from backend.settings import settings
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

DOCUMENT = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
    {'type': 'text', 'text': 'Crossing observations'}]}]}
GRAPH = {'nodes': [{'id': 'n1', 'kind': 'problem', 'title': 'Safer crossings',
                    'x': 10, 'y': 20}], 'edges': []}


def test_project_export_conversation_covers_the_notebook_family(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The parent export includes child-chat messages labeled by chat title,
    keeps progress on the requested notebook and never crosses owners."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, root_path, _oidc = _client(tmp_path, 'family-conversation')
    origin = {'Origin': 'https://testserver'}
    notebook = client.post('/api/v1/reader/threads', headers=origin,
                           json={'name': 'Crossing project'}).json()['notebook']['id']
    chat = client.post('/api/v1/reader/threads', headers=origin, json={
        'kind': 'chat', 'parent_notebook_id': notebook,
    }).json()['notebook']['id']
    student.update_thread(chat, name='Concept comparison')
    student.add_message(notebook, 'user', 'Original notebook discussion.')
    student.add_message(chat, 'user', 'Our refuge island helps residents cross safely.')
    student.update_thread(notebook, metadata={'learning_journey': {
        'current_stage': 'problem_identification',
    }})
    student.update_thread(chat, metadata={'learning_journey': {
        'current_stage': 'concept_generation', 'completed_stages': ['problem_identification'],
    }})
    artifact = student.create_artifact(notebook, 'Shared notes', DOCUMENT)

    other = StudentStore(root_path, identifier='cognito:other')
    foreign_notebook = other.create_thread(
        name='Other owner project', model_id='mock', support_mode='critical-thinking',
        reader_notebook=True)
    foreign_chat = other.create_thread(
        name='Other owner chat', model_id='mock', support_mode='critical-thinking',
        quick_chat=True, parent_notebook_id=foreign_notebook)
    other.add_message(foreign_notebook, 'user', 'Foreign secret notebook text.')
    other.add_message(foreign_chat, 'user', 'Foreign secret child text.')

    response = client.get(f'/api/v1/reader/threads/{notebook}/project/export',
                          params={'artifacts': artifact['id']}, headers=origin)
    assert response.status_code == 200, response.text
    envelope = response.json()
    transcript = envelope['conversation']['transcript']
    assert 'Original notebook discussion.' in transcript
    assert 'Our refuge island helps residents cross safely.' in transcript
    assert 'Concept comparison' in transcript
    assert 'Crossing project' in transcript
    assert envelope['conversation']['message_count'] == 2
    assert envelope['conversation']['truncated'] is False
    # Progress stays the requested notebook's, not the child chat's.
    assert envelope['thinking_path']['current_stage'] == 'problem_identification'
    assert envelope['artifacts'][0]['title'] == 'Shared notes'
    assert envelope['title'] == 'Crossing project'
    # Another owner's notebook and child chat never enter the family export.
    assert 'Foreign secret notebook text.' not in transcript
    assert 'Foreign secret child text.' not in transcript
    assert 'Other owner project' not in transcript
    assert 'Other owner chat' not in transcript
    body = response.text
    assert foreign_notebook not in body and foreign_chat not in body
    assert chat not in body
    assert other.owner_id not in body
    assert 'owner_id' not in envelope


def test_project_export_conversation_caps_messages_across_the_family(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The family conversation stays bounded to the newest messages and labels
    the truncation instead of silently omitting older work."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, _root_path, _oidc = _client(tmp_path, 'family-cap')
    origin = {'Origin': 'https://testserver'}
    notebook = client.post('/api/v1/reader/threads', headers=origin,
                           json={'name': 'Bounded project'}).json()['notebook']['id']
    chat = client.post('/api/v1/reader/threads', headers=origin, json={
        'kind': 'chat', 'parent_notebook_id': notebook,
    }).json()['notebook']['id']
    student.update_thread(chat, name='Long child chat')
    student.add_message(notebook, 'user', 'Oldest parent message.')
    for index in range(MAX_EXPORT_MESSAGES):
        student.add_message(chat, 'user', f'Child message {index}.')

    response = client.get(f'/api/v1/reader/threads/{notebook}/project/export',
                          headers=origin)
    assert response.status_code == 200, response.text
    conversation = response.json()['conversation']
    assert conversation['message_count'] == MAX_EXPORT_MESSAGES
    assert conversation['truncated'] is True
    transcript = conversation['transcript']
    assert 'Oldest parent message.' not in transcript
    assert 'Child message 0.' in transcript
    assert f'Child message {MAX_EXPORT_MESSAGES - 1}.' in transcript
    assert 'Long child chat' in transcript


def test_project_export_from_a_child_chat_covers_every_sibling(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """An export opened from a child chat includes the project's other chats.

    The family is the whole project, so a sibling chat's message and title are
    exported even when the requested notebook is one child chat.
    """
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, _root_path, _oidc = _client(tmp_path, 'family-child-export')
    origin = {'Origin': 'https://testserver'}
    notebook = client.post('/api/v1/reader/threads', headers=origin,
                           json={'name': 'Crossing project'}).json()['notebook']['id']
    first = client.post('/api/v1/reader/threads', headers=origin, json={
        'kind': 'chat', 'parent_notebook_id': notebook,
    }).json()['notebook']['id']
    sibling = client.post('/api/v1/reader/threads', headers=origin, json={
        'kind': 'chat', 'parent_notebook_id': notebook,
    }).json()['notebook']['id']
    student.update_thread(first, name='First child chat')
    student.update_thread(sibling, name='Sibling child chat')
    student.add_message(notebook, 'user', 'Project framing message.')
    student.add_message(first, 'user', 'First child reflection.')
    student.add_message(sibling, 'user', 'Sibling chat insight.')

    response = client.get(f'/api/v1/reader/threads/{first}/project/export',
                          headers=origin)
    assert response.status_code == 200, response.text
    envelope = response.json()
    transcript = envelope['conversation']['transcript']
    assert 'Sibling chat insight.' in transcript
    assert 'Sibling child chat' in transcript
    assert 'First child reflection.' in transcript
    assert 'Project framing message.' in transcript
    assert envelope['conversation']['message_count'] == 3
    # The export is still titled by the notebook it was opened from.
    assert envelope['title'] == 'First child chat'


def _client(tmp_path: Path, name: str) -> tuple[TestClient, StudentStore, Path, FakeOIDC]:
    root = StudentStore(tmp_path / f'{name}.sqlite3')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'other', 'student')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    return client, StudentStore(root.path, identifier='cognito:student'), root.path, oidc


def test_project_export_assembles_selected_saved_work_with_provenance(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The selected export combines conversation, summary, Thinking Path, chosen
    artifacts/canvases and source references from saved authorized rows only —
    with revision metadata, AI provenance and the shared download policy."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, _root_path, _oidc = _client(tmp_path, 'project-export')
    thread = student.create_thread(name='Market project', model_id='mock',
                                   support_mode='critical-thinking')
    student.update_thread(thread, metadata={'learning_journey': {
        'current_stage': 'concept_generation', 'completed_stages': ['problem_identification'],
        'stage_notes': {'problem_identification': 'Coach summary'},
    }})
    message_id = student.add_message(thread, 'user', 'Residents need safer crossings.', metadata={
        'thinking_stage': 'problem_identification', 'interaction_intent': 'project_coaching',
    })
    student.add_message(thread, 'assistant', 'Compare two concepts.', metadata={
        'assessment': {
            'current_stage': 'problem_identification', 'recommendation': 'stay',
            'learning_summary': 'Identified a need for safer crossings.',
            'review_strengths': ['Identified the affected residents.'],
            'review_improvements': ['Compare other crossing options.'],
            'facione_scores': {'analysis': 3},
        },
    })
    source = add_text_source(student, thread, 'Field study',
                             'Older residents avoid the market crossing at dusk.')
    created = client.post(f'/api/v1/reader/threads/{thread}/artifacts', headers={
        'Origin': 'https://testserver',
    }, json={'title': 'Field notes', 'kind': 'notes', 'document': DOCUMENT,
             'references': [{'kind': 'source', 'id': source['id']},
                            {'kind': 'message', 'id': message_id}]})
    assert created.status_code == 201
    artifact_id = created.json()['id']
    canvas = client.post(f'/api/v1/reader/threads/{thread}/canvases', headers={
        'Origin': 'https://testserver',
    }, json={'title': 'Crossing map', 'graph': GRAPH})
    assert canvas.status_code == 201
    canvas_id = canvas.json()['id']
    saved_graph = canvas.json()['graph']

    response = client.get(
        f'/api/v1/reader/threads/{thread}/project/export'
        f'?artifacts={artifact_id}&canvases={canvas_id}',
        headers={'Origin': 'https://testserver'})

    assert response.status_code == 200, response.text
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'
    disposition = response.headers['content-disposition']
    assert disposition.startswith('attachment')
    assert 'Market%20project-project.json' in disposition

    envelope = response.json()
    assert envelope['kind'] == 'project_export'
    assert envelope['title'] == 'Market project'

    # Conversation is the saved active transcript projection.
    assert 'Residents need safer crossings.' in envelope['conversation']['transcript']
    assert envelope['conversation']['truncated'] is False

    # Thinking Path and summary come from the same student-facing projections.
    assert [stage['label'] for stage in envelope['thinking_path']['stages']][0] == 'Problem identification'
    assert envelope['thinking_path']['current_stage'] == 'concept_generation'
    assert envelope['thinking_path']['stages'][0]['completed'] is True
    assert envelope['summary']['saved_summary'] == 'Identified a need for safer crossings.'
    assert envelope['summary']['facione_scores'][0] == {'dimension': 'Analysis', 'score': 3}

    # Selected artifact: revision metadata, AI provenance and labeled references.
    exported = envelope['artifacts']
    assert [entry['title'] for entry in exported] == ['Field notes']
    assert exported[0]['revision'] == 1 and exported[0]['kind'] == 'notes'
    assert exported[0]['origin'] == 'editor'
    assert exported[0]['document'] == DOCUMENT
    references = {entry['kind']: entry for entry in exported[0]['references']}
    assert references['source']['available'] is True
    assert references['source']['title'] == 'Field study'
    assert references['message']['available'] is True
    assert 'Residents need safer crossings.' in references['message']['title']

    # Selected canvas keeps the canonical saved graph.
    assert [entry['title'] for entry in envelope['canvases']] == ['Crossing map']
    assert envelope['canvases'][0]['graph'] == saved_graph
    assert envelope['canvases'][0]['revision'] == 1

    # Source references are listed with availability labels.
    assert {'kind': 'source', 'title': 'Field study', 'available': True} \
        in envelope['source_references']

    body = response.text
    # No workspace identifiers, owner identity or operational fields leave the service.
    assert artifact_id not in body
    assert canvas_id not in body
    assert thread not in body
    assert student.owner_id not in body
    assert 'owner_id' not in envelope


def test_project_export_cannot_read_a_foreign_or_unknown_resource(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Selections resolve only inside the owner's notebook; anything else is not found."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, root_path, _oidc = _client(tmp_path, 'project-export-foreign')
    thread = student.create_thread(name='Mine', model_id='mock', support_mode='critical-thinking')

    other = StudentStore(root_path, identifier='cognito:other')
    foreign_thread = other.create_thread(name='Other', model_id='mock',
                                         support_mode='critical-thinking')
    foreign_artifact = other.create_artifact(foreign_thread, 'Secret notes', DOCUMENT)
    foreign_canvas = other.create_canvas(foreign_thread, 'Secret map', GRAPH)

    base = f'/api/v1/reader/threads/{thread}/project/export'
    for query in (f'artifacts={foreign_artifact["id"]}', f'canvases={foreign_canvas["id"]}',
                  'artifacts=does-not-exist', 'canvases=does-not-exist'):
        response = client.get(f'{base}?{query}', headers={'Origin': 'https://testserver'})
        assert response.status_code == 404, (query, response.status_code)
        assert 'Secret' not in response.text

    # An unauthenticated caller gets the same boundary with no projection at all.
    anonymous = TestClient(create_app(StudentStore(root_path), oidc_client=FakeOIDC(root_path)),
                           base_url='https://testserver')
    assert anonymous.get(base).status_code == 401


def test_project_export_bounds_are_fail_closed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Item-count and selection bounds reject oversized selections before any work."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, _root_path, _oidc = _client(tmp_path, 'project-export-bounds')
    thread = student.create_thread(name='Bounds', model_id='mock', support_mode='critical-thinking')
    for index in range(MAX_EXPORT_ARTIFACTS + 1):
        student.create_artifact(thread, f'Notes {index}', DOCUMENT)
    ids = ','.join(row['id'] for row in student.list_artifacts(thread))
    response = client.get(f'/api/v1/reader/threads/{thread}/project/export?artifacts={ids}',
                          headers={'Origin': 'https://testserver'})
    assert response.status_code == 422
    assert 'Too many' in response.text
    malformed = client.get(
        f'/api/v1/reader/threads/{thread}/project/export?artifacts=a%2Fb',
        headers={'Origin': 'https://testserver'})
    assert malformed.status_code == 422


def test_project_export_labels_missing_references_and_survives_restart(
        tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A reference whose evidence disappeared is labeled unavailable, never substituted,
    and the export still works from persisted rows after a real backend restart."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    client, student, root_path, oidc = _client(tmp_path, 'project-export-restart')
    thread = student.create_thread(name='Restart', model_id='mock', support_mode='critical-thinking')
    message_id = student.add_message(thread, 'user', 'Before supersede.', metadata={
        'thinking_stage': 'problem_identification', 'interaction_intent': 'project_coaching',
    })
    source = add_text_source(student, thread, 'Guide', 'Course guidance text.')
    artifact = student.create_artifact(
        thread, 'Linked notes', DOCUMENT,
        references=[{'kind': 'source', 'id': source['id']},
                    {'kind': 'message', 'id': message_id}])
    student.delete_source(thread, source['id'])

    def export(target: TestClient) -> dict[str, object]:
        response = target.get(
            f'/api/v1/reader/threads/{thread}/project/export?artifacts={artifact["id"]}',
            headers={'Origin': 'https://testserver'})
        assert response.status_code == 200, response.text
        return response.json()

    envelope = export(client)
    references = {entry['kind']: entry for entry in envelope['artifacts'][0]['references']}
    assert references['source'] == {'kind': 'source', 'available': False}
    assert references['message']['available'] is True
    assert {'kind': 'source', 'available': False} in envelope['source_references']

    restarted = TestClient(create_app(StudentStore(root_path), oidc_client=oidc),
                           base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    assert export(restarted) == envelope
