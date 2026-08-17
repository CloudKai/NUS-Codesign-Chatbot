"""Unit tests for derived source chunk artifacts and upload wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.persistence.factory import get_file_storage
from backend.persistence.object_keys import build_source_chunks_object_key
from backend.retrieval import (
    CompositeContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    _chunk_text,
    canonical_chunk_text,
)
from backend.source_library import add_file_sources
from pydantic import ValidationError

from backend.sources.chunk_artifacts import (
    CHUNK_ARTIFACT_SCHEMA_VERSION,
    CHUNKER_VERSION,
    MAX_ARTIFACT_BYTES,
    SourceChunkArtifact,
    build_chunk_artifact,
    chunk_texts,
    extracted_text_digest,
    parse_chunk_artifact,
    serialize_chunk_artifact,
)
from backend.student_store import StudentStore

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_MULTI_CHUNK_TEXT = ("design thinking research evidence. " * 80).strip()


def _notebook(tmp_path: Path) -> tuple[StudentStore, str]:
    """Create an isolated notebook store for upload tests."""
    store = StudentStore(tmp_path / "student.sqlite3", identifier="chunk-student")
    notebook_id = store.create_thread(
        model_id="gpt-5.4-mini",
        support_mode="critical-thinking",
    )
    return store, notebook_id


def test_chunk_text_alias_is_canonical_chunker() -> None:
    assert _chunk_text is canonical_chunk_text


def test_build_chunk_artifact_matches_canonical_chunk_boundaries() -> None:
    expected = canonical_chunk_text(
        _MULTI_CHUNK_TEXT, chunk_chars=1800, overlap_chars=220
    )
    artifact = build_chunk_artifact(source_id="src-1", text=_MULTI_CHUNK_TEXT)
    assert artifact is not None
    assert expected
    assert list(chunk_texts(artifact)) == expected
    assert artifact.chunk_chars == 1800
    assert artifact.overlap_chars == 220
    assert artifact.schema_version == CHUNK_ARTIFACT_SCHEMA_VERSION
    assert artifact.chunker_version == CHUNKER_VERSION


def test_serialize_parse_round_trip() -> None:
    artifact = build_chunk_artifact(source_id="src-round", text=_MULTI_CHUNK_TEXT)
    assert artifact is not None
    raw = serialize_chunk_artifact(artifact)
    assert raw
    parsed = parse_chunk_artifact(
        raw,
        expected_source_id="src-round",
        expected_digest=extracted_text_digest(_MULTI_CHUNK_TEXT),
    )
    assert parsed == artifact


def _encode(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_parse_returns_none_for_invalid_json() -> None:
    assert (
        parse_chunk_artifact(
            b"{not-json",
            expected_source_id="src-1",
            expected_digest="abc",
        )
        is None
    )


def test_parse_returns_none_for_wrong_schema_version() -> None:
    artifact = build_chunk_artifact(source_id="src-1", text="short evidence")
    assert artifact is not None
    payload = artifact.model_dump(mode="json")
    payload["schema_version"] = CHUNK_ARTIFACT_SCHEMA_VERSION + 1
    assert (
        parse_chunk_artifact(
            _encode(payload),
            expected_source_id="src-1",
            expected_digest=artifact.content_digest,
        )
        is None
    )


def test_parse_returns_none_for_wrong_chunker_version() -> None:
    artifact = build_chunk_artifact(source_id="src-1", text="short evidence")
    assert artifact is not None
    payload = artifact.model_dump(mode="json")
    payload["chunker_version"] = "other_chunker"
    assert (
        parse_chunk_artifact(
            _encode(payload),
            expected_source_id="src-1",
            expected_digest=artifact.content_digest,
        )
        is None
    )


def test_parse_returns_none_for_wrong_source_id() -> None:
    artifact = build_chunk_artifact(source_id="src-1", text="short evidence")
    assert artifact is not None
    raw = serialize_chunk_artifact(artifact)
    assert (
        parse_chunk_artifact(
            raw,
            expected_source_id="other-source",
            expected_digest=artifact.content_digest,
        )
        is None
    )


def test_parse_returns_none_for_wrong_digest() -> None:
    artifact = build_chunk_artifact(source_id="src-1", text="short evidence")
    assert artifact is not None
    raw = serialize_chunk_artifact(artifact)
    assert (
        parse_chunk_artifact(
            raw,
            expected_source_id="src-1",
            expected_digest="0" * 64,
        )
        is None
    )


def test_parse_returns_none_for_oversize_payload() -> None:
    raw = b"x" * (MAX_ARTIFACT_BYTES + 1)
    assert (
        parse_chunk_artifact(
            raw,
            expected_source_id="src-1",
            expected_digest="abc",
        )
        is None
    )


def test_text_upload_stores_extracted_text_chunks_and_digest(tmp_path: Path) -> None:
    store, notebook_id = _notebook(tmp_path)
    body = b"Evidence from the study about pedestrian crossings."
    created = add_file_sources(
        store,
        notebook_id,
        [("evidence.txt", body, "text/plain")],
    )
    assert len(created) == 1
    source = created[0]
    extracted = str(source["extractedText"])
    assert extracted
    digest = extracted_text_digest(extracted)
    assert source["extracted_text_key"]
    assert "/derived/extracted.txt" in source["extracted_text_key"]
    assert (source.get("metadata") or {}).get("extracted_text_sha256") == digest
    storage = get_file_storage()
    assert storage.get_bytes(source["extracted_text_key"]) == extracted.encode("utf-8")
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source["id"],
    )
    raw = storage.get_bytes(chunks_key)
    parsed = parse_chunk_artifact(
        raw,
        expected_source_id=source["id"],
        expected_digest=digest,
    )
    assert parsed is not None
    assert parsed.content_digest == digest


def test_image_upload_stores_neither_artifact_nor_digest(tmp_path: Path) -> None:
    store, notebook_id = _notebook(tmp_path)
    created = add_file_sources(
        store,
        notebook_id,
        [("diagram.png", _PNG, "image/png")],
    )
    assert len(created) == 1
    source = created[0]
    assert not source.get("extracted_text_key")
    assert "extracted_text_sha256" not in (source.get("metadata") or {})
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source["id"],
    )
    assert not get_file_storage().exists(chunks_key)


def test_chunk_put_failure_does_not_fail_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, notebook_id = _notebook(tmp_path)
    storage = get_file_storage()
    original_put = storage.put_bytes

    def put_bytes(
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> object:
        if str(key).endswith("/derived/chunks.v1.json"):
            raise OSError("simulated chunk write failure")
        return original_put(key=key, data=data, content_type=content_type)

    monkeypatch.setattr(storage, "put_bytes", put_bytes)
    created = add_file_sources(
        store,
        notebook_id,
        [("notes.txt", b"Usable extracted notes.", "text/plain")],
    )
    assert len(created) == 1
    source = store.get_source(notebook_id, created[0]["id"])
    assert source is not None
    assert source["extractedText"] == "Usable extracted notes."
    assert source["extracted_text_key"]
    assert get_file_storage().exists(source["extracted_text_key"])
    chunks_key = build_source_chunks_object_key(
        user_id=store.owner_id,
        notebook_id=notebook_id,
        source_id=source["id"],
    )
    assert not get_file_storage().exists(chunks_key)


def test_retriever_uses_precomputed_chunks_without_chunking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
        raise AssertionError("canonical_chunk_text should not run")

    monkeypatch.setattr("backend.retrieval.canonical_chunk_text", boom)
    retriever = LocalChunkRetriever()
    source = RetrievalSource(
        source_id="src-pre",
        label="S1",
        title="Notes",
        text="this text would be chunked if the fallback path ran",
        chunks=("precomputed one", "precomputed two"),
    )
    candidates = retriever._candidates([source])
    assert [item.text for item in candidates] == ["precomputed one", "precomputed two"]
    assert [item.chunk_index for item in candidates] == [1, 2]


def test_retriever_empty_precomputed_chunks_contribute_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
        raise AssertionError("canonical_chunk_text should not run")

    monkeypatch.setattr("backend.retrieval.canonical_chunk_text", boom)
    retriever = LocalChunkRetriever()
    source = RetrievalSource(
        source_id="src-empty",
        label="S1",
        title="Notes",
        text="fallback text",
        chunks=(),
    )
    assert retriever._candidates([source]) == []


def test_source_chunk_artifact_rejects_out_of_order_indexes() -> None:
    with pytest.raises(ValidationError):
        SourceChunkArtifact(
            schema_version=CHUNK_ARTIFACT_SCHEMA_VERSION,
            chunker_version=CHUNKER_VERSION,
            source_id="src-1",
            content_digest=extracted_text_digest("abc"),
            chunk_chars=1800,
            overlap_chars=220,
            chunks=(
                {"chunk_index": 2, "text": "second"},
                {"chunk_index": 1, "text": "first"},
            ),
        )


def _source(
    source_id: str,
    label: str,
    title: str,
    text: str,
    *,
    chunks: tuple[str, ...] | None = None,
) -> RetrievalSource:
    """Build one retrieval source, optionally with precomputed chunk texts."""
    return RetrievalSource(
        source_id=source_id,
        label=label,
        title=title,
        text=text,
        chunks=chunks,
    )


def test_precomputed_and_dynamic_chunks_rank_equivalently() -> None:
    """Same text+query: dynamic ``chunks=None`` vs precomputed canonical chunks.

    Uses LocalChunkRetriever defaults (max_chunks=8, max_chunks_per_source=2,
    max_context_chars=16_000), not the Fast Chat 4/8k post-bound.
    """
    text = (
        "Lecture notes on accessibility explain that older pedestrians need "
        "longer crossing times, audible signals, and step-free kerb design. "
        + ("design thinking research evidence. " * 80)
    )
    expected = canonical_chunk_text(text, chunk_chars=1800, overlap_chars=220)
    retriever = LocalChunkRetriever()
    message = "What does the lecture say about accessibility?"
    dynamic = retriever.retrieve(
        RetrievalQuery(
            current_message=message,
            current_stage="problem_identification",
            sources=(_source("src-eq", "S1", "Lecture notes", text, chunks=None),),
        )
    )
    precomputed = retriever.retrieve(
        RetrievalQuery(
            current_message=message,
            current_stage="problem_identification",
            sources=(
                _source(
                    "src-eq",
                    "S1",
                    "Lecture notes",
                    text,
                    chunks=tuple(expected),
                ),
            ),
        )
    )
    assert [chunk.chunk_index for chunk in dynamic.chunks] == [
        chunk.chunk_index for chunk in precomputed.chunks
    ]
    assert [chunk.title for chunk in dynamic.chunks] == [
        chunk.title for chunk in precomputed.chunks
    ]
    assert [chunk.label for chunk in dynamic.chunks] == [
        chunk.label for chunk in precomputed.chunks
    ]
    assert [chunk.text for chunk in dynamic.chunks] == [
        chunk.text for chunk in precomputed.chunks
    ]
    assert dynamic.context == precomputed.context
    assert len(dynamic.context) <= retriever.max_context_chars


def test_precomputed_generic_query_uses_bounded_representative_fallback() -> None:
    """Twin of the dynamic generic-query fallback, using precomputed chunks."""
    sources = tuple(
        _source(
            f"source-{index}",
            f"S{index}",
            f"Document {index}",
            (f"Distinct document {index} content. " * 100),
            chunks=tuple(
                canonical_chunk_text(
                    f"Distinct document {index} content. " * 100,
                    chunk_chars=500,
                    overlap_chars=50,
                )
            ),
        )
        for index in range(1, 5)
    )
    result = LocalChunkRetriever(
        chunk_chars=500,
        overlap_chars=50,
        max_chunks=2,
        max_chunks_per_source=1,
        max_context_chars=1_500,
    ).retrieve(
        RetrievalQuery(
            current_message="What do these sources say?",
            current_stage="problem_identification",
            sources=sources,
        )
    )
    assert len(result.chunks) == 2
    assert len({chunk.source_id for chunk in result.chunks}) == 2
    assert len(result.context) <= 1_500


def test_precomputed_path_honors_max_chunks_per_source() -> None:
    """Diversity cap applies when candidates come from precomputed artifacts."""
    survey = "Older adults reported insufficient crossing time in the survey. " * 40
    audit = (
        "The crossing audit measured insufficient signal timing for older adults. "
        * 40
    )
    sources = (
        _source(
            "survey",
            "S1",
            "Survey",
            survey,
            chunks=tuple(
                canonical_chunk_text(survey, chunk_chars=400, overlap_chars=40)
            ),
        ),
        _source(
            "audit",
            "S2",
            "Street audit",
            audit,
            chunks=tuple(
                canonical_chunk_text(audit, chunk_chars=400, overlap_chars=40)
            ),
        ),
    )
    result = LocalChunkRetriever(
        chunk_chars=400,
        overlap_chars=40,
        max_chunks=4,
        max_chunks_per_source=1,
    ).retrieve(
        RetrievalQuery(
            current_message="What evidence concerns crossing time for older adults?",
            current_stage="concept_generation",
            sources=sources,
        )
    )
    counts: dict[str, int] = {}
    for chunk in result.chunks:
        counts[chunk.source_id] = counts.get(chunk.source_id, 0) + 1
        assert counts[chunk.source_id] <= 1
    assert set(counts) == {"survey", "audit"}
    assert {chunk.label for chunk in result.chunks} == {"S1", "S2"}


class _FakeCourseRetriever:
    """Sequential Knowledge Base stand-in that returns one course chunk."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return one ``knowledge_base`` hit for the first selected course source."""
        source = query.sources[0]
        chunk = RetrievedChunk(
            source_id=source.source_id,
            label=source.label,
            title=source.title,
            chunk_id=f"{source.label}-C1",
            text="Week 1 course excerpt about innovation.",
            score=0.91,
            source_index=1,
            chunk_index=1,
            retrieval_origin="knowledge_base",
        )
        return RetrievalResult(
            context=f"--- [{source.label}] {source.title} --- {chunk.text}",
            chunks=(chunk,),
        )


