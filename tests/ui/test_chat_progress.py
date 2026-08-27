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
    assert "apply_completed_turn_to_session" in chat
    assert "fragment_to_api_ms" in chat
    assert "pre_api_ms" in chat
    assert "composer_layout_ms" in chat
    assert "thread_lookup_ms" in chat
    assert "thinking_render_ms" in chat
    assert "api_to_started_ms" in runtime
    assert "configure_ui_perf_logger" in runtime
    assert 'st.container(key="chat_inflight")' in chat
    assert "_render_inflight_user_prompt" in chat
    assert "chat_inflight," in chat
    assert "cd-user-bubble-text" in chat
    assert "_recover_awaiting_coach_turn_fragment" in chat
    assert "_try_complete_awaiting_coach_turn" in chat
    assert "mount_awaiting_coach_turn_recovery" in chat
    assert "Coach is finishing" in chat
    assert "disabled=awaiting_locked" in chat


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


def test_done_payload_reconciles_from_persisted_history(monkeypatch) -> None:
    """A successful stay turn remounts so history owns the completed bubble."""
    from ui import chat

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request, **_kwargs)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    prompt = "What is a design problem I could explore?"
    app.chat_input[0].set_value(prompt).run()
    assert not app.exception
    assert submissions == [prompt]
    assert reruns == ["app"]
    assert app.session_state["_coach_turn_streaming"] is False
    assert len(app.chat_message) >= 3
    assert _reply_visible(app, "That's an interesting direction")
    assert app.session_state["learning_journey"]["current_stage"] == DEFAULT_STAGE


def test_successful_send_does_not_duplicate_submit_on_next_run(monkeypatch) -> None:
    """Trigger-widget chat_input plus unchanged nonce cannot resubmit the turn."""
    from ui import chat

    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request, **_kwargs)

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


def _reply_message_count(app: AppTest, text: str) -> int:
    """Count chat-message widgets whose body contains ``text``."""
    hits = 0
    for message in app.chat_message:
        body = "\n".join(str(getattr(block, "value", "") or "") for block in message)
        markdowns = getattr(message, "markdown", None) or []
        markdown_text = "\n".join(
            str(getattr(item, "value", "") or "") for item in markdowns
        )
        if text in body or text in markdown_text:
            hits += 1
    return hits


def _chat_message_bodies(app: AppTest) -> list[str]:
    """Return concatenated AppTest text for each ``st.chat_message`` widget."""
    bodies: list[str] = []
    for message in app.chat_message:
        parts = [str(getattr(block, "value", "") or "") for block in message]
        markdowns = getattr(message, "markdown", None) or []
        parts.extend(str(getattr(item, "value", "") or "") for item in markdowns)
        bodies.append("\n".join(parts))
    return bodies


def test_submitted_prompt_does_not_share_widget_with_previous_assistant(
    monkeypatch,
) -> None:
    """Reopening chat_log reused the last assistant bubble; inflight keeps them apart."""
    from ui import chat
    from ui.coach_welcome import COACH_WELCOME_TITLE

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    first_prompt = "What is a design problem I could explore?"
    second_prompt = "How should I book a library study room?"
    previous_reply = "That's an interesting direction"

    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request, **_kwargs)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.chat_input[0].set_value(first_prompt).run()
    assert not app.exception
    assert submissions == [first_prompt]
    assert reruns == ["app"]
    assert _reply_visible(app, previous_reply)
    first_bodies = _chat_message_bodies(app)
    assert any(first_prompt in body for body in first_bodies)
    assert any(COACH_WELCOME_TITLE in body for body in first_bodies)
    assert not any(
        first_prompt in body and COACH_WELCOME_TITLE in body for body in first_bodies
    )

    app.chat_input[0].set_value(second_prompt).run()
    assert not app.exception
    assert submissions == [first_prompt, second_prompt]
    assert reruns == ["app", "app"]
    second_bodies = _chat_message_bodies(app)
    assert any(second_prompt in body for body in second_bodies)
    assert any(previous_reply in body for body in second_bodies)
    assert not any(
        second_prompt in body and previous_reply in body for body in second_bodies
    )
    assert _reply_message_count(app, previous_reply) == 1
    app.run()
    assert submissions == [first_prompt, second_prompt]
    assert _reply_message_count(app, previous_reply) == 1
    assert not any(
        second_prompt in body and previous_reply in body
        for body in _chat_message_bodies(app)
    )


