"""P0 operation-count tests for selected-source chunk hydration. No AWS."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.persistence.object_keys import (
    build_extracted_text_object_key,
    build_source_chunks_object_key,
    source_prefix,
)
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import (
    CompositeContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    UNANALYZABLE_SOURCE_PLACEHOLDER,
    canonical_chunk_text,
)
from backend.settings import settings
from backend.source_library import (
    add_file_sources,
    add_text_source,
    image_inputs_for_source_ids,
    list_visible_sources,
)
from backend.sources.chunk_artifacts import (
    CHUNK_ARTIFACT_SCHEMA_VERSION,
    build_chunk_artifact,
)
from backend.sources.chunk_cache import reset_student_source_chunk_cache
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from counting_file_storage import CountingFileStorage, install_counting_storage
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_SOURCE_QUESTION = "What does the lecture say about accessibility?"
_ACCESSIBILITY = (
    "Lecture notes on accessibility explain that older pedestrians need "
    "longer crossing times, audible signals, and step-free kerb design."
)
_CHUNK_SECRET = "UNIQUE_CHUNK_SECRET_PHRASE_DO_NOT_LOG"
_STALE_CHUNK = "STALE_ARTIFACT_TEXT_MUST_NOT_BE_RANKED"
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class RecordingLocalRetriever:
    """Local lexical retriever that records queries and ranked results."""

    def __init__(self) -> None:
        self._inner = LocalChunkRetriever()
        self.calls: list[RetrievalQuery] = []
        self.results: list[RetrievalResult] = []

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Record one retrieve, then rank with the production local adapter."""
        self.calls.append(query)
        result = self._inner.retrieve(query)
        self.results.append(result)
        return result


def _coaching_payload() -> dict[str, Any]:
    """Return one lightweight fast-chat coaching body."""
    return {
        "mode": "coaching",
        "response_text": "What assumption is carrying this preference?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }


def _service(
    store: StudentStore,
    retriever: RecordingLocalRetriever | None = None,
) -> tuple[CoachApplicationService, RecordingLocalRetriever]:
    """Build the application path with injected AgentCore and local retrieval."""
    recorder = retriever or RecordingLocalRetriever()
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(
            AgentCoreCoachProvider(
                _RUNTIME_ARN,
                region="us-west-2",
                qualifier="DEFAULT",
                timeout_seconds=110.0,
                max_retries=0,
                client=FakeAgentCoreRuntime(payload=_coaching_payload()),
            ),
            transitions,
        ),
        LearningProgressService(store, notebooks, transitions),
        retriever=recorder,
    )
    return service, recorder


def _submit(
    service: CoachApplicationService,
    thread_id: str,
    *,
    key: str,
    message: str = _SOURCE_QUESTION,
) -> Any:
    """Submit one coaching turn. Defaults to a source-asking message."""
    return service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key=key,
        )
    )


def _notebook(tmp_path: Path) -> tuple[StudentStore, str]:
    """Create an owner-scoped notebook store for hydration tests."""
    store = StudentStore(tmp_path / "hydrate.sqlite3", identifier="cognito:a")
    thread_id = store.create_thread(
        model_id="mock",
        support_mode="critical-thinking",
    )
    return store, thread_id


def _source_ids_from_keys(keys: list[str]) -> set[str]:
    """Return source ids embedded in ``users/.../sources/<id>/...`` object keys."""
    found: set[str] = set()
    for key in keys:
        parts = str(key).replace("\\", "/").split("/")
        try:
            index = parts.index("sources")
        except ValueError:
            continue
        if index + 1 < len(parts):
            found.add(parts[index + 1])
    return found


def _overwrite_chunks_artifact(
    storage: CountingFileStorage,
    *,
    owner_id: str,
    notebook_id: str,
    source_id: str,
    text: str,
    schema_version: int | None = None,
    chunker_version: str | None = None,
    content_digest: str | None = None,
    chunk_text: str | None = None,
) -> str:
    """Replace the stored chunk artifact with a mutated but well-formed JSON body.

    Returns:
        The chunks object key that was overwritten.
    """
    artifact = build_chunk_artifact(source_id=source_id, text=text)
    assert artifact is not None
    payload = artifact.model_dump(mode="json")
    if schema_version is not None:
        payload["schema_version"] = schema_version
    if chunker_version is not None:
        payload["chunker_version"] = chunker_version
    if content_digest is not None:
        payload["content_digest"] = content_digest
    if chunk_text is not None:
        payload["chunks"] = [{"chunk_index": 1, "text": chunk_text}]
    key = build_source_chunks_object_key(
        user_id=owner_id,
        notebook_id=notebook_id,
        source_id=source_id,
    )
    storage.put_bytes(
        key=key,
        data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
    )
    return key


