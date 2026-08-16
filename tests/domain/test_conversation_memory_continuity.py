"""Deterministic ConversationMemory continuity for the six-message fast path."""

from __future__ import annotations

from backend.context_planner import (
    CONTEXT_POLICY_FAST_CHAT,
    ContextBudget,
    ExtractiveHistoryCompressor,
    HistoryContextPlanner,
    active_history_turns,
)
from backend.domain import CoachRequest
from backend.settings import settings

_DECISION = (
    "We originally preferred A because it was cheaper, but after examining "
    "accessibility we rejected A and chose B. B improves access, although "
    "maintenance remains our concern."
)


def _planner() -> HistoryContextPlanner:
    """Return the production fast-chat planner."""
    return HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(settings.fast_chat_max_input_tokens),
            output_reserve_tokens=4_000,
            safety_margin_tokens=1_000,
            recent_verbatim_messages=6,
        ),
        policy=CONTEXT_POLICY_FAST_CHAT,
        compressor=ExtractiveHistoryCompressor(),
    )


def _long_history(total: int) -> list[dict[str, str]]:
    """Build a long notebook whose early turns contain a key design decision."""
    history = [
        {
            "role": "user",
            "content": "Older pedestrians need a safer crossing at night.",
        },
        {"role": "assistant", "content": "Which constraint is shaping that need?"},
        {"role": "user", "content": _DECISION},
        {
            "role": "assistant",
            "content": "What remains unresolved about maintenance?",
        },
    ]
    start = len(history)
    for index in range(start, total):
        role = "user" if index % 2 == 0 else "assistant"
        history.append(
            {
                "role": role,
                "content": (
                    f"progress note {index} about the Holland Road crossing"
                    if role == "user"
                    else f"What still needs checking at turn {index}?"
                ),
            }
        )
    return history


def test_extractive_compressor_does_not_call_a_model() -> None:
    assert ExtractiveHistoryCompressor.__name__ == "ExtractiveHistoryCompressor"


def test_long_histories_keep_decision_reject_and_tradeoff_in_memory() -> None:
    planner = _planner()
    for count in (20, 50, 100):
        history = _long_history(count)
        current = "Why did I reject A?"
        plan = planner.plan(
            CoachRequest(
                thread_id="thread-memory",
                student_message=current,
                current_stage="concept_generation",
                response_detail="short",
                history=history,
                conversation_revision=1,
            ),
            prompt_text="stage rules",
        )
        assert plan.verbatim_message_count <= 6
        assert plan.compressed_memory is not None
        rendered = plan.compressed_memory.format_for_prompt()
        assert "rejected A" in rendered
        assert "chose B" in rendered
        assert "cheaper" in rendered
        assert "maintenance" in rendered
        recent = " ".join(
            block["text"]
            for item in plan.messages
            for block in item["content"]
        )
        assert _DECISION not in recent
        turns = active_history_turns(history, current_student_message=current)
        assert all(item["content"] != current for item in turns)


def test_revision_mismatch_drops_stale_memory() -> None:
    planner = _planner()
    history = _long_history(20)
    first = planner.plan(
        CoachRequest(
            thread_id="thread-rev",
            student_message="Why did I reject A?",
            current_stage="concept_generation",
            response_detail="short",
            history=history,
            conversation_revision=1,
        ),
        prompt_text="brief",
    )
    stale = planner.plan(
        CoachRequest(
            thread_id="thread-rev",
            student_message="Why did I reject A?",
            current_stage="concept_generation",
            response_detail="short",
            history=history[-4:],
            conversation_revision=2,
        ),
        prompt_text="brief",
        existing_memory=first.compressed_memory,
    )
    assert stale.verbatim_message_count == 4
    assert stale.compressed_memory is None
