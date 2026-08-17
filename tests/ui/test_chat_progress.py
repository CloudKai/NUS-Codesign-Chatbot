"""Behavioural AppTest coverage for coach progress, reply rendering, and reruns."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from streamlit.testing.v1 import AppTest

from backend.domain import CoachTurn, EducationalAssessment
from backend.student_journey import DEFAULT_STAGE


def test_chat_panel_consumes_status_events_and_skips_fake_tokens() -> None:
    """AppTest cannot observe live st.status labels; keep those source contracts."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    runtime = Path("ui/services/runtime.py").read_text(encoding="utf-8")
    http = Path("backend/http/app.py").read_text(encoding="utf-8")
    assert 'kind == "status"' in chat
    assert 'phase == "retrieving"' in chat
    assert 'phase == "thinking"' in chat
    assert 'phase == "saving"' in chat
    assert "chunk_size = 32" not in runtime
    assert "chunk_size = 32" not in http
    assert "This helper does not invent token slices" in runtime
    assert "not emit fake token slices" in http
    assert "Coach reply ready" in chat
    assert "assistant_message_from_turn" in chat
    assert "needs_reconcile" in chat


def _reply_visible(app: AppTest, text: str) -> bool:
    """Return whether assistant markdown or chat messages include ``text``."""
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    if text in rendered:
        return True
    for message in app.chat_message:
        body = "\n".join(str(getattr(block, "value", "") or "") for block in message)
        if text in body:
            return True
        # AppTest chat_message children vary by Streamlit version.
        markdowns = getattr(message, "markdown", None) or []
        if any(text in str(getattr(item, "value", "") or "") for item in markdowns):
            return True
    return text in str(app.chat_message)


def test_done_payload_renders_reply_without_forced_rerun(monkeypatch) -> None:
    """The validated done payload is shown in the same script run as Send."""
    from ui import chat

    reruns: list[str] = []
    monkeypatch.setattr(chat, "rerun_app", lambda: reruns.append("app"))

    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    prompt = "What is a design problem I could explore?"
    app.chat_input[0].set_value(prompt).run()
    assert not app.exception
    assert submissions == [prompt]
    assert reruns == []
    assert len(app.chat_message) >= 3
    assert _reply_visible(app, "That's an interesting direction")
    assert app.session_state["learning_journey"]["current_stage"] == DEFAULT_STAGE


def test_successful_send_does_not_duplicate_submit_on_next_run(monkeypatch) -> None:
    """Trigger-widget chat_input plus unchanged nonce cannot resubmit the turn."""
    from ui import chat

    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    prompt = "What is a design problem I could explore?"
    app.chat_input[0].set_value(prompt).run()
    assert submissions == [prompt]
    assert _reply_visible(app, "That's an interesting direction")
    app.run()
    assert submissions == [prompt]
    assert _reply_visible(app, "That's an interesting direction")
    app.chat_input[0].set_value(prompt).run()
    assert submissions == [prompt, prompt]


def test_auto_advance_reconciles_thinking_path_after_reply_is_visible(
    monkeypatch,
) -> None:
    """Stage changes still remount studio after the assistant reply is drawn."""
    from ui import chat

    reruns: list[str] = []

    def spy_rerun() -> None:
        reruns.append("app")
        # Delay the remount. AppTest cannot snapshot widgets if ``st.rerun()``
        # replaces the tree in the same script. Production still bumps the
        # composer nonce before calling ``rerun_app()``.

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    def fake_stream(_request: Any) -> Iterator[dict[str, Any]]:
        yield {"event": "status", "phase": "thinking", "label": "Coach is thinking…"}
        turn = CoachTurn(
            response_text=(
                "You named a concrete user group. Let's generate concepts next."
            ),
            assessment=EducationalAssessment(
                current_stage="problem_identification",
                recommendation="advance",
                guidance_questions=["Which concept should we compare first?"],
            ),
            auto_advanced_to="concept_generation",
        )
        yield {"event": "done", "turn": turn.model_dump(mode="json")}

    monkeypatch.setattr(chat, "stream_coach_turn_events", fake_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.chat_input[0].set_value("Older pedestrians need more crossing time.").run()
    assert not app.exception
    assert reruns == ["app"]
    assert _reply_visible(app, "You named a concrete user group")
    assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
    app.run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Generate and compare plausible concepts that respond to the problem." in rendered


def test_citation_buttons_render_from_done_payload_without_get_source(
    monkeypatch,
) -> None:
    """Citations use the already-loaded source id set, not per-id fetches."""
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore
    from ui import chat
    from ui.runtime import store as runtime_store

    source_fetches: list[str] = []
    original_get_source = runtime_store.get_source

    def counting_get_source(thread_id: str, source_id: str):
        source_fetches.append(source_id)
        return original_get_source(thread_id, source_id)

    monkeypatch.setattr(runtime_store, "get_source", counting_get_source)
    monkeypatch.setattr(chat, "rerun_app", lambda: None)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    local_store = StudentStore()
    added = add_text_source(
        local_store,
        app.session_state["thread_id"],
        "Lecture evidence",
        "The study included eighty students and compared two teaching methods.",
    )
    source_id = str(added["id"])
    app.run()

    def fake_stream(_request: Any) -> Iterator[dict[str, Any]]:
        turn = CoachTurn(
            response_text="The lecture reports a comparison of two methods [S1].",
            assessment=EducationalAssessment(
                current_stage="problem_identification",
                citations=[
                    {
                        "source_id": source_id,
                        "label": "S1",
                        "title": "Lecture evidence",
                    }
                ],
            ),
        )
        yield {"event": "done", "turn": turn.model_dump(mode="json")}

    monkeypatch.setattr(chat, "stream_coach_turn_events", fake_stream)
    app.chat_input[0].set_value("What evidence does my source provide?").run()
    assert not app.exception
    assert source_fetches == []
    assert any(
        (button.label or "").startswith("[S1] Lecture evidence")
        for button in app.button
    )


def test_deep_review_button_appears_after_qualifying_turn(monkeypatch) -> None:
    """Deep Review availability is reconciled from notebook metadata after done."""
    from backend.domain import ProviderAssessmentResult
    from backend.mock_provider import DeterministicCoachProvider
    from backend.settings import settings
    from backend.student_store import StudentStore
    from backend.specialists.review_orchestration import (
        COUNTER_SETTINGS_KEY,
        parse_coaching_turns_since_deep_review,
    )
    from ui import chat

    monkeypatch.setattr(settings, "deep_review_interval_turns", 1)
    real_assess = DeterministicCoachProvider.assess

    def qualifying_assess(self, request: Any) -> ProviderAssessmentResult:
        result = real_assess(self, request)
        if result.specialist == "coaching":
            return result.model_copy(update={"qualifying_coaching_turn": True})
        return result

    monkeypatch.setattr(DeterministicCoachProvider, "assess", qualifying_assess)

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not any(button.label == "Start Deep Review" for button in app.button)
    app.chat_input[0].set_value(
        "I want to evaluate a crossing design for older pedestrians."
    ).run()
    assert not app.exception
    thread = StudentStore().get_thread(app.session_state["thread_id"]) or {}
    counter = parse_coaching_turns_since_deep_review(
        (thread.get("metadata") or {}).get(COUNTER_SETTINGS_KEY)
    )
    assert counter >= 1
    assert reruns == ["app"]
    assert any(button.label == "Start Deep Review" for button in app.button)
