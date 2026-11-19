"""First-call ``needs_sources`` flag and its second-call fallback. No AWS.

The flag sits behind ``FAST_CHAT_NEEDS_SOURCES_ENABLED`` (default off). These
tests drive the real application path with a fake AgentCore runtime and with
the mock provider. The mock provider's flag is a deterministic stand-in (a
question-shaped message), so the mock tests prove the plumbing and the
behaviour of the surrounding application, not a model's judgement.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentcore_runtime.models import (
    FastChatTurnOutput,
    adapt_fast_chat_turn_payload,
)
from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.coaching.execution import _wants_source_need_check
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider, mock_flags_needs_sources
from backend.prompts import compose_coach_prompt
from backend.providers import ProviderUnavailableError
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk
from backend.settings import settings
from backend.source_library import (
    add_text_source,
    list_course_library_sources,
    sync_lecture_notes_folder,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
# gm005 in the eval set: a course question with no regex cue word. The gate
# skips it, so the model never sees course excerpts on the first call.
_NO_CUE_COURSE_QUESTION = "what questions do we ask in the JTBD interview"
_PROJECT_STATEMENT = "I think option B is stronger."


def _payload(
    *,
    mode: str = "qa",
    text: str = "Short reply.",
    needs_sources: Any = False,
    needs_source_retrieval: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mode": mode,
        "response_text": text,
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": needs_source_retrieval,
        "needs_sources": needs_sources,
        "out_of_scope": False,
    }
    if mode == "coaching":
        body["recommendation"] = "stay"
        body["recommendation_rationale"] = "More evidence is needed."
    return body


class _CourseRetriever:
    """Return one chunk for the first source of each query; record queries."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.queries: list[RetrievalQuery] = []
        self._error = error

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        source = query.sources[0]
        chunk = RetrievedChunk(
            source_id=source.source_id,
            label=source.label,
            title=source.title,
            chunk_id="c1",
            text="A JTBD interview asks about the struggling moment.",
            score=0.9,
            source_index=0,
            chunk_index=0,
        )
        return RetrievalResult(
            context=f"--- [{source.label}] {source.title} --- {chunk.text}",
            chunks=(chunk,),
        )


def _store(tmp_path, monkeypatch) -> tuple[StudentStore, str]:
    """Create a notebook with two synced course-library sources."""
    from backend import source_library

    store = StudentStore(tmp_path / "needs-sources.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notes = tmp_path / "lecture_notes" / "lectureNotes"
    notes.mkdir(parents=True)
    (notes / "Week 2 JTBD.pdf").write_text("Week 2 JTBD body", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", tmp_path / "lecture_notes")
    monkeypatch.setattr(source_library.settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(source_library.settings, "course_materials_bucket", "")
    monkeypatch.setattr(source_library.settings, "max_lecture_notes", 50)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)
    sync_lecture_notes_folder(store, thread_id)
    return store, thread_id


def _agentcore_service(
    store: StudentStore, client: FakeAgentCoreRuntime, retriever: Any
) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
        retriever=retriever,
    )


def _mock_service(store: StudentStore, retriever: Any) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
        retriever=retriever,
    )


def _request(thread_id: str, message: str, key: str) -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


def _enable(monkeypatch, value: bool = True) -> None:
    monkeypatch.setattr(settings, "fast_chat_needs_sources_enabled", value)


def _assistant_messages(store: StudentStore, thread_id: str) -> list[dict[str, Any]]:
    return [m for m in store.get_messages(thread_id) if m["role"] == "assistant"]


def _trusted_instructions(call: dict[str, Any]) -> str:
    return str(json.loads(call["payload"]).get("trusted_instructions") or "")


# --- setting and eligibility -------------------------------------------------


def test_setting_defaults_off() -> None:
    from backend.settings import Settings

    assert Settings.__dataclass_fields__["fast_chat_needs_sources_enabled"].default is False


@pytest.mark.parametrize(
    ("enabled", "searched", "scoped", "expected"),
    [
        (True, False, False, True),
        (False, False, False, False),
        (True, True, False, False),
        (True, False, True, False),
    ],
)
def test_wants_source_need_check(enabled, searched, scoped, expected) -> None:
    assert (
        _wants_source_need_check(
            enabled=enabled, searched=searched, evidence_scoped=scoped
        )
        is expected
    )


# --- contract ----------------------------------------------------------------


def test_needs_sources_is_optional_boolean_in_schema() -> None:
    schema = FastChatTurnOutput.model_json_schema()
    assert "needs_sources" not in (schema.get("required") or [])
    prop = schema["properties"]["needs_sources"]
    assert prop["type"] == "boolean"
    assert "anyOf" not in prop


@pytest.mark.parametrize("value", [None, "true", 1, "yes", [True]])
def test_malformed_needs_sources_is_false(value: Any) -> None:
    output = FastChatTurnOutput.model_validate(
        {"mode": "qa", "response_text": "x", "needs_sources": value}
    )
    assert output.needs_sources is False