def test_consecutive_qa_turns_keep_persisted_history(monkeypatch) -> None:
    """Each Send remounts from DSQL/SQLite history so prior Q&A cannot vanish."""
    from backend.student_store import StudentStore
    from ui import chat

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    prompts = (
        "What does week 1 say about stakeholders?",
        "What does the same lecture say about innovation?",
        "How is analogy used in that lecture?",
    )
    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request, **_kwargs)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = str(app.session_state["thread_id"])
    for prompt in prompts:
        app.chat_input[0].set_value(prompt).run()
        assert not app.exception
    assert submissions == list(prompts)
    assert reruns == ["app", "app", "app"]
    persisted = StudentStore().get_messages(thread_id)
    persisted_users = [
        str(message.get("content") or "")
        for message in persisted
        if message.get("role") == "user"
    ]
    persisted_assistants = [
        message
        for message in persisted
        if message.get("role") == "assistant"
        and str(message.get("content") or "").strip()
    ]
    for prompt in prompts:
        assert prompt in persisted_users
        assert any(prompt in body for body in _chat_message_bodies(app))
    assert len(persisted_assistants) == 1 + len(prompts)
    app.run()
    assert submissions == list(prompts)
    assert len(
        [
            message
            for message in StudentStore().get_messages(thread_id)
            if message.get("role") == "assistant"
            and str(message.get("content") or "").strip()
        ]
    ) == 1 + len(prompts)


def test_coaching_qa_coaching_keeps_history_and_skips_qa_counter(
    monkeypatch,
) -> None:
    """Coaching → Q&A → Coaching remounts from history; Q&A does not unlock Review."""
    from backend.settings import settings
    from backend.student_store import StudentStore
    from ui import chat

    monkeypatch.setattr(settings, "deep_review_interval_turns", 3)
    _force_qualifying_coaching(monkeypatch)

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    coaching_one = "I want to evaluate a crossing design for older pedestrians."
    qa_prompt = "What does week 1 say about stakeholders?"
    coaching_two = "I assume older pedestrians always need more crossing time."
    prompts = (coaching_one, qa_prompt, coaching_two)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = str(app.session_state["thread_id"])
    counters: list[int] = []
    for prompt in prompts:
        app.chat_input[0].set_value(prompt).run()
        assert not app.exception
        counters.append(_notebook_deep_review_counter(thread_id))
    assert counters == [1, 1, 2]
    assert reruns == ["app", "app", "app"]
    persisted = StudentStore().get_messages(thread_id)
    persisted_users = [
        str(message.get("content") or "")
        for message in persisted
        if message.get("role") == "user"
    ]
    for prompt in prompts:
        assert prompt in persisted_users
        assert any(prompt in body for body in _chat_message_bodies(app))
    assert app.session_state["learning_journey"]["current_stage"] == (
        "problem_identification"
    )
    app.run()
    assert _notebook_deep_review_counter(thread_id) == 2
    assert _reply_message_count(app, coaching_one) == 1
    assert _reply_message_count(app, qa_prompt) == 1
    assert _reply_message_count(app, coaching_two) == 1


