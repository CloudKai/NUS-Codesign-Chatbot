"""Evidence references: structural validation, ownership resolution and fail-closed writes."""

from pathlib import Path

import pytest

from backend.persistence.store.operations.references import (
    canonical_references,
    notebook_family_ids,
    resolve_references,
)
from backend.student_store import StudentStore


def test_references_are_structurally_validated_and_bounded() -> None:
    """Only known kinds with bounded ids pass; lists are capped."""
    assert canonical_references(None) == []
    valid = [{'kind': 'source', 'id': 's-1'}, {'kind': 'message', 'id': 'm-1'},
             {'kind': 'artifact', 'id': 'a-1'},
             {'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1'}]
    assert canonical_references(valid) == valid
    with pytest.raises(ValueError, match='Unsupported reference kind'):
        canonical_references([{'kind': 'professor', 'id': 'x'}])
    with pytest.raises(ValueError, match='bounded non-empty'):
        canonical_references([{'kind': 'source', 'id': ''}])
    with pytest.raises(ValueError, match='needs a canvas'):
        canonical_references([{'kind': 'canvas_node', 'id': 'n-1'}])
    with pytest.raises(ValueError, match='Too many references'):
        canonical_references([{'kind': 'source', 'id': f's-{index}'} for index in range(21)])
    duplicates = [{'kind': 'source', 'id': 's-1'}, {'kind': 'source', 'id': 's-1'}]
    assert canonical_references(duplicates) == [duplicates[0]]


def test_artifact_references_keep_their_revision_origin() -> None:
    """An artifact reference may carry the saved revision its content came from.

    Artifact-to-canvas nodes record which artifact revision they were drawn
    from so later document edits are detectable instead of silent. The field
    stays absent when unsupplied so legacy snapshots compare exactly.
    """
    reference = {'kind': 'artifact', 'id': 'a-1', 'revision': 3}
    assert canonical_references([reference]) == [reference]
    assert canonical_references([{'kind': 'artifact', 'id': 'a-1'}]) == [
        {'kind': 'artifact', 'id': 'a-1'}]
    with pytest.raises(ValueError, match='revision'):
        canonical_references([{'kind': 'artifact', 'id': 'a-1', 'revision': 0}])
    with pytest.raises(ValueError, match='revision'):
        canonical_references([{'kind': 'artifact', 'id': 'a-1', 'revision': 'stale'}])
    with pytest.raises(ValueError, match='revision'):
        canonical_references([{'kind': 'message', 'id': 'm-1', 'revision': 2}])


def test_canvas_node_references_keep_their_saved_canvas_revision() -> None:
    """A canvas-node reference may record the canvas revision it was drawn from.

    The revision stays absent when unsupplied so legacy snapshots compare
    exactly, and only artifact/canvas_node references accept one.
    """
    reference = {'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1', 'revision': 4}
    assert canonical_references([reference]) == [reference]
    assert canonical_references([{'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1'}]) == [
        {'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1'}]
    for bad in (0, -1, 'stale', True, 1_000_001):
        with pytest.raises(ValueError, match='revision'):
            canonical_references([{**reference, 'revision': bad}])
    with pytest.raises(ValueError, match='revision'):
        canonical_references([{'kind': 'source', 'id': 's-1', 'revision': 2}])


def test_duplicate_references_keep_the_newest_revision() -> None:
    """The same node linked twice collapses to one entry carrying the newer stamp.

    A later lower revision never regresses the recorded stamp, a duplicate
    without a revision leaves the existing entry unchanged, and legacy lists
    without revisions still collapse to the first entry.
    """
    older = {'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1', 'revision': 1}
    newer = {**older, 'revision': 3}
    assert canonical_references([older, newer]) == [newer]
    assert canonical_references([newer, older]) == [newer]
    plain = {'kind': 'canvas_node', 'canvas_id': 'c-1', 'id': 'n-1'}
    assert canonical_references([newer, plain]) == [newer]
    assert canonical_references([plain, newer]) == [newer]
    assert canonical_references([plain, plain]) == [plain]
    legacy = [{'kind': 'source', 'id': 's-1'}, {'kind': 'message', 'id': 'm-1'}]
    assert canonical_references(legacy) == legacy


