"""Persistent artifact storage: legacy upgrade, ownership, revision-guarded saves and delete plan."""

from pathlib import Path
import sqlite3

import pytest

from backend.persistence.store.migrations import migrate_student_artifacts
from backend.persistence.store.operations.artifacts import (
    _request_fingerprint,
    canonical_artifact_document,
)
from backend.persistence.store.sqlite_schema import NOTEBOOK_CHILD_DELETE_PLAN, SQLITE_SCHEMA
from backend.student_store import StudentStore


def test_artifact_creation_replays_the_original_request_with_provenance(tmp_path: Path) -> None:
    """A lost acknowledgement recovers the same owned artifact after restart; changed retries refuse."""
    store = StudentStore(tmp_path / 'create-receipt.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    canvas = store.create_canvas(thread, 'Map', {'nodes': [
        {'id': 'n1', 'kind': 'note', 'title': 'Observation', 'x': 0, 'y': 0},
    ], 'edges': []})
    references = [{'kind': 'canvas_node', 'canvas_id': canvas['id'], 'id': 'n1', 'revision': 1}]
    document = {'type': 'doc', 'content': []}
    first = store.create_artifact(thread, 'Synthesized notes', document,
                                  references=references, origin='coach_draft',
                                  request_id='draft:draft-1')
    reopened = StudentStore(store.path)
    replay = reopened.create_artifact(thread, 'Synthesized notes', document,
                                     references=references, origin='coach_draft',
                                     request_id='draft:draft-1')
    assert replay['id'] == first['id']
    assert len(reopened.list_artifacts(thread)) == 1
    assert replay['origin'] == 'coach_draft'
    assert replay['references'][0]['canvas_id'] == canvas['id']
    assert replay['references'][0]['revision'] == 1
    reopened.update_artifact(first['id'], document, 1, 'Edited title')
    assert reopened.get_artifact(first['id'])['references'][0]['revision'] == 1
    with pytest.raises(ValueError, match='operation'):
        reopened.create_artifact(thread, 'Changed retry', document,
                                 references=references, origin='coach_draft',
                                 request_id='draft:draft-1')


