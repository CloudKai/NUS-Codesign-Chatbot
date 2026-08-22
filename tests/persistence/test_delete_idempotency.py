"""Deterministic tests for retryable student S3 delete idempotency."""

from __future__ import annotations

from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.persistence.dsql_connection import run_dsql_transaction
from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.persistence.factory import reset_file_storage_cache
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.object_keys import (
    build_source_chunks_object_key,
    notebook_prefix,
    sanitize_filename,
    source_prefix,
)
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import settings
from backend.source_library import add_file_sources, add_text_source
from backend.sources.chunk_artifacts import parse_chunk_artifact
from backend.sources.chunk_cache import (
    ChunkCacheKey,
    reset_student_source_chunk_cache,
    student_source_chunk_cache,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from backend.workspace_service import WorkspaceService
from fake_agentcore_runtime import FakeAgentCoreRuntime


def _install_memory_storage(monkeypatch, memory: MemoryFileStorage) -> None:
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )


def test_source_prefix_matches_object_key_layout():
    prefix = source_prefix(
        user_id="cognito:user/../a",
        notebook_id="nb/../b",
        source_id="src/../c",
    )
    assert prefix == "users/a/notebooks/b/sources/c/"
    assert prefix.startswith(notebook_prefix(user_id="a", notebook_id="b"))


def test_source_prefix_delete_retries_after_db_commit(tmp_path, monkeypatch):
    class _FlakyPrefixStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.prefix_calls: list[str] = []
            self._failures_left = 1

        def delete_prefix(self, prefix: str) -> int:
            self.prefix_calls.append(prefix)
            if self._failures_left > 0:
                self._failures_left -= 1
                raise PermissionError(f"transient AccessDenied: {prefix}")
            return super().delete_prefix(prefix)

    memory = _FlakyPrefixStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "src-retry.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    created = add_file_sources(
        store,
        notebook_id,
        [("report.txt", b"retry-body", "text/plain")],
    )
    source_id = created[0]["id"]
    object_key = created[0]["object_key"]
    extracted_key = created[0]["extracted_text_key"]
    expected_prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    assert memory.exists(object_key)
    assert extracted_key and memory.exists(extracted_key)

    with pytest.raises(PermissionError, match="transient AccessDenied"):
        store.delete_source(notebook_id, source_id)

    assert store.get_source(notebook_id, source_id) is None
    assert memory.exists(object_key)
    assert memory.prefix_calls == [expected_prefix]

    store.delete_source(notebook_id, source_id)
    assert not memory.exists(object_key)
    assert not memory.exists(extracted_key)
    assert memory.prefix_calls == [expected_prefix, expected_prefix]


def test_notebook_prefix_delete_retries_after_db_commit(tmp_path, monkeypatch):
    class _FlakyPrefixStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.prefix_calls: list[str] = []
            self._failures_left = 1

        def delete_prefix(self, prefix: str) -> int:
            self.prefix_calls.append(prefix)
            if self._failures_left > 0:
                self._failures_left -= 1
                raise PermissionError(f"transient AccessDenied: {prefix}")
            return super().delete_prefix(prefix)

    memory = _FlakyPrefixStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "nb-retry.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    created = add_file_sources(
        store,
        notebook_id,
        [("notes.pdf", b"%PDF-nb", "application/pdf")],
    )
    object_key = created[0]["object_key"]
    expected_prefix = notebook_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
    )
    assert memory.exists(object_key)

    with pytest.raises(PermissionError, match="transient AccessDenied"):
        store.delete_thread(notebook_id)

    assert store.get_thread(notebook_id) is None
    assert memory.exists(object_key)
    assert memory.prefix_calls == [expected_prefix]

    store.delete_thread(notebook_id)
    assert not memory.exists(object_key)
    assert memory.prefix_calls == [expected_prefix, expected_prefix]


