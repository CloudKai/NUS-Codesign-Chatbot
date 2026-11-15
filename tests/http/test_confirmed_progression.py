"""Confirmation and revisit contracts through the student API, with fake models."""
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.domain import StageDecision
from backend.mock_provider import DeterministicCoachProvider
from backend.settings import settings
from backend.student_store import StudentStore


def test_informal_framing_waits_for_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A semantic ADVANCE on informal student wording awaits an explicit choice."""
    import backend.owner_context as owners
    monkeypatch.setattr(settings, "student_stage_selection", True)
    monkeypatch.setattr(owners, "configured_coach_provider", lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    store = StudentStore(tmp_path / "confirm.sqlite3")
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f"/api/v1/threads/{thread}"
    reply = client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': 'Older pedestrians near our school struggle to cross before the signal changes. They need to reach nearby shops safely and without stress.',
        'interaction_intent': 'project_coaching', 'response_detail': 'short',
    })
    assert reply.status_code == 200, reply.text
    pending = client.get(f'{path}/phase-transitions/pending').json()
    assert pending is not None
    assert client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'problem_identification'}).status_code == 200
    assert client.get(f'{path}/phase-transitions/pending').json()['id'] == pending['id']
    journey = client.get(f'{path}/learning-state').json()['learning_journey']
    assert journey['current_stage'] == 'problem_identification'
    assert journey['completed_stages'] == []
    locked = client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'concept_generation'})
    assert locked.status_code == 400
    resolved = client.post(f"{path}/phase-transitions/{pending['id']}/resolve", json={'accepted': True})
    assert resolved.status_code == 200, resolved.text
    journey = client.get(f'{path}/learning-state').json()['learning_journey']
    assert journey['current_stage'] == 'concept_generation'
    assert journey['completed_stages'] == ['problem_identification']


@pytest.mark.parametrize('message', [
    'How might we do something for people so that things become better?',
    'How might we install a 60-second light for older pedestrians so that they have more time?',
])
def test_formal_syntax_cannot_override_semantic_stay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Vague and solution-locked drafts stay when the semantic assessor says stay."""
    import backend.owner_context as owners
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.STAY))
    store = StudentStore(tmp_path / 'stay.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store, auto_advance_stages=False))
    reply = client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': message, 'interaction_intent': 'project_coaching',
        'response_detail': 'short',
    })
    assert reply.status_code == 200
    assert reply.json()['assessment']['recommendation'] == 'stay'
    assert reply.json()['pending_transition'] is None


def test_revisit_does_not_request_new_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Previously completed stages accept refinement without another award."""
    import backend.owner_context as owners
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    store = StudentStore(tmp_path / 'revisit.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    store.update_thread(thread, metadata={'learning_journey': {
        'current_stage': 'concept_generation', 'completed_stages': ['problem_identification'],
        'stage_notes': {'problem_identification': 'Original student framing'},
    }})
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    before = client.get(f'{path}/learning-state').json()['learning_journey']
    assert client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'problem_identification'}).status_code == 200
    reply = client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': 'How might we improve crossings for older pedestrians so that they reach the shops safely?',
        'interaction_intent': 'project_coaching', 'response_detail': 'short',
    })
    assert reply.status_code == 200
    assert reply.json()['pending_transition'] is None
    assert client.get(f'{path}/phase-transitions/pending').json() is None
    assert client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'concept_generation'}).status_code == 200
    after = client.get(f'{path}/learning-state').json()['learning_journey']
    assert after['completed_stages'] == before['completed_stages']
    assert after['stage_notes'] == before['stage_notes']


def test_pending_reject_restart_and_competing_confirmations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pending decisions recover after restart, and two tabs produce one winner."""
    from concurrent.futures import ThreadPoolExecutor
    import backend.owner_context as owners
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    database = tmp_path / 'tabs.sqlite3'
    store = StudentStore(database)
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    request = {'thread_id': thread, 'current_stage': 'problem_identification',
               'student_message': 'Older pedestrians need safer crossings near school to reach the shops without rushing.',
               'interaction_intent': 'project_coaching', 'response_detail': 'short'}
    assert client.post('/api/v1/coach/turn', json=request).status_code == 200
    pending = client.get(f'{path}/phase-transitions/pending').json()
    assert client.post(f"{path}/phase-transitions/{pending['id']}/resolve", json={'accepted': False}).status_code == 200
    assert client.get(f'{path}/learning-state').json()['learning_journey']['completed_stages'] == []
    assert client.post('/api/v1/coach/turn', json=request).status_code == 200
    pending = client.get(f'{path}/phase-transitions/pending').json()
    tab_a = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    tab_b = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    assert tab_a.get(f'{path}/phase-transitions/pending').json()['id'] == pending['id']
    url = f"{path}/phase-transitions/{pending['id']}/resolve"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda tab: tab.post(url, json={'accepted': True}).status_code, [tab_a, tab_b]))
    assert sorted(results) == [200, 404]
    assert tab_b.post(url, json={'accepted': True}).status_code == 404
    recovered = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    journey = recovered.get(f'{path}/learning-state').json()['learning_journey']
    assert journey['current_stage'] == 'concept_generation'
    assert journey['completed_stages'] == ['problem_identification']
    assert recovered.get(f'{path}/phase-transitions/pending').json() is None


