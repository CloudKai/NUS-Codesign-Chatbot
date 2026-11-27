"""Deterministic ConversationMemory continuity for the six-message fast path."""

from __future__ import annotations

from typing import Any

from backend.context_planner import (
    CONTEXT_POLICY_FAST_CHAT,
    ConversationMemory,
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
            recent_history_max_tokens=int(settings.fast_chat_recent_history_max_tokens),
            history_message_max_tokens=int(
                settings.fast_chat_history_message_max_tokens
            ),
            soft_input_tokens=int(settings.fast_chat_soft_input_tokens),
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


def test_chunky_history_preserves_rejected_alternative_in_memory() -> None:
    planner = _planner()
    bulky = "Pasted ChatGPT draft. " + ("lorem ipsum " * 1_200)
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
    for index in range(26):
        role = "user" if index % 2 == 0 else "assistant"
        history.append(
            {
                "role": role,
                "content": bulky if role == "user" else f"What still needs checking {index}?",
            }
        )
    plan = planner.plan(
        CoachRequest(
            thread_id="thread-chunky",
            student_message="Why did I reject A?",
            current_stage="concept_generation",
            response_detail="short",
            history=history,
            conversation_revision=1,
        ),
        prompt_text="stage rules",
    )
    assert plan.verbatim_message_count <= 6
    assert plan.estimated_recent_history_tokens <= 3_000
    assert plan.compressed_memory is not None
    rendered = plan.compressed_memory.format_for_prompt()
    assert "rejected A" in rendered
    assert "chose B" in rendered
    assert "accessibility" in rendered.lower()
    assert "maintenance" in rendered


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


def _compress(messages: list[dict[str, Any]], *, existing=None) -> "ConversationMemory":
    """Compress aged turns with the extractive compressor (no recent window)."""
    return ExtractiveHistoryCompressor().compress(
        aged_messages=messages, existing=existing, conversation_revision=1
    )


def test_later_correction_supersedes_earlier_selection() -> None:
    """A student correcting their own choice is remembered as the current one."""
    memory = _compress(
        [
            {"role": "user", "content": "We originally chose QR codes for sign-up."},
            {"role": "assistant", "content": "What about when students are offline?"},
            {"role": "user", "content": "Actually we switched to pictograms "
                "because the site has patchy internet."},
        ]
    )
    assert memory.selected_concept
    assert "QR codes" not in memory.selected_concept
    assert "pictograms" in memory.selected_concept
    # The replaced choice is documented, not silently kept at equal authority.
    assert any("QR codes" in item for item in memory.changes_in_reasoning)
    assert all("QR codes" not in item for item in memory.key_decisions)
    assert all("QR codes" not in item for item in memory.rejected_alternatives)
    assert memory.selected_concept_turn == 2


def test_correction_removes_stale_decision_across_compressions() -> None:
    """Recency ordering survives incremental compression across batches."""
    first = _compress(
        [
            {"role": "user", "content": "We preferred A because it was cheaper "
                "but then chose B for accessibility."},
            {"role": "assistant", "content": "Does that still hold now?"},
        ]
    )
    second = _compress(
        [
            {"role": "user", "content": "We decided to use pictograms; "
                "actually switch away from B."},
        ],
        existing=first,
    )
    assert any("pictograms" in d for d in second.key_decisions)
    # The latest turn's concept is the current selection.
    assert "pictograms" in second.selected_concept
    assert second.selected_concept_turn == 2
    # The earlier B decision is demoted into changes_in_reasoning.
    assert any(
        "B" in d
        for d in second.changes_in_reasoning
    ), second.changes_in_reasoning


def test_legacy_memory_without_turns_is_superseded() -> None:
    """A memory created before turn tracking still lets a correction win."""
    legacy = ConversationMemory.model_validate(
        {
            "conversation_revision": 1,
            "selected_concept": "QR codes",
            "key_decisions": ["Originally chose QR codes."],
            # no key_decision_turns -> unknown (-1), always superseded
        }
    )
    updated = _compress(
        [
            {"role": "user", "content": "We went with pictograms after all."},
        ],
        existing=legacy,
    )
    assert "QR codes" not in updated.selected_concept
    assert "pictograms" in updated.selected_concept


def test_incremental_compression_does_not_mutate_existing_memory() -> None:
    """A request-local correction must not corrupt the saved projection it read."""
    existing = _compress([
        {"role": "user", "content": "We chose QR codes for sign-up."},
        {"role": "user", "content": "We decided the sign must cost at most $30."},
    ])
    before = existing.model_dump(mode="json")
    updated = _compress([
        {"role": "user", "content": "Actually we chose pictograms instead of QR codes."},
    ], existing=existing)
    assert "pictograms" in updated.selected_concept
    assert existing.model_dump(mode="json") == before
    assert "We decided the sign must cost at most $30." in updated.key_decisions


def test_spec_scenario_two_recovers_current_concept_and_connectivity_constraint() -> None:
    """QR codes -> pictograms (patchy internet) surfaces the current concept AND
    the connectivity constraint, not the superseded concept."""
    memory = _compress(
        [
            {"role": "user", "content": "We originally chose QR codes to track attendance."},
            {"role": "assistant", "content": "Any constraints on how they attend?"},
            {"role": "user", "content": "The site has patchy internet, so attendance "
                "must work offline."},
            {"role": "assistant", "content": "Should we change the tracking method?"},
            {"role": "user", "content": "Actually we switched to pictograms because of it."},
        ]
    )
    assert "pictograms" in memory.selected_concept
    assert "QR codes" not in memory.selected_concept
    assert any(
        ("internet" in d or "offline" in d or "patchy" in d)
        for d in memory.constraints
    ), memory.constraints
    assert any("QR codes" in d for d in memory.changes_in_reasoning), memory.changes_in_reasoning


def test_spec_scenario_one_preserves_budget_constraint_without_the_word() -> None:
    """A '$30' budget is captured even when the student never wrote 'budget'."""
    memory = _compress(
        [
            {"role": "user", "content": "We can build the sign for at most $30."},
            {"role": "assistant", "content": "Anything else to factor in?"},
            {"role": "user", "content": "It must fit a small classroom grant."},
        ]
    )
    assert any(
        "$30" in d and "at most" in d for d in memory.constraints
    ), memory.constraints


def test_spec_scenario_one_budget_survives_full_transcript() -> None:
    """The budget constraint survives past the recent window in memory."""
    base = [
        {"role": "user", "content": "We can build the sign for at most $30."},
        {"role": "assistant", "content": "Noted."},
    ]
    filler = []
    for index in range(30):
        role = "user" if index % 2 == 0 else "assistant"
        filler.append(
            {"role": role, "content": (
                "progress note about the Holland Road crossing"
                if role == "user"
                else "what still needs checking at turn " + str(index)
            )}
        )
    memory = _compress(base + filler)
    assert any(
        "$30" in d for d in memory.constraints
    ), memory.constraints
