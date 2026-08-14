"""Deterministic Bedrock Retrieve adapter tests (no AWS or paid calls)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.bedrock_retrieve import (
    BedrockKnowledgeBaseRetriever,
    configured_context_retriever,
)
from backend.retrieval import (
    CompositeContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalSource,
)
from backend.settings import settings


class FakeRetrieveClient:
    """Injected bedrock-agent-runtime client that records Retrieve calls."""

    def __init__(
        self,
        *,
        results: list[dict[str, Any]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = results or []
        self._error = error

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        """Record one Retrieve invocation and return fake hits."""
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"retrievalResults": list(self._results)}


def _course_source(
    source_id: str,
    label: str,
    *,
    object_key: str,
    title: str = "Lecture",
) -> RetrievalSource:
    """Return one locked course retrieval source."""
    return RetrievalSource(
        source_id=source_id,
        label=label,
        title=title,
        text="Local extracted course text should not be required for KB hits.",
        group="lectureNotes",
        object_key=object_key,
    )


def _upload_source() -> RetrievalSource:
    """Return one student-upload source that must stay on the local retriever."""
    return RetrievalSource(
        source_id="upload-1",
        label="S2",
        title="My crossing notes",
        text=(
            "Older pedestrians need a longer crossing interval at low-light "
            "junctions near the school gate."
        ),
        object_key="users/student/notebook/notes.txt",
    )


def _hit(uri: str, text: str, *, score: float = 0.9) -> dict[str, Any]:
    """Return one Retrieve result shaped like bedrock-agent-runtime."""
    return {
        "content": {"text": text},
        "location": {"type": "S3", "s3Location": {"uri": uri}},
        "score": score,
    }


def _query(*sources: RetrievalSource) -> RetrievalQuery:
    """Build a retrieval query over the given selected sources."""
    return RetrievalQuery(
        current_message="What crossing time do older pedestrians need?",
        current_stage="problem_identification",
        sources=sources,
    )


def test_retrieve_maps_selected_course_keys_to_stable_labels():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "Older adults need longer signal time [course].",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert len(client.calls) == 1
    assert client.calls[0]["knowledgeBaseId"] == "JUQNP8AZAZ"
    assert "RetrieveAndGenerate" not in str(client.calls[0])
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.source_id == "src-lecture"
    assert chunk.label == "S1"
    assert chunk.chunk_id == "S1-KB1"
    assert "longer signal time" in chunk.text
    assert "[S1]" in result.context or "S1" in result.context


def test_retrieve_drops_foreign_and_unselected_course_keys():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://other-bucket/course/lectureNotes/secret.pdf",
                "Foreign bucket excerpt.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/course/readings/unselected.pdf",
                "Unselected reading excerpt.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "Selected lecture excerpt.",
            ),
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert [chunk.text for chunk in result.chunks] == ["Selected lecture excerpt."]
    assert "Foreign bucket" not in result.context
    assert "Unselected reading" not in result.context


def test_retrieve_failures_return_empty_instead_of_inventing_sources():
    client = FakeRetrieveClient(error=RuntimeError("aws-error"))
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ", client=client
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert result.chunks == ()
    assert result.context == ""


def test_composite_keeps_student_uploads_on_local_retriever():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "KB lecture excerpt about signal timing.",
            )
        ]
    )
    retriever = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(chunk_chars=500, overlap_chars=80, max_chunks=3),
    )
    result = retriever.retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            ),
            _upload_source(),
        )
    )
    labels = {chunk.label for chunk in result.chunks}
    assert "S1" in labels
    assert "S2" in labels
    assert "KB lecture excerpt" in result.context
    assert "school gate" in result.context
    assert len(client.calls) == 1


def test_configured_retriever_stays_local_in_mock_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "model_provider", "mock")
    monkeypatch.setattr(settings, "mock_openai", True)
    retriever = configured_context_retriever()
    assert isinstance(retriever, LocalChunkRetriever)


def test_configured_retriever_uses_composite_when_live_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "mock_openai", False)
    monkeypatch.setattr(settings, "course_materials_bucket", "cde2300-course-content-s3")
    retriever = configured_context_retriever(client=FakeRetrieveClient(results=[]))
    assert isinstance(retriever, CompositeContextRetriever)
