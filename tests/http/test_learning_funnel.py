"""Learning feedback and lecturer funnel behavior at the public HTTP boundary."""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_usefulness_is_explicit_and_report_is_authorized_audited_and_private(tmp_path: Path) -> None:
    """Saved answers are not useful until rated; only lecturers see aggregate counts."""
    root = StudentStore(tmp_path / 'funnel.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='PRIVATE NOTEBOOK', model_id='mock', support_mode='critical-thinking')
    answer = student.add_message(thread, 'assistant', 'PRIVATE ANSWER', metadata={
        'interaction_intent': 'lecture_help', 'source_refs': [{'id': 'source', 'label': 'S1'}],
    })
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    student_cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    professor_cookie = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    url = '/api/v1/professor/learning-funnel'
    assert client.get(url).status_code == 401
    assert client.get(url, cookies=student_cookie).status_code == 403
    report = client.get(url, cookies=professor_cookie)
    assert report.status_code == 200
    lecture = report.json()['lecture_help']
    assert lecture['useful_answers']['numerator'] == 0
    assert lecture['useful_answers']['denominator'] == 0
    assert lecture['rated_answers']['denominator'] == 1
    event_url = f'/api/v1/threads/{thread}/messages/{answer}/learning-signal'
    for _ in range(2):
        assert client.post(event_url, json={'kind': 'useful'}, cookies=student_cookie).status_code == 200
    report = client.get(url, cookies=professor_cookie)
    assert report.json()['lecture_help']['useful_answers']['numerator'] == 1
    assert report.json()['lecture_help']['rated_answers'] == {
        'numerator': 1, 'denominator': 1, 'unit': 'answers',
    }
    assert 'PRIVATE' not in report.text
    assert answer not in report.text
    assert 'Guest' in report.text
    with root._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_access_events WHERE action='professor.learning_funnel'").fetchone()[0] == 2


def test_project_confirmations_are_not_lost_when_display_receipt_is_unknown(tmp_path: Path) -> None:
    """Legacy confirmations and later saved stage-two work remain separately observable."""
    root = StudentStore(tmp_path / 'project.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Project', model_id='mock', support_mode='critical-thinking')
    student.add_message(thread, 'user', 'Affected students need accessible crossings', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'problem_identification',
    })
    answer = student.add_message(thread, 'assistant', 'Compare concepts next', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'problem_identification',
        'proposed_stage': 'concept_generation', 'decision_status': 'confirmed',
        'decision_at': '2026-01-01T00:00:00+00:00',
    })
    student.add_message(thread, 'user', 'Compare longer crossing time with refuge islands', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'concept_generation',
    })
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    prof_cookie = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    student_cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    report = client.get('/api/v1/professor/learning-funnel', cookies=prof_cookie).json()['project_work']
    assert report['recommendation_displayed']['numerator'] == 0
    assert report['confirmed']['numerator'] == 1
    assert report['subsequent_stage2_contribution']['numerator'] == 1
    for _ in range(2):
        assert client.post(f'/api/v1/threads/{thread}/messages/{answer}/learning-signal',
                           json={'kind': 'recommendation_displayed'}, cookies=student_cookie).status_code == 200
    report = client.get('/api/v1/professor/learning-funnel', cookies=prof_cookie).json()['project_work']
    assert report['recommendation_displayed'] == {'numerator': 1, 'denominator': 1, 'unit': 'notebooks'}