def _capture_prepared(service: CoachApplicationService) -> dict[str, Any]:
    """Wrap ``workflow.run`` so tests can inspect the server-built request."""
    captured: dict[str, Any] = {}
    original = service._workflow.run

    def _run(request: CoachRequest) -> Any:
        captured["request"] = request
        return original(request)

    service._workflow.run = _run  # type: ignore[method-assign]
    return captured


class _FakeKbRetriever:
    """Sequential Knowledge Base stand-in that returns one course chunk."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return one ``knowledge_base`` hit per selected course source."""
        chunks: list[RetrievedChunk] = []
        for index, source in enumerate(query.sources, start=1):
            chunks.append(
                RetrievedChunk(
                    source_id=source.source_id,
                    label=source.label,
                    title=source.title,
                    chunk_id=f"{source.label}-C1",
                    text=(
                        "Course excerpt about accessibility for older pedestrians."
                    ),
                    score=0.9,
                    source_index=index,
                    chunk_index=1,
                    retrieval_origin="knowledge_base",
                )
            )
        context = "\n\n".join(
            f"--- [{chunk.label}] {chunk.title} ---\n{chunk.text}" for chunk in chunks
        )
        return RetrievalResult(context=context, chunks=tuple(chunks))


@pytest.fixture(autouse=True)
def _reset_chunk_cache() -> None:
    """Start each test from an empty student-source chunk cache."""
    reset_student_source_chunk_cache()
    yield
    reset_student_source_chunk_cache()


@pytest.fixture
def counting_storage(monkeypatch: pytest.MonkeyPatch) -> CountingFileStorage:
    """Install in-memory counting storage for one test."""
    storage = CountingFileStorage()
    install_counting_storage(monkeypatch, storage)
    return storage