def test_artifact_table_is_additive_and_preserves_legacy_data(tmp_path: Path) -> None:
    """Opening a pre-artifact legacy database upgrades it in place without touching rows."""
    legacy = sqlite3.connect(tmp_path / 'legacy.sqlite3')
    # A pre-artifact store: the full schema minus the student_artifacts table.
    legacy.executescript(SQLITE_SCHEMA.split('CREATE TABLE IF NOT EXISTS student_artifacts')[0])
    legacy.execute(
        "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
        "VALUES ('u1', 'cognito:u1', 'student', '{}', '2026-01-01T00:00:00Z')"
    )
    legacy.execute(
        "INSERT INTO notebooks (id, user_id, title, created_at, updated_at) "
        "VALUES ('nb1', 'u1', 'Legacy work', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    legacy.commit()
    legacy.close()

    store = StudentStore(tmp_path / 'legacy.sqlite3', identifier='cognito:u1')
    with store._connect() as connection:
        tables = {row['name'] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert 'student_artifacts' in tables
        assert connection.execute('SELECT COUNT(*) AS total FROM student_artifacts').fetchone()['total'] == 0
    assert store.get_thread('nb1') is not None
    # The explicit migration is idempotent and leaves existing rows intact.
    with store._connect() as connection:
        migrate_student_artifacts(connection)
    assert store.list_artifacts('nb1') == []


def test_artifact_create_get_list_update_and_ownership(tmp_path: Path) -> None:
    """One owned notebook's artifact round-trips; foreign owners never see or change it."""
    root = StudentStore(tmp_path / 'artifacts.sqlite3')
    _seed(root, 'alice')
    _seed(root, 'bob')
    alice = StudentStore(root.path, identifier='cognito:alice')
    bob = StudentStore(root.path, identifier='cognito:bob')
    thread = alice.create_thread(name='Crossing study', model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Crossing observations'}]}]}

    created = alice.create_artifact(thread, 'Field notes', document)
    assert created['title'] == 'Field notes'
    assert created['document'] == document
    assert created['revision'] == 1 and created['schema_version'] == 1
    assert created['origin'] == 'editor' and created['thread_id'] == thread

    saved = alice.update_artifact(created['id'], document, created['revision'], title='Field notes v2')
    assert saved['revision'] == 2 and saved['title'] == 'Field notes v2'
    assert saved['updated_at'] >= created['updated_at']

    entries = alice.list_artifacts(thread)
    assert [entry['id'] for entry in entries] == [created['id']]
    assert 'document' not in entries[0]

    # A stale conditional save fails without changing the stored work.
    with pytest.raises(Exception, match='changed. Reopen'):
        alice.update_artifact(created['id'], document, created['revision'])
    assert alice.get_artifact(created['id'])['revision'] == 2

    # Foreign ownership is invisible and unwritable through every operation.
    assert bob.get_artifact(created['id']) is None
    assert bob.list_artifacts(thread) == []
    with pytest.raises(LookupError):
        bob.update_artifact(created['id'], document, 2)
    with pytest.raises((LookupError, ValueError)):
        alice.create_artifact('unknown-notebook', 'X', document)


def test_artifact_documents_are_canonical_bounded_tiptap_json(tmp_path: Path) -> None:
    """Unsafe structures and oversized or malformed documents fail before storage."""
    store = StudentStore(tmp_path / 'documents.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Docs', model_id='mock', support_mode='critical-thinking')
    for document in (
        'not json', ['not', 'an', 'object'], {'type': 'paragraph'}, {'type': 'doc', 'content': {}},
    ):
        with pytest.raises(ValueError):
            store.create_artifact(thread, 'X', document)
    huge = {'type': 'doc', 'content': [{'type': 'text', 'text': 'x' * 300_000}]}
    with pytest.raises(ValueError, match='too large'):
        store.create_artifact(thread, 'X', huge)


def test_artifact_kinds_duplicate_and_confirmed_delete(tmp_path: Path) -> None:
    """Curriculum kinds are allowlisted; duplicates copy exactly; deletion requires confirmation."""
    store = StudentStore(tmp_path / 'kinds.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Docs', model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Concept sketches'}]}]}

    with pytest.raises(ValueError, match='Unsupported artifact type'):
        store.create_artifact(thread, 'X', document, 'invented-kind')
    created = store.create_artifact(thread, 'Concept sketches', document, 'concept_generation')
    assert created['kind'] == 'concept_generation'
    assert store.list_artifacts(thread)[0]['kind'] == 'concept_generation'

    copied = store.duplicate_artifact(created['id'])
    assert copied['id'] != created['id']
    assert copied['kind'] == created['kind'] and copied['document'] == document
    assert copied['title'] == 'Concept sketches (copy)'
    assert copied['created_at'] == copied['updated_at']

    with pytest.raises(ValueError, match='Confirm'):
        store.delete_artifact(created['id'], False)
    assert store.get_artifact(created['id']) is not None
    store.delete_artifact(created['id'], True)
    assert store.get_artifact(created['id']) is None
    with pytest.raises(LookupError):
        store.delete_artifact(created['id'], True)
    # The duplicate is untouched by another artifact's deletion.
    assert store.get_artifact(copied['id']) is not None


def test_version_history_records_saves_and_restores_as_new_revisions(tmp_path: Path) -> None:
    """Every save checkpoints a version; restore creates a new revision keeping all intermediates."""
    store = StudentStore(tmp_path / 'versions.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Docs', model_id='mock', support_mode='critical-thinking')
    first = store.create_artifact(thread, 'Notes', {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'v1'}]}]})
    store.update_artifact(first['id'], {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'v2'}]}]}, 1)
    store.update_artifact(first['id'], {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'v3'}]}]}, 2, title='Notes v3')

    versions = store.list_artifact_versions(first['id'])
    assert [entry['revision'] for entry in versions] == [3, 2, 1]
    assert versions[0]['origin'] == 'editor' and versions[0]['restored_from'] is None
    preview = store.get_artifact_version(first['id'], 1)
    assert preview is not None
    assert preview['document']['content'][0]['content'][0]['text'] == 'v1'
    assert store.get_artifact_version(first['id'], 99) is None

    # Restore version 1 as a new revision: the current work and all intermediates stay in history.
    restored = store.restore_artifact(first['id'], 1, 3)
    assert restored['revision'] == 4 and restored['origin'] == 'restore'
    assert restored['document']['content'][0]['content'][0]['text'] == 'v1'
    assert restored['title'] == 'Notes'  # The restored version's title returns with its content.
    revisions = [entry['revision'] for entry in store.list_artifact_versions(first['id'])]
    assert revisions == [4, 3, 2, 1]
    kept = store.get_artifact_version(first['id'], 3)
    assert kept is not None and kept['document']['content'][0]['content'][0]['text'] == 'v3'

    # Stale restore (current revision moved on) fails without writing.
    with pytest.raises(ValueError, match='changed. Reopen'):
        store.restore_artifact(first['id'], 1, 3)
    assert store.get_artifact(first['id'])['revision'] == 4
    # Foreign and unknown versions are invisible.
    assert store.get_artifact_version(first['id'], 1) is not None
    _seed(store, 'bob')
    bob = StudentStore(store.path, identifier='cognito:bob')
    assert bob.list_artifact_versions(first['id']) == []
    assert bob.get_artifact_version(first['id'], 1) is None
    with pytest.raises(LookupError):
        bob.restore_artifact(first['id'], 1, 1)

    # Direct artifact deletion removes its version history.
    store.delete_artifact(first['id'], True)
    assert store.list_artifact_versions(first['id']) == []


