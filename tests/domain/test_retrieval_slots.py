"""Phase 1 retrieval fixes: reserved slots, KB over-fetch, parallel retrieval.

Mock providers and fake retrievers only. No AWS or paid calls.
"""

from __future__ import annotations

import contextvars
import threading
from typing import Any

import pytest

from backend.bedrock_retrieve import BedrockKnowledgeBaseRetriever
from backend.retrieval import (
    CompositeContextRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    bounded_retrieval_result,
    split_result_slots,
)
from backend.settings import settings

_BUCKET = "cde2300-course-content-s3"
_WEEK1_KEY = "course/lectureNotes/week1.pdf"


def _chunk(
    label: str,
    index: int,
    *,
    origin: str,
    score: float,
    text: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        source_id=f"src-{label}",
        label=label,
        title=f"Title {label}",
        chunk_id=f"{label}-{index}",
        text=text or f"Distinct excerpt {label} number {index} about crossings.",
        score=score,
        source_index=1,
        chunk_index=index,
        retrieval_origin=origin,
    )


def _course_chunks(count: int) -> tuple[RetrievedChunk, ...]:
    return tuple(
        _chunk("S1", i, origin="knowledge_base", score=1.0 - i / 100)
        for i in range(1, count + 1)
    )


def _student_chunks(count: int) -> tuple[RetrievedChunk, ...]:
    return tuple(
        _chunk("S2", i, origin="extracted_text", score=5.0 - i)
        for i in range(1, count + 1)
    )


class _StubRetriever:
    def __init__(self, chunks: tuple[RetrievedChunk, ...], status: str = "ok") -> None:
        self._chunks = chunks
        self._status = status
        self.calls = 0

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.calls += 1
        return RetrievalResult(
            context="",
            chunks=self._chunks,
            course_retrieval_status=self._status,
        )


def _course_source() -> RetrievalSource:
    return RetrievalSource(
        source_id="src-S1",
        label="S1",
        title="Week 1",
        text="",
        group="Lecture Notes",
        object_key=_WEEK1_KEY,
        virtual_course_source=True,
        shared_course_object=True,
    )


def _upload_source() -> RetrievalSource:
    return RetrievalSource(
        source_id="src-S2",
        label="S2",
        title="My notes",
        text="Older pedestrians wait at the school gate.",
        object_key="users/student/notebook/notes.txt",
    )


def _query(*sources: RetrievalSource) -> RetrievalQuery:
    return RetrievalQuery(
        current_message="what do the crossings notes say?",
        current_stage="problem_identification",
        sources=tuple(sources),
    )


def _origins(result: RetrievalResult) -> list[str]:
    return [chunk.retrieval_origin for chunk in result.chunks]


# ---- Item 1: reserved slots -------------------------------------------------


def test_default_slot_split_is_two_course_and_two_student() -> None:
    assert settings.fast_chat_retrieval_max_chunks == 4
    assert split_result_slots(
        settings.fast_chat_retrieval_max_chunks,
        settings.fast_chat_retrieval_course_slots,
    ) == (2, 2)


@pytest.mark.parametrize(
    ("total", "course", "expected"),
    [(4, 2, (2, 2)), (4, 9, (3, 1)), (4, 0, (1, 3)), (8, 2, (2, 6)), (2, 5, (1, 1)), (1, 2, (1, 0))],
)
def test_split_result_slots_keeps_both_sides_when_possible(
    total: int, course: int, expected: tuple[int, int]
) -> None:
    assert split_result_slots(total, course) == expected


def test_student_uploads_are_not_crowded_out_by_course_results() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=_StubRetriever(_course_chunks(4)),
        local=_StubRetriever(_student_chunks(3)),
    )
    result = composite.retrieve(_query(_course_source(), _upload_source()))
    assert _origins(result) == [
        "knowledge_base",
        "knowledge_base",
        "extracted_text",
        "extracted_text",
    ]
    # The execution layer re-bounds to FAST_CHAT_RETRIEVAL_MAX_CHUNKS in order.
    final = bounded_retrieval_result(
        result.chunks,
        max_chunks=settings.fast_chat_retrieval_max_chunks,
    )
    assert _origins(final) == _origins(result)


def test_unused_student_slots_go_to_course_results() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=_StubRetriever(_course_chunks(4)),
        local=_StubRetriever(_student_chunks(1)),
    )
    result = composite.retrieve(_query(_course_source(), _upload_source()))
    assert _origins(result) == ["knowledge_base"] * 3 + ["extracted_text"]


def test_unused_course_slots_go_to_student_results() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=_StubRetriever(_course_chunks(1)),
        local=_StubRetriever(_student_chunks(4)),
    )
    result = composite.retrieve(_query(_course_source(), _upload_source()))
    assert _origins(result) == ["knowledge_base"] + ["extracted_text"] * 3


def test_course_only_turn_still_gets_every_slot() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=_StubRetriever(_course_chunks(4)),
        local=_StubRetriever(()),
    )
    result = composite.retrieve(_query(_course_source()))
    assert _origins(result) == ["knowledge_base"] * 4


def test_explicit_slot_overrides_are_honoured() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=_StubRetriever(_course_chunks(4)),
        local=_StubRetriever(_student_chunks(4)),
        max_chunks=6,
        course_slots=1,
    )
    result = composite.retrieve(_query(_course_source(), _upload_source()))
    assert _origins(result) == ["knowledge_base"] * 2 + ["extracted_text"] * 4


# ---- Item 2: over-fetch candidates, validate, keep best 4 -------------------