def test_list_visible_sources_metadata_only_skips_extracted_gets(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    counting_storage.reset_counts()
    metadata_only = list_visible_sources(
        store, thread_id, include_extracted_text=False
    )
    assert counting_storage.gets(kind="extracted") == []
    assert metadata_only
    assert metadata_only[0]["extractedText"] == ""
    counting_storage.reset_counts()
    hydrated = list_visible_sources(store, thread_id, include_extracted_text=True)
    assert counting_storage.gets(kind="extracted")
    assert _ACCESSIBILITY in str(hydrated[0]["extractedText"])


def test_unselected_sources_are_not_content_loaded(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    created = [
        add_text_source(store, thread_id, f"Lecture {label}", f"{_ACCESSIBILITY} {label}.")
        for label in ("A", "B", "C", "D", "E")
    ]
    selected = {created[0]["id"], created[2]["id"]}
    unselected = {created[1]["id"], created[3]["id"], created[4]["id"]}
    for source_id in unselected:
        store.set_source_selected(thread_id, source_id, False)
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    turn = _submit(service, thread_id, key="unselected")
    assert turn.response_text
    content_keys = [
        item.key
        for item in counting_storage.gets(kind="extracted")
        + counting_storage.gets(kind="chunks")
    ]
    loaded = _source_ids_from_keys(content_keys)
    assert loaded <= selected
    assert loaded & unselected == set()
    assert counting_storage.counts().student_chunk_lists == 0


def test_successful_precomputed_path_does_not_get_extracted(
    tmp_path: Path,
    counting_storage: CountingFileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, thread_id = _notebook(tmp_path)
    add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    chunk_calls = {"count": 0}
    original = canonical_chunk_text

    def _counting_chunk_text(
        text: str, *, chunk_chars: int, overlap_chars: int
    ) -> list[str]:
        chunk_calls["count"] += 1
        return original(text, chunk_chars=chunk_chars, overlap_chars=overlap_chars)

    monkeypatch.setattr("backend.retrieval.canonical_chunk_text", _counting_chunk_text)
    counting_storage.reset_counts()
    service, recorder = _service(store)
    _submit(service, thread_id, key="precomputed")
    assert len(counting_storage.gets(kind="chunks")) <= 1
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0
    assert chunk_calls["count"] == 0
    assert recorder.results
    assert recorder.results[0].chunks


def test_cache_hit_skips_storage_and_still_ranks(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    service, recorder = _service(store)
    _submit(service, thread_id, key="cache-miss")
    counting_storage.reset_counts()
    turn = _submit(service, thread_id, key="cache-hit")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0
    assert len(recorder.results) == 2
    assert recorder.results[-1].chunks


def test_legacy_missing_artifact_falls_back_to_extracted(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    source = add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
    )
    counting_storage.delete(chunks_key)
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="legacy-missing")
    assert turn.response_text
    assert len(counting_storage.gets(kind="chunks")) == 1
    assert len(counting_storage.gets(kind="extracted")) == 1
    assert recorder.results
    assert recorder.results[0].chunks


def test_legacy_without_digest_skips_chunks_get(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    source_id = str(uuid.uuid4())
    extracted_key = build_extracted_text_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source_id,
    )
    counting_storage.put_bytes(
        key=extracted_key,
        data=_ACCESSIBILITY.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    store.add_source(
        thread_id,
        kind="text",
        title="Legacy notes",
        mime="text/plain",
        extracted_text_key=extracted_key,
        size=len(_ACCESSIBILITY.encode("utf-8")),
        selected=True,
        metadata={"origin": "pasted_text"},
        source_id=source_id,
    )
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="legacy-no-digest")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert len(counting_storage.gets(kind="extracted")) == 1
    assert recorder.results
    assert recorder.results[0].chunks


def test_corrupt_artifact_falls_back_without_logging_chunk_text(
    tmp_path: Path, counting_storage: CountingFileStorage, caplog: pytest.LogCaptureFixture
) -> None:
    store, thread_id = _notebook(tmp_path)
    source = add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
    )
    counting_storage.put_bytes(
        key=chunks_key,
        data=f"{{not-json {_CHUNK_SECRET}".encode("utf-8"),
        content_type="application/json",
    )
    counting_storage.reset_counts()
    caplog.set_level(logging.INFO)
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="corrupt")
    assert turn.response_text
    assert len(counting_storage.gets(kind="extracted")) == 1
    assert recorder.results
    assert recorder.results[0].chunks
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert _CHUNK_SECRET not in joined


def test_course_only_does_not_get_student_chunk_artifacts(
    tmp_path: Path,
    counting_storage: CountingFileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "course_materials_bucket", "course-test")
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "max_lecture_notes", 50)
    monkeypatch.setattr(settings, "max_course_material_size_mb", 1)
    counting_storage.put_bytes(
        key="course/lectureNotes/week-01.txt",
        data=b"Lecture 1 accessibility notes for older pedestrians.",
        content_type="text/plain",
    )
    store, thread_id = _notebook(tmp_path)
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    turn = _submit(service, thread_id, key="course-only")
    assert turn.response_text
    student_chunk_gets = [
        item
        for item in counting_storage.gets(kind="chunks")
        if str(item.key).replace("\\", "/").startswith("users/")
    ]
    assert student_chunk_gets == []
    assert counting_storage.counts().student_chunk_lists == 0