def test_deleting_a_notebook_removes_its_artifacts(tmp_path: Path) -> None:
    """Artifacts are first-class notebook children in the runtime delete plan."""
    assert 'student_artifacts' in [table for table, _predicate in NOTEBOOK_CHILD_DELETE_PLAN]
    store = StudentStore(tmp_path / 'delete.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Docs', model_id='mock', support_mode='critical-thinking')
    created = store.create_artifact(thread, 'Notes', {'type': 'doc', 'content': []})
    store.delete_thread(thread)
    assert store.get_artifact(created['id']) is None


def test_artifact_create_replays_a_supplied_request_id(tmp_path: Path) -> None:
    """A request id makes create idempotent: replay returns the same row with no extra checkpoint."""
    store = StudentStore(tmp_path / 'request-id.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': []}

    first = store.create_artifact(thread, 'Notes', document, request_id='draft:abc123')
    replay = store.create_artifact(thread, 'Notes', document, request_id='draft:abc123')

    assert replay['id'] == first['id']
    assert replay['revision'] == 1
    assert replay['title'] == 'Notes'
    assert len(store.list_artifacts(thread)) == 1
    assert [entry['revision'] for entry in store.list_artifact_versions(first['id'])] == [1]

    # A changed payload under the same request id refuses instead of replaying.
    with pytest.raises(ValueError, match='operation'):
        store.create_artifact(thread, 'Changed retry title', document, request_id='draft:abc123')

    # A different request id is a distinct create.
    other = store.create_artifact(thread, 'Notes', document, request_id='draft:def456')
    assert other['id'] != first['id']
    # No request id keeps the ordinary non-idempotent behaviour.
    store.create_artifact(thread, 'Notes', document)
    store.create_artifact(thread, 'Notes', document)
    assert len(store.list_artifacts(thread)) == 4


