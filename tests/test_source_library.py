from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.chat_service import ChatOptions, StudentChatEngine, response_input_for_model
from backend.source_library import (
    CourseMaterialSyncCoordinator,
    SourceImportError,
    add_file_sources,
    add_text_source,
    backfill_legacy_sources,
    course_material_group,
    fetch_public_webpage,
    image_inputs_for_source_ids,
    selected_source_context,
    sync_lecture_notes_folder,
    validate_public_url,
)
from backend.student_store import StudentStore


def make_notebook(tmp_path: Path, monkeypatch):
    from backend import file_processing, source_library, student_store

    files_dir = tmp_path / "files"
    monkeypatch.setattr(file_processing.settings, "files_dir", files_dir)
    monkeypatch.setattr(source_library.settings, "files_dir", files_dir)
    monkeypatch.setattr(student_store.settings, "files_dir", files_dir)
    store = StudentStore(tmp_path / "student.sqlite3", identifier="source-student")
    thread_id = store.create_thread(
        model_id="gpt-5.4-mini",
        support_mode="critical-thinking",
    )
    return store, thread_id, files_dir


def test_notebook_source_crud_selection_and_file_cleanup(tmp_path, monkeypatch):
    store, thread_id, files_dir = make_notebook(tmp_path, monkeypatch)
    created = add_file_sources(
        store,
        thread_id,
        [("evidence.txt", b"Evidence from the study.", "text/plain")],
    )
    assert len(created) == 1
    source = created[0]
    assert source["selected"] is True
    assert Path(source["path"]).is_file()
    assert files_dir in Path(source["path"]).parents

    store.set_source_selected(thread_id, source["id"], False)
    assert store.list_sources(thread_id, selected_only=True) == []
    store.set_all_sources_selected(thread_id, True)
    assert store.list_sources(thread_id, selected_only=True)[0]["id"] == source["id"]

    path = Path(source["path"])
    store.delete_source(thread_id, source["id"])
    assert store.list_sources(thread_id) == []
    assert not path.exists()


def test_source_paths_cannot_escape_notebook_storage(tmp_path, monkeypatch):
    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Unsafe source path"):
        store.add_source(
            thread_id,
            kind="file",
            title="Unsafe",
            path=str(tmp_path / "outside.txt"),
        )


def test_pasted_source_context_has_stable_labels_and_limit(tmp_path, monkeypatch):
    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    first = add_text_source(store, thread_id, "Lecture", "A" * 100)
    second = add_text_source(store, thread_id, "Reading", "B" * 100)
    context, references = selected_source_context([first, second], limit=145)
    assert references[0]["label"] == "S1"
    assert references[1]["label"] == "S2"
    assert "[S1] Lecture" in context
    assert len(context) <= 145


def test_image_inputs_for_source_ids_resolves_selected_png(tmp_path, monkeypatch):
    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    created = add_file_sources(
        store,
        thread_id,
        [("diagram.png", png, "image/png")],
    )
    text = add_text_source(store, thread_id, "Notes", "Text only")
    images = image_inputs_for_source_ids(
        store,
        thread_id,
        [created[0]["id"], text["id"]],
    )
    assert len(images) == 1
    assert images[0]["source_id"] == created[0]["id"]
    assert images[0]["data_url"].startswith("data:image/png;base64,")


def test_lecture_notes_folder_syncs_updates_and_removes_sources(tmp_path, monkeypatch):
    from backend import source_library

    store, thread_id, files_dir = make_notebook(tmp_path, monkeypatch)
    lecture_notes = tmp_path / "lecture_notes"
    lecture_notes.mkdir()
    (lecture_notes / "README.txt").write_text("Instructions only", encoding="utf-8")
    notes_folder = lecture_notes / "lectureNotes"
    notes_folder.mkdir()
    note = notes_folder / "week-01.txt"
    note.write_text("Pedestrian crossing evidence from lecture one.", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", lecture_notes)
    monkeypatch.setattr(source_library.settings, "max_lecture_notes", 50)
    monkeypatch.setattr(source_library.settings, "max_file_size_mb", 0)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)

    first = sync_lecture_notes_folder(store, thread_id)
    source = store.list_sources(thread_id)[0]
    context, references = selected_source_context([source])

    assert first.added == 1
    assert first.skipped == 0
    assert source["selected"] is True
    assert source["metadata"]["origin"] == "lecture_notes_folder"
    assert source["metadata"]["lecture_note_relative_path"] == "lectureNotes/week-01.txt"
    assert source["metadata"]["course_material_group"] == "Lecture Notes"
    assert source["metadata"]["locked_source"] is True
    assert source["title"] == "week-01.txt"
    assert files_dir in Path(source["path"]).parents
    assert "Pedestrian crossing evidence" in context
    assert references[0]["id"] == source["id"]
    assert sync_lecture_notes_folder(store, thread_id).unchanged == 1

    with pytest.raises(ValueError, match="Course materials cannot be removed"):
        store.delete_source(thread_id, source["id"])

    note.write_text("Updated lecture evidence with a larger sample.", encoding="utf-8")
    refreshed = sync_lecture_notes_folder(store, thread_id)
    refreshed_sources = store.list_sources(thread_id)
    assert refreshed.updated == 1
    assert len(refreshed_sources) == 1
    assert "larger sample" in refreshed_sources[0]["extractedText"]

    note.unlink()
    removed = sync_lecture_notes_folder(store, thread_id)
    assert removed.removed == 1
    assert store.list_sources(thread_id) == []