def test_mixed_course_kb_and_precomputed_student_chunks() -> None:
    """Course hits stay on the KB adapter; student hits use local artifacts.

    Sequential CompositeContextRetriever only. Combined bound is the retriever
    default (16_000 chars).
    """
    student_text = "I observed older pedestrians waiting at the school gate."
    artifact = build_chunk_artifact(source_id="upload-1", text=student_text)
    assert artifact is not None
    student = RetrievalSource(
        source_id="upload-1",
        label="S2",
        title="My notes",
        text=student_text,
        object_key="users/student/notebook/notes.txt",
        chunks=chunk_texts(artifact),
    )
    course = RetrievalSource(
        source_id="virtual-week-1",
        label="S1",
        title="Week 1 Introduction to innovation v3.pdf",
        text="",
        group="Lecture Notes",
        object_key="course/lectureNotes/Week 1 Introduction to innovation v3.pdf",
        virtual_course_source=True,
        shared_course_object=True,
    )
    result = CompositeContextRetriever(
        knowledge_base=_FakeCourseRetriever(),
        local=LocalChunkRetriever(chunk_chars=500, overlap_chars=80, max_chunks=3),
    ).retrieve(
        RetrievalQuery(
            current_message=(
                "what are the week 1 contents talking about at the school gate?"
            ),
            current_stage="problem_identification",
            sources=(course, student),
        )
    )
    labels = {chunk.label for chunk in result.chunks}
    origins = {chunk.retrieval_origin for chunk in result.chunks}
    assert labels == {"S1", "S2"}
    assert "knowledge_base" in origins
    assert "extracted_text" in origins
    assert "Week 1 course excerpt" in result.context
    assert "school gate" in result.context
    assert len(result.context) <= 16_000