def test_missing_needs_sources_defaults_false_and_true_is_kept() -> None:
    base = {"mode": "qa", "response_text": "x"}
    assert FastChatTurnOutput.model_validate(base).needs_sources is False
    assert (
        FastChatTurnOutput.model_validate({**base, "needs_sources": True}).needs_sources
        is True
    )


def test_out_of_scope_clears_needs_sources() -> None:
    output = FastChatTurnOutput.model_validate(
        {"mode": "qa", "response_text": "x", "needs_sources": True, "out_of_scope": True}
    )
    assert output.needs_sources is False


def test_adapter_carries_needs_sources_through_each_wire_shape() -> None:
    slim = adapt_fast_chat_turn_payload(_payload(needs_sources=True))
    assert slim.needs_sources is True
    bare_qa = adapt_fast_chat_turn_payload(
        {"response_text": "x", "needs_sources": True}
    )
    assert bare_qa.needs_sources is True
    nested = adapt_fast_chat_turn_payload(
        {
            "response_text": "x",
            "needs_sources": True,
            "assessment": {"recommendation": "stay"},
        }
    )
    assert nested.needs_sources is True


def test_payload_without_the_field_still_validates() -> None:
    payload = _payload()
    del payload["needs_sources"]
    assert adapt_fast_chat_turn_payload(payload).needs_sources is False


# --- prompt ------------------------------------------------------------------


def _fast_chat_runtime(**request_overrides: Any) -> str:
    fields: dict[str, Any] = {"response_detail": "short", **request_overrides}
    request = CoachRequest(
        thread_id="t",
        student_message="what is a persona",
        current_stage="problem_identification",
        **fields,
    )
    return compose_coach_prompt(
        request, include_recent_messages=False, context_policy="fast_chat"
    ).runtime_instructions


def test_prompt_has_source_check_only_when_stamped() -> None:
    assert "SOURCE CHECK" in _fast_chat_runtime(source_need_check=True)
    assert "needs_sources" not in _fast_chat_runtime()


@pytest.mark.parametrize("detail", ["short", "long"])
def test_source_check_survives_runtime_budget_in_guide_and_free(detail: str) -> None:
    runtime = _fast_chat_runtime(source_need_check=True, response_detail=detail)
    assert "Always return needs_sources as a JSON boolean." in runtime


# --- AgentCore path ----------------------------------------------------------


def test_flag_on_course_question_without_cue_retries_with_course_catalog(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payloads=[
            _payload(text="I would need the lecture first.", needs_sources=True),
            _payload(text="Ask about the struggling moment [S1]."),
        ]
    )
    service = _agentcore_service(store, client, retriever)

    turn = service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "ns-on"))

    assert len(client.calls) == 2
    assert "SOURCE CHECK" in _trusted_instructions(client.calls[0])
    assert "SOURCE CHECK" not in _trusted_instructions(client.calls[1])
    assert len(retriever.queries) == 1
    searched = {source.source_id for source in retriever.queries[0].sources}
    course = {item["id"] for item in list_course_library_sources(store, thread_id)}
    assert searched and searched == course
    assert turn.response_text.startswith("Ask about the struggling moment")
    assistants = _assistant_messages(store, thread_id)
    assert len(assistants) == 1
    assert "lecture first" not in assistants[0]["content"]


def test_flag_on_model_says_false_stays_one_call(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payload=_payload(mode="coaching", text="What assumption is behind that?")
    )
    service = _agentcore_service(store, client, retriever)

    service.submit(_request(thread_id, _PROJECT_STATEMENT, "ns-false"))

    assert len(client.calls) == 1
    assert retriever.queries == []
    assert "SOURCE CHECK" in _trusted_instructions(client.calls[0])


def test_flag_off_has_no_prompt_text_and_ignores_a_volunteered_flag(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch, False)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payload=_payload(text="Answer without sources.", needs_sources=True)
    )
    service = _agentcore_service(store, client, retriever)

    turn = service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "ns-off"))

    assert len(client.calls) == 1
    assert retriever.queries == []
    assert "SOURCE CHECK" not in _trusted_instructions(client.calls[0])
    assert turn.response_text == "Answer without sources."


def test_regex_gate_hit_retrieves_first_pass_and_skips_the_check(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payload=_payload(text="Week 2 covers JTBD [S1].", needs_sources=True)
    )
    service = _agentcore_service(store, client, retriever)

    service.submit(
        _request(thread_id, "what is a creative matrix", "ns-regex-path")
    )

    assert len(retriever.queries) == 1
    assert len(client.calls) == 1
    assert "SOURCE CHECK" not in _trusted_instructions(client.calls[0])


