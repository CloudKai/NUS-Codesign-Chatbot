"""Opt-in local student-upload retrieval policy. No AWS.

``FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED`` (default off) searches the selected
student uploads when the regex gate skipped retrieval and the turn is not
navigation or chit-chat. These tests use stub retrievers and the fake
AgentCore runtime only.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.coaching.execution import (
    _wants_student_upload_retrieval,
    is_chit_chat,
    searchable_student_uploads,
)
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import (
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    is_greeting_or_acknowledgement,
)
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
# gm109 in the eval set: an upload question the regex gate skips.
_UPLOAD_QUESTION = "what does the survey say about peak hours"
_SURVEY_TEXT = "Peak hours are 12pm to 1pm; 64% leave when the queue is long."


def _payload(*, mode: str = "coaching", text: str = "Short reply.", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mode": mode,
        "response_text": text,
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "needs_sources": False,
        "out_of_scope": False,
    }
    if mode == "coaching":
        body["recommendation"] = "stay"
        body["recommendation_rationale"] = "More evidence is needed."
    body.update(extra)
    return body


class _Retriever:
    """Return one chunk for the first source; record queries; fail on demand."""

    def __init__(self, *, errors: list[BaseException] | None = None) -> None:
        self.queries: list[RetrievalQuery] = []
        self._errors = list(errors or [])

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        if self._errors:
            raise self._errors.pop(0)
        source = query.sources[0]
        chunk = RetrievedChunk(
            source_id=source.source_id,
            label=source.label,
            title=source.title,
            chunk_id="c1",
            text=_SURVEY_TEXT,
            score=0.9,
            source_index=0,
            chunk_index=0,
        )
        return RetrievalResult(context=chunk.text, chunks=(chunk,))


def _store(tmp_path, monkeypatch, *, upload: bool = True) -> tuple[StudentStore, str]:
    """Notebook with one synced course file and, optionally, a selected upload."""
    from backend import source_library

    store = StudentStore(tmp_path / "upload-policy.sqlite3")
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
    if upload:
        add_text_source(store, thread_id, "Survey results", _SURVEY_TEXT)
    return store, thread_id


def _service(
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


def _request(thread_id: str, message: str, key: str) -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


def _enable(monkeypatch, value: bool = True) -> None:
    monkeypatch.setattr(settings, "fast_chat_upload_retrieval_enabled", value)


def _trusted(call: dict[str, Any]) -> str:
    return str(json.loads(call["payload"]).get("trusted_instructions") or "")


# --- setting and helpers -----------------------------------------------------


def test_setting_defaults_off() -> None:
    from backend.settings import Settings

    field = Settings.__dataclass_fields__["fast_chat_upload_retrieval_enabled"]
    assert field.default is False


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ok.", True),
        ("Thanks!", True),
        ("hello there", True),
        ("Good morning", True),
        ("what is a persona", False),
        ("thank you", False),
        ("", False),
    ],
)
def test_is_greeting_or_acknowledgement(message: str, expected: bool) -> None:
    assert is_greeting_or_acknowledgement(message) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("thanks", True),
        ("hey there", True),
        ("hi, what does my survey say about peak hours?", False),
        ("what did the participants say about falling at night?", False),
        ("I think option B is stronger.", False),
    ],
)
def test_is_chit_chat(message: str, expected: bool) -> None:
    assert is_chit_chat(message) is expected


def test_searchable_student_uploads_drops_course_rows_and_images() -> None:
    upload = {"id": "u1", "kind": "file", "mime": "application/pdf"}
    image_kind = {"id": "i1", "kind": "image"}
    image_mime = {"id": "i2", "kind": "file", "mime": "image/png"}
    course = {
        "id": "c1",
        "kind": "file",
        "metadata": {"locked_source": True, "origin": "lecture_notes_folder"},
    }
    assert searchable_student_uploads([upload, image_kind, image_mime, course]) == [upload]
    assert searchable_student_uploads([image_kind, course]) == []


_QUESTION = "what did the participants say about falling at night?"


@pytest.mark.parametrize(
    ("enabled", "needs", "upload", "scoped", "message", "expected"),
    [
        (True, False, True, False, _QUESTION, True),
        (False, False, True, False, _QUESTION, False),
        (True, True, True, False, _QUESTION, False),
        (True, False, False, False, _QUESTION, False),
        (True, False, True, True, _QUESTION, False),
        (True, False, True, False, "thanks", False),
        (True, False, True, False, "hey there", False),
        (True, False, True, False, "hi, what does my survey say about peak hours?", True),
        (True, False, True, False, "I think option B is stronger.", True),
    ],
)
def test_wants_student_upload_retrieval(
    enabled: bool,
    needs: bool,
    upload: bool,
    scoped: bool,
    message: str,
    expected: bool,
) -> None:
    assert (
        _wants_student_upload_retrieval(
            enabled=enabled,
            needs_retrieval=needs,
            has_student_upload=upload,
            evidence_scoped=scoped,
            student_message=message,
        )
        is expected
    )


def test_image_only_upload_does_not_count_as_a_searchable_upload() -> None:
    sources = [{"id": "i1", "kind": "image", "mime": "image/png"}]
    assert (
        _wants_student_upload_retrieval(
            enabled=True,
            needs_retrieval=False,
            has_student_upload=bool(searchable_student_uploads(sources)),
            evidence_scoped=False,
            student_message=_QUESTION,
        )
        is False
    )


# --- application path --------------------------------------------------------


def test_setting_off_keeps_the_gate_skip(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch, False)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever()
    client = FakeAgentCoreRuntime(payload=_payload())
    service = _service(store, client, retriever)

    service.submit(_request(thread_id, _UPLOAD_QUESTION, "up-off"))

    assert retriever.queries == []
    assert len(client.calls) == 1
    assert _SURVEY_TEXT not in json.dumps(json.loads(client.calls[0]["payload"]))


def test_setting_on_searches_only_the_student_upload(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever()
    client = FakeAgentCoreRuntime(payload=_payload(mode="qa", text="Peak is 12pm [S1]."))
    service = _service(store, client, retriever)

    turn = service.submit(_request(thread_id, _UPLOAD_QUESTION, "up-on"))

    assert len(retriever.queries) == 1
    searched = {source.source_id for source in retriever.queries[0].sources}
    course = {item["id"] for item in list_course_library_sources(store, thread_id)}
    assert course and not searched & course
    uploads = [
        source["id"]
        for source in store.list_sources(thread_id)
        if source.get("title") == "Survey results"
    ]
    assert searched == set(uploads)
    assert len(client.calls) == 1
    assert _SURVEY_TEXT in json.dumps(json.loads(client.calls[0]["payload"]))
    assert turn.response_text.startswith("Peak is 12pm")


@pytest.mark.parametrize(
    "message",
    [
        "thanks",
        "hey there",
        "let's go to concept generation",
        "can we move on",
        "what should I do next",
        "what stage am I on?",
    ],
)
def test_chit_chat_and_navigation_do_not_search(
    tmp_path, monkeypatch, message: str
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever()
    service = _service(store, FakeAgentCoreRuntime(payload=_payload()), retriever)

    prepared, _ = service._prepare_authoritative_turn(
        _request(thread_id, message, "up-scope")
    )

    assert retriever.queries == []
    assert prepared.retrieval_required is False
    assert prepared.retrieved_chunks == []


def test_course_catalog_alone_is_not_searched(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch, upload=False)
    retriever = _Retriever()
    service = _service(store, FakeAgentCoreRuntime(payload=_payload()), retriever)

    prepared, _ = service._prepare_authoritative_turn(
        _request(thread_id, _UPLOAD_QUESTION, "up-course-only")
    )

    assert retriever.queries == []
    assert prepared.retrieval_required is False


def test_retrieval_failure_continues_as_if_the_policy_had_not_fired(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever(errors=[RuntimeError("local index broken")])
    client = FakeAgentCoreRuntime(payload=_payload(text="What did you expect?"))
    service = _service(store, client, retriever)

    turn = service.submit(_request(thread_id, _UPLOAD_QUESTION, "up-fail"))

    assert len(retriever.queries) == 1
    assert len(client.calls) == 1
    assert turn.response_text == "What did you expect?"
    payload = json.loads(client.calls[0]["payload"])
    assert _SURVEY_TEXT not in json.dumps(payload)
    assert "could not retrieve" not in _trusted(client.calls[0])


def test_retrieval_value_error_still_raises(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever(errors=[ValueError("outside scope")])
    service = _service(store, FakeAgentCoreRuntime(payload=_payload()), retriever)

    with pytest.raises(ValueError):
        service._prepare_authoritative_turn(
            _request(thread_id, _UPLOAD_QUESTION, "up-value-error")
        )


def test_policy_turn_with_needs_sources_on_sends_no_source_check(
    tmp_path, monkeypatch
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "fast_chat_needs_sources_enabled", True)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever()
    client = FakeAgentCoreRuntime(payload=_payload(mode="qa", text="Peak is 12pm [S1]."))
    service = _service(store, client, retriever)

    service.submit(_request(thread_id, _UPLOAD_QUESTION, "up-ns"))

    assert len(client.calls) == 1
    assert len(retriever.queries) == 1
    assert "SOURCE CHECK" not in _trusted(client.calls[0])


def test_failed_policy_search_keeps_the_needs_sources_second_chance(
    tmp_path, monkeypatch
) -> None:
    """After a failed policy search the turn is stamped as before and a flag
    still retries with the course catalog."""
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "fast_chat_needs_sources_enabled", True)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _Retriever(errors=[RuntimeError("local index broken")])
    client = FakeAgentCoreRuntime(
        payloads=[
            _payload(mode="qa", text="placeholder", needs_sources=True),
            _payload(mode="qa", text="Grounded reply [S1]."),
        ]
    )
    service = _service(store, client, retriever)

    turn = service.submit(_request(thread_id, _UPLOAD_QUESTION, "up-ns-fail"))

    assert "SOURCE CHECK" in _trusted(client.calls[0])
    assert len(client.calls) == 2
    assert len(retriever.queries) == 2
    course = {item["id"] for item in list_course_library_sources(store, thread_id)}
    second = {source.source_id for source in retriever.queries[1].sources}
    assert course and course <= second
    assert turn.response_text.startswith("Grounded reply")
