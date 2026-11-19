"""Student project contracts through the authenticated browser HTTP boundary."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch, mark

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_project_resumes_canonical_authored_work(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Browser reads reuse saved artifacts and canonical unlocks without inferred awards."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    root = StudentStore(tmp_path / 'project.sqlite3')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    student.update_thread(thread, metadata={'learning_journey': {
        'current_stage': 'concept_generation', 'completed_stages': ['problem_identification'],
        'stage_notes': {'problem_identification': 'Coach summary'},
    }})
    student.add_message(thread, 'user', 'Residents need safer crossings.', metadata={
        'thinking_stage': 'problem_identification', 'interaction_intent': 'project_coaching',
    })
    student.add_message(thread, 'user', 'What is analogy?', metadata={
        'thinking_stage': 'problem_identification', 'interaction_intent': 'lecture_help',
    })
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    response = client.get(f'/api/v1/reader/threads/{thread}/project')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    view = response.json()
    assert view['owner_id'] == student.owner_id
    assert view['current_stage'] == 'concept_generation'
    assert view['pending'] is None
    assert [stage['id'] for stage in view['stages'] if stage['selectable']] == ['problem_identification', 'concept_generation']
    framing = view['stages'][0]
    assert framing['student_work'][0]['text'] == 'Residents need safer crossings.'
    assert len(framing['student_work']) == 1
    assert framing['coach_summary'] == 'Coach summary'
    assert framing['completed'] is True
    assert view['stages'][1]['next_action'] == 'Describe two different concepts and compare how each addresses the need.'
    assert all(item['score'] is None for item in view['review']['facione_scores'])
    student.add_message(thread, 'assistant', 'Consider other crossing options.', metadata={
        'assessment': {
            'current_stage': 'problem_identification', 'recommendation': 'stay',
            'learning_summary': 'Identified a need for safer crossings.',
            'review_strengths': ['Identified the affected residents.'],
            'review_improvements': ['Compare other crossing options.'],
            'facione_scores': {'analysis': 3},
        },
    })
    review = client.get(f'/api/v1/reader/threads/{thread}/project').json()['review']
    assert review['summary'] == 'Identified a need for safer crossings.'
    assert review['strengths'][0]['items'] == ['Identified the affected residents.']
    assert review['improvements'][0]['items'] == ['Compare other crossing options.']
    assert review['facione_scores'][0] == {'dimension': 'Analysis', 'score': 3}
    student.update_thread(thread, metadata={'journey_stage_reviews': {
        'jobs': {'problem_identification': {'status': 'complete'}},
        'reviews': {'problem_identification': {
            'strengths': ['Named a concrete setting.'],
            'areas_to_revisit': ['Check how people reach the bus stop.'],
            'facione_scores': {'analysis': 4},
        }},
    }})
    review = client.get(f'/api/v1/reader/threads/{thread}/project').json()['review']
    assert review['strengths'][0]['items'] == [
        'Named a concrete setting.', 'Identified the affected residents.',
    ]
    assert review['improvements'][0]['items'] == [
        'Check how people reach the bus stop.', 'Compare other crossing options.',
    ]
    assert review['facione_scores'][0]['score'] == 4


def test_reader_project_turn_requires_confirmation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A saved project recommendation is visible without awarding completion."""
    import json
    import backend.owner_context as owners
    from backend.domain import StageDecision
    from backend.mock_provider import DeterministicCoachProvider

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    root = StudentStore(tmp_path / 'turn.sqlite3')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc, auto_advance_stages=False), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    text = 'Older residents need to cross safely to reach the shops.'
    response = client.post(f'{path}/project/stream', json={
        'student_message': text, 'idempotency_key': 'project-one',
    }, headers={'Origin': 'https://testserver'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    turn = next(event['turn'] for event in events if event['event'] == 'done')
    view = client.get(f'{path}/project').json()
    assert view['pending']['id'] == turn['pending_transition']['id']
    assert view['pending']['rationale']
    assert view['current_stage'] == 'problem_identification'
    assert not view['stages'][0]['completed']
    assert view['stages'][0]['student_work'][0]['text'] == text
    review = view['review']
    assert review['summary'] == turn['assessment']['learning_summary']
    assert all(item['score'] is None for item in review['facione_scores'])
    assert client.get(f'{path}/coach-turn?idempotency_key=project-one').json() == turn


@mark.parametrize("quick_chat", [False, True], ids=["notebook", "standalone-chat"])
def test_reader_decisions_revisits_and_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch, quick_chat: bool,
) -> None:
    """Reject/confirm/repeat/stale actions retain canonical completion across restart."""
    import json
    import backend.owner_context as owners
    from backend.domain import StageDecision
    from backend.mock_provider import DeterministicCoachProvider

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    root = StudentStore(tmp_path / 'decisions.sqlite3')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking', quick_chat=quick_chat)
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc, auto_advance_stages=False), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    origin = {'Origin': 'https://testserver'}
    for key, accepted in [('reject', False), ('confirm', True)]:
        response = client.post(f'{path}/project/stream', json={
            'student_message': 'Older residents need to cross safely to reach the shops.', 'idempotency_key': key,
        }, headers=origin)
        turn = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
        transition = turn['pending_transition']['id']
        assert client.post(f'{path}/project/resolve/{transition}', json={'accepted': accepted}, headers=origin).status_code == 200
        assert client.post(f'{path}/project/resolve/{transition}', json={'accepted': True}, headers=origin).status_code == 409
        view = client.get(f'{path}/project').json()
        assert view['pending'] is None
        assert view['current_stage'] == ('concept_generation' if accepted else 'problem_identification')
        assert view['stages'][0]['completed'] is accepted
    assert client.post(f'{path}/project/select-stage', json={'stage_id': 'reflection'}, headers=origin).status_code == 409
    for stage in ['problem_identification', 'problem_identification', 'concept_generation']:
        assert client.post(f'{path}/project/select-stage', json={'stage_id': stage}, headers=origin).status_code == 200
    before = client.get(f'{path}/project').json()
    assert before['stages'][0]['completed']
    assert not before['stages'][1]['completed']
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc, auto_advance_stages=False), base_url='https://testserver')
    restarted.cookies.update(client.cookies)
    assert restarted.get(f'{path}/project').json() == before


