"""Source management contracts at the authenticated student browser HTTP seam."""

from pathlib import Path
import time

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_sources_inspect_download_and_isolate(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Owned sources expose bounded plain text and exact bytes, never storage metadata."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'sources.sqlite3')
    for name in ['student', 'other']:
        _seed_user(root, name, 'student')
    oidc = FakeOIDC(root)
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        thread = client.post('/api/v1/threads', json={'name': 'Notes', 'model_id': 'mock', 'support_mode': 'critical-thinking'}).json()['id']
        source = client.post(f'/api/v1/threads/{thread}/sources', files=[
            ('files', ('notes.txt', b'Field evidence: safe crossings.', 'text/plain')),
        ]).json()[0]
        path = f'/api/v1/reader/threads/{thread}/sources'
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        view = response.json()
        assert view['thread_id'] == thread
        assert view['sources'] == [{'id': source['id'], 'title': 'notes.txt', 'selected': True,
                                    'locked': False, 'kind': 'file', 'size': 31}]
        detail = client.get(f"{path}/{source['id']}").json()
        assert detail['text'] == 'Field evidence: safe crossings.'
        assert not detail['truncated']
        content = client.get(f"{path}/{source['id']}/content")
        assert content.content == b'Field evidence: safe crossings.'
        assert content.headers['content-disposition'].startswith('attachment;')
        assert content.headers['x-content-type-options'] == 'nosniff'
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
        for suffix in ['', f"/{source['id']}", f"/{source['id']}/content"]:
            assert client.get(path + suffix).status_code == 404


def test_reader_upload_progress_retry_discard_and_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """HTTP jobs retain bounded retries, reconcile without replay and leave durable sources."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'jobs.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    token = oidc.add('student')
    origin = {'Origin': 'https://testserver'}
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, token)
        thread = client.post('/api/v1/threads', json={'name': 'Uploads', 'model_id': 'mock', 'support_mode': 'critical-thinking'}).json()['id']
        path = f'/api/v1/reader/threads/{thread}'
        response = client.post(path + '/uploads', files=[('files', ('notes.txt', b'Safe crossings.', 'text/plain'))], headers=origin)
        assert response.status_code == 202
        job_id = response.json()['id']
        for _ in range(100):
            jobs = client.get(path + '/uploads').json()['jobs']
            if jobs[0]['state'] not in {'queued', 'processing'}:
                break
            time.sleep(.01)
        assert jobs == [{'id': job_id, 'filenames': ['notes.txt'], 'state': 'saved', 'retryable': False}]
        source = client.get(path + '/sources').json()['sources'][0]
        assert source['selected']
        assert client.post(path + f'/uploads/{job_id}/retry', headers=origin).status_code == 409
        assert client.post(path + f'/uploads/{job_id}/discard', headers=origin).status_code == 200
        assert client.get(path + '/uploads').json()['jobs'] == []
        assert client.post(path + f'/uploads/{job_id}/discard', headers=origin).status_code == 409
        # A real unavailable storage path fails in the file boundary, without mocking our services.
        blocked = tmp_path / 'unavailable-files'
        blocked.write_text('not a directory')
        monkeypatch.setattr(settings, 'files_dir', blocked)
        failed = client.post(path + '/uploads', files=[('files', ('retry.txt', b'Retry evidence', 'text/plain'))], headers=origin)
        assert failed.status_code == 202
        failed_id = failed.json()['id']
        for attempt in range(3):
            for _ in range(100):
                job = client.get(path + '/uploads').json()['jobs'][0]
                if job['state'] == 'failed':
                    break
                time.sleep(.01)
            assert job['state'] == 'failed'
            assert job['retryable'] is (attempt < 2)
            retry = client.post(path + f'/uploads/{failed_id}/retry', headers=origin)
            assert retry.status_code == (202 if attempt < 2 else 409)
        assert len(client.get(path + '/sources').json()['sources']) == 1
        monkeypatch.setattr(settings, 'files_dir', tmp_path / 'runtime' / 'files')
    with TestClient(create_app(StudentStore(root.path), oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, token)
        assert client.get(path + '/uploads').json()['jobs'] == []
        assert client.get(path + f"/sources/{source['id']}/content").content == b'Safe crossings.'


def test_reader_source_selection_removal_and_saved_citation_mapping(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Deselect/remove affect future authority while saved citations keep their exact identity."""
    import json

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'selection.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    origin = {'Origin': 'https://testserver'}
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        thread = client.post('/api/v1/threads', json={'name': 'Sources', 'model_id': 'mock', 'support_mode': 'critical-thinking'}).json()['id']
        path = f'/api/v1/reader/threads/{thread}'
        sources = client.post(f'/api/v1/threads/{thread}/sources', files=[
            ('files', ('alpha.txt', b'Analogy connects familiar patterns to new design problems.', 'text/plain')),
            ('files', ('beta.txt', b'Analogy supports design ideation using familiar comparisons.', 'text/plain')),
        ]).json()
        first, second = [s['id'] for s in sources]
        changed = client.post(path + f'/sources/{first}/select', json={'selected': False}, headers=origin)
        assert changed.status_code == 200
        response = client.post(path + '/lecture/stream', json={'student_message': 'Explain analogy in design', 'idempotency_key': 'grounded'}, headers=origin)
        turn = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
        assert {c['source_id'] for c in turn['assessment']['citations']} == {second}
        message = client.get(path + '/messages/page').json()['messages'][-1]
        saved_mapping = message['citations']
        assert {c['source_id'] for c in saved_mapping} == {second}
        assert client.post(path + f'/sources/{second}/remove', headers=origin).status_code == 200
        assert client.post(path + f'/sources/{second}/select', json={'selected': True}, headers=origin).status_code == 409
        assert client.post(path + f'/sources/{second}/remove', headers=origin).status_code == 409
        assert client.get(path + '/messages/page').json()['messages'][-1]['citations'] == saved_mapping
        citation = path + f"/messages/{message['id']}/citations/{second}/content"
        assert client.get(citation).status_code == 200
        assert client.get(path + f'/sources/{second}').status_code == 404
        response = client.post(path + '/lecture/stream', json={'student_message': 'Explain analogy in design', 'idempotency_key': 'removed'}, headers=origin)
        later = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
        assert later['assessment']['citations'] == []
        remove = f'/api/v1/reader/threads/library/sources/{second}/remove'
        assert client.post(remove, headers=origin).status_code == 422
        assert client.post(remove, headers=origin, json={'confirmed': True}).status_code == 200
        assert client.get(citation).status_code == 404
        saved_message = next(row for row in client.get(path + '/messages/page').json()['messages'] if row['id'] == message['id'])
        assert saved_message['citations'] == saved_mapping


def test_reader_sources_all_route_guards_and_limits(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Every source/job route rejects anonymous, staff, cross-origin and foreign actions."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    monkeypatch.setattr(settings, 'max_files', 1)
    monkeypatch.setattr(settings, 'max_file_size_mb', 1)
    root = StudentStore(tmp_path / 'guards.sqlite3')
    for name, role in [('student', 'student'), ('other', 'student'), ('staff', 'lecturer')]:
        _seed_user(root, name, role)
    student = StudentStore(root.path, identifier='cognito:student')
    thread = student.create_thread(model_id='mock', support_mode='critical-thinking')
    oidc = FakeOIDC(root)
    origin = {'Origin': 'https://testserver'}
    path = f'/api/v1/reader/threads/{thread}'
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        routes = [('GET', '/sources'), ('GET', '/sources/missing'), ('GET', '/sources/missing/content'),
                  ('GET', '/uploads'), ('POST', '/sources/missing/select'), ('POST', '/sources/missing/remove'),
                  ('POST', '/uploads'), ('POST', '/uploads/missing/retry'), ('POST', '/uploads/missing/discard')]
        for role, expected in [(None, 401), ('staff', 403), ('other', 404)]:
            client.cookies.clear()
            if role:
                client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add(role))
            for method, route in routes:
                kwargs = {'files': [('files', ('a.txt', b'notes', 'text/plain'))]} if route == '/uploads' and method == 'POST' else {'json': {'selected': False}} if route.endswith('/select') else {}
                assert client.request(method, path + route, headers=origin, **kwargs).status_code == expected
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        for method, route in routes:
            kwargs = {'files': [('files', ('a.txt', b'notes', 'text/plain'))]} if route == '/uploads' and method == 'POST' else {'json': {'selected': False}} if route.endswith('/select') else {}
            assert client.request(method, path + route, headers={'Origin': 'https://evil.test'}, **kwargs).status_code == 403
            if method == 'POST':
                assert client.request(method, path + route, **kwargs).status_code == 403
        assert client.post(path + '/uploads', headers=origin, files=[('files', ('a.txt', b'a', 'text/plain'))] * 2).status_code == 400
        assert client.post(path + '/uploads', headers=origin, files=[('files', ('a.txt', b'a' * (1048576 + 1), 'text/plain'))]).status_code == 413
        assert client.post(path + '/sources/missing/select', headers=origin, json={'selected': False, 'owner_id': 'other'}).status_code == 422
        assert client.post(path + '/sources/missing/select', headers=origin, json={'selected': 'false'}).status_code == 422


def test_reader_upload_admission_and_corrected_retry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Real failed batches fill finite owner allowance; corrected retry independently saves sources."""
    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'admission.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    original_files = settings.files_dir
    blocked = tmp_path / 'blocked'
    blocked.write_text('not a directory')
    monkeypatch.setattr(settings, 'files_dir', blocked)
    origin = {'Origin': 'https://testserver'}
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        thread = client.post('/api/v1/threads', json={'name': 'Capacity', 'model_id': 'mock', 'support_mode': 'critical-thinking'}).json()['id']
        other = client.post('/api/v1/threads', json={'name': 'Other', 'model_id': 'mock', 'support_mode': 'critical-thinking'}).json()['id']
        path = f'/api/v1/reader/threads/{thread}'
        ids = []
        for index in range(4):
            response = client.post(path + '/uploads', files=[('files', (f'{index}.txt', b'Evidence', 'text/plain'))], headers=origin)
            assert response.status_code == 202
            ids.append(response.json()['id'])
        rejected = client.post(path + '/uploads', files=[('files', ('fifth.txt', b'Evidence', 'text/plain'))], headers=origin)
        assert rejected.status_code == 429
        assert rejected.headers['retry-after'] == '5'
        for _ in range(100):
            if all(job['state'] == 'failed' for job in client.get(path + '/uploads').json()['jobs']):
                break
            time.sleep(.01)
        for action in ['retry', 'discard']:
            assert client.post(f'/api/v1/reader/threads/{other}/uploads/{ids[0]}/{action}', headers=origin).status_code == 409
        monkeypatch.setattr(settings, 'files_dir', original_files)
        assert client.post(path + f'/uploads/{ids[0]}/retry', headers=origin).status_code == 202
        # Poll durable sources instead of job progress: save and payload release need no progress reads.
        for _ in range(100):
            sources = client.get(path + '/sources').json()['sources']
            if sources:
                break
            time.sleep(.01)
        assert [source['title'] for source in sources] == ['0.txt']
        assert client.post(path + '/uploads', files=[('files', ('freed.txt', b'Freed allowance', 'text/plain'))], headers=origin).status_code == 202


def test_library_uploads_links_attachment_scope_and_image_validation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Keep one private original across paths and authorize RAG by actual scope."""
    import io
    import json

    from PIL import Image
    from backend.source_library import image_inputs_for_source_ids

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    root = StudentStore(tmp_path / 'library.sqlite3')
    for student in ('student', 'other'):
        _seed_user(root, student, 'student')
    oidc = FakeOIDC(root)
    origin = {'Origin': 'https://testserver'}
    base = '/api/v1/reader/threads'
    library = base + '/library'
    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        notebook = client.post(base, json={'name': 'Lecture notebook'}, headers=origin).json()['notebook']['id']
        chat = client.post(base, json={'kind': 'chat'}, headers=origin).json()['notebook']['id']
        other_chat = client.post(base, json={'kind': 'chat'}, headers=origin).json()['notebook']['id']
        notebook_path = f'{base}/{notebook}'
        chat_path = f'{base}/{chat}'

        def upload(path: str, name: str, data: bytes, mime: str) -> dict:
            response = client.post(path + '/uploads', files={'files': (name, data, mime)}, headers=origin)
            assert response.status_code == 202, response.text
            for _ in range(150):
                rows = client.get(path + '/sources').json()['sources']
                source = next((row for row in rows if row['title'] == name), None)
                if source:
                    return source
                time.sleep(.01)
            raise AssertionError('Upload did not become visible')

        private = upload(library, 'private.txt', b'Private notes unrelated to the lecture.', 'text/plain')
        assert not client.get(notebook_path + '/sources').json()['sources']
        lecture = upload(notebook_path, 'lecture-design.txt', b'Analogy connects familiar patterns to new design problems.', 'text/plain')
        assert lecture['selected']
        assert {row['id'] for row in client.get(library + '/sources').json()['sources']} == {private['id'], lecture['id']}
        assert client.post(f"{notebook_path}/sources/{private['id']}/link", headers=origin).status_code == 200
        assert client.post(f"{notebook_path}/sources/{private['id']}/select", json={'selected': False}, headers=origin).status_code == 200
        assert client.post(chat_path + '/move', json={'parent_notebook_id': notebook}, headers=origin).status_code == 200

        def turn(thread: str, request: dict) -> dict:
            response = client.post(f'{base}/{thread}/lecture/stream', json=request, headers=origin)
            return next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')

        result = turn(chat, {'student_message': 'Explain analogy in design.', 'idempotency_key': 'inside'})
        assert {item['source_id'] for item in result['assessment']['citations']} == {lecture['id']}
        assert client.post(chat_path + '/move', json={'parent_notebook_id': None}, headers=origin).status_code == 200
        result = turn(chat, {'student_message': 'Explain analogy in design.', 'idempotency_key': 'outside'})
        assert result['assessment']['citations'] == []

        invalid = client.post(chat_path + '/attachments', files={'files': ('fake.png', b'not a PNG', 'image/png')}, headers=origin)
        assert invalid.status_code == 422
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
        assert client.post(library + '/uploads', files={'files': ('wrong.jpg', image.getvalue(), 'image/jpeg')}, headers=origin).status_code == 422
        valid = upload(library, 'diagram.png', image.getvalue(), 'image/png')
        assert valid['kind'] == 'image'
        assert client.get(library + f"/sources/{valid['id']}/content").content == image.getvalue()
        assert client.post(f"{notebook_path}/sources/{valid['id']}/link", headers=origin).status_code == 200
        store = StudentStore(root.path, identifier='cognito:student')
        vision = image_inputs_for_source_ids(store, notebook, [valid['id']])
        assert [(item['source_id'], item['mime']) for item in vision] == [(valid['id'], 'image/png')]
        assert vision[0]['data_url'].startswith('data:image/png;base64,')
        attachment = client.post(chat_path + '/attachments', files={
            'files': ('chat.txt', b'Analogy provides a comparison to develop a design idea.', 'text/plain')
        }, headers=origin)
        assert attachment.status_code == 200, attachment.text
        attached = attachment.json()[0]['id']
        assert attached in {row['id'] for row in client.get(library + '/sources').json()['sources']}
        assert attached not in {row['id'] for row in client.get(chat_path + '/sources').json()['sources']}
        request = {'student_message': 'Summarize the attached file.', 'idempotency_key': 'attached', 'attachment_source_ids': [attached]}
        # Evidence from the composer is scoped to the chat and this turn.
        result = turn(chat, request)
        assert {item['source_id'] for item in result['assessment']['citations']} == {attached}
        foreign_turn = client.post(f'{base}/{other_chat}/lecture/stream', json=request, headers=origin)
        assert foreign_turn.status_code != 200 or '"event":"done"' not in foreign_turn.text.replace(' ', '')
        assert client.post(f"{notebook_path}/remove", headers=origin, json={'confirmed': True}).status_code == 200
        assert client.get(library + f"/sources/{lecture['id']}/content").status_code == 200
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('other'))
        assert client.get(library + '/sources').json()['sources'] == []
        assert client.get(library + f'/sources/{attached}/content').status_code == 404


