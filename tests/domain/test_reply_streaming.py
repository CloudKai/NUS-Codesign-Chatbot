"""Reply text streaming: event order, discard on failure, idempotency, persistence. No AWS."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.coaching.reply_text import ReplyTextExtractor
from backend.coaching.stream_events import COACH_EVENT_ADAPTER
from backend.coaching.streaming import coach_events, stream_error
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.providers import ProviderUnavailableError
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from test_needs_sources import (
    _NO_CUE_COURSE_QUESTION,
    _CourseRetriever,
    _enable,
    _store,
)


def _service(store: StudentStore, provider: Any, retriever: Any = None) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
        **({"retriever": retriever} if retriever is not None else {}),
    )


def _request(thread_id: str, key: str, message: str = "Older users wait longer at the crossing.") -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


def _drain(coach: CoachApplicationService, request: CoachRequest, *, deltas: bool) -> list[Any]:
    return list(coach_events(coach, request, reply_deltas=deltas))


def _names(items: list[Any]) -> list[str]:
    return [item if isinstance(item, str) else (type(item).__name__ if isinstance(item, BaseException) else item["event"]) for item in items]


def _assistant(store: StudentStore, thread_id: str) -> list[dict[str, Any]]:
    return [m for m in store.get_messages(thread_id) if m["role"] == "assistant"]


class StreamingStub(DeterministicCoachProvider):
    """Mock provider that emits chosen fragments, then returns or fails."""

    def __init__(self, pieces: list[str], *, fail: BaseException | None = None, store: StudentStore | None = None) -> None:
        super().__init__(StageDecision.STAY)
        self.pieces = pieces
        self.fail = fail
        self.store = store
        self.thread_id = ""
        self.calls = 0

    def assess(self, request: CoachRequest):  # type: ignore[override]
        from backend.coaching.progress import emit_coach_reply_delta

        self.calls += 1
        for piece in self.pieces:
            if self.store is not None:
                # Persistence only follows validation: nothing is saved while text streams.
                assert _assistant(self.store, request.thread_id) == []
            emit_coach_reply_delta(piece)
        if self.fail is not None:
            raise self.fail
        return self._assess_turn(request)


# --- incremental reply-text extraction -------------------------------------------------

_OBJECT = {
    "assessment": {"response_text": "NESTED"},
    "response_text": 'Say "hi"\n\u00e9 \U0001F600 \u2603 \\ end',
    "recommendation": "stay",
}


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_extractor_decodes_top_level_reply_for_any_fragment_size(size: int) -> None:
    raw = json.dumps(_OBJECT)  # ensure_ascii splits the emoji into a surrogate pair escape
    extractor = ReplyTextExtractor()
    out = "".join(extractor.feed(raw[i : i + size]) for i in range(0, len(raw), size))
    assert out == _OBJECT["response_text"]
    assert extractor.finished


def test_extractor_ignores_nested_key_and_malformed_input_never_raises() -> None:
    assert ReplyTextExtractor().feed('{"assessment":{"response_text":"NESTED"}}') == ""
    broken = ReplyTextExtractor()
    assert broken.feed('{"response_text": "ab\\q cd"}') == "ab"
    assert broken.finished
    assert broken.feed("more") == ""


# --- event order and compatibility ----------------------------------------------------


def test_events_arrive_in_order_and_nothing_is_saved_until_done(tmp_path) -> None:
    store = StudentStore(tmp_path / "order.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = StreamingStub(["First part ", "second part."], store=store)
    items = _drain(_service(store, provider), _request(thread_id, "order"), deltas=True)

    names = _names(items)
    assert names == [
        "started", "status", "reply_delta", "reply_delta", "reply_ready", "status", "done",
    ]
    assert [i["text"] for i in items if i["event"] == "reply_delta"] == ["First part ", "second part."]
    assert items[names.index("status") ]["phase"] == "thinking"
    done = items[-1]["turn"]
    assert items[names.index("reply_ready")]["text"] == done["response_text"]
    assert len(_assistant(store, thread_id)) == 1
    for item in items:
        COACH_EVENT_ADAPTER.validate_python(item)


def test_without_opt_in_the_original_event_set_is_unchanged(tmp_path) -> None:
    store = StudentStore(tmp_path / "old-client.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = StreamingStub(["streamed text"])
    items = _drain(_service(store, provider), _request(thread_id, "old"), deltas=False)
    assert _names(items) == ["started", "status", "reply_ready", "status", "done"]


def test_mock_provider_streams_the_reply_in_pieces_that_rebuild_it(tmp_path) -> None:
    store = StudentStore(tmp_path / "mock.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    items = _drain(_service(store, DeterministicCoachProvider(StageDecision.STAY)), _request(thread_id, "mock"), deltas=True)
    pieces = [i["text"] for i in items if i["event"] == "reply_delta"]
    ready = next(i for i in items if i["event"] == "reply_ready")
    assert len(pieces) > 1
    assert "".join(pieces) == ready["text"] == items[-1]["turn"]["response_text"]


# --- failure after streamed text -------------------------------------------------------


def test_failure_after_streamed_text_discards_it_and_saves_nothing(tmp_path) -> None:
    store = StudentStore(tmp_path / "fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = StreamingStub(["unvalidated draft"], fail=ProviderUnavailableError("Provider returned a malformed coaching turn", category="malformed"), store=store)
    request = _request(thread_id, "fail")
    coach = _service(store, provider)
    items = _drain(coach, request, deltas=True)

    assert _names(items) == ["started", "status", "reply_delta", "reply_discard", "ProviderUnavailableError"]
    assert stream_error(items[-1])["status"] == 503
    assert _assistant(store, thread_id) == []
    assert coach.completed_turn(thread_id, "fail") is None

    # The same key retried later runs again and saves exactly once.
    provider.fail = None
    retry = _drain(coach, request, deltas=True)
    assert _names(retry)[-1] == "done"
    assert len(_assistant(store, thread_id)) == 1


def test_failure_without_opt_in_sends_no_discard_event(tmp_path) -> None:
    store = StudentStore(tmp_path / "fail-old.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = StreamingStub(["draft"], fail=ProviderUnavailableError("down"))
    items = _drain(_service(store, provider), _request(thread_id, "fail-old"), deltas=False)
    assert _names(items) == ["started", "status", "ProviderUnavailableError"]


# --- idempotent retry ------------------------------------------------------------------


def test_replay_of_a_saved_turn_streams_no_text_and_calls_no_model(tmp_path) -> None:
    store = StudentStore(tmp_path / "replay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = StreamingStub(["only once"])
    coach = _service(store, provider)
    request = _request(thread_id, "replay")
    first = _drain(coach, request, deltas=True)
    again = _drain(coach, request, deltas=True)

    assert "reply_delta" in _names(first)
    assert "reply_delta" not in _names(again)
    assert again[-1]["event"] == "done"
    assert again[-1]["turn"] == first[-1]["turn"]
    assert provider.calls == 1
    assert len(_assistant(store, thread_id)) == 1


# --- discard before the source-check retry --------------------------------------------


def test_source_check_retry_withdraws_the_first_pass_text(tmp_path, monkeypatch) -> None:
    _enable(monkeypatch)
    store, thread_id = _store(tmp_path, monkeypatch)
    retriever = _CourseRetriever()
    coach = _service(store, DeterministicCoachProvider(), retriever)
    items = _drain(coach, _request(thread_id, "retry", _NO_CUE_COURSE_QUESTION), deltas=True)

    names = _names(items)
    assert len(retriever.queries) == 1
    assert names.count("reply_discard") == 1
    discard = names.index("reply_discard")
    assert names[:discard].count("reply_delta") > 0 and names[discard + 1 :].count("reply_delta") > 0
    after = "".join(i["text"] for i in items[discard + 1 :] if i["event"] == "reply_delta")
    ready = next(i for i in items if i["event"] == "reply_ready")
    assert after == ready["text"]
    assert len(_assistant(store, thread_id)) == 1


# --- HTTP opt-in -----------------------------------------------------------------------


def _post(client: TestClient, thread_id: str, key: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    response = client.post(
        "/api/v1/coach/turn/stream",
        json={"thread_id": thread_id, "student_message": "Assess my design idea.", "current_stage": "problem_identification",
              "response_detail": "short", "idempotency_key": key},
        headers=headers or {},
    )
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_setting_defaults_off() -> None:
    assert settings.coach_stream_reply_deltas_enabled is False


@pytest.mark.parametrize(
    ("enabled", "header", "expect_deltas"),
    [(False, "1", False), (True, None, False), (True, "0", False), (True, "1", True)],
)
def test_http_stream_sends_deltas_only_with_setting_and_header(tmp_path, monkeypatch, enabled, header, expect_deltas) -> None:
    monkeypatch.setattr(settings, "coach_stream_reply_deltas_enabled", enabled)
    store = StudentStore(tmp_path / "http.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    events = _post(client, thread_id, "http-key", {"X-Coach-Reply-Deltas": header} if header is not None else None)
    kinds = [e["event"] for e in events]
    assert ("reply_delta" in kinds) is expect_deltas
    assert kinds[0] == "started" and kinds[-1] == "done" and "reply_ready" in kinds
    if expect_deltas:
        assert kinds.index("reply_delta") < kinds.index("reply_ready")
