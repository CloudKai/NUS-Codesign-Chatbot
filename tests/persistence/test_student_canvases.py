"""Persistent design canvas storage: ownership, validation, revision-guarded saves and delete plan."""

from pathlib import Path
import sqlite3

import pytest

from backend.persistence.store.migrations import migrate_student_canvases
from backend.persistence.store.sqlite_schema import NOTEBOOK_CHILD_DELETE_PLAN, SQLITE_SCHEMA
from backend.student_store import StudentStore


def _graph(node_count: int = 1) -> dict[str, object]:
    nodes = [{'id': f'n{index}', 'kind': 'concept', 'title': f'Node {index}',
              'description': '', 'x': float(index), 'y': 0.0} for index in range(node_count)]
    edges = [{'id': 'e0', 'source': 'n0', 'target': 'n1', 'relation': 'supports',
              'explanation': ''}] if node_count > 1 else []
    return {'nodes': nodes, 'edges': edges}


def test_canvas_table_is_additive_and_preserves_legacy_data(tmp_path: Path) -> None:
    """Opening a pre-canvas legacy database upgrades it in place without touching rows."""
    legacy = sqlite3.connect(tmp_path / 'legacy.sqlite3')
    # A pre-canvas store: the full schema minus the student_canvases table.
    legacy.executescript(SQLITE_SCHEMA.split('CREATE TABLE IF NOT EXISTS student_canvases')[0])
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
        assert 'student_canvases' in tables
        assert connection.execute('SELECT COUNT(*) AS total FROM student_canvases').fetchone()['total'] == 0
    assert store.get_thread('nb1') is not None
    # The explicit migration is idempotent and leaves existing rows intact.
    with store._connect() as connection:
        migrate_student_canvases(connection)
    assert store.list_canvases('nb1') == []


def test_canvas_create_get_list_update_and_ownership(tmp_path: Path) -> None:
    """One owned notebook's canvas round-trips; foreign owners never see or change it."""
    root = StudentStore(tmp_path / 'canvases.sqlite3')
    _seed(root, 'alice')
    _seed(root, 'bob')
    alice = StudentStore(root.path, identifier='cognito:alice')
    bob = StudentStore(root.path, identifier='cognito:bob')
    thread = alice.create_thread(name='Crossing study', model_id='mock', support_mode='critical-thinking')
    graph = _graph(2)

    created = alice.create_canvas(thread, 'Concept map', graph)
    assert created['title'] == 'Concept map'
    assert created['graph'] == graph
    assert created['revision'] == 1 and created['schema_version'] == 1
    assert created['origin'] == 'editor' and created['thread_id'] == thread

    saved = alice.update_canvas(created['id'], graph, created['revision'], title='Concept map v2')
    assert saved['revision'] == 2 and saved['title'] == 'Concept map v2'
    assert saved['updated_at'] >= created['updated_at']

    entries = alice.list_canvases(thread)
    assert [entry['id'] for entry in entries] == [created['id']]
    assert 'graph' not in entries[0]

    # A stale conditional save fails without changing the stored work.
    with pytest.raises(Exception, match='changed. Reopen'):
        alice.update_canvas(created['id'], graph, created['revision'])
    assert alice.get_canvas(created['id'])['revision'] == 2

    # Foreign ownership is invisible and unwritable through every operation.
    assert bob.get_canvas(created['id']) is None
    assert bob.list_canvases(thread) == []
    with pytest.raises(LookupError):
        bob.update_canvas(created['id'], graph, 2)
    with pytest.raises((LookupError, ValueError)):
        alice.create_canvas('unknown-notebook', 'X', graph)