def test_reader_project_guards_and_untrusted_authority(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Every browser project route fails closed on credentials, CSRF, role and ownership."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'guards.sqlite3')
    for name, role in [('student', 'student'), ('other', 'student'), ('staff', 'lecturer')]:
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    path = f'/api/v1/reader/threads/{thread}/project'
    requests = [('stream', {'student_message': 'My work', 'idempotency_key': 'guard'}),
                ('resolve/missing', {'accepted': True}), ('select-stage', {'stage_id': 'problem_identification'})]
    origin = {'Origin': 'https://testserver'}
    assert client.get(path).status_code == 401
    for route, body in requests:
        assert client.post(f'{path}/{route}', json=body, headers=origin).status_code == 401
    for identity, expected in [('other', 404), ('staff', 403)]:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add(identity))
        assert client.get(path).status_code == expected
        for route, body in requests:
            assert client.post(f'{path}/{route}', json=body, headers=origin).status_code == expected
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    for route, body in requests:
        for headers in [{}, {'Origin': 'https://evil.test'}, {**origin, 'Sec-Fetch-Site': 'cross-site'}]:
            assert client.post(f'{path}/{route}', json=body, headers=headers).status_code == 403
        assert client.post(f'{path}/{route}', json={**body, 'current_stage': 'reflection'}, headers=origin).status_code == 422
    assert client.post(f'{path}/resolve/missing', json={'accepted': 'true'}, headers=origin).status_code == 422
    assert client.get(path).json()['current_stage'] == 'problem_identification'


def test_reader_stale_recommendation_and_completed_stage_coaching(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A newer turn fences old decisions; revisiting never awards completion again."""
    import json
    import backend.owner_context as owners
    from backend.domain import StageDecision
    from backend.mock_provider import DeterministicCoachProvider

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    root = StudentStore(tmp_path / 'stale.sqlite3')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc, auto_advance_stages=False), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    origin = {'Origin': 'https://testserver'}
    response = client.post(f'{path}/project/stream', json={
        'student_message': 'Older residents need safe crossings to reach nearby shops.', 'idempotency_key': 'first',
    }, headers=origin)
    turn = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
    transitions = [turn['pending_transition']['id']]
    user = client.get(f'{path}/messages/page').json()['messages'][0]
    revised = client.post(f'/api/v1/threads/{thread}/messages/{user["id"]}/revise', json={
        'content': 'Older residents need more time to cross the junction safely to reach shops.',
        'idempotency_key': 'revised', 'response_detail': 'short',
    })
    assert revised.status_code == 200
    transitions.append(revised.json()['pending_transition']['id'])
    assert client.post(f'{path}/project/resolve/{transitions[0]}', json={'accepted': True}, headers=origin).status_code == 409
    assert client.get(f'{path}/project').json()['pending']['id'] == transitions[1]
    assert client.post(f'{path}/project/resolve/{transitions[1]}', json={'accepted': True}, headers=origin).status_code == 200
    assert client.post(f'{path}/project/select-stage', json={'stage_id': 'problem_identification'}, headers=origin).status_code == 200
    response = client.post(f'{path}/project/stream', json={
        'student_message': 'Interviews suggest residents need longer crossing times at the junction.', 'idempotency_key': 'refine',
    }, headers=origin)
    turn = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
    assert turn['pending_transition'] is None
    view = client.get(f'{path}/project').json()
    assert view['current_stage'] == 'problem_identification'
    assert [stage['id'] for stage in view['stages'] if stage['completed']] == ['problem_identification']