def test_signal_ownership_validation_rating_changes_and_restart(tmp_path: Path) -> None:
    """Foreign or ineligible receipts fail; latest rating survives app recreation."""
    root = StudentStore(tmp_path / 'ownership.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    for sub in ['student', 'other']:
        _seed_user(root, sub, 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Private', model_id='mock', support_mode='critical-thinking')
    user = student.add_message(thread, 'user', 'Private question')
    answer = student.add_message(thread, 'assistant', 'Answer', metadata={'interaction_intent': 'lecture_help'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    other = {settings.cognito_id_token_cookie_name: oidc.add('other')}
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    path = f'/api/v1/threads/{thread}/messages/{answer}/learning-signal'
    assert client.post(path, json={'kind': 'useful'}, cookies=other).status_code == 404
    assert client.post(path.replace(answer, user), json={'kind': 'useful'}, cookies=cookie).status_code == 404
    assert client.post(path, json={'kind': 'useful', 'content': 'private'}, cookies=cookie).status_code == 422
    assert client.post(path, json={'kind': 'anything'}, cookies=cookie).status_code == 422
    assert client.post(path, json={'kind': 'recommendation_displayed'}, cookies=cookie).status_code == 404
    assert client.post(path, json={'kind': 'evidence_opened'}, cookies=cookie).status_code == 404
    assert client.post(path, json={'kind': 'useful'}, cookies=cookie).status_code == 200
    assert client.post(path, json={'kind': 'not_useful'}, cookies=cookie).status_code == 200
    restarted = TestClient(create_app(StudentStore(root.path, identifier='local-student'), oidc_client=oidc))
    report = restarted.get('/api/v1/professor/learning-funnel', cookies=prof).json()['lecture_help']
    assert report['useful_answers'] == {'numerator': 0, 'denominator': 1, 'unit': 'answers'}
    assert report['rated_answers']['numerator'] == 1


def test_return_after_useful_requires_later_day_and_deduplicates_notebooks(tmp_path: Path, monkeypatch) -> None:
    """A later turn counts once per owner, regardless of additional notebooks."""
    root = StudentStore(tmp_path / 'return.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    monkeypatch.setattr('backend.student_store.utc_now', lambda: '2026-01-01T12:00:00+00:00')
    thread = student.create_thread(name='One', model_id='mock', support_mode='critical-thinking')
    answer = student.add_message(thread, 'assistant', 'Lecture answer', metadata={'interaction_intent': 'lecture_help'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    assert client.post(f'/api/v1/threads/{thread}/messages/{answer}/learning-signal', json={'kind': 'useful'}, cookies=cookie).status_code == 200
    student.add_message(thread, 'user', 'Same day')
    url = '/api/v1/professor/learning-funnel'
    assert client.get(url, cookies=prof).json()['lecture_help']['returned_after_useful']['numerator'] == 0
    monkeypatch.setattr('backend.student_store.utc_now', lambda: '2026-01-02T12:00:00+00:00')
    second = student.create_thread(name='Two', model_id='mock', support_mode='critical-thinking')
    student.add_message(second, 'user', 'Next day')
    student.add_message(thread, 'user', 'Another return')
    report = client.get(url, cookies=prof).json()
    assert report['lecture_help']['returned_after_useful'] == {'numerator': 1, 'denominator': 1, 'unit': 'owner identities'}
    assert report['identities']['notebooks'] == 2
    assert report['identities']['owners'] == 1


def test_report_names_populations_and_keeps_human_substance_unknown(tmp_path: Path) -> None:
    """A project starter without a recommendation stays in the participation denominator."""
    root = StudentStore(tmp_path / 'denominators.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Starter', model_id='mock', support_mode='critical-thinking')
    student.add_message(thread, 'user', 'People need accessible crossings', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'problem_identification',
    })
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    report = client.get('/api/v1/professor/learning-funnel', cookies=prof).json()
    assert report['project_work']['stage2_saved_turn_participation'] == {'numerator': 0, 'denominator': 1, 'unit': 'notebooks'}
    assert 'rated' in report['definitions']['useful_answers']
    assert report['human_reviewed_substantive_stage2_notebooks'] is None


def test_concurrent_connections_preserve_rating_and_evidence_receipts(tmp_path: Path) -> None:
    """Concurrent public requests from separate applications preserve both receipts."""
    from concurrent.futures import ThreadPoolExecutor

    root = StudentStore(tmp_path / 'concurrent.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Concurrent', model_id='mock', support_mode='critical-thinking')
    oidc = FakeOIDC(root)
    cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    clients = [TestClient(create_app(StudentStore(root.path, identifier='local-student'), oidc_client=oidc)) for _ in range(2)]
    for _ in range(8):
        answer = student.add_message(thread, 'assistant', 'Grounded lecture answer', metadata={
            'interaction_intent': 'lecture_help', 'source_refs': [{'id': 'fixture-source', 'label': 'S1'}],
        })
        path = f'/api/v1/threads/{thread}/messages/{answer}/learning-signal'
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda pair: pair[0].post(path, json={'kind': pair[1]}, cookies=cookie), zip(clients, ['useful', 'evidence_opened'])))
        assert [r.status_code for r in responses] == [200, 200]
    report = clients[0].get('/api/v1/professor/learning-funnel', cookies=prof).json()['lecture_help']
    assert report['useful_answers']['numerator'] == 8
    assert report['evidence_opened']['numerator'] == 8


def test_malformed_imported_receipts_remain_unknown_without_hiding_answers(tmp_path: Path) -> None:
    """Partial imported metadata cannot break the lecturer aggregate or student feedback."""
    root = StudentStore(tmp_path / 'legacy.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Legacy', model_id='mock', support_mode='critical-thinking')
    answer = student.add_message(thread, 'assistant', 'Preserved answer', metadata={
        'interaction_intent': 'lecture_help', 'source_refs': [{'id': 'fixture-source', 'label': 'S1'}],
        'learning_signals': {'rating': {'kind': 'useful'}, 'evidence_opened': '2026-01-01T12:00:00Z'},
    })
    student.add_message(thread, 'user', 'A later turn')
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    report = client.get('/api/v1/professor/learning-funnel', cookies=prof)
    assert report.status_code == 200
    assert report.json()['lecture_help']['rated_answers']['numerator'] == 0
    assert report.json()['lecture_help']['evidence_opened']['numerator'] == 1
    saved = client.post(f'/api/v1/threads/{thread}/messages/{answer}/learning-signal', json={'kind': 'not_useful'}, cookies=cookie)
    assert saved.status_code == 200
    assert saved.json()['signals']['evidence_opened'] == '2026-01-01T12:00:00Z'
    messages = client.get(f'/api/v1/threads/{thread}/messages', cookies=cookie).json()
    assert next(m for m in messages if m['id'] == answer)['content'] == 'Preserved answer'


def test_engagement_section_aggregates_activity_within_existing_authorization(
    tmp_path: Path, monkeypatch,
) -> None:
    """Artifact/canvas/review activity joins the audited funnel as counts, never content."""
    root = StudentStore(tmp_path / 'engagement.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    _seed_user(root, 'quiet', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    quiet = StudentStore(root.path, identifier='cognito:quiet')
    monkeypatch.setattr('backend.student_store.utc_now', lambda: '2026-01-01T12:00:00+00:00')
    thread = student.create_thread(name='PRIVATE NOTEBOOK', model_id='mock', support_mode='critical-thinking')
    quiet.create_thread(name='Quiet', model_id='mock', support_mode='critical-thinking')
    student.add_message(thread, 'user', 'What is analogy?', metadata={'interaction_intent': 'lecture_help'})
    student.add_message(thread, 'user', 'People need accessible crossings', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'problem_identification',
    })
    monkeypatch.setattr('backend.student_store.utc_now', lambda: '2026-01-02T12:00:00+00:00')
    student.add_message(thread, 'user', 'Compare concepts', metadata={
        'interaction_intent': 'project_coaching', 'thinking_stage': 'concept_generation',
    })
    artifact = student.create_artifact(thread, 'PRIVATE ARTIFACT TITLE', {
        'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Draft'}]}],
    })
    student.update_artifact(artifact['id'], artifact['document'], revision=1)
    canvas = student.create_canvas(thread, 'PRIVATE CANVAS TITLE', {
        'nodes': [{'id': 'n0', 'kind': 'concept', 'title': 'Node 0', 'description': '', 'x': 0.0, 'y': 0.0}],
        'edges': [],
    })
    student.update_canvas(canvas['id'], canvas['graph'], revision=1)
    student.update_canvas(canvas['id'], canvas['graph'], revision=2)
    thread_row = student.get_thread(thread) or {}
    metadata = dict(thread_row.get('metadata') or {})
    metadata['deep_review_job'] = {
        'review_id': 'review-1', 'status': 'completed', 'reviewed_revision': 1,
        'stage_at_start': 'problem_identification', 'source_ids': [], 'message_ids': [],
        'started_at': '2026-01-02T12:00:00+00:00',
    }
    student.update_thread(thread, metadata=metadata)
    student.add_message(thread, 'assistant', 'Answer', metadata={'interaction_intent': 'lecture_help'}, is_error=True)
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    student_cookie = {settings.cognito_id_token_cookie_name: oidc.add('student')}
    url = '/api/v1/professor/learning-funnel'
    assert client.get(url, cookies=student_cookie).status_code == 403
    report = client.get(url, cookies=prof)
    assert report.status_code == 200
    engagement = report.json()['engagement']
    assert engagement['returning_students'] == {'numerator': 1, 'denominator': 1, 'unit': 'owner identities'}
    assert engagement['stage_progression'] == {'numerator': 1, 'denominator': 1, 'unit': 'notebooks'}
    assert engagement['artifacts_authored'] == {'numerator': 1, 'denominator': 2, 'unit': 'notebooks'}
    assert engagement['artifact_revisions_saved']['numerator'] == 1
    assert engagement['canvases_explored'] == {'numerator': 1, 'denominator': 2, 'unit': 'notebooks'}
    assert engagement['canvas_revisions_saved']['numerator'] == 2
    assert engagement['coaching_turns'] == {'numerator': 2, 'denominator': 3, 'unit': 'student turns'}
    assert engagement['lecture_help_turns'] == {'numerator': 1, 'denominator': 3, 'unit': 'student turns'}
    assert engagement['deep_reviews'] == {'numerator': 1, 'denominator': 2, 'unit': 'notebooks'}
    assert engagement['notebooks_without_saved_turns'] == {'numerator': 1, 'denominator': 2, 'unit': 'notebooks'}
    assert engagement['notebooks_with_saved_errors'] == {'numerator': 1, 'denominator': 2, 'unit': 'notebooks'}
    definitions = report.json()['definitions']
    for name in engagement:
        assert definitions.get(name)
    assert any('activity signals' in limitation for limitation in report.json()['limitations'])
    assert 'PRIVATE ARTIFACT TITLE' not in report.text
    assert 'PRIVATE CANVAS TITLE' not in report.text
    assert 'review-1' not in report.text
    with root._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM research_access_events WHERE action='professor.learning_funnel'"
        ).fetchone()[0] == 1


