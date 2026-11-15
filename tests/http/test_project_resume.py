"""Returning-student resume contracts through the owned learning-state API."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


def test_resume_separates_saved_student_work_from_coach_feedback(tmp_path: Path) -> None:
    """A legacy notebook resumes exact authored text without inventing authorship."""
    store = StudentStore(tmp_path / 'resume.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    store.update_thread(thread, metadata={'learning_journey': {
        'current_stage': 'concept_generation', 'completed_stages': ['problem_identification'],
        'stage_notes': {'problem_identification': 'Coach summary of the framing'},
    }})
    store.add_message(thread, 'user', 'Older residents need a safer crossing.', metadata={'thinking_stage': 'problem_identification', 'interaction_intent': 'project_coaching'})
    store.add_message(thread, 'assistant', 'Consider the crossing context.', metadata={'thinking_stage': 'problem_identification'})
    store.add_message(thread, 'user', 'What does the lecture say?', metadata={'thinking_stage': 'problem_identification', 'interaction_intent': 'lecture_help'})
    store.add_message(thread, 'user', 'Legacy text without a stage')
    client = TestClient(create_app(store))
    response = client.get(f'/api/v1/threads/{thread}/learning-state')
    assert response.status_code == 200
    resume = response.json()['project_resume']
    assert resume['current_stage'] == 'concept_generation'
    framing = resume['stages'][0]
    assert [work['text'] for work in framing['student_work']] == ['Older residents need a safer crossing.']
    assert framing['coach_summary'] == 'Coach summary of the framing'
    assert framing['feedback'][0]['text'] == 'Consider the crossing context.'
    assert resume['stages'][1]['student_work'] == []
    assert resume['stages'][1]['next_action'] == 'Describe two different concepts and compare how each addresses the need.'
    assert response.json()['learning_journey']['stage_notes']['problem_identification'] == 'Coach summary of the framing'


def test_resume_tracks_confirmation_revisit_and_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saved decisions and authored work survive moves and a new app instance."""
    from backend.domain import StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.settings import settings
    import backend.owner_context as owners

    monkeypatch.setattr(settings, 'student_stage_selection', True)
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    database = tmp_path / 'restart.sqlite3'
    store = StudentStore(database)
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    text = 'Older residents need to cross safely to reach the shops.'
    sent = client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': text, 'interaction_intent': 'project_coaching', 'response_detail': 'short',
    })
    assert sent.status_code == 200, sent.text
    pending = sent.json()['pending_transition']
    before = client.get(f'{path}/learning-state').json()['project_resume']['stages'][0]
    assert before['decision'] == 'pending'
    assert 'Confirm next stage' in before['next_action']
    assert client.post(f"{path}/phase-transitions/{pending['id']}/resolve", json={'accepted': True}).status_code == 200
    assert client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'problem_identification'}).status_code == 200
    restored = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    resume = restored.get(f'{path}/learning-state').json()['project_resume']
    assert resume['current_stage'] == 'problem_identification'
    assert resume['stages'][0]['student_work'][0]['text'] == text
    assert resume['stages'][0]['decision'] == 'confirmed'
    assert resume['stages'][0]['completed'] is True
    assert len({stage['next_action'] for stage in resume['stages']}) == 5
    assert len(resume['stages'][0]['feedback']) == len(before['feedback'])


def test_resume_keeps_canonical_focus_without_inferring_completion(tmp_path: Path) -> None:
    """A saved later focus confers no completion awards, including legacy gaps."""
    store = StudentStore(tmp_path / 'legacy.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    store.update_thread(thread, metadata={'learning_journey': {'current_stage': 'deep_analysis', 'completed_stages': []}})
    client = TestClient(create_app(store))
    response = client.get(f'/api/v1/threads/{thread}/learning-state')
    assert response.status_code == 200
    assert response.json()['project_resume']['current_stage'] == 'deep_analysis'
    assert not any(view['completed'] for view in response.json()['project_resume']['stages'])


def test_resume_uses_active_revision_after_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Edited contributions replace superseded text in the resume view only."""
    from backend.mock_provider import DeterministicCoachProvider
    from backend.domain import StageDecision
    import backend.owner_context as owners

    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.STAY))
    store = StudentStore(tmp_path / 'edit.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store))
    path = f'/api/v1/threads/{thread}'
    sent = client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': 'Our initial framing is crossing safety.',
        'interaction_intent': 'project_coaching', 'response_detail': 'short',
    })
    assert sent.status_code == 200, sent.text
    user = next(row for row in client.get(f'{path}/messages').json() if row['role'] == 'user')
    edited = client.post(f"{path}/messages/{user['id']}/revise", json={
        'content': 'Our revised framing concerns residents reaching nearby shops safely.',
        'idempotency_key': 'resume-edit', 'response_detail': 'short',
    })
    assert edited.status_code == 200, edited.text
    state = client.get(f'{path}/learning-state').json()['project_resume']
    assert [row['text'] for row in state['stages'][0]['student_work']] == ['Our revised framing concerns residents reaching nearby shops safely.']
    assert all('initial framing' not in row['text'] for row in state['stages'][0]['feedback'])


def test_resume_reads_all_stages_without_generation_or_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All five stage artifacts are saved-work projections with no provider use."""
    from backend.mock_provider import DeterministicCoachProvider

    def forbidden_assessment(*args: object, **kwargs: object) -> None:
        """Fail if any resume read tries to invoke the model boundary."""
        raise AssertionError('Resume must not invoke a model')

    monkeypatch.setattr(DeterministicCoachProvider, 'assess', forbidden_assessment)
    monkeypatch.setattr(DeterministicCoachProvider, 'assess_stage_checkpoint', forbidden_assessment)
    store = StudentStore(tmp_path / 'all-stages.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    stage_ids = ['problem_identification', 'concept_generation', 'design_specification', 'deep_analysis', 'reflection']
    texts = ['Residents need safer crossings.', 'Signals and refuge islands have different trade-offs.', 'Test whether crossing time meets mobility needs.', 'Longer signals may delay emergency vehicles.', 'Interviews changed my assumption about speed.']
    for stage, text in zip(stage_ids, texts, strict=True):
        store.add_message(thread, 'user', text, metadata={'thinking_stage': stage, 'interaction_intent': 'project_coaching'})
    client = TestClient(create_app(store))
    path = f'/api/v1/threads/{thread}'
    before = client.get(path).json()
    messages = client.get(f'{path}/messages').json()
    first = client.get(f'{path}/learning-state').json()['project_resume']
    second = client.get(f'{path}/learning-state').json()['project_resume']
    assert first == second
    assert [stage['student_work'][0]['text'] for stage in first['stages']] == texts
    assert len({stage['next_action'] for stage in first['stages']}) == 5
    assert client.get(path).json() == before
    assert client.get(f'{path}/messages').json() == messages
    other = StudentStore(tmp_path / 'all-stages.sqlite3', identifier='another-student')
    assert TestClient(create_app(other)).get(f'{path}/learning-state').status_code == 404