def test_empty_notebook_has_zero_student_derived_gets(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    turn = _submit(service, thread_id, key="idle-empty")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0


def test_no_selected_student_files_has_zero_student_derived_gets(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    source = add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    store.set_source_selected(thread_id, source["id"], False)
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    turn = _submit(service, thread_id, key="idle-unselected")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0


def test_selected_idle_turn_skips_student_derived_gets(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    counting_storage.reset_counts()
    service, recorder = _service(store)
    idle = _submit(service, thread_id, key="idle-selected", message="thanks")
    assert idle.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0
    assert recorder.calls == []
    counting_storage.reset_counts()
    asked = _submit(service, thread_id, key="source-after-idle")
    assert asked.response_text
    assert len(counting_storage.gets(kind="chunks")) <= 1
    assert counting_storage.gets(kind="extracted") == []
    assert counting_storage.counts().student_chunk_lists == 0
    assert recorder.results
    assert recorder.results[0].chunks


def test_wrong_schema_version_falls_back_to_extracted(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    source = add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    _overwrite_chunks_artifact(
        counting_storage,
        owner_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
        text=_ACCESSIBILITY,
        schema_version=CHUNK_ARTIFACT_SCHEMA_VERSION + 1,
        chunk_text=_STALE_CHUNK,
    )
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="schema-mismatch")
    assert turn.response_text
    assert len(counting_storage.gets(kind="chunks")) == 1
    assert len(counting_storage.gets(kind="extracted")) == 1
    ranked = " ".join(chunk.text for chunk in recorder.results[0].chunks)
    assert "accessibility" in ranked.casefold()
    assert _STALE_CHUNK not in ranked


def test_content_digest_mismatch_ranks_current_extracted(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    source = add_text_source(store, thread_id, "Lecture A", _ACCESSIBILITY)
    _overwrite_chunks_artifact(
        counting_storage,
        owner_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
        text=_ACCESSIBILITY,
        content_digest="0" * 64,
        chunk_text=_STALE_CHUNK,
    )
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="digest-mismatch")
    assert turn.response_text
    assert len(counting_storage.gets(kind="extracted")) == 1
    ranked = " ".join(chunk.text for chunk in recorder.results[0].chunks)
    assert "accessibility" in ranked.casefold()
    assert _STALE_CHUNK not in ranked


def test_source_replacement_does_not_serve_deleted_artifact(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    old = add_text_source(
        store,
        thread_id,
        "Old notes",
        f"{_ACCESSIBILITY} OLD_REPLACED_SOURCE_PHRASE.",
    )
    old_chunks = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=old["id"],
    )
    old_prefix = source_prefix(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=old["id"],
    )
    service, recorder = _service(store)
    _submit(service, thread_id, key="before-replace")
    store.delete_source(thread_id, old["id"])
    assert store.get_source(thread_id, old["id"]) is None
    assert not counting_storage.exists(old_chunks)
    new = add_text_source(
        store,
        thread_id,
        "New notes",
        f"{_ACCESSIBILITY} NEW_REPLACEMENT_SOURCE_PHRASE.",
    )
    counting_storage.reset_counts()
    turn = _submit(service, thread_id, key="after-replace")
    assert turn.response_text
    loaded = _source_ids_from_keys(
        [item.key for item in counting_storage.gets(kind="chunks")]
        + [item.key for item in counting_storage.gets(kind="extracted")]
    )
    assert old["id"] not in loaded
    for item in counting_storage.gets():
        assert not str(item.key).replace("\\", "/").startswith(old_prefix)
    ranked = " ".join(chunk.text for chunk in recorder.results[-1].chunks)
    assert "NEW_REPLACEMENT_SOURCE_PHRASE" in ranked
    assert "OLD_REPLACED_SOURCE_PHRASE" not in ranked
    new_chunks = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=new["id"],
    )
    assert counting_storage.exists(new_chunks)


def test_png_upload_skips_chunk_gets_and_supplies_image_inputs(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    created = add_file_sources(
        store,
        thread_id,
        [("diagram.png", _PNG, "image/png")],
    )
    source = created[0]
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
    )
    assert not counting_storage.exists(chunks_key)
    assert not source.get("extracted_text_key")
    counting_storage.reset_counts()
    service, recorder = _service(store)
    captured = _capture_prepared(service)
    turn = _submit(service, thread_id, key="image-coach")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    assert counting_storage.gets(kind="extracted") == []
    prepared = captured["request"]
    assert prepared.image_inputs
    assert prepared.image_inputs[0].source_id == source["id"]
    ranked = (
        " ".join(chunk.text for chunk in recorder.results[-1].chunks)
        if recorder.results
        else ""
    )
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in ranked


def test_coach_turn_does_not_get_source_per_selected_image(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    """Authorized snapshot images skip per-image metadata lookups."""
    store, thread_id = _notebook(tmp_path)
    created = add_file_sources(
        store,
        thread_id,
        [
            ("diagram.png", _PNG, "image/png"),
            ("notes.txt", b"Accessibility notes.", "text/plain"),
            ("sketch.png", _PNG, "image/png"),
        ],
    )
    image_ids = [
        str(source["id"])
        for source in created
        if str(source.get("kind") or "").lower() == "image"
        or str(source.get("mime") or "").lower().startswith("image/")
    ]
    expected = image_inputs_for_source_ids(store, thread_id, image_ids)
    assert [item["source_id"] for item in expected] == image_ids

    calls = {"get_source": 0}
    original = store.get_source

    def _count(
        thread_id: str,
        source_id: str,
        *,
        include_extracted_text: bool = True,
    ) -> dict[str, Any] | None:
        calls["get_source"] += 1
        return original(
            thread_id,
            source_id,
            include_extracted_text=include_extracted_text,
        )

    store.get_source = _count  # type: ignore[method-assign]
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    captured = _capture_prepared(service)
    turn = _submit(service, thread_id, key="image-no-nplus1")
    assert turn.response_text
    assert calls["get_source"] == 0
    prepared = captured["request"]
    actual = [
        {
            "source_id": item.source_id,
            "mime": item.mime,
            "data_url": item.data_url,
        }
        for item in prepared.image_inputs
    ]
    assert actual == expected


def test_more_than_five_selected_images_are_rejected(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    """The max-5 selected-image rule still runs before image bytes are read."""
    store, thread_id = _notebook(tmp_path)
    add_file_sources(
        store,
        thread_id,
        [(f"img{index}.png", _PNG, "image/png") for index in range(5)],
    )
    add_file_sources(
        store,
        thread_id,
        [("img5.png", _PNG, "image/png")],
    )
    counting_storage.reset_counts()
    service, _recorder = _service(store)
    with pytest.raises(ValueError, match="Select at most 5 image sources"):
        _submit(service, thread_id, key="too-many-images")
    assert counting_storage.gets(kind="raw") == []


def test_empty_extract_is_placeholder_and_not_ranked(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    created = add_file_sources(
        store,
        thread_id,
        [("empty.txt", b"", "text/plain")],
    )
    source = created[0]
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
    )
    assert not counting_storage.exists(chunks_key)
    assert not (source.get("metadata") or {}).get("extracted_text_sha256")
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="empty-extract")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    if recorder.results:
        ranked = " ".join(chunk.text for chunk in recorder.results[-1].chunks)
        assert UNANALYZABLE_SOURCE_PLACEHOLDER not in ranked


def test_unsupported_file_is_placeholder_and_not_ranked(
    tmp_path: Path, counting_storage: CountingFileStorage
) -> None:
    store, thread_id = _notebook(tmp_path)
    created = add_file_sources(
        store,
        thread_id,
        [("notes.xyz", b"not-a-supported-document", "application/octet-stream")],
    )
    source = created[0]
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=thread_id,
        source_id=source["id"],
    )
    assert not counting_storage.exists(chunks_key)
    counting_storage.reset_counts()
    service, recorder = _service(store)
    turn = _submit(service, thread_id, key="unsupported")
    assert turn.response_text
    assert counting_storage.gets(kind="chunks") == []
    if recorder.results:
        ranked = " ".join(chunk.text for chunk in recorder.results[-1].chunks)
        assert UNANALYZABLE_SOURCE_PLACEHOLDER not in ranked
        assert "not-a-supported-document" not in ranked


def test_mixed_course_and_student_skips_course_chunk_get(
    tmp_path: Path,
    counting_storage: CountingFileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "course_materials_bucket", "course-test")
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "max_lecture_notes", 50)
    monkeypatch.setattr(settings, "max_course_material_size_mb", 1)
    counting_storage.put_bytes(
        key="course/lectureNotes/week-01.txt",
        data=b"Lecture 1 accessibility notes for older pedestrians.",
        content_type="text/plain",
    )
    store, thread_id = _notebook(tmp_path)
    student = add_text_source(store, thread_id, "My notes", _ACCESSIBILITY)
    local = RecordingLocalRetriever()
    composite = CompositeContextRetriever(
        knowledge_base=_FakeKbRetriever(),
        local=local,
    )
    counting_storage.reset_counts()
    service, _recorder = _service(store, retriever=composite)
    captured = _capture_prepared(service)
    turn = _submit(service, thread_id, key="mixed")
    assert turn.response_text
    student_chunk_gets = [
        item
        for item in counting_storage.gets(kind="chunks")
        if str(item.key).replace("\\", "/").startswith("users/")
    ]
    course_chunk_gets = [
        item
        for item in counting_storage.gets(kind="chunks")
        if str(item.key).replace("\\", "/").startswith("course/")
    ]
    assert course_chunk_gets == []
    assert len(student_chunk_gets) <= 1
    loaded = _source_ids_from_keys([item.key for item in student_chunk_gets])
    assert loaded <= {student["id"]}
    prepared = captured["request"]
    labels = {chunk.label for chunk in prepared.retrieved_chunks}
    origins = {str(chunk.retrieval_origin or "") for chunk in prepared.retrieved_chunks}
    assert labels <= {"S1", "S2"}
    assert labels
    assert "knowledge_base" in origins or bool(local.results)
    assert len(prepared.source_context) <= int(settings.fast_chat_retrieval_max_chars)
    assert counting_storage.counts().student_chunk_lists == 0
