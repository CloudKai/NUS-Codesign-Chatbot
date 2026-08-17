"""Bounded Knowledge Base Retrieve pool tests. No AWS or long sleeps."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from backend.bedrock_retrieve import (
    BedrockKnowledgeBaseRetriever,
    RetrieveCapacityError,
    classify_retrieve_failure,
    reset_shared_retrieve_executor,
    retrieve_pool_stats,
)
from backend.retrieval import RetrievalQuery, RetrievalSource
from backend.settings import settings


class HungRetrieveClient:
    """Injected client that blocks until the test releases an event."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = 0
        self.finished = 0
        self._lock = threading.Lock()

    def retrieve(self, **kwargs: Any) -> Any:
        del kwargs
        with self._lock:
            self.started += 1
        try:
            self.release.wait(timeout=5)
            return {"retrievalResults": []}
        finally:
            with self._lock:
                self.finished += 1

    def wait_idle(self) -> None:
        """Wait briefly for in-flight hung calls to leave the worker."""
        deadline = time.monotonic() + 1.0
        while self.finished < self.started and time.monotonic() < deadline:
            time.sleep(0.01)


def _course_query() -> RetrievalQuery:
    """Return one selected course-source query."""
    return RetrievalQuery(
        current_message="What crossing time do older pedestrians need?",
        current_stage="problem_identification",
        sources=(
            RetrievalSource(
                source_id="src-lecture",
                label="S1",
                title="Lecture",
                text="Local extracted course text should not be required for KB hits.",
                group="lectureNotes",
                object_key="course/lectureNotes/crossing.pdf",
            ),
        ),
    )


def _retriever(client: HungRetrieveClient, timeout: float) -> BedrockKnowledgeBaseRetriever:
    """Return a retriever that uses the hung client and a short wall-clock cap."""
    return BedrockKnowledgeBaseRetriever(
        "JUQNP8AZAZ",
        course_bucket="cde2300-course-content-s3",
        client=client,
        retrieve_timeout_seconds=timeout,
    )


@pytest.fixture(autouse=True)
def _reset_pool() -> None:
    """Isolate the shared Retrieve pool across cases."""
    reset_shared_retrieve_executor()
    yield
    reset_shared_retrieve_executor()


def test_classify_capacity_error_is_distinct_from_timeout() -> None:
    assert (
        classify_retrieve_failure(RetrieveCapacityError("knowledge_base_retrieve_capacity_exhausted"))
        == "capacity_exhausted"
    )
    assert classify_retrieve_failure(TimeoutError("knowledge_base_retrieve_timeout")) == "timeout"


def test_timeout_returns_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "knowledge_base_retrieve_executor_workers", 2)
    hung = HungRetrieveClient()
    clock = __import__("time").perf_counter
    begin = clock()
    try:
        result = _retriever(hung, 0.05).retrieve(_course_query())
        elapsed = clock() - begin
        assert elapsed < 0.4
        assert result.course_retrieval_status == "unavailable"
        assert result.failure_category == "timeout"
        assert result.chunks == ()
    finally:
        hung.release.set()
        hung.wait_idle()


def test_repeated_timeouts_never_create_unbounded_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "knowledge_base_retrieve_executor_workers", 2)
    hung = HungRetrieveClient()
    retriever = _retriever(hung, 0.05)
    try:
        for _ in range(8):
            result = retriever.retrieve(_course_query())
            assert result.course_retrieval_status == "unavailable"
            assert result.failure_category in {"timeout", "capacity_exhausted"}
            stats = retrieve_pool_stats()
            assert stats["max_workers"] == 2
            assert stats["admitted"] <= 2
            assert stats["worker_threads"] <= 2
        assert hung.started == 2
    finally:
        hung.release.set()
        hung.wait_idle()


def test_burst_larger_than_worker_count_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "knowledge_base_retrieve_executor_workers", 2)
    hung = HungRetrieveClient()
    retriever = _retriever(hung, 0.2)
    results: list[str] = []
    barrier = threading.Barrier(6)
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            barrier.wait(timeout=2)
            result = retriever.retrieve(_course_query())
            results.append(str(result.failure_category or ""))
        except BaseException as exc:  # noqa: BLE001 — test records the failure
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(6)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive()
        assert errors == []
        assert len(results) == 6
        assert results.count("timeout") == 2
        assert results.count("capacity_exhausted") == 4
        stats = retrieve_pool_stats()
        assert stats["admitted"] <= 2
        assert stats["worker_threads"] <= 2
        assert hung.started == 2
        for result_category in results:
            assert result_category in {"timeout", "capacity_exhausted"}
    finally:
        hung.release.set()
        hung.wait_idle()


def test_capacity_exhaustion_fails_closed_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "knowledge_base_retrieve_executor_workers", 1)
    hung = HungRetrieveClient()
    retriever = _retriever(hung, 0.3)
    first_started = threading.Event()

    original = hung.retrieve

    def _retrieve(**kwargs: Any) -> Any:
        first_started.set()
        return original(**kwargs)

    hung.retrieve = _retrieve  # type: ignore[method-assign]
    holder = threading.Thread(target=lambda: retriever.retrieve(_course_query()))
    try:
        holder.start()
        assert first_started.wait(timeout=1)
        clock = __import__("time").perf_counter
        begin = clock()
        result = retriever.retrieve(_course_query())
        elapsed = clock() - begin
        assert elapsed < 0.2
        assert result.course_retrieval_status == "unavailable"
        assert result.failure_category == "capacity_exhausted"
        assert result.chunks == ()
        assert hung.started == 1
    finally:
        hung.release.set()
        hung.wait_idle()
        holder.join(timeout=3)