def test_confirmation_preserves_concurrent_learning_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The winning decision merges into transaction-current learning history."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import backend.owner_context as owners
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    reached = threading.Event()
    resume = threading.Event()

    class PausedDecisionStore(StudentStore):
        """Pause the persistence boundary to deterministically interleave two tabs."""
        def apply_phase_transition_decision(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            """Wait until a separate tab has saved more learning history."""
            reached.set()
            assert resume.wait(10)
            return super().apply_phase_transition_decision(*args, **kwargs)

    database = tmp_path / 'preserve.sqlite3'
    store = PausedDecisionStore(database)
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    assert client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': 'Older pedestrians need safer crossings to reach the shops without rushing.',
        'interaction_intent': 'project_coaching', 'response_detail': 'short',
    }).status_code == 200
    pending = client.get(f'{path}/phase-transitions/pending').json()
    other_tab = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    with ThreadPoolExecutor(max_workers=1) as pool:
        decision = pool.submit(client.post, f"{path}/phase-transitions/{pending['id']}/resolve", json={'accepted': True})
        assert reached.wait(10)
        assert other_tab.patch(path, json={'metadata': {'response_detail': 'long'}}).status_code == 200
        assert other_tab.post('/api/v1/coach/turn', json={
            'thread_id': thread, 'current_stage': 'problem_identification',
            'student_message': 'My new observation is that older pedestrians rush at the school signal to reach nearby shops.',
            'interaction_intent': 'project_coaching', 'response_detail': 'long',
        }).status_code == 200
        latest_summary = other_tab.get(f'{path}/learning-state').json()['learning_journey']['learning_summary']
        resume.set()
        assert decision.result().status_code == 200
    journey = other_tab.get(f'{path}/learning-state').json()['learning_journey']
    assert journey['response_detail'] == 'long'
    assert journey['learning_summary'] == latest_summary
    assert journey['completed_stages'] == ['problem_identification']


def test_legacy_noncontiguous_history_is_preserved_without_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing focus and explicit completions survive; gaps grant no new awards."""
    monkeypatch.setattr(settings, 'student_stage_selection', True)
    store = StudentStore(tmp_path / 'legacy.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    store.update_thread(thread, metadata={'learning_journey': {
        'current_stage': 'design_specification', 'completed_stages': ['concept_generation'],
        'stage_notes': {'concept_generation': 'Existing student idea notes'},
    }})
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    before = client.get(f'{path}/learning-state').json()['learning_journey']
    assert before['current_stage'] == 'design_specification'
    assert before['completed_stages'] == ['concept_generation']
    for target in ['concept_generation', 'problem_identification', 'concept_generation']:
        response = client.post(f'{path}/learning-state/select-stage', json={'stage_id': target})
        assert response.status_code == 200, response.text
        journey = response.json()['learning_journey']
        assert journey['completed_stages'] == before['completed_stages']
        assert journey['stage_notes'] == before['stage_notes']
    assert client.post(f'{path}/learning-state/select-stage', json={'stage_id': 'deep_analysis'}).status_code == 400


def test_superseded_pending_cannot_win_confirmation_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An edit in another tab invalidates an old same-stage pending decision."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import backend.owner_context as owners
    monkeypatch.setattr(owners, 'configured_coach_provider', lambda: DeterministicCoachProvider(StageDecision.ADVANCE))
    reached = threading.Event()
    resume = threading.Event()

    class PausedConnection:
        """SQLite adapter proxy that pauses before the decision's conditional write."""
        def __init__(self, connection: Any, pause: bool) -> None:
            self.connection = connection
            self.pause = pause

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

        def __enter__(self) -> Any:
            self.connection.__enter__()
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.connection.__exit__(*args)

        def execute(self, sql: str, parameters: Any = ()) -> Any:
            """Interleave an append-only edit after the old pending row was read."""
            if self.pause and "WHERE id=? AND decision_status='pending'" in sql:
                reached.set()
                assert resume.wait(10)
            return self.connection.execute(sql, parameters)

    class PausedStore(StudentStore):
        """Supply the deterministic connection adapter for this race only."""
        pause = False

        def _connect(self) -> Any:
            return PausedConnection(super()._connect(), self.pause)

    database = tmp_path / 'superseded.sqlite3'
    store = PausedStore(database)
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f'/api/v1/threads/{thread}'
    assert client.post('/api/v1/coach/turn', json={
        'thread_id': thread, 'current_stage': 'problem_identification',
        'student_message': 'Older pedestrians need safer crossings to reach nearby shops without stress.',
        'interaction_intent': 'project_coaching', 'response_detail': 'short',
    }).status_code == 200
    pending = client.get(f'{path}/phase-transitions/pending').json()
    user = next(row for row in client.get(f'{path}/messages').json() if row['role'] == 'user')
    other = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    store.pause = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        decision = pool.submit(client.post, f"{path}/phase-transitions/{pending['id']}/resolve", json={'accepted': True})
        assert reached.wait(10)
        edited = other.post(f"{path}/messages/{user['id']}/revise", json={
            'content': 'Older pedestrians need safer crossings near school to reach shops without rushing.',
            'idempotency_key': 'edit-racing-confirm', 'response_detail': 'short',
        })
        assert edited.status_code == 200, edited.text
        replacement = other.get(f'{path}/phase-transitions/pending').json()
        assert replacement['id'] != pending['id']
        resume.set()
        assert decision.result().status_code == 404
    assert other.get(f'{path}/phase-transitions/pending').json()['id'] == replacement['id']
    journey = other.get(f'{path}/learning-state').json()['learning_journey']
    assert journey['current_stage'] == 'problem_identification'
    assert journey['completed_stages'] == []