def test_request_id_column_upgrades_a_legacy_artifact_table_in_place(tmp_path: Path) -> None:
    """A pre-request-id database gains the nullable column and index without touching rows."""
    legacy = sqlite3.connect(tmp_path / 'legacy-request-id.sqlite3')
    legacy.executescript(SQLITE_SCHEMA.split('CREATE TABLE IF NOT EXISTS student_artifacts')[0])
    legacy.execute(
        """
        CREATE TABLE student_artifacts (
            id TEXT PRIMARY KEY,
            notebook_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'notes',
            document_text TEXT NOT NULL,
            references_text TEXT NOT NULL DEFAULT '[]',
            schema_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            origin TEXT NOT NULL DEFAULT 'editor',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    legacy.execute(
        "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
        "VALUES ('u1', 'cognito:legacy', 'student', '{}', '2026-01-01T00:00:00Z')"
    )
    legacy.execute(
        "INSERT INTO notebooks (id, user_id, title, created_at, updated_at) "
        "VALUES ('nb1', 'u1', 'Legacy work', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    legacy.execute(
        "INSERT INTO student_artifacts "
        "(id, notebook_id, user_id, title, kind, document_text, references_text, "
        " schema_version, revision, origin, created_at, updated_at) "
        "VALUES ('a1', 'nb1', 'u1', 'Legacy notes', 'notes', '{\"type\":\"doc\",\"content\":[]}', "
        "'[]', 1, 1, 'editor', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    legacy.commit()
    legacy.close()

    store = StudentStore(tmp_path / 'legacy-request-id.sqlite3', identifier='cognito:legacy')
    with store._connect() as connection:
        columns = {str(row[1]) for row in connection.execute('PRAGMA table_info(student_artifacts)')}
        assert 'request_id' in columns
        row = connection.execute("SELECT * FROM student_artifacts WHERE id='a1'").fetchone()
        assert row['title'] == 'Legacy notes' and row['request_id'] is None
    assert store.get_artifact('a1')['document'] == {'type': 'doc', 'content': []}
    created = store.create_artifact('nb1', 'New notes', {'type': 'doc', 'content': []},
                                    request_id='draft:legacy')
    assert created['id'] != 'a1'


def test_artifact_create_stores_an_allowlisted_origin_in_row_and_checkpoint(tmp_path: Path) -> None:
    """AI-draft provenance survives on the artifact and its first version checkpoint."""
    store = StudentStore(tmp_path / 'origin.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': []}

    created = store.create_artifact(thread, 'Draft', document, origin='coach_draft')
    assert created['origin'] == 'coach_draft'
    assert store.list_artifact_versions(created['id'])[0]['origin'] == 'coach_draft'
    assert store.get_artifact_version(created['id'], 1)['origin'] == 'coach_draft'
    assert store.create_artifact(thread, 'Plain', document)['origin'] == 'editor'
    with pytest.raises(ValueError, match='origin'):
        store.create_artifact(thread, 'Bad', document, origin='model_generated')


def test_artifact_create_race_on_the_same_request_id_replays_the_winner(tmp_path: Path) -> None:
    """A concurrent winner between the request lookup and INSERT still replays, not raises."""
    store = StudentStore(tmp_path / 'request-race.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': []}
    serialized = canonical_artifact_document(document)
    fingerprint = _request_fingerprint('Notes', 'notes', serialized, '[]', 'editor')
    # The competing create commits after our lookup but before our INSERT.
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO student_artifacts
              (id, notebook_id, user_id, title, kind, document_text, references_text,
               schema_version, revision, origin, request_id, request_fingerprint,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
            """,
            ('race-winner', thread, store.owner_id, 'Notes', 'notes', serialized, '[]',
             'editor', 'draft:race', fingerprint, '2026-01-01T00:00:00Z',
             '2026-01-01T00:00:00Z'),
        )
        connection.commit()

    raced = {'lookup_missed': False}
    connect = store._connect
    store._connect = lambda: _RacedLookupConnection(connect(), raced)  # type: ignore[method-assign]

    replayed = store.create_artifact(thread, 'Notes', document, request_id='draft:race')

    assert raced['lookup_missed'] is True
    assert replayed['id'] == 'race-winner'
    assert replayed['revision'] == 1
    assert len(store.list_artifacts(thread)) == 1