def test_auto_advance_reconciles_thinking_path_after_reply_is_visible(
    monkeypatch,
) -> None:
    """Reconcile remounts from history so the assistant bubble is painted once."""
    from backend.student_journey import normalize_journey
    from backend.student_store import StudentStore
    from ui import chat

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)
    reply = "You named a concrete user group. Let's generate concepts next."

    def fake_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        yield {"event": "status", "phase": "thinking", "label": "Coach is thinking…"}
        local_store = StudentStore()
        local_store.add_message(request.thread_id, "user", request.student_message)
        local_store.add_message(request.thread_id, "assistant", reply)
        thread = local_store.get_thread(request.thread_id) or {}
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        journey["current_stage"] = "concept_generation"
        completed = list(journey.get("completed_stages") or [])
        if "problem_identification" not in completed:
            completed.append("problem_identification")
        journey["completed_stages"] = completed
        local_store.update_thread(
            request.thread_id, metadata={"learning_journey": journey}
        )
        turn = CoachTurn(
            response_text=reply,
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
    thread_id = app.session_state["thread_id"]
    app.chat_input[0].set_value("Older pedestrians need more crossing time.").run()
    assert not app.exception
    assert reruns == ["app"]
    persisted = [
        message
        for message in StudentStore().get_messages(thread_id)
        if message.get("role") == "assistant" and reply in str(message.get("content") or "")
    ]
    assert len(persisted) == 1
    assert _reply_message_count(app, reply) == 1
    assert _reply_visible(app, "You named a concrete user group")
    assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
    app.run()
    assert _reply_message_count(app, reply) == 1
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

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

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

    def fake_stream(request: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
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
        store = StudentStore()
        store.add_message(request.thread_id, "user", request.student_message)
        store.add_message(
            request.thread_id,
            "assistant",
            turn.response_text,
            metadata={
                "assessment": turn.assessment.model_dump(mode="json"),
                "source_refs": [
                    {
                        "id": source_id,
                        "label": "S1",
                        "title": "Lecture evidence",
                    }
                ],
            },
        )
        yield {"event": "done", "turn": turn.model_dump(mode="json")}

    monkeypatch.setattr(chat, "stream_coach_turn_events", fake_stream)
    app.chat_input[0].set_value("What evidence does my source provide?").run()
    assert not app.exception
    assert reruns == ["app"]
    assert source_fetches == []
    assert any(
        (button.label or "").startswith("[S1] Lecture evidence")
        for button in app.button
    )


def _deep_review_button(app: AppTest) -> Any:
    """Return the Review-tab Generate Deep Analysis PDF control."""
    app.session_state["studio_tab"] = "Review"
    app.run()
    return next(
        button
        for button in app.button
        if button.label == "Generate Deep Analysis PDF"
        and button.key == "start_deep_review"
    )


def _caption_text(app: AppTest) -> str:
    """Join Streamlit captions for Deep Review progress assertions."""
    return "\n".join(caption.value or "" for caption in app.caption)


def _force_qualifying_coaching(monkeypatch: Any) -> None:
    """Make mock coaching turns count toward the persisted Deep Review counter."""
    from backend.domain import ProviderAssessmentResult
    from backend.mock_provider import DeterministicCoachProvider

    real_assess = DeterministicCoachProvider.assess

    def qualifying_assess(self, request: Any) -> ProviderAssessmentResult:
        result = real_assess(self, request)
        if result.specialist == "coaching":
            return result.model_copy(update={"qualifying_coaching_turn": True})
        return result

    monkeypatch.setattr(DeterministicCoachProvider, "assess", qualifying_assess)


def _notebook_deep_review_counter(thread_id: str) -> int:
    """Read the persisted Deep Review counter for ``thread_id``."""
    from backend.student_store import StudentStore
    from backend.specialists.review_orchestration import (
        COUNTER_SETTINGS_KEY,
        parse_coaching_turns_since_deep_review,
    )

    thread = StudentStore().get_thread(thread_id) or {}
    return parse_coaching_turns_since_deep_review(
        (thread.get("metadata") or {}).get(COUNTER_SETTINGS_KEY)
    )


def test_deep_review_button_appears_after_qualifying_turn(monkeypatch) -> None:
    """Generate Deep Analysis PDF stays visible but locked until Reflection completes."""
    from backend.learning.stages import THINKING_STAGES
    from backend.student_store import StudentStore
    from ui import chat

    reruns: list[str] = []
    real_rerun = chat.rerun_app

    def spy_rerun() -> None:
        reruns.append("app")
        real_rerun()

    monkeypatch.setattr(chat, "rerun_app", spy_rerun)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    button = _deep_review_button(app)
    assert button.disabled is True
    app.chat_input[0].set_value(
        "I want to evaluate a crossing design for older pedestrians."
    ).run()
    assert not app.exception
    assert reruns == ["app"]
    button = _deep_review_button(app)
    assert button.disabled is True

    store = StudentStore()
    thread_id = app.session_state["thread_id"]
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    metadata["learning_journey"] = journey
    store.update_thread(thread_id, metadata=metadata)
    app.session_state["learning_journey"] = journey
    button = _deep_review_button(app)
    assert button.disabled is False


def test_deep_review_progress_caption_refreshes_after_qualifying_turn(
    monkeypatch,
) -> None:
    """Locked caption names Reflection until the full Thinking Path is complete."""
    del monkeypatch
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    button = _deep_review_button(app)
    assert button.disabled is True
    captions = _caption_text(app)
    assert "Deep Analysis PDF unlocks when the Thinking Path including Reflection" in captions


def test_ineligible_deep_review_click_does_not_start(monkeypatch) -> None:
    """A locked Generate Deep Analysis PDF control must not call the review route."""
    from ui.panels import studio as studio_panel

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def spy_start(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(studio_panel, "start_deep_review", spy_start)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    button = _deep_review_button(app)
    assert button.disabled is True
    button.click().run()
    assert not app.exception
    assert calls == []


def test_deep_review_failure_keeps_counter_and_safe_error(monkeypatch) -> None:
    """Failed Deep Analysis leaves eligibility intact and hides provider text."""
    from backend.learning.stages import THINKING_STAGES
    from backend.student_store import StudentStore
    from ui.panels import studio as studio_panel

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("AgentCore timeout in us-west-2")

    monkeypatch.setattr(studio_panel, "start_deep_review", boom)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    store = StudentStore()
    thread_id = app.session_state["thread_id"]
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    metadata["learning_journey"] = journey
    store.update_thread(thread_id, metadata=metadata)
    app.session_state["learning_journey"] = journey
    button = _deep_review_button(app)
    assert button.disabled is False
    before = _notebook_deep_review_counter(thread_id)
    button.click().run()
    assert not app.exception
    errors = "\n".join(error.value or "" for error in app.error)
    assert "Deep Analysis PDF could not be completed. Try again." in errors
    assert "AgentCore" not in errors
    assert "us-west-2" not in errors
    assert _notebook_deep_review_counter(thread_id) == before
    assert _deep_review_button(app).disabled is False


def test_chat_stays_enabled_while_persisted_deep_review_job_is_running() -> None:
    """Review spinner follows the backend job, not a Streamlit session flag."""
    from backend.specialists.review_orchestration import (
        COUNTER_SETTINGS_KEY,
        DEEP_REVIEW_JOB_KEY,
        DEEP_REVIEW_JOB_RUNNING,
    )
    from backend.student_store import StudentStore
    from backend.persistence.store.contracts import utc_now

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    started = utc_now()
    StudentStore().update_thread(
        thread_id,
        metadata={
            COUNTER_SETTINGS_KEY: 3,
            DEEP_REVIEW_JOB_KEY: {
                "review_id": "ui-running",
                "status": DEEP_REVIEW_JOB_RUNNING,
                "reviewed_revision": 0,
                "stage_at_start": "problem_identification",
                "source_ids": [],
                "message_ids": [],
                "started_at": started,
                "updated_at": started,
                "error_code": None,
            },
        },
    )
    app.run()
    assert not app.exception
    assert app.chat_input
    assert _deep_review_button(app).disabled is True
    assert "_deep_review_running_thread_id" not in app.session_state