def test_canvas_node_revision_round_trips_on_artifact_references(tmp_path: Path) -> None:
    """An artifact saved from canvas nodes keeps each node's source canvas revision."""
    root = StudentStore(tmp_path / 'canvas-node-revision.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    thread = alice.create_thread(name='Design', model_id='mock', support_mode='critical-thinking')
    canvas = alice.create_canvas(thread, 'Map', {'nodes': [
        {'id': 'node-1', 'kind': 'problem', 'title': 'Crossing', 'x': 0, 'y': 0}], 'edges': []})
    reference = {'kind': 'canvas_node', 'canvas_id': canvas['id'], 'id': 'node-1',
                 'revision': canvas['revision']}
    created = alice.create_artifact(thread, 'Notes', {'type': 'doc', 'content': []},
                                    references=[reference])
    assert created['references'] == [{**reference, 'available': True, 'title': 'Crossing'}]
    reloaded = alice.get_artifact(created['id'])
    assert reloaded['references'][0]['revision'] == canvas['revision']


def test_references_resolve_under_owner_and_notebook_boundaries(tmp_path: Path) -> None:
    """Owned sources, active messages, artifacts and canvas nodes resolve; everything else fails."""
    root = StudentStore(tmp_path / 'refs.sqlite3')
    _seed(root, 'alice')
    _seed(root, 'bob')
    alice = StudentStore(root.path, identifier='cognito:alice')
    bob = StudentStore(root.path, identifier='cognito:bob')
    thread = alice.create_thread(name='Design', model_id='mock', support_mode='critical-thinking')
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "selected, metadata_text, created_at, updated_at) "
            "VALUES ('src-1', ?, 'pdf', 'Lecture slides', 'application/pdf', 10, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (thread,))
        connection.execute(
            "INSERT INTO messages (id, notebook_id, role, content, created_at) "
            "VALUES ('msg-1', ?, 'user', 'The crossing feels unsafe', '2026-01-01T00:00:00Z')",
            (thread,))
        connection.commit()
    artifact = alice.create_artifact(thread, 'Notes', {'type': 'doc', 'content': []})
    canvas = alice.create_canvas(thread, 'Map', {'nodes': [
        {'id': 'node-1', 'kind': 'problem', 'title': 'Crossing', 'x': 0, 'y': 0}], 'edges': []})

    resolved = resolve_references(alice, thread, [
        {'kind': 'source', 'id': 'src-1'}, {'kind': 'message', 'id': 'msg-1'},
        {'kind': 'artifact', 'id': artifact['id']},
        {'kind': 'canvas_node', 'canvas_id': canvas['id'], 'id': 'node-1'},
    ])
    by_kind = {(entry['kind'], entry['id']): entry for entry in resolved}
    assert by_kind[('source', 'src-1')]['available'] is True
    assert by_kind[('source', 'src-1')]['title'] == 'Lecture slides'
    assert by_kind[('message', 'msg-1')]['available'] is True
    assert 'crossing feels unsafe' in by_kind[('message', 'msg-1')]['title']
    assert by_kind[('artifact', artifact['id'])]['available'] is True
    assert by_kind[('artifact', artifact['id'])]['title'] == 'Notes'
    assert by_kind[('canvas_node', 'node-1')]['available'] is True
    assert by_kind[('canvas_node', 'node-1')]['title'] == 'Crossing'

    # Deleted, superseded, foreign and cross-project references resolve unavailable — never substituted.
    alice.delete_artifact(artifact['id'], True)
    foreign_thread = bob.create_thread(name='Other', model_id='mock', support_mode='critical-thinking')
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO messages (id, notebook_id, role, content, created_at, superseded_at_revision) "
            "VALUES ('msg-old', ?, 'user', 'old', '2026-01-01T00:00:00Z', 2)", (thread,))
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "selected, metadata_text, created_at, updated_at) "
            "VALUES ('foreign-src', ?, 'pdf', 'Other notebook', 'application/pdf', 10, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (foreign_thread,))
        connection.commit()
    resolved = resolve_references(alice, thread, [
        {'kind': 'artifact', 'id': artifact['id']},
        {'kind': 'message', 'id': 'msg-old'},
        {'kind': 'source', 'id': 'foreign-src'},
        {'kind': 'source', 'id': 'missing-src'},
        {'kind': 'canvas_node', 'canvas_id': canvas['id'], 'id': 'missing-node'},
        {'kind': 'artifact', 'id': 'unknown-artifact'},
    ])
    assert all(entry['available'] is False and entry['title'] is None for entry in resolved)