def test_workspace_delete_retries_reach_absent_row_prefix_cleanup(
    tmp_path, monkeypatch
):
    """FastAPI's workspace boundary must not block post-commit cleanup retries."""

    class _FlakyPrefixStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.failures: set[str] = set()

        def delete_prefix(self, prefix: str) -> int:
            if prefix not in self.failures:
                self.failures.add(prefix)
                raise PermissionError(f"transient cleanup failure: {prefix}")
            return super().delete_prefix(prefix)

    memory = _FlakyPrefixStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "workspace-retry.sqlite3", identifier="owner-a")
    service = WorkspaceService(store)

    source_notebook = store.create_thread(model_id="mock", support_mode="guided")
    source = add_file_sources(
        store,
        source_notebook,
        [("source.txt", b"source-body", "text/plain")],
    )[0]
    with pytest.raises(PermissionError, match="transient cleanup failure"):
        service.delete_source(source_notebook, source["id"])
    with pytest.raises(ValueError, match="Source not found"):
        service.delete_source(source_notebook, source["id"])
    assert not memory.exists(source["object_key"])

    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    notebook_source = add_file_sources(
        store,
        notebook_id,
        [("notebook.txt", b"notebook-body", "text/plain")],
    )[0]
    with pytest.raises(PermissionError, match="transient cleanup failure"):
        service.delete_thread(notebook_id)
    with pytest.raises(ValueError, match="Notebook not found"):
        service.delete_thread(notebook_id)
    assert not memory.exists(notebook_source["object_key"])


def test_repeated_successful_source_and_notebook_delete_harmless(tmp_path, monkeypatch):
    memory = MemoryFileStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "repeat.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    source = add_file_sources(
        store,
        notebook_id,
        [("a.pdf", b"%PDF-a", "application/pdf")],
    )[0]

    store.delete_source(notebook_id, source["id"])
    store.delete_source(notebook_id, source["id"])
    assert not memory.exists(source["object_key"])

    other = add_file_sources(
        store,
        notebook_id,
        [("b.pdf", b"%PDF-b", "application/pdf")],
    )[0]
    store.delete_thread(notebook_id)
    store.delete_thread(notebook_id)
    assert not memory.exists(other["object_key"])
    assert store.get_thread(notebook_id) is None


def test_user_a_retry_never_deletes_user_b_prefix(tmp_path, monkeypatch):
    memory = MemoryFileStorage()
    _install_memory_storage(monkeypatch, memory)
    store_a = StudentStore(tmp_path / "a.sqlite3", identifier="cognito:a")
    store_b = StudentStore(tmp_path / "b.sqlite3", identifier="cognito:b")
    notebook_a = store_a.create_thread(model_id="mock", support_mode="guided")
    notebook_b = store_b.create_thread(model_id="mock", support_mode="guided")
    created_a = add_file_sources(
        store_a, notebook_a, [("report.pdf", b"%PDF-a", "application/pdf")]
    )
    created_b = add_file_sources(
        store_b, notebook_b, [("report.pdf", b"%PDF-b", "application/pdf")]
    )
    key_a = created_a[0]["object_key"]
    key_b = created_b[0]["object_key"]
    prefix_a = source_prefix(
        user_id=store_a.owner_id,
        notebook_id=notebook_a,
        source_id=created_a[0]["id"],
    )
    prefix_b = source_prefix(
        user_id=store_b.owner_id,
        notebook_id=notebook_b,
        source_id=created_b[0]["id"],
    )
    assert sanitize_filename(store_a.owner_id) not in prefix_b
    assert key_a.startswith(prefix_a)
    assert key_b.startswith(prefix_b)

    store_a.delete_source(notebook_a, created_a[0]["id"])
    assert store_a.get_source(notebook_a, created_a[0]["id"]) is None
    assert not memory.exists(key_a)
    assert memory.exists(key_b)

    # Absent-row retry still scopes cleanup to authenticated owner A.
    store_a.delete_source(notebook_a, created_a[0]["id"])
    assert memory.exists(key_b)
    assert memory.get_bytes(key_b) == b"%PDF-b"

    # Passing B's ids still builds A's owner prefix, never B's objects.
    foreign_prefix = source_prefix(
        user_id=store_a.owner_id,
        notebook_id=notebook_b,
        source_id=created_b[0]["id"],
    )
    assert not key_b.startswith(foreign_prefix)
    store_a.delete_source(notebook_b, created_b[0]["id"])
    assert memory.exists(key_b)


