"""Privacy-safe timing of real Strands Fast Chat stream events."""

from __future__ import annotations

from agentcore_runtime.main import _first_text_timing_callback


def test_structured_reply_timing_waits_for_response_text_character() -> None:
    """Metadata and partial JSON keys are not counted as visible reply text."""
    capture, timings = _first_text_timing_callback(0.0)
    capture(
        type="tool_use_stream",
        delta={"toolUse": {"input": '{"mode":"coaching","res'}},
        current_tool_use={"toolUseId": "tool-1"},
    )
    assert "model_first_content_ms" in timings
    assert "model_first_reply_text_ms" not in timings
    capture(
        type="tool_use_stream",
        delta={"toolUse": {"input": 'ponse_text":"H'}},
        current_tool_use={"toolUseId": "tool-1"},
    )
    assert "model_first_reply_text_ms" in timings
    assert all(isinstance(value, int) for value in timings.values())


def test_unstructured_repair_prose_is_not_counted_as_reply_text() -> None:
    """A failed first cycle cannot claim that its prose was the coach reply."""
    capture, timings = _first_text_timing_callback(0.0)
    capture(data="I cannot return a structured result.")
    assert "model_first_content_ms" in timings
    assert "model_first_reply_text_ms" not in timings
    capture(
        type="tool_use_stream",
        delta={"toolUse": {"input": '{"response_text":"Valid reply"}'}},
        current_tool_use={"toolUseId": "repair-tool"},
    )
    assert "model_first_reply_text_ms" in timings
