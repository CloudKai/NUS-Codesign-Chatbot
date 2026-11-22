"""Whole-chat project briefs through authenticated reader HTTP and a scripted model port."""
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import MonkeyPatch, mark

from backend.api import create_app
from backend.domain import CoachRequest, EducationalAssessment, ProviderAssessmentResult
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


BRIEF = {
    'who_and_why': {'text': 'Older residents crossing near campus need enough time to cross safely.', 'evidence': ['Older residents near campus need more time to cross safely.']},
    'problem': {'text': 'The crossing signal changes before slower pedestrians finish crossing.', 'evidence': ['The signal changes before slower pedestrians finish crossing.']},
    'current_idea': {'text': 'Considering a button that requests extra crossing time; no option is selected yet.', 'evidence': ['We might try a button for extra crossing time, but have not selected an idea.']},
    'what_matters': {'text': None, 'evidence': []},
    'still_to_explore': {'text': 'Whether residents could find and use the button remains untested.', 'evidence': ['We have not tested whether residents can find and use the button.']},
}


def test_brief_summarises_the_whole_active_chat_and_caches_without_changing_learning(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Early context survives newer chatter; unknown requirements stay empty and reads reuse the result."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'brief.sqlite3')
    _seed_user(root, 'student', 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(name='Crossing project', model_id='mock', support_mode='critical-thinking')
    for value in BRIEF.values():
        for quote in value['evidence']:
            owner.add_message(thread, 'user', quote)
    for index in range(25):
        owner.add_message(thread, 'user', f'Hello again {index}')
    calls = []

    class Model:
        """Scripted response at the external model boundary; no network or guessed summary."""
        provider_id = 'scripted'

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Return a known grounded brief and retain the public model input."""
            calls.append(request)
            return ProviderAssessmentResult(response_text='Project brief.', assessment=EducationalAssessment(
                current_stage=request.current_stage, project_brief=BRIEF))

    monkeypatch.setattr('backend.owner_context.configured_coach_provider', Model)
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    path = f'/api/v1/reader/threads/{thread}'
    before = client.get(path + '/project').json()
    response = client.post(path + '/project/brief', json={}, headers={'Origin': 'https://testserver'})
    assert response.status_code == 200
    assert response.json()['brief'] == BRIEF
    assert len(calls) == 1 and len(calls[0].history) == 29
    assert calls[0].history[0]['content'] == 'Older residents near campus need more time to cross safely.'
    assert client.post(path + '/project/brief', json={}, headers={'Origin': 'https://testserver'}).json() == response.json()
    assert len(calls) == 1
    after = client.get(path + '/project').json()
    assert after['review']['project_brief'] == response.json()
    for field in ('current_stage', 'stages', 'pending'):
        assert after[field] == before[field]


def test_live_adapter_receives_every_message_and_the_grounded_brief_contract(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The real adapter must send early context too, rather than its normal recent-message window."""
    from types import SimpleNamespace
    import json
    from backend.providers import OpenAICoachProvider

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'adapter.sqlite3')
    _seed_user(root, 'student', 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(model_id='mock', support_mode='critical-thinking')
    for index in range(30):
        owner.add_message(thread, 'user', f'Unique discussion item {index:02d}: a question about the project.')
    prompts = []

    class Responses:
        """Fake external SDK transport, not a replacement for the application/provider adapter."""
        def create(self, **kwargs: Any) -> SimpleNamespace:
            """Return validated empty facts rather than inventing details from vague chat."""
            prompts.append(kwargs['input'])
            return SimpleNamespace(output_text=json.dumps({'response_text': 'Summary ready.', 'assessment': {
                'current_stage': 'problem_identification', 'project_brief': {key: {'text': None, 'evidence': []} for key in BRIEF},
            }}))

    monkeypatch.setattr('backend.providers.OpenAI', lambda **kwargs: SimpleNamespace(responses=Responses()))
    monkeypatch.setattr('backend.owner_context.configured_coach_provider', lambda: OpenAICoachProvider('fake-test-key', 'fake-model'))
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    response = client.post(f'/api/v1/reader/threads/{thread}/project/brief', json={}, headers={'Origin': 'https://testserver'})
    assert response.status_code == 200
    assert 'Unique discussion item 00:' in prompts[0] and 'Unique discussion item 29:' in prompts[0]
    assert 'who_and_why' in prompts[0] and 'exact' in prompts[0] and 'null' in prompts[0]


@mark.parametrize("small_budget", [False, True])
def test_agentcore_brief_survives_structured_review_adapter(tmp_path: Path, monkeypatch: MonkeyPatch, small_budget: bool) -> None:
    """The configured production adapter preserves the brief instead of discarding optional review fields."""
    from backend.agentcore_provider import AgentCoreCoachProvider
    from fake_agentcore_runtime import FakeAgentCoreRuntime

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'runtime.sqlite3')
    _seed_user(root, 'student', 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(model_id='mock', support_mode='critical-thinking')
    for point in BRIEF.values():
        for quote in point['evidence']:
            owner.add_message(thread, 'user', quote)
    from backend.context_planner import ContextBudget, HistoryContextPlanner
    if small_budget:
        for index in range(100):
            owner.add_message(thread, 'user', f'Detail {index}: ' + 'context ' * 100)
    runtime = FakeAgentCoreRuntime(deep_payload={
        'response_text': 'Summary ready.', 'synthesis': 'Project brief.',
        'current_stage': 'problem_identification', 'recommendation': 'stay',
        'confidence': 0.5, 'rationale_summary': 'Summary only.', 'stage_reviews': [],
        'strengths': [], 'areas_to_develop': [], 'readiness_evidence': [],
        'missing_requirements': [], 'review_depth': 'deep', 'project_brief': BRIEF,
    })
    monkeypatch.setattr('backend.owner_context.configured_coach_provider', lambda: AgentCoreCoachProvider(
        'arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test', client=runtime,
        deep_planner=HistoryContextPlanner(ContextBudget(max_input_tokens=20000)) if small_budget else None))
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
    response = client.post(f'/api/v1/reader/threads/{thread}/project/brief', json={}, headers={'Origin': 'https://testserver'})
    if small_budget:
        assert response.status_code == 503
        assert runtime.calls == []
    else:
        assert response.status_code == 200
        assert response.json()['brief'] == BRIEF


def test_brief_evidence_ownership_origin_and_stale_cache_are_enforced(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Unsupported student claims never become saved summaries; private and stale briefs stay unavailable."""
    from copy import deepcopy
    from backend.mock_provider import DeterministicCoachProvider

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'guards.sqlite3')
    for subject in ('student', 'other'):
        _seed_user(root, subject, 'student')
    owner = StudentStore(root.path, identifier='cognito:student')
    thread = owner.create_thread(model_id='mock', support_mode='critical-thinking')
    for point in BRIEF.values():
        for quote in point['evidence']:
            owner.add_message(thread, 'user', quote)
    calls = []
    unsupported = deepcopy(BRIEF)
    unsupported['what_matters'] = {'text': 'A $50 budget is confirmed.', 'evidence': ['The budget is exactly $50.']}

    class Model:
        """Scripted model boundary can return invalid evidence before its corrected response."""
        provider_id = 'scripted'
        payload = unsupported

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Use ordinary mock chat for an actual new turn; summary output stays scripted."""
            if request.specialist != 'review':
                return DeterministicCoachProvider().assess(request)
            calls.append(request)
            return ProviderAssessmentResult(response_text='Summary.', assessment=EducationalAssessment(
                current_stage=request.current_stage, project_brief=self.payload))

    model = Model()
    monkeypatch.setattr('backend.owner_context.configured_coach_provider', lambda: model)
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver')
    token = oidc.add('student')
    client.cookies.set(settings.cognito_id_token_cookie_name, token)
    path = f'/api/v1/reader/threads/{thread}/project'
    origin = {'Origin': 'https://testserver'}
    assert client.post(path + '/brief', json={}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post(path + '/brief', json={'history': []}, headers=origin).status_code == 422
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
    assert client.post(path + '/brief', json={}, headers=origin).status_code == 404
    client.cookies.set(settings.cognito_id_token_cookie_name, token)
    assert calls == []
    assert client.post(path + '/brief', json={}, headers=origin).status_code == 503
    failed = client.get(path).json()['review']['project_brief']
    assert failed['status'] == 'failed' and failed['brief'] is None
    assert client.post(path + '/brief', json={}, headers=origin).json()['status'] == 'failed'
    assert len(calls) == 1
    model.payload = BRIEF
    assert client.post(path + '/brief', json={'retry': True}, headers=origin).status_code == 200
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver')
    restarted.cookies.set(settings.cognito_id_token_cookie_name, token)
    assert restarted.get(path).json()['review']['project_brief']['status'] == 'current'
    assert restarted.post(path + '/brief', json={}, headers=origin).status_code == 200
    assert len(calls) == 2
    streamed = restarted.post(path + '/stream', json={'student_message': 'I am reconsidering the button idea.', 'idempotency_key': 'new-direction'}, headers=origin)
    assert streamed.status_code == 200 and '"event":"done"' in streamed.text.replace(' ', '')
    stale = restarted.get(path).json()['review']['project_brief']
    assert stale['status'] == 'missing' and stale['brief'] is None