def test_canvas_snapshots_are_validated_and_bounded(tmp_path: Path) -> None:
    """Duplicate ids, broken endpoints, unsafe kinds and oversized graphs fail before storage."""
    store = StudentStore(tmp_path / 'snapshots.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Maps', model_id='mock', support_mode='critical-thinking')
    with pytest.raises(ValueError, match='Unsupported node type'):
        store.create_canvas(thread, 'X', _graph_with_kind('invented'))
    with pytest.raises(ValueError, match='unknown node'):
        store.create_canvas(thread, 'X', {'nodes': [], 'edges': [
            {'id': 'e0', 'source': 'missing', 'target': 'also-missing', 'relation': 'supports'}]})
    with pytest.raises(ValueError, match='Duplicate node id'):
        store.create_canvas(thread, 'X', {'nodes': [
            {'id': 'n0', 'kind': 'note', 'title': 'A', 'x': 0, 'y': 0},
            {'id': 'n0', 'kind': 'note', 'title': 'B', 'x': 1, 'y': 0}], 'edges': []})
    with pytest.raises(ValueError, match='Unsupported relationship'):
        store.create_canvas(thread, 'X', {'nodes': [
            {'id': 'n0', 'kind': 'note', 'title': 'A', 'x': 0, 'y': 0}], 'edges': [
            {'id': 'e0', 'source': 'n0', 'target': 'n0', 'relation': 'hacked'}]})
    with pytest.raises(ValueError, match='joins a node to itself'):
        store.create_canvas(thread, 'X', {'nodes': [
            {'id': 'n0', 'kind': 'note', 'title': 'A', 'x': 0, 'y': 0}], 'edges': [
            {'id': 'e0', 'source': 'n0', 'target': 'n0', 'relation': 'supports'}]})
    with pytest.raises(ValueError, match='unsupported values'):
        store.create_canvas(thread, 'X', {'nodes': [
            {'id': 'n0', 'kind': 'note', 'title': 'A', 'x': float('inf'), 'y': 0}], 'edges': []})
    huge = {'nodes': [{'id': f'n{index}', 'kind': 'note', 'title': f'Node {index}',
                       'x': 0.0, 'y': 0.0} for index in range(200)], 'edges': []}
    with pytest.raises(ValueError, match='too many nodes'):
        store.create_canvas(thread, 'X', huge)
    junk = {'nodes': [], 'edges': [], 'junk': {'nested': 'x' * 1000}}
    with pytest.raises(ValueError, match='unsupported keys'):
        store.create_canvas(thread, 'X', junk)
    oversized = {'nodes': [{'id': f'n{index}', 'kind': 'note', 'title': f'Node {index}',
                            'x': 0.0, 'y': 0.0} for index in range(100)],
                 'edges': [{'id': f'e{index}', 'source': 'n0',
                            'target': f'n{index % 99 + 1}', 'relation': 'supports',
                            'explanation': 'x' * 2000} for index in range(200)]}
    with pytest.raises(ValueError, match='too large'):
        store.create_canvas(thread, 'X', oversized)


def test_canvas_nodes_carry_optional_thinking_path_stages(tmp_path: Path) -> None:
    """A node may associate with one Thinking Path stage; other values fail closed."""
    store = StudentStore(tmp_path / 'stages.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Maps', model_id='mock', support_mode='critical-thinking')
    graph = {'nodes': [
        {'id': 'n0', 'kind': 'problem', 'title': 'Crossing problem', 'description': '',
         'stage': 'problem_identification', 'x': 0, 'y': 0},
        {'id': 'n1', 'kind': 'note', 'title': 'Loose idea', 'description': '', 'x': 100, 'y': 0},
    ], 'edges': []}
    created = store.create_canvas(thread, 'Staged map', graph)
    assert created['graph']['nodes'][0]['stage'] == 'problem_identification'
    # Omitting the association stays absent, and legacy snapshots keep opening.
    assert 'stage' not in created['graph']['nodes'][1]
    saved = store.update_canvas(created['id'], graph, created['revision'])
    assert saved['graph'] == graph
    with pytest.raises(ValueError, match='Unknown Thinking Path stage'):
        store.update_canvas(created['id'], {'nodes': [
            {'id': 'n0', 'kind': 'note', 'title': 'A', 'stage': 'invented', 'x': 0, 'y': 0}],
            'edges': []}, saved['revision'])


