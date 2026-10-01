"""UI TIMING logger visibility, privacy, and pre-API span contracts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator

from streamlit.testing.v1 import AppTest

from ui.services import runtime as runtime_module


def _flagged_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """Return handlers marked as the Streamlit ui_perf stderr stream."""
    return [
        handler
        for handler in logger.handlers
        if getattr(handler, runtime_module._UI_PERF_HANDLER_FLAG, False)
        or getattr(handler, runtime_module._OPERATIONAL_HANDLER_FLAG, False)
    ]


def test_ui_perf_info_is_dropped_until_configured(capsys) -> None:
    """INFO UI TIMING is invisible under Streamlit's WARNING lastResort."""
    logger = logging.getLogger(runtime_module._UI_PERF_LOGGER_NAME)
    root = logging.getLogger()
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    previous_root_level = root.level
    try:
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
        root.setLevel(logging.WARNING)
        logger.info("UI TIMING hidden_probe=1")
        hidden = capsys.readouterr()
        assert "hidden_probe" not in hidden.out
        assert "hidden_probe" not in hidden.err
        runtime_module.configure_ui_perf_logger()
        assert logger.isEnabledFor(logging.INFO)
        runtime_module.log_ui_timing(request_id="rid-visible", pre_api_ms=1.5)
        shown = capsys.readouterr()
        combined = f"{shown.out}{shown.err}"
        assert "UI TIMING" in combined
        assert "request_id=rid-visible" in combined
        assert "pre_api_ms=1.5" in combined
        assert root.level == logging.WARNING
    finally:
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        root.setLevel(previous_root_level)


def test_configure_ui_perf_logger_is_idempotent() -> None:
    """Repeated setup must not stack Streamlit rerun handlers."""
    logger = logging.getLogger(runtime_module._UI_PERF_LOGGER_NAME)
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    try:
        logger.handlers.clear()
        runtime_module.configure_ui_perf_logger()
        runtime_module.configure_ui_perf_logger()
        runtime_module.configure_ui_perf_logger()
        flagged = _flagged_handlers(logger)
        assert len(flagged) == 1
        assert logger.level == logging.INFO
        assert logger.isEnabledFor(logging.INFO)
    finally:
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)


def test_log_ui_timing_drops_whitespace_and_keeps_request_id(capsys) -> None:
    """Strings with whitespace are rejected; request_id tokens are kept."""
    logger = logging.getLogger(runtime_module._UI_PERF_LOGGER_NAME)
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    try:
        logger.handlers.clear()
        runtime_module.configure_ui_perf_logger()
        runtime_module.log_ui_timing(
            request_id="abc-123",
            note="hello student prompt",
            prompt="What is a design problem I could explore?",
            pre_api_ms=12.0,
        )
        shown = capsys.readouterr()
        combined = f"{shown.out}{shown.err}"
        assert "UI TIMING" in combined
        assert "request_id=abc-123" in combined
        assert "pre_api_ms=12.0" in combined
        assert "hello student prompt" not in combined
        assert "What is a design problem" not in combined
        assert "note=" not in combined
        assert "prompt=" not in combined
    finally:
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)


def test_handle_prompt_timing_fields_exclude_student_text() -> None:
    """Send telemetry kwargs are numeric/request_id only."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    send_block = chat.split("def handle_prompt(", 1)[1].split(
        "def _confirm_edit_earlier_message_dialog", 1
    )[0]
    timing = send_block.split("log_ui_timing(", 1)[1].split(
        "def _close_thinking", 1
    )[0]
    assert "request_id=request_id" in timing
    assert "fragment_to_api_ms=" in timing
    assert "pre_api_ms=" in timing
    assert "composer_layout_ms=" in timing
    assert "thread_lookup_ms=" in timing
    assert "pending_user_render_ms=" in timing
    assert "chat_scroll_send_ms=" in timing
    assert "thinking_render_ms=" in timing
    assert "prompt_accept_ms=" in timing
    assert "student_message" not in timing
    assert "prompt=" not in timing
    assert "thread_id" not in timing
    assert "content" not in timing


def test_fragment_submit_architecture_unchanged() -> None:
    """Send still stays inside the composer fragment and does not pull rails."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    normalized = chat.replace("\r\n", "\n")
    assert "@st.fragment\ndef _render_composer_submit_fragment(" in normalized
    composer_block = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    composer_body = composer_block.split('"""', 2)[-1]
    assert "render_studio_panel(" not in composer_body
    assert "render_sources_panel(" not in composer_body
    assert "st.chat_input(" in composer_body
    assert "sync_composer_layout(" in composer_body
    assert "handle_prompt(" in composer_body
    assert "rerun_app()" not in composer_body
    send_block = chat.split("def handle_prompt(", 1)[1].split(
        "def _confirm_edit_earlier_message_dialog", 1
    )[0]
    assert "stream_coach_turn_events(" in send_block
    assert "rerun_app()" in send_block


def test_streamlit_entrypoint_configures_ui_perf_logger() -> None:
    """Production Streamlit process must configure ui_perf independently of FastAPI."""
    entry = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "configure_ui_perf_logger" in entry
    runtime = Path("ui/services/runtime.py").read_text(encoding="utf-8")
    assert "def configure_ui_perf_logger(" in runtime
    assert 'logging.getLogger("co_design.ui_perf")' in runtime or (
        "_UI_PERF_LOGGER_NAME" in runtime
    )
    assert "StreamHandler" in runtime


def test_send_emits_pre_api_spans_without_prompt_text(monkeypatch, caplog) -> None:
    """One mock Send logs step timings and never echoes the student prompt."""
    from ui import chat

    caplog.set_level(logging.INFO, logger=runtime_module._UI_PERF_LOGGER_NAME)
    runtime_module.configure_ui_perf_logger()
    prompt = "What is a design problem I could explore?"
    submissions: list[str] = []
    real_stream = chat.stream_coach_turn_events

    def counting_stream(request: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        submissions.append(request.student_message)
        yield from real_stream(request, **kwargs)

    monkeypatch.setattr(chat, "stream_coach_turn_events", counting_stream)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.chat_input[0].set_value(prompt).run()
    assert not app.exception
    assert submissions == [prompt]
    lines = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("UI TIMING")
    ]
    joined = "\n".join(lines)
    assert lines
    assert prompt not in joined
    assert "fragment_to_api_ms=" in joined
    assert "pre_api_ms=" in joined
    assert "composer_layout_ms=" in joined
    assert "thread_lookup_ms=" in joined
    assert "pending_user_render_ms=" in joined
    assert "chat_scroll_send_ms=" in joined
    assert "thinking_render_ms=" in joined
    assert "request_id=" in joined
    assert "stream_ms=" in joined
    assert "api_to_started_ms=" in joined or "api_to_first_event_ms=" in joined