def test_course_material_groups_readings_without_moving_files():
    assert course_material_group("readings/Article.pdf") == "Readings"
    assert course_material_group("lectureNotes/Week 1.pdf") == "Lecture Notes"
    assert course_material_group("Reading 2.pdf") == "Readings"
    assert course_material_group("Unsorted handout.pdf") == "Lecture Notes"


def test_concurrent_course_sync_keeps_fixed_seven_and_three_groups(
    tmp_path,
    monkeypatch,
):
    """Overlapping refreshes must share one logical 7/3 course library."""
    from backend import source_library

    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    course_root = tmp_path / "lecture_notes"
    notes = course_root / "lectureNotes"
    readings = course_root / "readings"
    notes.mkdir(parents=True)
    readings.mkdir()
    for index in range(7):
        (notes / f"Week {index + 1}.txt").write_text(
            f"Lecture evidence {index + 1}",
            encoding="utf-8",
        )
    for index in range(3):
        (readings / f"Reading {index + 1}.txt").write_text(
            f"Reading evidence {index + 1}",
            encoding="utf-8",
        )
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", course_root)
    monkeypatch.setattr(source_library.settings, "max_lecture_notes", 50)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda _index: sync_lecture_notes_folder(store, thread_id),
                range(3),
            )
        )

    sources = store.list_sources(thread_id)
    groups = [source["metadata"]["course_material_group"] for source in sources]
    assert len(sources) == 10
    assert groups.count("Lecture Notes") == 7
    assert groups.count("Readings") == 3
    assert sum(result.added for result in results) == 10