def test_reader_improve_grounds_feedback_with_only_requested_evidence(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """Improve can critique directly, use an attachment, or cite course notes."""
    import json

    import fitz

    from backend.source_library import sync_lecture_notes_folder

    monkeypatch.setattr(settings, 'public_api_base_url', 'https://testserver')
    course = tmp_path / 'course' / 'lectureNotes'
    course.mkdir(parents=True)
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), 'Lecture 4 visibility: test the timer under direct sunlight.')
        document.save(course / 'Lecture 4.pdf')
    monkeypatch.setattr(settings, 'lecture_notes_dir', course.parent)
    monkeypatch.setattr(settings, 'course_material_sync_enabled', True)
    monkeypatch.setattr(settings, 'course_materials_bucket', '')
    root = StudentStore(tmp_path / 'improve-sources.sqlite3')
    _seed_user(root, 'student', 'student')
    oidc = FakeOIDC(root)
    origin = {'Origin': 'https://testserver'}

    with TestClient(create_app(root, oidc_client=oidc), base_url='https://testserver') as client:
        client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add('student'))
        created = client.post('/api/v1/reader/threads', json={'kind': 'chat'}, headers=origin)
        assert created.status_code in (200, 201)
        thread = created.json()['notebook']['id']
        student = StudentStore(root.path, identifier='cognito:student')
        sync_lecture_notes_folder(student, thread)
        path = f'/api/v1/reader/threads/{thread}'

        def save_feedback(question: str, key: str, attachment_ids: list[str] | None = None) -> dict:
            response = client.post(path + '/improve/stream', json={
                'student_message': question,
                'idempotency_key': key,
                'attachment_source_ids': attachment_ids or [],
            }, headers=origin)
            assert response.status_code == 200
            done = next(event['turn'] for event in map(json.loads, response.text.splitlines())
                        if event['event'] == 'done')
            saved = client.get(path + '/messages/page').json()['messages'][-1]
            assert saved['citations'] == done['assessment']['citations']
            return saved

        critique = save_feedback(
            'How can I improve the visibility of my crossing timer?', 'critique',
        )
        assert critique['citations'] == []

        attachment = client.post(path + '/attachments', files={
            'files': ('prototype.txt', b'The crossing timer has a pale display with small numbers.', 'text/plain'),
        }, headers=origin)
        assert attachment.status_code == 200
        attachment_id = attachment.json()[0]['id']
        attached_feedback = save_feedback(
            'Please critique my crossing timer for visibility.', 'attached', [attachment_id],
        )
        assert {citation['source_id'] for citation in attached_feedback['citations']} == {attachment_id}

        course_feedback = save_feedback(
            'How should I test the visibility of my crossing timer using Lecture 4?', 'course',
        )
        assert [citation['title'] for citation in course_feedback['citations']] == ['Lecture 4.pdf']