def test_canvas_version_history_records_saves_and_restores_as_new_revisions(tmp_path: Path) -> None:
    """Every save checkpoints a version; restore creates a new revision keeping all intermediates."""
    store = StudentStore(tmp_path / 'canvas-versions.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Maps', model_id='mock', support_mode='critical-thinking')
    first = store.create_canvas(thread, 'Map', {'nodes': [
        {'id': 'n0', 'kind': 'note', 'title': 'v1', 'x': 0, 'y': 0}], 'edges': []})
    second = {'nodes': [{'id': 'n0', 'kind': 'note', 'title': 'v2', 'x': 0, 'y': 0}], 'edges': []}
    third = {'nodes': [{'id': 'n0', 'kind': 'note', 'title': 'v3', 'x': 0, 'y': 0}], 'edges': []}
    store.update_canvas(first['id'], second, 1)
    store.update_canvas(first['id'], third, 2, title='Map v3')

    versions = store.list_canvas_versions(first['id'])
    assert [entry['revision'] for entry in versions] == [3, 2, 1]
    assert versions[0]['origin'] == 'editor' and versions[0]['restored_from'] is None
    preview = store.get_canvas_version(first['id'], 1)
    assert preview is not None
    assert preview['graph']['nodes'][0]['title'] == 'v1'
    assert store.get_canvas_version(first['id'], 99) is None

    # Restore version 1 as a new revision: the current work and all intermediates stay in history.
    restored = store.restore_canvas(first['id'], 1, 3)
    assert restored['revision'] == 4 and restored['origin'] == 'restore'
    assert restored['graph']['nodes'][0]['title'] == 'v1'
    assert restored['title'] == 'Map'  # The restored version's title returns with its content.
    revisions = [entry['revision'] for entry in store.list_canvas_versions(first['id'])]
    assert revisions == [4, 3, 2, 1]
    kept = store.get_canvas_version(first['id'], 3)
    assert kept is not None and kept['graph']['nodes'][0]['title'] == 'v3'

    # Stale restore (current revision moved on) fails without writing.
    with pytest.raises(ValueError, match='changed. Reopen'):
        store.restore_canvas(first['id'], 1, 3)
    assert store.get_canvas(first['id'])['revision'] == 4
    # Foreign and unknown versions are invisible.
    _seed(store, 'bob')
    bob = StudentStore(store.path, identifier='cognito:bob')
    assert bob.list_canvas_versions(first['id']) == []
    assert bob.get_canvas_version(first['id'], 1) is None
    with pytest.raises(LookupError):
        bob.restore_canvas(first['id'], 1, 1)


def test_deleting_a_notebook_removes_its_canvases(tmp_path: Path) -> None:
    """Canvases are first-class notebook children in the runtime delete plan."""
    assert 'student_canvases' in [table for table, _predicate in NOTEBOOK_CHILD_DELETE_PLAN]
    store = StudentStore(tmp_path / 'delete.sqlite3')
    _seed(store, 'alice')
    store = StudentStore(store.path, identifier='cognito:alice')
    thread = store.create_thread(name='Maps', model_id='mock', support_mode='critical-thinking')
    created = store.create_canvas(thread, 'Map', {'nodes': [], 'edges': []})
    store.delete_thread(thread)
    assert store.get_canvas(created['id']) is None


def test_canvas_graph_survives_a_store_restart(tmp_path: Path) -> None:
    """The saved snapshot reopens exactly through a fresh store instance."""
    root = StudentStore(tmp_path / 'restart.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    thread = alice.create_thread(name='Maps', model_id='mock', support_mode='critical-thinking')
    graph = _graph(2)
    created = alice.create_canvas(thread, 'Concept map', graph)
    reopened = StudentStore(root.path, identifier='cognito:alice')
    assert reopened.get_canvas(created['id'])['graph'] == graph


def _graph_with_kind(kind: str) -> dict[str, object]:
    return {'nodes': [{'id': 'n0', 'kind': kind, 'title': 'A', 'x': 0, 'y': 0}], 'edges': []}


def _seed(root: StudentStore, name: str) -> None:
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
            "VALUES (?, ?, 'student', '{}', '2026-01-01T00:00:00Z')",
            (f'user-{name}', f'cognito:{name}'),
        )
        connection.commit()