def test_notebook_family_is_the_whole_project_from_any_notebook(tmp_path: Path) -> None:
    """A child chat's family includes its parent and every sibling chat.

    The project boundary is the parent plus all of its children, so evidence
    and exports opened from any chat cover the same full set, while a
    standalone notebook's family stays itself.
    """
    root = StudentStore(tmp_path / 'family-ids.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    parent = alice.create_thread(name='Project', model_id='mock', support_mode='critical-thinking')
    children = [
        alice.create_thread(name=f'Chat {index}', model_id='mock',
                            support_mode='critical-thinking',
                            parent_notebook_id=parent, quick_chat=True)
        for index in range(3)
    ]
    standalone = alice.create_thread(name='Standalone', model_id='mock',
                                     support_mode='critical-thinking')
    expected = sorted([parent, *children])
    with root._connect() as connection:
        assert notebook_family_ids(connection, parent, alice.owner_id) == expected
        assert notebook_family_ids(connection, children[0], alice.owner_id) == expected
        assert notebook_family_ids(connection, standalone, alice.owner_id) == [standalone]


def test_message_references_resolve_across_the_notebook_family(tmp_path: Path) -> None:
    """A canvas in a parent notebook resolves messages from its child chats; other families fail."""
    root = StudentStore(tmp_path / 'family.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    thread = alice.create_thread(name='Design notebook', model_id='mock', support_mode='critical-thinking')
    chat = alice.create_thread(name='Crossing chat', model_id='mock',
                               support_mode='critical-thinking',
                               parent_notebook_id=thread, quick_chat=True)
    other = alice.create_thread(name='Other project', model_id='mock', support_mode='critical-thinking')
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO messages (id, notebook_id, role, content, created_at) "
            "VALUES ('msg-1', ?, 'user', 'The crossing feels unsafe', '2026-01-01T00:00:00Z')",
            (chat,))
        connection.execute(
            "INSERT INTO messages (id, notebook_id, role, content, created_at) "
            "VALUES ('msg-2', ?, 'user', 'Unrelated project', '2026-01-01T00:00:00Z')",
            (other,))
        connection.commit()
    resolved = resolve_references(alice, thread, [{'kind': 'message', 'id': 'msg-1'}])
    assert resolved[0]['available'] is True and 'crossing feels unsafe' in resolved[0]['title']
    # A message from another notebook family stays unavailable.
    resolved = resolve_references(alice, thread, [{'kind': 'message', 'id': 'msg-2'}])
    assert resolved[0]['available'] is False


def test_canvas_nodes_carry_resolved_evidence_references(tmp_path: Path) -> None:
    """A node reference list saves, reopens and fails closed on foreign evidence."""
    root = StudentStore(tmp_path / 'canvas-refs.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    thread = alice.create_thread(name='Design', model_id='mock', support_mode='critical-thinking')
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "selected, metadata_text, created_at, updated_at) "
            "VALUES ('src-1', ?, 'pdf', 'Lecture slides', 'application/pdf', 10, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (thread,))
        connection.commit()
    graph = {'nodes': [
        {'id': 'n0', 'kind': 'problem', 'title': 'Crossing', 'x': 0, 'y': 0,
         'references': [{'kind': 'source', 'id': 'src-1'}]}], 'edges': []}
    created = alice.create_canvas(thread, 'Evidence map', graph)
    resolved = created['graph']['nodes'][0]['references']
    assert resolved == [{'kind': 'source', 'id': 'src-1'}]
    with pytest.raises(ValueError, match='Unresolved reference'):
        alice.create_canvas(thread, 'Bad map', {'nodes': [
            {'id': 'n0', 'kind': 'problem', 'title': 'X', 'x': 0, 'y': 0,
             'references': [{'kind': 'source', 'id': 'unknown'}]}], 'edges': []})


def test_artifacts_carry_resolved_evidence_references(tmp_path: Path) -> None:
    """Artifact references save with the document and reopen through the projection."""
    root = StudentStore(tmp_path / 'artifact-refs.sqlite3')
    _seed(root, 'alice')
    alice = StudentStore(root.path, identifier='cognito:alice')
    thread = alice.create_thread(name='Design', model_id='mock', support_mode='critical-thinking')
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, byte_size, "
            "selected, metadata_text, created_at, updated_at) "
            "VALUES ('src-1', ?, 'pdf', 'Lecture slides', 'application/pdf', 10, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (thread,))
        connection.commit()
    document = {'type': 'doc', 'content': []}
    created = alice.create_artifact(thread, 'Notes', document,
                                    references=[{'kind': 'source', 'id': 'src-1'}])
    assert created['references'] == [{'kind': 'source', 'id': 'src-1', 'available': True,
                                      'title': 'Lecture slides'}]
    saved = alice.update_artifact(created['id'], document, created['revision'], title=None,
                                  references=[])
    assert saved['references'] == []
    with pytest.raises(ValueError, match='Unresolved reference'):
        alice.update_artifact(created['id'], document, saved['revision'],
                              references=[{'kind': 'message', 'id': 'unknown'}])


def _seed(root: StudentStore, name: str) -> None:
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
            "VALUES (?, ?, 'student', '{}', '2026-01-01T00:00:00Z')",
            (f'user-{name}', f'cognito:{name}'),
        )
        connection.commit()
