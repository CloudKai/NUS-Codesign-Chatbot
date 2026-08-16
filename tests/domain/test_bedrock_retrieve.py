"""Deterministic Bedrock Retrieve adapter tests (no AWS or paid calls)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from backend.bedrock_retrieve import (
    BedrockKnowledgeBaseRetriever,
    classify_retrieve_failure,
    configured_context_retriever,
    sanitized_s3_uri,
)
from backend.retrieval import (
    CompositeContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalSource,
    UNANALYZABLE_SOURCE_PLACEHOLDER,
    COURSE_RETRIEVAL_EMPTY_CONTEXT,
    COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
    course_material_id_from_object_key,
    expand_session_query_text,
)
from backend.settings import settings


class FakeRetrieveClient:
    """Injected bedrock-agent-runtime client that records Retrieve calls."""

    def __init__(
        self,
        *,
        results: list[dict[str, Any]] | None = None,
        results_sequence: list[list[dict[str, Any]]] | None = None,
        error: BaseException | None = None,
        errors_sequence: list[BaseException | None] | None = None,
        raw_response: Any | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = results or []
        self._results_sequence = results_sequence
        self._error = error
        self._errors_sequence = errors_sequence
        self._raw_response = raw_response

    def retrieve(self, **kwargs: Any) -> Any:
        """Record one Retrieve invocation and return fake hits or raise."""
        self.calls.append(kwargs)
        if self._errors_sequence is not None:
            index = min(len(self.calls) - 1, len(self._errors_sequence) - 1)
            error = self._errors_sequence[index]
            if error is not None:
                raise error
        elif self._error is not None:
            raise self._error
        if self._raw_response is not None:
            return self._raw_response
        if self._results_sequence is not None:
            index = min(len(self.calls) - 1, len(self._results_sequence) - 1)
            return {"retrievalResults": list(self._results_sequence[index])}
        return {"retrievalResults": list(self._results)}


def _aws_error(code: str, *, name: str | None = None) -> Exception:
    """Return a ClientError-shaped exception with a secret-safe error code."""
    class_name = name or code
    error_type = type(class_name, (Exception,), {})
    exc = error_type(code)
    exc.response = {"Error": {"Code": code, "Message": "synthetic"}}
    return exc


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


def test_retrieve_expands_lecture_number_to_week_phrasing():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/week1.pdf",
                "Introduction to innovation.",
            )
        ]
    )
    BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
    ).retrieve(
        RetrievalQuery(
            current_message="what is lecture 1 about",
            current_stage="problem_identification",
            sources=(
                _course_source(
                    "src-week-1",
                    "S1",
                    object_key="course/lectureNotes/week1.pdf",
                ),
            ),
        )
    )
    assert client.calls[0]["retrievalQuery"]["text"] == (
        "what is lecture 1 about week 1"
    )


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
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "client_error"


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


def test_configured_retriever_is_composite_without_local_course_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "model_provider", "mock")
    monkeypatch.setattr(settings, "mock_openai", True)
    retriever = configured_context_retriever()
    assert isinstance(retriever, CompositeContextRetriever)
    assert retriever._knowledge_base is None


def test_configured_retriever_uses_composite_when_live_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "mock_openai", False)
    monkeypatch.setattr(settings, "course_materials_bucket", "cde2300-course-content-s3")
    retriever = configured_context_retriever(client=FakeRetrieveClient(results=[]))
    assert isinstance(retriever, CompositeContextRetriever)


def test_retrieve_sends_course_material_id_metadata_filter():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "Selected lecture excerpt.",
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
    vector = client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert vector["filter"] == {
        "equals": {"key": "course_material_id", "value": "lecture_crossing"}
    }
    assert result.chunks[0].retrieval_origin == "knowledge_base"


def test_retrieve_falls_back_without_filter_then_post_validates():
    client = FakeRetrieveClient(
        results_sequence=[
            [],
            [
                _hit(
                    "s3://cde2300-course-content-s3/course/readings/unselected.pdf",
                    "Unselected reading excerpt.",
                ),
                _hit(
                    "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                    "Selected lecture excerpt after fallback.",
                ),
            ],
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
    assert len(client.calls) == 2
    first_filter = client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    second_filter = client.calls[1]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert "filter" in first_filter
    assert "filter" not in second_filter
    assert [chunk.text for chunk in result.chunks] == [
        "Selected lecture excerpt after fallback."
    ]
    assert "Unselected reading" not in result.context


def test_composite_course_only_does_not_require_student_retriever():
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
            )
        )
    )
    assert len(client.calls) == 1
    assert [chunk.label for chunk in result.chunks] == ["S1"]
    assert "school gate" not in result.context
    assert result.chunks[0].retrieval_origin == "knowledge_base"


def test_composite_student_only_does_not_call_knowledge_base():
    client = FakeRetrieveClient(results=[_hit("s3://unused/course/x.pdf", "secret")])
    retriever = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(chunk_chars=500, overlap_chars=80, max_chunks=3),
    )
    result = retriever.retrieve(_query(_upload_source()))
    assert client.calls == []
    assert [chunk.label for chunk in result.chunks] == ["S2"]
    assert all(chunk.retrieval_origin == "extracted_text" for chunk in result.chunks)
    assert "school gate" in result.context
    assert "secret" not in result.context


def test_retrieve_rejects_suffix_overlapping_unselected_keys():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/readings/week1.pdf",
                "Selected week1 excerpt.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/course/readings/archive/week1.pdf",
                "Archive week1 must not match by suffix.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/course/readings/myweek1.pdf",
                "myweek1 must not match week1.pdf.",
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
                "src-reading",
                "S1",
                object_key="course/readings/week1.pdf",
                title="Week 1",
            )
        )
    )
    assert [chunk.text for chunk in result.chunks] == ["Selected week1 excerpt."]
    assert "Archive week1" not in result.context
    assert "myweek1" not in result.context


def test_strict_metadata_filter_does_not_retry_unfiltered(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "knowledge_base_strict_metadata_filter", True)
    client = FakeRetrieveClient(results=[])
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
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
    assert result.chunks == ()
    assert result.context == ""
    assert result.course_retrieval_status == "empty"


_WEEK1_KEY = (
    "course/lectureNotes/Week 1 Introduction to innovation v3.pdf"
)
_WEEK1_TITLE = "Week 1 Introduction to innovation v3.pdf"


def _virtual_week1_source() -> RetrievalSource:
    """Return the shared Week 1 catalog source with empty extracted text."""
    return RetrievalSource(
        source_id="virtual-week-1",
        label="S1",
        title=_WEEK1_TITLE,
        text="",
        group="lectureNotes",
        object_key=_WEEK1_KEY,
        course_material_id=course_material_id_from_object_key(_WEEK1_KEY),
        virtual_course_source=True,
        shared_course_object=True,
    )


def test_virtual_week1_kb_hit_reaches_context():
    client = FakeRetrieveClient(
        results=[
            _hit(
                f"s3://cde2300-course-content-s3/{_WEEK1_KEY}",
                "Week 1 introduces innovation as a process of identifying jobs to be done.",
            )
        ]
    )
    result = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.course_retrieval_status == "ok"
    assert result.chunks
    assert result.chunks[0].text.startswith("Week 1 introduces innovation")
    assert result.chunks[0].retrieval_origin == "knowledge_base"
    assert result.chunks[0].label == "S1"
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context
    vector = client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert vector["filter"] == {
        "equals": {
            "key": "course_material_id",
            "value": "lecture_week_1_introduction_to_innovation_v3",
        }
    }
    query_text = client.calls[0]["retrievalQuery"]["text"]
    assert "week 1" in query_text.casefold()
    assert "lecture 1" in query_text.casefold()


def test_virtual_week1_without_kb_is_evidence_gap():
    result = CompositeContextRetriever(
        knowledge_base=None,
        local=LocalChunkRetriever(),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "config_missing"
    assert COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT in result.context
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context


def test_virtual_week1_kb_zero_results_does_not_use_local_placeholder():
    client = FakeRetrieveClient(results=[])
    result = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "empty"
    assert COURSE_RETRIEVAL_EMPTY_CONTEXT in result.context
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context
    assert len(client.calls) == 2


def test_virtual_week1_access_denied_does_not_use_local_placeholder():
    client = FakeRetrieveClient(error=_aws_error("AccessDeniedException"))
    result = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "access_denied"
    assert COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT in result.context
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context


def test_mixed_course_kb_and_student_local_chunks():
    client = FakeRetrieveClient(
        results=[
            _hit(
                f"s3://cde2300-course-content-s3/{_WEEK1_KEY}",
                "Week 1 course excerpt about innovation.",
            )
        ]
    )
    student = RetrievalSource(
        source_id="upload-1",
        label="S2",
        title="My notes",
        text="I observed older pedestrians waiting at the school gate.",
        object_key="users/student/notebook/notes.txt",
    )
    result = CompositeContextRetriever(
        knowledge_base=BedrockKnowledgeBaseRetriever(
            "JUQNP8AZAZ",
            course_bucket="cde2300-course-content-s3",
            client=client,
        ),
        local=LocalChunkRetriever(chunk_chars=500, overlap_chars=80, max_chunks=3),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about at the school gate?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(), student),
        )
    )
    labels = {chunk.label for chunk in result.chunks}
    origins = {chunk.retrieval_origin for chunk in result.chunks}
    assert labels == {"S1", "S2"}
    assert "knowledge_base" in origins
    assert "extracted_text" in origins
    assert "Week 1 course excerpt" in result.context
    assert "school gate" in result.context
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context


def test_lecture_query_targets_week_one_source():
    expanded = expand_session_query_text("what are lecture 1 slides about?")
    assert "week 1" in expanded
    client = FakeRetrieveClient(
        results=[
            _hit(
                f"s3://cde2300-course-content-s3/{_WEEK1_KEY}",
                "Lecture 1 / Week 1 slides introduce innovation.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
    ).retrieve(
        RetrievalQuery(
            current_message="what are lecture 1 slides about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert "week 1" in client.calls[0]["retrievalQuery"]["text"].casefold()
    assert result.chunks[0].title == _WEEK1_TITLE


def test_glued_week_and_lecture_queries_expand():
    assert "week 1" in expand_session_query_text("week1")
    assert "lecture 1" in expand_session_query_text("week1")
    assert "week 1" in expand_session_query_text("lecture01")
    assert "lecture 1" in expand_session_query_text("lecture01")


def test_week1_intro_pdf_rejects_similar_object_keys():
    client = FakeRetrieveClient(
        results=[
            _hit(
                f"s3://cde2300-course-content-s3/{_WEEK1_KEY}",
                "Canonical Week 1 excerpt.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/archive/Week 1 Introduction to innovation v3.pdf",
                "Archive Week 1 must not match.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/myWeek 1 Introduction to innovation v3.pdf",
                "Prefix Week 1 must not match.",
            ),
            _hit(
                "s3://cde2300-course-content-s3/another-folder/Week 1 Introduction to innovation v3.pdf",
                "Other folder Week 1 must not match.",
            ),
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert [chunk.text for chunk in result.chunks] == ["Canonical Week 1 excerpt."]
    assert "Archive Week 1" not in result.context
    assert "Prefix Week 1" not in result.context
    assert "Other folder" not in result.context


def test_configured_retriever_empty_kb_id_stays_composite(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "")
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "mock_openai", False)
    retriever = configured_context_retriever()
    assert isinstance(retriever, CompositeContextRetriever)
    assert retriever._knowledge_base is None
    result = retriever.retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "config_missing"
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context


def test_classify_retrieve_failure_categories():
    assert classify_retrieve_failure(_aws_error("AccessDeniedException")) == "access_denied"
    assert classify_retrieve_failure(_aws_error("UnauthorizedException")) == "access_denied"
    assert classify_retrieve_failure(_aws_error("ResourceNotFoundException")) == "not_found"
    assert classify_retrieve_failure(_aws_error("ValidationException")) == "validation_error"
    assert classify_retrieve_failure(_aws_error("ThrottlingException")) == "throttled"
    timeout = type("ReadTimeoutError", (Exception,), {})("timed out")
    assert classify_retrieve_failure(timeout) == "timeout"
    assert classify_retrieve_failure(RuntimeError("boom")) == "client_error"


def test_retrieve_missing_kb_id_is_config_missing():
    result = BedrockKnowledgeBaseRetriever("").retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "config_missing"


def test_retrieve_boto_client_unavailable():
    retriever = BedrockKnowledgeBaseRetriever("JUQNP8AZAZ")
    retriever._runtime_client = lambda: None  # type: ignore[method-assign]
    result = retriever.retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "client_error"


def test_runtime_client_bounds_retrieve_wait_and_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
):
    import boto3
    import botocore.config

    observed: dict[str, Any] = {}
    sentinel = object()

    class FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            observed["config"] = kwargs

    def fake_client(service: str, *, region_name: str, config: Any) -> object:
        observed.update(
            {"service": service, "region_name": region_name, "client_config": config}
        )
        return sentinel

    monkeypatch.setattr(botocore.config, "Config", FakeConfig)
    monkeypatch.setattr(boto3, "client", fake_client)

    retriever = BedrockKnowledgeBaseRetriever("JUQNP8AZAZ", region="us-west-2")
    assert retriever._runtime_client() is sentinel
    assert observed["service"] == "bedrock-agent-runtime"
    assert observed["region_name"] == "us-west-2"
    assert observed["config"] == {
        "retries": {"total_max_attempts": 1, "mode": "standard"},
        "read_timeout": 15.0,
        "connect_timeout": 3.0,
    }


def test_retrieve_access_denied_is_unavailable(caplog: pytest.LogCaptureFixture):
    client = FakeRetrieveClient(error=_aws_error("AccessDeniedException"))
    with caplog.at_level(logging.WARNING, logger="backend.bedrock_retrieve"):
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
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "access_denied"
    assert result.chunks == ()
    assert "course_retrieval_access_denied" in caplog.text
    assert "AccessDeniedException" in caplog.text
    assert "us-west-2" in caplog.text


def test_retrieve_not_found_is_unavailable():
    client = FakeRetrieveClient(error=_aws_error("ResourceNotFoundException"))
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
    assert result.failure_category == "not_found"
    assert result.course_retrieval_status == "unavailable"


def test_retrieve_timeout_is_unavailable():
    timeout = type("ReadTimeoutError", (Exception,), {})("timed out")
    client = FakeRetrieveClient(error=timeout)
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
    assert result.failure_category == "timeout"
    assert result.course_retrieval_status == "unavailable"


def test_retrieve_throttled_is_unavailable():
    client = FakeRetrieveClient(error=_aws_error("ThrottlingException"))
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
    assert result.failure_category == "throttled"


def test_retrieve_validation_exception_retries_unfiltered():
    client = FakeRetrieveClient(
        errors_sequence=[_aws_error("ValidationException"), None],
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "Selected lecture excerpt after validation fallback.",
            )
        ],
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=False,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert len(client.calls) == 2
    first_filter = client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    second_filter = client.calls[1]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert "filter" in first_filter
    assert "filter" not in second_filter
    assert result.course_retrieval_status == "ok"
    assert result.chunks[0].retrieval_origin == "knowledge_base"
    assert "validation fallback" in result.chunks[0].text


def test_strict_metadata_filter_does_not_retry_validation_exception():
    client = FakeRetrieveClient(error=_aws_error("ValidationException"))
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
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
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "validation_error"


def test_retrieve_zero_hits_is_empty():
    client = FakeRetrieveClient(results=[])
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
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
    assert result.chunks == ()
    assert result.course_retrieval_status == "empty"


def test_retrieve_raw_hits_without_exact_key_are_empty():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/other.pdf",
                "Unselected lecture excerpt.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
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
    assert result.course_retrieval_status == "empty"
    assert "Unselected lecture" not in result.context


def test_retrieve_wrong_bucket_is_discarded():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://wrong-bucket/course/lectureNotes/crossing.pdf",
                "Wrong bucket excerpt.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
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
    assert result.course_retrieval_status == "empty"
    assert "Wrong bucket" not in result.context


def test_retrieve_unexpected_response_shape_is_empty():
    client = FakeRetrieveClient(raw_response={"retrievalResults": "not-a-list"})
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        strict_metadata_filter=True,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert result.course_retrieval_status == "empty"
    assert result.chunks == ()


def test_sanitized_s3_uri_drops_query_string():
    assert (
        sanitized_s3_uri(
            "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf?AWSAccessKeyId=AKIA"
        )
        == "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf"
    )


def test_sanitized_https_s3_uri_canonicalizes_bucket_and_key():
    assert (
        sanitized_s3_uri(
            "https://cde2300-course-content-s3.s3.us-west-2.amazonaws.com/"
            "course/lectureNotes/crossing.pdf"
        )
        == "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf"
    )


def test_retrieve_accepts_https_s3_virtual_hosted_exact_key():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "https://cde2300-course-content-s3.s3.us-west-2.amazonaws.com/"
                "course/lectureNotes/crossing.pdf",
                "HTTPS location excerpt.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        knowledge_base_type="managed",
        strict_metadata_filter=True,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert result.course_retrieval_status == "ok"
    assert result.chunks[0].text == "HTTPS location excerpt."


def test_retrieve_discards_https_export_prefix_with_same_filename():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "https://cde2300-course-content-s3.s3.us-west-2.amazonaws.com/"
                "CDE2300_course_files_export/Course_materials/"
                "Week 1 Introduction to innovation v3.pdf",
                "Export-prefix excerpt must not match course/lectureNotes.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        knowledge_base_type="managed",
        strict_metadata_filter=True,
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(_virtual_week1_source(),),
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "empty"
    assert "Export-prefix" not in result.context


def test_configured_live_retriever_uses_region_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "knowledge_base_region", "")
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "mock_openai", False)
    monkeypatch.setattr(settings, "course_materials_bucket", "cde2300-course-content-s3")
    retriever = configured_context_retriever(client=FakeRetrieveClient(results=[]))
    assert isinstance(retriever, CompositeContextRetriever)
    assert retriever._knowledge_base is not None
    assert retriever._knowledge_base._region == "us-west-2"
    assert retriever._knowledge_base._course_bucket == "cde2300-course-content-s3"
    assert retriever._knowledge_base._knowledge_base_type == "vector"


def test_strict_managed_retrieve_uses_managed_search_configuration():
    client = FakeRetrieveClient(
        results=[
            _hit(
                "s3://cde2300-course-content-s3/course/lectureNotes/crossing.pdf",
                "Managed search excerpt.",
            )
        ]
    )
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        knowledge_base_type="MANAGED",
        strict_metadata_filter=True,
    ).retrieve(
        _query(
            _course_source(
                "src-lecture",
                "S1",
                object_key="course/lectureNotes/crossing.pdf",
            )
        )
    )
    assert "vectorSearchConfiguration" not in client.calls[0]["retrievalConfiguration"]
    search = client.calls[0]["retrievalConfiguration"]["managedSearchConfiguration"]
    assert search["numberOfResults"] >= 1
    assert search["filter"] == {
        "equals": {"key": "course_material_id", "value": "lecture_crossing"}
    }
    assert result.chunks[0].retrieval_origin == "knowledge_base"


def test_managed_retrieve_does_not_retry_empty_unfiltered_search():
    client = FakeRetrieveClient(results=[])
    result = BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        knowledge_base_type="managed",
        strict_metadata_filter=False,
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
    search = client.calls[0]["retrievalConfiguration"]["managedSearchConfiguration"]
    assert "filter" not in search
    assert result.course_retrieval_status == "empty"


def test_configured_live_retriever_uses_managed_type(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    monkeypatch.setattr(settings, "knowledge_base_type", "MANAGED")
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "mock_openai", False)
    monkeypatch.setattr(settings, "course_materials_bucket", "cde2300-course-content-s3")
    retriever = configured_context_retriever(client=FakeRetrieveClient(results=[]))
    assert retriever._knowledge_base is not None
    assert retriever._knowledge_base._knowledge_base_type == "managed"