def test_lecturer_report_keeps_improve_and_historical_lecture_feedback_separate(tmp_path: Path) -> None:
    """Classified Improve activity and answer ratings stay in their own funnel."""
    root = StudentStore(tmp_path / 'improve.sqlite3', identifier='local-student')
    _seed_user(root, 'prof', 'lecturer')
    _seed_user(root, 'student', 'student')
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(name='Design', model_id='mock', support_mode='critical-thinking')
    student.add_message(thread, 'user', 'What is analogy?', metadata={'interaction_intent': 'lecture_help'})
    student.add_message(thread, 'assistant', 'Older answer', metadata={'interaction_intent': 'lecture_help'})
    student.add_message(thread, 'user', 'How can I improve my timer?', metadata={'interaction_intent': 'improve_design'})
    answer = student.add_message(thread, 'assistant', 'Try larger digits', metadata={'interaction_intent': 'improve_design'})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    prof = {settings.cognito_id_token_cookie_name: oidc.add('prof')}
    owner = {settings.cognito_id_token_cookie_name: oidc.add('student')}

    assert client.post(
        f'/api/v1/threads/{thread}/messages/{answer}/learning-signal',
        json={'kind': 'useful'}, cookies=owner,
    ).status_code == 200
    response = client.get('/api/v1/professor/learning-funnel', cookies=prof)
    assert response.status_code == 200
    report = response.json()
    assert report['improve_design']['rated_answers'] == {'numerator': 1, 'denominator': 1, 'unit': 'answers'}
    assert report['lecture_help']['rated_answers'] == {'numerator': 0, 'denominator': 1, 'unit': 'answers'}
    assert report['engagement']['improve_design_turns'] == {'numerator': 1, 'denominator': 2, 'unit': 'student turns'}
    assert report['engagement']['lecture_help_turns'] == {'numerator': 1, 'denominator': 2, 'unit': 'student turns'}
    assert report['engagement']['coaching_turns']['numerator'] == 0
    assert report['identities']['unclassified_messages'] == 0