class _MinimalDsqlConnection:
    """Tiny DSQL stand-in for OCC-boundary tests (no AWS)."""

    def __init__(self) -> None:
        self._owner: str | None = None

    def execute(self, sql: str, params: Any = None) -> Any:
        upper = sql.strip().upper()
        if upper.startswith("SELECT ID FROM USERS WHERE IDENTIFIER"):
            owner = self._owner

            class _R:
                def fetchone(self_inner):
                    return {"id": owner} if owner else None

            return _R()
        if upper.startswith("INSERT INTO USERS"):
            self._owner = (params or [None])[0]

            class _R:
                rowcount = 1

                def fetchone(self_inner):
                    return None

            return _R()

        class _Empty:
            rowcount = 0

            def fetchone(self_inner):
                return None

        return _Empty()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> _MinimalDsqlConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


def test_dsql_source_delete_keeps_s3_outside_occ_callback(monkeypatch):
    """Object-prefix cleanup must not run inside run_dsql_transaction."""
    events: list[str] = []
    original_run = run_dsql_transaction

    def tracking_run(work, *args: Any, **kwargs: Any):
        events.append("occ_enter")
        try:
            return original_run(work, *args, **kwargs)
        finally:
            events.append("occ_exit")

    class _TrackingStorage(MemoryFileStorage):
        def delete_prefix(self, prefix: str) -> int:
            events.append(f"delete_prefix:{prefix}")
            return super().delete_prefix(prefix)

    memory = _TrackingStorage()
    _install_memory_storage(monkeypatch, memory)
    monkeypatch.setattr(
        "backend.persistence.dsql_student_store.run_dsql_transaction",
        tracking_run,
    )
    monkeypatch.setattr(
        "backend.settings.settings.dsql_endpoint",
        "example.dsql.amazonaws.com",
    )
    monkeypatch.setattr("backend.settings.settings.aws_region", "us-west-2")

    shared_conn = _MinimalDsqlConnection()
    store = DsqlStudentStore(
        identifier="cognito:occ",
        connection_factory=lambda: shared_conn,
        ensure_owner=True,
    )
    notebook_id = "nb-1"
    source_id = "src-1"
    prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    memory.put_bytes(key=f"{prefix}file.pdf", data=b"%PDF-occ")

    # Absent-row path: cleanup-only, no OCC around S3.
    events.clear()
    store.delete_source(notebook_id, source_id)
    assert events == [f"delete_prefix:{prefix}"]
    assert not memory.exists(f"{prefix}file.pdf")

    memory.put_bytes(key=f"{prefix}file.pdf", data=b"%PDF-occ2")
    events.clear()
    source_seen = {"value": True}

    def get_once(thread_id: str, sid: str):
        if source_seen["value"]:
            source_seen["value"] = False
            return {
                "id": sid,
                "notebook_id": thread_id,
                "object_key": f"{prefix}file.pdf",
                "extracted_text_key": None,
                "metadata": {},
            }
        return None

    store.get_source = get_once  # type: ignore[method-assign]
    store.delete_source(notebook_id, source_id)

    assert events.index("occ_enter") < events.index("occ_exit")
    assert events.index("occ_exit") < events.index(f"delete_prefix:{prefix}")
    assert not memory.exists(f"{prefix}file.pdf")


def test_locked_course_source_still_blocked_when_metadata_exists(tmp_path, monkeypatch):
    memory = MemoryFileStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "locked.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    source_id = store.add_source(
        notebook_id,
        kind="file",
        title="course.pdf",
        path="users/owner/course.pdf",
        metadata={
            "locked_source": True,
            "storage_provider": "memory",
            "object_key": "users/owner/course.pdf",
        },
    )
    with pytest.raises(ValueError, match="Course materials"):
        store.delete_source(notebook_id, source_id)
    assert store.get_source(notebook_id, source_id) is not None