@pytest.mark.parametrize(
    "message",
    [
        "what stage am I on?",
        "let's go to concept generation",
        "what should I do next",
    ],
)
def test_gate_overrides_keep_evidence_scope_fixed(
    tmp_path, monkeypatch, message: str
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    service = _agentcore_service(
        store, FakeAgentCoreRuntime(payload=_payload()), _CourseRetriever()
    )
    prepared, _ = service._prepare_authoritative_turn(
        _request(thread_id, message, "ns-scope")
    )
    assert prepared.source_need_check is False


def test_client_cannot_set_source_need_check(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch, False)
    store, thread_id = _store(tmp_path, monkeypatch)
    service = _agentcore_service(
        store, FakeAgentCoreRuntime(payload=_payload()), _CourseRetriever()
    )
    request = _request(thread_id, _NO_CUE_COURSE_QUESTION, "ns-client")
    request = request.model_copy(update={"source_need_check": True})
    prepared, _ = service._prepare_authoritative_turn(request)
    assert prepared.source_need_check is False


def test_unstamped_request_ignores_flag_even_when_setting_is_on(
    tmp_path, monkeypatch
) -> None:
    """The provider drops the flag when the request was not stamped."""
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payload=_payload(mode="coaching", text="Which step is hardest?", needs_sources=True)
    )
    service = _agentcore_service(store, client, retriever)
    # Meta-guidance is never stamped, yet the model returns the flag.
    service.submit(_request(thread_id, "what should I do next", "ns-unstamped"))
    assert len(client.calls) == 1
    assert retriever.queries == []


def test_retrieval_failure_on_second_chance_asks_model_to_state_the_gap(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever(error=RuntimeError("kb down"))
    client = FakeAgentCoreRuntime(
        payloads=[
            _payload(text="placeholder", needs_sources=True),
            _payload(text="I could not retrieve a validated excerpt."),
        ]
    )
    service = _agentcore_service(store, client, retriever)

    turn = service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "ns-kb-down"))

    assert len(client.calls) == 2
    assert turn.response_text.startswith("I could not retrieve")
    second = json.loads(client.calls[1]["payload"])
    assert "unavailable" in json.dumps(second).lower()


def test_second_call_failure_stays_inside_the_two_call_budget(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    client = FakeAgentCoreRuntime(
        payloads=[
            _payload(needs_sources=True),
            {"ok": False, "error": True, "category": "structured_output_failure"},
        ]
    )
    service = _agentcore_service(store, client, _CourseRetriever())
    with pytest.raises(ProviderUnavailableError):
        service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "ns-budget"))
    assert len(client.calls) == 2
    assert store.get_messages(thread_id) == []


def test_legacy_needs_source_retrieval_still_retries_with_flag_on(
    tmp_path, monkeypatch
) -> None:
    """Selected-source fallback is unchanged and does not add the catalog."""
    _enable(monkeypatch)
    store = StudentStore(tmp_path / "legacy.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = _CourseRetriever()
    client = FakeAgentCoreRuntime(
        payloads=[
            _payload(mode="coaching", needs_source_retrieval=True),
            _payload(mode="coaching", text="What does that figure change?"),
        ]
    )
    service = _agentcore_service(store, client, retriever)

    service.submit(_request(thread_id, _PROJECT_STATEMENT, "ns-legacy"))

    assert len(client.calls) == 2
    assert len(retriever.queries) == 1


# --- mock provider -----------------------------------------------------------


def test_mock_rule_is_question_shaped() -> None:
    assert mock_flags_needs_sources(_NO_CUE_COURSE_QUESTION) is True
    assert mock_flags_needs_sources(_PROJECT_STATEMENT) is False


def test_mock_provider_flag_on_runs_the_fallback_and_grounds_the_reply(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    service = _mock_service(store, retriever)

    turn = service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "mock-on"))

    assert len(retriever.queries) == 1
    assert "struggling moment" in turn.response_text
    assert len(_assistant_messages(store, thread_id)) == 1


def test_mock_provider_flag_off_matches_pre_change_behaviour(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch, False)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    service = _mock_service(store, retriever)

    turn = service.submit(_request(thread_id, _NO_CUE_COURSE_QUESTION, "mock-off"))

    assert retriever.queries == []
    assert "struggling moment" not in turn.response_text
    assert len(_assistant_messages(store, thread_id)) == 1


def test_mock_provider_flag_on_project_statement_does_not_retrieve(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    service = _mock_service(store, retriever)

    turn = service.submit(_request(thread_id, _PROJECT_STATEMENT, "mock-project"))

    assert retriever.queries == []
    assert turn.response_text
    assert len(_assistant_messages(store, thread_id)) == 1


def test_mock_provider_flag_on_does_not_widen_attachment_scope(
    tmp_path, monkeypatch
) -> None:
    """A private-attachment question stays attachment-scoped (no stamp)."""
    from backend.source_library import CHAT_ATTACHMENT_ORIGIN, add_file_sources

    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    attachment = add_file_sources(
        store,
        thread_id,
        [("notes.pdf", b"Private attachment evidence", "application/pdf")],
        origin=CHAT_ATTACHMENT_ORIGIN,
        selected=False,
    )[0]
    service = _mock_service(store, _CourseRetriever())
    request = CoachRequest(
        thread_id=thread_id,
        student_message="Could you outline the attached PDF",
        current_stage="problem_identification",
        response_detail="short",
        attachment_source_ids=[attachment["id"]],
        idempotency_key="mock-attachment",
    )
    prepared, _ = service._prepare_authoritative_turn(request)
    assert prepared.source_need_check is False