def test_artifact_create_race_on_the_same_request_id_refuses_a_changed_retry(tmp_path: Path) -> None:
    """A racing winner with a different payload refuses instead of replaying changed work."""
    store = StudentStore(tmp_path / 'request-race-changed.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': []}
    serialized = canonical_artifact_document(document)
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO student_artifacts
              (id, notebook_id, user_id, title, kind, document_text, references_text,
               schema_version, revision, origin, request_id, request_fingerprint,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
            """,
            ('race-winner', thread, store.owner_id, 'Original title', 'notes', serialized, '[]',
             'editor', 'draft:race', 'a-different-payload-fingerprint',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
        )
        connection.commit()

    raced = {'lookup_missed': False}
    connect = store._connect
    store._connect = lambda: _RacedLookupConnection(connect(), raced)  # type: ignore[method-assign]

    with pytest.raises(ValueError, match='operation'):
        store.create_artifact(thread, 'Notes', document, request_id='draft:race')

    assert raced['lookup_missed'] is True
    assert [entry['id'] for entry in store.list_artifacts(thread)] == ['race-winner']


class _RacedLookupConnection:
    """Connection facade that lets the first request-key lookup miss, then delegates."""

    def __init__(self, connection: sqlite3.Connection, state: dict[str, bool]) -> None:
        self._connection = connection
        self._state = state

    def execute(self, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
        if not self._state['lookup_missed'] and 'request_id=?' in sql:
            self._state['lookup_missed'] = True
            return _MissingRow()
        return self._connection.execute(sql, params)

    def __enter__(self) -> '_RacedLookupConnection':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self._connection.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._connection, name)


class _MissingRow:
    """Cursor stand-in for a lookup that ran before the winning create committed."""

    def fetchone(self) -> None:
        return None


def _seed(root: StudentStore, name: str) -> None:
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
            "VALUES (?, ?, 'student', '{}', '2026-01-01T00:00:00Z')",
            (f'user-{name}', f'cognito:{name}'),
        )
        connection.commit()


def test_artifact_create_serialization_failure_propagates_for_occ_retry(tmp_path: Path) -> None:
    """A DSQL serialization conflict must reach the OCC retry wrapper, not the race recovery.

    The recovery's broad failure handling would otherwise catch the 40001 and
    re-read on the aborted connection, replacing the retryable error with a
    transaction-aborted error the OCC wrapper cannot classify.
    """
    import sqlite3

    store = StudentStore(tmp_path / 'serial.sqlite3')
    thread = store.create_thread(model_id='mock', support_mode='critical-thinking')
    document = {'type': 'doc', 'content': []}
    real_connect = store._connect
    attempts = {'insert': 0}

    class SerializationFailure(Exception):
        sqlstate = '40001'

    class TransactionAborted(Exception):
        sqlstate = '25P02'

    class AbortedAfterInsertProxy:
        """Connection that fails the artifact insert with 40001, then behaves like an aborted transaction."""

        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, sql, params=None):
            if 'INSERT INTO student_artifacts\n' in sql and attempts['insert'] == 0:
                attempts['insert'] += 1
                raise SerializationFailure('could not serialize access')
            if attempts['insert'] == 1:
                raise TransactionAborted('current transaction is aborted')
            return self._connection.execute(sql, params or ())

        def rollback(self) -> None:
            return self._connection.rollback()

        def commit(self) -> None:
            return self._connection.commit()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connect_proxy():
        return AbortedAfterInsertProxy(real_connect().__enter__())

    import contextlib

    @contextlib.contextmanager
    def patched_connect():
        yield connect_proxy()

    store._connect = patched_connect  # type: ignore[method-assign]
    with pytest.raises(SerializationFailure) as raised:
        store.create_artifact(thread, 'Notes', document, request_id='draft:retry-1')
    assert raised.value.sqlstate == '40001', (
        'the original serialization error must propagate for the OCC retry wrapper')