_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _coach_service(store: StudentStore) -> CoachApplicationService:
    """Build a mock AgentCore coaching service for post-delete turns."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(
            AgentCoreCoachProvider(
                _RUNTIME_ARN,
                region="us-west-2",
                qualifier="DEFAULT",
                timeout_seconds=110.0,
                max_retries=0,
                client=FakeAgentCoreRuntime(
                    payload={
                        "mode": "coaching",
                        "response_text": "What assumption is carrying this preference?",
                        "recommendation": "stay",
                        "recommendation_rationale": "More evidence is still needed.",
                        "citations": [],
                        "hmw_scaffold_ready": False,
                        "needs_source_retrieval": False,
                        "out_of_scope": False,
                    }
                ),
            ),
            transitions,
        ),
        LearningProgressService(store, notebooks, transitions),
    )


def test_source_delete_removes_chunk_artifact_and_blocks_coach(tmp_path, monkeypatch):
    reset_student_source_chunk_cache()
    memory = MemoryFileStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "chunk-del.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    source = add_text_source(
        store,
        notebook_id,
        "notes.txt",
        "Accessibility notes for older pedestrians.",
    )
    source_id = source["id"]
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    expected_prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    assert memory.exists(chunks_key)
    digest = str((source.get("metadata") or {}).get("extracted_text_sha256") or "")
    parsed = parse_chunk_artifact(
        memory.get_bytes(chunks_key),
        expected_source_id=source_id,
        expected_digest=digest,
    )
    assert parsed is not None
    cache = student_source_chunk_cache()
    cache.put(ChunkCacheKey.current(chunks_key, digest), parsed)
    assert cache.get(ChunkCacheKey.current(chunks_key, digest)) is not None
    store.delete_source(notebook_id, source_id)
    assert store.get_source(notebook_id, source_id) is None
    assert not memory.exists(chunks_key)
    extracted_key = source.get("extracted_text_key")
    if extracted_key:
        assert not memory.exists(extracted_key)
    assert cache.get(ChunkCacheKey.current(chunks_key, digest)) is None
    assert expected_prefix.endswith("/")
    service = _coach_service(store)
    with pytest.raises(ValueError, match="unknown"):
        service.submit(
            CoachRequest(
                thread_id=notebook_id,
                student_message="What does the lecture say about accessibility?",
                current_stage="problem_identification",
                response_detail="short",
                source_ids=[source_id],
                idempotency_key="after-delete",
            )
        )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook_id,
            student_message="What does the lecture say about accessibility?",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="after-delete-empty",
        )
    )
    assert turn.response_text
    reset_student_source_chunk_cache()


def test_source_delete_invalidates_chunk_cache_when_storage_cleanup_fails(
    tmp_path, monkeypatch
):
    """Metadata delete plus cache drop still happen when prefix cleanup raises."""

    class _FlakyPrefixStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.prefix_calls: list[str] = []
            self._failures_left = 1

        def delete_prefix(self, prefix: str) -> int:
            self.prefix_calls.append(prefix)
            if self._failures_left > 0:
                self._failures_left -= 1
                raise PermissionError(f"transient AccessDenied: {prefix}")
            return super().delete_prefix(prefix)

    reset_student_source_chunk_cache()
    memory = _FlakyPrefixStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "cache-survive.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    source = add_text_source(
        store,
        notebook_id,
        "notes.txt",
        "Accessibility notes for older pedestrians.",
    )
    source_id = source["id"]
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    expected_prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    digest = str((source.get("metadata") or {}).get("extracted_text_sha256") or "")
    parsed = parse_chunk_artifact(
        memory.get_bytes(chunks_key),
        expected_source_id=source_id,
        expected_digest=digest,
    )
    assert parsed is not None
    cache = student_source_chunk_cache()
    cache.put(ChunkCacheKey.current(chunks_key, digest), parsed)
    assert cache.get(ChunkCacheKey.current(chunks_key, digest)) is not None

    with pytest.raises(PermissionError, match="transient AccessDenied"):
        store.delete_source(notebook_id, source_id)

    assert store.get_source(notebook_id, source_id) is None
    assert memory.exists(chunks_key)
    assert memory.prefix_calls == [expected_prefix]
    assert cache.get(ChunkCacheKey.current(chunks_key, digest)) is None

    service = _coach_service(store)
    with pytest.raises(ValueError, match="unknown"):
        service.submit(
            CoachRequest(
                thread_id=notebook_id,
                student_message="What does the lecture say about accessibility?",
                current_stage="problem_identification",
                response_detail="short",
                source_ids=[source_id],
                idempotency_key="after-failed-cleanup",
            )
        )

    store.delete_source(notebook_id, source_id)
    assert not memory.exists(chunks_key)
    assert memory.prefix_calls == [expected_prefix, expected_prefix]
    reset_student_source_chunk_cache()


def test_chunk_cache_invalidation_failure_does_not_mask_storage_error(
    tmp_path, monkeypatch
):
    """A raising cache drop must not replace the original storage exception."""

    class _FlakyPrefixStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.prefix_calls: list[str] = []

        def delete_prefix(self, prefix: str) -> int:
            self.prefix_calls.append(prefix)
            raise PermissionError(f"transient AccessDenied: {prefix}")

    reset_student_source_chunk_cache()
    memory = _FlakyPrefixStorage()
    _install_memory_storage(monkeypatch, memory)
    cache = student_source_chunk_cache()

    def _boom(_prefix: str) -> int:
        raise RuntimeError("cache boom")

    monkeypatch.setattr(cache, "invalidate_prefix", _boom)
    store = StudentStore(tmp_path / "cache-mask.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    source = add_text_source(
        store,
        notebook_id,
        "notes.txt",
        "Accessibility notes for older pedestrians.",
    )
    source_id = source["id"]
    expected_prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )

    with pytest.raises(PermissionError, match="transient AccessDenied"):
        store.delete_source(notebook_id, source_id)

    assert store.get_source(notebook_id, source_id) is None
    assert memory.prefix_calls == [expected_prefix]
    reset_student_source_chunk_cache()


def test_notebook_delete_removes_chunk_artifacts_and_sources(tmp_path, monkeypatch):
    reset_student_source_chunk_cache()
    memory = MemoryFileStorage()
    _install_memory_storage(monkeypatch, memory)
    store = StudentStore(tmp_path / "nb-chunk-del.sqlite3", identifier="owner-a")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    created = [
        add_text_source(store, notebook_id, "a.txt", "First accessibility note."),
        add_text_source(store, notebook_id, "b.txt", "Second accessibility note."),
    ]
    chunk_keys = [
        build_source_chunks_object_key(
            user_id=store.owner_id,
            notebook_id=notebook_id,
            source_id=item["id"],
        )
        for item in created
    ]
    expected_prefix = notebook_prefix(
        user_id=store.owner_id,
        notebook_id=notebook_id,
    )
    assert all(memory.exists(key) for key in chunk_keys)
    store.delete_thread(notebook_id)
    assert store.get_thread(notebook_id) is None
    assert store.list_sources(notebook_id) == []
    for item in created:
        assert store.get_source(notebook_id, item["id"]) is None
    for key in chunk_keys:
        assert not memory.exists(key)
        assert key.startswith(expected_prefix)
    service = _coach_service(store)
    with pytest.raises(ValueError, match="Notebook not found"):
        service.submit(
            CoachRequest(
                thread_id=notebook_id,
                student_message="What does the lecture say about accessibility?",
                current_stage="problem_identification",
                response_detail="short",
                source_ids=[created[0]["id"]],
                idempotency_key="after-nb-delete",
            )
        )
    reset_student_source_chunk_cache()
