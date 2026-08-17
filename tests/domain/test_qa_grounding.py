"""Q&A evidence-gap grounding: history is not course evidence."""

from __future__ import annotations

import json
from typing import Any

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.coaching.mode_policy import QA_EVIDENCE_GAP_RESPONSE
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.prompts.composer import PromptComposer, PromptContext
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import (
    COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
    RetrievedChunk,
    RetrievalQuery,
    RetrievalResult,
    bounded_retrieval_result,
)
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


class _EmptyCourseRetriever:
    """Selected-source retriever that never returns validated excerpts."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        del query
        return RetrievalResult(
            context=COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
            chunks=(),
            course_retrieval_status="unavailable",
            failure_category="config_missing",
        )


class _Week1Retriever:
    """Return one Week 1 excerpt mapped onto the first selected source."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        source = query.sources[0]
        text = (
            "Week 1\nInnovation-driven economy\nAnalogy and metaphor in design"
        )
        return bounded_retrieval_result(
            [
                RetrievedChunk(
                    source_id=source.source_id,
                    label=source.label,
                    title="Week 1 Introduction to innovation v3.pdf",
                    chunk_id=f"{source.label}-KB1",
                    text=text,
                    score=0.91,
                    source_index=1,
                    chunk_index=1,
                    retrieval_origin="knowledge_base",
                )
            ]
        )


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=30.0,
        max_retries=0,
        client=client,
    )


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    *,
    retriever: Any,
) -> CoachApplicationService:
    """Build the application path with an injected retriever."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=retriever,
    )


def _trusted_instructions(client: FakeAgentCoreRuntime) -> str:
    """Return trusted_instructions from the first fake invoke."""
    raw = client.calls[0]["payload"]
    if isinstance(raw, (bytes, bytearray)):
        payload = json.loads(bytes(raw).decode("utf-8"))
    else:
        payload = json.loads(str(raw))
    return str(payload.get("trusted_instructions") or "")


def test_failed_qa_does_not_use_prior_assistant_as_course_evidence(tmp_path) -> None:
    """Empty current retrieval must not replay history as Week 1 facts."""
    store = StudentStore(tmp_path / "qa-gap.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        thread_id,
        "Week 1 Introduction to innovation v3.pdf",
        "Placeholder extracted text that must not become evidence.",
    )
    store.add_message(
        thread_id,
        "assistant",
        "Week 1 covers Innovation-driven economy and Analogy and metaphor in design.",
    )
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 1 covers Innovation-driven economy [S1].",
            "citations": [],
            "needs_source_retrieval": False,
        }
    )
    service = _service(store, client, retriever=_EmptyCourseRetriever())
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="what does week 1 material cover",
            current_stage="problem_identification",
            response_detail="long",
            idempotency_key="week1-gap",
        )
    )
    assert client.calls == []
    assert turn.response_text == QA_EVIDENCE_GAP_RESPONSE
    assert "Innovation-driven economy" not in turn.response_text
    assert "[S1]" not in turn.response_text
    assert "library problem" not in turn.response_text.casefold()
    assert turn.assessment.response_mode == "qa"
    assert turn.assessment.recommendation is None
    assert turn.assessment.citations == []
    gap_rows = [
        message
        for message in store.get_messages(thread_id)
        if message.get("role") == "assistant"
        and message.get("content") == QA_EVIDENCE_GAP_RESPONSE
    ]
    assert len(gap_rows) == 1


def test_successful_qa_cites_retrieved_week_one_and_does_not_coach(tmp_path) -> None:
    """Validated excerpts may answer the Week 1 question without project coaching."""
    store = StudentStore(tmp_path / "qa-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    added = add_text_source(
        store,
        thread_id,
        "Week 1 Introduction to innovation v3.pdf",
        "Week 1 Innovation-driven economy Analogy and metaphor in design",
    )
    source_id = str(added["id"])
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": (
                "Week 1 covers innovation-driven economy and analogy and "
                "metaphor in design. [S1]"
            ),
            "citations": [{"label": "S1", "source_id": source_id}],
            "needs_source_retrieval": False,
        }
    )
    service = _service(store, client, retriever=_Week1Retriever())
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="what does week 1 material cover",
            current_stage="problem_identification",
            response_detail="long",
            idempotency_key="week1-ok",
        )
    )
    assert len(client.calls) == 1
    trusted = _trusted_instructions(client)
    assert "Guidance mode: Strict" not in trusted
    assert "recommend stay or advance" in trusted.casefold()
    assert turn.assessment.response_mode == "qa"
    assert turn.assessment.recommendation is None
    assert "library problem" not in turn.response_text.casefold()
    assert "shifted away" not in turn.response_text.casefold()
    assert "[S1]" in turn.response_text
    labels = {citation.label for citation in turn.assessment.citations}
    assert "S1" in labels


def test_composer_empty_qa_forbids_history_as_evidence() -> None:
    """Empty retrieved context in Q&A must emit the strong gap rule."""
    prepared = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            retrieved_course_context="",
            student_message="what does week 1 material cover",
            response_detail="long",
            allow_model_knowledge=False,
            expected_response_mode="qa",
            context_policy="fast_chat",
            recent_messages=[
                {
                    "role": "assistant",
                    "content": "Week 1 covers Innovation-driven economy.",
                }
            ],
        )
    )
    text = prepared.runtime_instructions
    assert "not authoritative course evidence" in text
    assert "could not retrieve a validated excerpt" in text
    assert "Guidance mode: Strict" not in text
    assert "Do not reconstruct course facts from earlier assistant replies" in text
