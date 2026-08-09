"""Deterministic S3 orphan cleanup and course-sync gate tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.factory import reset_file_storage_cache
from backend.persistence.memory_files import MemoryFileStorage
from backend.settings import settings
from backend.source_library import (
    CourseMaterialSyncCoordinator,
    add_file_sources,
    sync_lecture_notes_folder,
)
from backend.student_store import StudentStore


def test_raw_and_extracted_objects_cleaned_when_db_insert_fails(tmp_path, monkeypatch):
    memory = MemoryFileStorage()
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )

    store = StudentStore(tmp_path / "orphan.sqlite3", identifier="owner-a")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    other = StudentStore(tmp_path / "other.sqlite3", identifier="owner-b")
    other_thread = other.create_thread(model_id="mock", support_mode="guided")
    other_created = add_file_sources(
        other,
        other_thread,
        [("keep.pdf", b"%PDF-keep", "application/pdf")],
    )
    other_key = other_created[0]["object_key"]
    assert memory.exists(other_key)

    original_add = store.add_source

    def boom(*args, **kwargs):
        raise RuntimeError("forced metadata failure")

    store.add_source = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="forced metadata failure"):
        add_file_sources(
            store,
            thread_id,
            [("report.pdf", b"%PDF-raw", "application/pdf")],
        )
    store.add_source = original_add  # type: ignore[method-assign]

    # Failed upload keys must be gone; unrelated owner objects remain.
    remaining = [key for key in memory._objects if key.startswith("users/")]
    assert remaining == [other_key]
    assert memory.get_bytes(other_key) == b"%PDF-keep"


def test_course_material_sync_disabled_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "course_material_sync_enabled", False)
    lecture_notes = tmp_path / "lecture_notes"
    notes = lecture_notes / "lectureNotes"
    notes.mkdir(parents=True)
    (notes / "week1.pdf").write_bytes(b"%PDF-1")
    monkeypatch.setattr(settings, "lecture_notes_dir", lecture_notes)

    store = StudentStore(tmp_path / "sync-off.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    result = sync_lecture_notes_folder(store, thread_id)
    assert result.added == 0
    assert store.list_sources(thread_id) == []

    future = CourseMaterialSyncCoordinator().request(store, thread_id)
    assert future.done()
    assert future.result().added == 0