class _FakeClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = results

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"retrievalResults": list(self._results)}


def _hit(key: str, text: str, score: float, bucket: str = _BUCKET) -> dict[str, Any]:
    return {
        "content": {"text": text},
        "location": {"type": "S3", "s3Location": {"uri": f"s3://{bucket}/{key}"}},
        "score": score,
    }


def _kb(client: _FakeClient, **kwargs: Any) -> BedrockKnowledgeBaseRetriever:
    return BedrockKnowledgeBaseRetriever(
        "KB123",
        course_bucket=_BUCKET,
        client=client,
        knowledge_base_type="managed",
        metadata_filter_mode="required",
        **kwargs,
    )


def test_candidate_count_default_is_within_twelve_to_sixteen() -> None:
    assert 12 <= settings.knowledge_base_retrieve_candidates <= 16


def test_retrieve_requests_candidates_and_keeps_best_four_validated() -> None:
    hits = [_hit(_WEEK1_KEY, f"Valid excerpt {i}.", 0.30 + i / 100) for i in range(10)]
    # Higher-scoring hits that fail validation must not take a kept slot.
    hits.append(_hit("course/lectureNotes/other.pdf", "Foreign key.", 0.99))
    hits.append(_hit(_WEEK1_KEY, "Foreign bucket.", 0.98, bucket="other-bucket"))
    client = _FakeClient(hits)
    result = _kb(client).retrieve(_query(_course_source()))
    search = client.calls[0]["retrievalConfiguration"]["managedSearchConfiguration"]
    assert search["numberOfResults"] == settings.knowledge_base_retrieve_candidates
    assert search["numberOfResults"] > settings.fast_chat_retrieval_max_chunks
    assert [chunk.text for chunk in result.chunks] == [
        "Valid excerpt 9.",
        "Valid excerpt 8.",
        "Valid excerpt 7.",
        "Valid excerpt 6.",
    ]
    assert result.course_retrieval_status == "ok"


def test_retrieve_ranks_by_score_not_by_return_order() -> None:
    client = _FakeClient(
        [
            _hit(_WEEK1_KEY, "Low.", 0.1),
            _hit(_WEEK1_KEY, "High.", 0.9),
            _hit(_WEEK1_KEY, "Mid.", 0.5),
        ]
    )
    result = _kb(client).retrieve(_query(_course_source()))
    assert [chunk.text for chunk in result.chunks] == ["High.", "Mid.", "Low."]
    assert [chunk.chunk_id for chunk in result.chunks] == ["S1-KB1", "S1-KB2", "S1-KB3"]


def test_all_candidates_invalid_is_empty_not_a_stale_hit() -> None:
    client = _FakeClient([_hit(_WEEK1_KEY, "Wrong bucket.", 0.9, bucket="other")])
    result = _kb(client).retrieve(_query(_course_source()))
    assert result.chunks == ()
    assert result.course_retrieval_status == "empty"


def test_candidates_never_drop_below_kept_results() -> None:
    client = _FakeClient([_hit(_WEEK1_KEY, "Only.", 0.5)])
    _kb(client, number_of_results=2, max_results=6).retrieve(_query(_course_source()))
    search = client.calls[0]["retrievalConfiguration"]["managedSearchConfiguration"]
    assert search["numberOfResults"] == 6


# ---- Item 3: parallel retrieval ---------------------------------------------


class _RendezvousRetriever:
    """Waits for its peer; only passes when both run at the same time."""

    def __init__(
        self,
        chunks: tuple[RetrievedChunk, ...],
        *,
        mine: threading.Event,
        peer: threading.Event,
    ) -> None:
        self._chunks = chunks
        self._mine = mine
        self._peer = peer
        self.met_peer = False
        self.thread_id: int | None = None
        self.var_seen: str | None = None

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.thread_id = threading.get_ident()
        self.var_seen = _MARKER.get()
        self._mine.set()
        self.met_peer = self._peer.wait(timeout=5.0)
        return RetrievalResult(context="", chunks=self._chunks)


_MARKER: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="unset")


def test_course_and_student_retrieval_run_in_parallel() -> None:
    course_started = threading.Event()
    student_started = threading.Event()
    course = _RendezvousRetriever(
        _course_chunks(2), mine=course_started, peer=student_started
    )
    student = _RendezvousRetriever(
        _student_chunks(2), mine=student_started, peer=course_started
    )
    _MARKER.set("turn-1")
    result = CompositeContextRetriever(knowledge_base=course, local=student).retrieve(
        _query(_course_source(), _upload_source())
    )
    assert course.met_peer and student.met_peer
    assert course.thread_id != student.thread_id
    assert course.var_seen == "turn-1"
    assert _origins(result) == ["knowledge_base"] * 2 + ["extracted_text"] * 2


def test_parallel_retrieval_propagates_course_errors() -> None:
    class _Boom:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            raise RuntimeError("kb exploded")

    composite = CompositeContextRetriever(
        knowledge_base=_Boom(), local=_StubRetriever(_student_chunks(2))
    )
    with pytest.raises(RuntimeError, match="kb exploded"):
        composite.retrieve(_query(_course_source(), _upload_source()))


def test_missing_knowledge_base_still_keeps_student_hits_and_gap() -> None:
    composite = CompositeContextRetriever(
        knowledge_base=None, local=_StubRetriever(_student_chunks(3))
    )
    result = composite.retrieve(_query(_course_source(), _upload_source()))
    assert result.course_retrieval_status == "unavailable"
    assert result.failure_category == "config_missing"
    assert _origins(result) == ["extracted_text"] * 3
