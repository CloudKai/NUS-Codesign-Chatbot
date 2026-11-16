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
        assert client.get(path + f"/messages/{message['id']}/citations/{second}/content").status_code == 404
        assert client.get(path + f'/sources/{second}').status_code == 404
        response = client.post(path + '/lecture/stream', json={'student_message': 'Explain analogy in design', 'idempotency_key': 'removed'}, headers=origin)
        later = next(event['turn'] for event in map(json.loads, response.text.splitlines()) if event['event'] == 'done')
        assert later['assessment']['citations'] == []


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