def test_course_sync_repairs_duplicate_rows_from_interrupted_refresh(
    tmp_path,
    monkeypatch,
):
    """A later refresh removes old duplicate managed-source rows safely."""
    from backend import source_library

    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    course_root = tmp_path / "lecture_notes"
    readings = course_root / "readings"
    readings.mkdir(parents=True)
    material = readings / "Reading 1.txt"
    material.write_text("Course reading", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", course_root)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)

    sync_lecture_notes_folder(store, thread_id)
    original = store.list_sources(thread_id)[0]
    add_file_sources(
        store,
        thread_id,
        [(material.name, material.read_bytes(), "text/plain")],
        origin="lecture_notes_folder",
        extra_metadata=dict(original["metadata"]),
        max_file_size_mb=1,
        preserve_display_names=True,
    )
    assert len(store.list_sources(thread_id)) == 2

    repaired = sync_lecture_notes_folder(store, thread_id)
    sources = store.list_sources(thread_id)
    assert repaired.removed == 1
    assert len(sources) == 1
    assert sources[0]["metadata"]["course_material_group"] == "Readings"


def test_course_sync_coordinator_reuses_an_inflight_refresh(
    tmp_path,
    monkeypatch,
):
    """A browser refresh must reuse, rather than duplicate, the active import."""
    import threading

    from backend import source_library

    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    course_root = tmp_path / "lecture_notes"
    notes = course_root / "lectureNotes"
    notes.mkdir(parents=True)
    (notes / "Week 1.txt").write_text("Evidence", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", course_root)

    started = threading.Event()
    release = threading.Event()

    def slow_sync(sync_store, sync_thread_id):
        started.set()
        assert release.wait(timeout=2)
        return sync_lecture_notes_folder(sync_store, sync_thread_id)

    monkeypatch.setattr(source_library, "sync_lecture_notes_folder", slow_sync)
    coordinator = CourseMaterialSyncCoordinator()
    first = coordinator.request(store, thread_id)
    assert started.wait(timeout=2)
    second = coordinator.request(store, thread_id)
    assert second is first
    release.set()
    assert first.result(timeout=3).added == 1


def test_public_url_validation_blocks_private_networks():
    private = lambda *_args, **_kwargs: [
        (2, 1, 6, "", ("127.0.0.1", 443))
    ]
    with pytest.raises(SourceImportError, match="Private or local"):
        validate_public_url("https://localhost/private", resolver=private)

    public = lambda *_args, **_kwargs: [
        (2, 1, 6, "", ("93.184.216.34", 443))
    ]
    assert (
        validate_public_url("https://example.com/research", resolver=public)
        == "https://example.com/research"
    )


def test_public_html_import_extracts_title_and_readable_text(monkeypatch):
    from backend import source_library

    monkeypatch.setattr(
        source_library,
        "validate_public_url",
        lambda value, **_kwargs: value,
    )

    class Headers(dict):
        def get_content_type(self):
            return "text/html"

        def get_content_charset(self):
            return "utf-8"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://example.com/research"

        def read(self, _limit):
            return (
                b"<html><head><title>Research page</title><script>ignore()</script></head>"
                b"<body><h1>Main claim</h1><p>Supporting evidence.</p></body></html>"
            )

    class Opener:
        def open(self, _request, timeout):
            assert timeout == 10
            return Response()

    title, text, url, size = fetch_public_webpage(
        "https://example.com/research",
        opener=Opener(),
    )
    assert title == "Research page"
    assert "Main claim" in text
    assert "Supporting evidence" in text
    assert "ignore()" not in text
    assert url == "https://example.com/research"
    assert size > 0


def test_legacy_message_attachment_is_backfilled_without_file_ownership(
    tmp_path,
    monkeypatch,
):
    store, thread_id, files_dir = make_notebook(tmp_path, monkeypatch)
    legacy_root = files_dir / "threads" / thread_id / "uploads"
    legacy_root.mkdir(parents=True)
    path = legacy_root / "legacy.txt"
    path.write_text("Legacy evidence", encoding="utf-8")
    store.add_message(
        thread_id,
        "user",
        "Review this.",
        metadata={
            "uploads": [
                {
                    "name": "legacy.txt",
                    "path": str(path),
                    "mime": "text/plain",
                    "size": path.stat().st_size,
                    "supported": True,
                }
            ]
        },
    )
    assert backfill_legacy_sources(store, thread_id) == 1
    assert backfill_legacy_sources(store, thread_id) == 0
    source = store.list_sources(thread_id)[0]
    store.delete_source(thread_id, source["id"])
    assert path.exists()


def test_response_continuation_requires_same_source_snapshot():
    user = {"role": "user", "content": "new"}
    current, response_id = response_input_for_model(
        [{"role": "user", "content": "old"}],
        user,
        previous_model="gpt-5.4",
        selected_model="gpt-5.4",
        previous_response_id="resp_1",
        previous_source_snapshot=["source-a"],
        selected_source_snapshot=["source-a"],
        previous_grounding_mode="source_first",
        selected_grounding_mode="source_first",
    )
    assert current == [user]
    assert response_id == "resp_1"

    replay, response_id = response_input_for_model(
        [{"role": "user", "content": "old"}],
        user,
        previous_model="gpt-5.4",
        selected_model="gpt-5.4",
        previous_response_id="resp_1",
        previous_source_snapshot=["source-a"],
        selected_source_snapshot=["source-b"],
        previous_grounding_mode="source_first",
        selected_grounding_mode="source_first",
    )
    assert [item["content"] for item in replay] == ["old", "new"]
    assert response_id is None


def test_mock_turn_persists_source_snapshot_and_citations(tmp_path, monkeypatch):
    from backend import chat_service

    store, thread_id, _ = make_notebook(tmp_path, monkeypatch)
    monkeypatch.setattr(chat_service.settings, "mock_openai", True)
    source = add_text_source(store, thread_id, "Evidence note", "The sample contained 80 students.")
    stream = StudentChatEngine(store).submit(
        thread_id,
        "What evidence is available?",
        ChatOptions(
            model_id="gpt-5.4-mini",
            source_ids=[source["id"]],
            allow_model_knowledge=False,
        ),
    )
    rendered = "".join(stream)
    assert "[S1] Evidence note" in rendered
    assert store.get_state(thread_id)["sourceSnapshot"] == [source["id"]]
    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["source_refs"][0]["label"] == "S1"
