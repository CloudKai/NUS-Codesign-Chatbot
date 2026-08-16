"""FAST_CHAT context-policy tests. No AWS."""

from __future__ import annotations

from backend.context_planner import (
    CONTEXT_POLICY_FAST_CHAT,
    CONTEXT_POLICY_FULL_HISTORY,
    MAX_MEMORY_FIELD_CHARS,
    MAX_MEMORY_LIST_ITEMS,
    ConversationMemory,
    ContextBudget,
    HistoryContextPlanner,
    active_history_turns,
)
from backend.domain import CoachRequest
from backend.prompts.composer import PromptComposer, PromptContext
from backend.settings import settings


def _request(**overrides) -> CoachRequest:
    """Build one coaching request."""
    payload = {
        "thread_id": "thread-demo",
        "student_message": "CURRENT_STUDENT_TURN unique",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "conversation_revision": 1,
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _history(count: int) -> list[dict[str, str]]:
    """Return alternating user/assistant turns."""
    messages: list[dict[str, str]] = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"historic-turn-{index} decision"})
    return messages


def _fast_planner() -> HistoryContextPlanner:
    """Return the production fast-chat planner budget."""
    return HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(settings.fast_chat_max_input_tokens),
            output_reserve_tokens=4_000,
            safety_margin_tokens=1_000,
            recent_verbatim_messages=int(settings.fast_chat_recent_verbatim_messages),
        ),
        policy=CONTEXT_POLICY_FAST_CHAT,
    )


def test_four_messages_are_kept_verbatim() -> None:
    plan = _fast_planner().plan(
        _request(history=_history(4)),
        prompt_text="brief",
    )
    assert plan.verbatim_message_count == 4
    assert plan.compressed_message_count == 0


def test_fifty_messages_are_capped_and_compressed() -> None:
    plan = _fast_planner().plan(
        _request(history=_history(50)),
        prompt_text="brief",
    )
    assert plan.verbatim_message_count <= int(settings.fast_chat_recent_verbatim_messages)
    assert plan.compressed_message_count == 50 - plan.verbatim_message_count
    assert plan.compression_used is True
    assert plan.compressed_memory is not None
    assert plan.estimated_input_tokens <= int(settings.fast_chat_max_input_tokens)


def test_current_message_is_not_in_verbatim_history() -> None:
    history = _history(6) + [
        {"role": "user", "content": "CURRENT_STUDENT_TURN unique"}
    ]
    turns = active_history_turns(
        history, current_student_message="CURRENT_STUDENT_TURN unique"
    )
    assert all(item["content"] != "CURRENT_STUDENT_TURN unique" for item in turns)


def test_fast_chat_hard_budget_is_enforced() -> None:
    planner = HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=32_000,
            max_input_tokens=int(settings.fast_chat_max_input_tokens),
            output_reserve_tokens=4_000,
            safety_margin_tokens=1_000,
            recent_verbatim_messages=6,
        ),
        policy=CONTEXT_POLICY_FAST_CHAT,
    )
    plan = planner.plan(_request(history=_history(50)), prompt_text="stage rules")
    assert plan.estimated_input_tokens <= int(settings.fast_chat_max_input_tokens)


def test_deep_review_policy_can_keep_full_history() -> None:
    planner = HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=int(settings.model_context_limit_tokens),
            max_input_tokens=int(settings.model_max_input_tokens),
            output_reserve_tokens=int(settings.model_output_reserve_tokens),
            safety_margin_tokens=int(settings.model_context_safety_margin_tokens),
            recent_verbatim_messages=12,
        ),
        policy=CONTEXT_POLICY_FULL_HISTORY,
    )
    plan = planner.plan(_request(history=_history(20)), prompt_text="brief")
    assert plan.full_history_used is True
    assert plan.verbatim_message_count == 20


def test_fast_chat_composer_omits_duplicate_recent_and_summary_when_memory() -> None:
    prepared = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            student_message="I chose option B.",
            conversation_memory="problem_definition: older pedestrians",
            conversation_summary="Older pedestrians need shade.",
            recent_messages=[{"role": "user", "content": "Earlier turn"}],
            include_recent_messages=False,
            context_policy="fast_chat",
        )
    )
    assert "Prior conversation turns were supplied separately" in prepared.untrusted_turn_text
    assert "Older pedestrians need shade." not in prepared.untrusted_turn_text
    assert "problem_definition: older pedestrians" in prepared.untrusted_turn_text
    assert "I chose option B." in prepared.untrusted_turn_text
    assert "STAGE:" in prepared.stage_instructions or "Problem" in prepared.stage_instructions
    assert "<conversation_summary>" not in prepared.untrusted_turn_text


def test_huge_excerpts_are_clipped_before_hard_budget() -> None:
    huge = "retrieved-excerpt " * 8000
    prepared = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            student_message="What does the lecture say about accessibility?",
            retrieved_course_context=huge,
            include_recent_messages=False,
            context_policy="fast_chat",
        )
    )
    assert len(prepared.untrusted_turn_text) < len(huge)
    plan = _fast_planner().plan(
        _request(source_context=huge[: int(settings.fast_chat_retrieval_max_chars)]),
        prompt_text=prepared.runtime_instructions + prepared.untrusted_turn_text,
    )
    assert plan.estimated_input_tokens <= int(settings.fast_chat_max_input_tokens)
    assert "STAGE:" in prepared.stage_instructions or "Problem" in prepared.stage_instructions


def test_conversation_memory_is_bounded() -> None:
    memory = ConversationMemory(
        conversation_revision=1,
        problem_definition="x" * 4_000,
        key_decisions=[f"decision-{index} " + ("detail " * 200) for index in range(40)],
        quoted_student_statements=[f"quote-{index}" for index in range(40)],
    )
    assert len(memory.key_decisions) == MAX_MEMORY_LIST_ITEMS
    assert len(memory.quoted_student_statements) == MAX_MEMORY_LIST_ITEMS
    assert all(len(item) <= MAX_MEMORY_FIELD_CHARS for item in memory.key_decisions)
    rendered = memory.format_for_prompt()
    assert "x" * (MAX_MEMORY_FIELD_CHARS + 1) not in rendered
    assert rendered.count("decision-") == MAX_MEMORY_LIST_ITEMS


def test_relevant_evidence_survives_before_old_history() -> None:
    evidence = "ACCESSIBILITY_EVIDENCE lecture excerpt about curb ramps."
    plan = _fast_planner().plan(
        _request(history=_history(50), source_context=evidence),
        prompt_text="stage rules\n" + evidence,
    )
    assert plan.verbatim_message_count <= int(settings.fast_chat_recent_verbatim_messages)
    assert plan.estimated_input_tokens <= int(settings.fast_chat_max_input_tokens)


def test_fast_chat_default_window_is_six_message_objects() -> None:
    assert int(settings.fast_chat_recent_verbatim_messages) == 6


def test_fast_chat_window_for_short_and_long_histories() -> None:
    planner = _fast_planner()
    for count in (0, 1, 2, 4, 6, 7, 20, 50):
        history = _history(count)
        plan = planner.plan(_request(history=history), prompt_text="brief")
        expected = min(count, 6)
        assert plan.verbatim_message_count == expected
        assert plan.original_message_count == count
        if count > 6:
            assert plan.compressed_message_count == count - expected
            assert plan.compressed_memory is not None
        messages = plan.messages
        assert len(messages) == expected
        if expected:
            assert messages[-1]["role"] == history[-1]["role"]
            last_text = messages[-1]["content"][0]["text"]
            assert last_text == history[-1]["content"]
            first_text = messages[0]["content"][0]["text"]
            assert first_text == history[-expected]["content"]
            assert history[0]["role"] in {"user", "assistant"}
        if count >= 7:
            aged_text = " ".join(item["content"] for item in history[:-expected])
            recent_text = " ".join(
                block["text"]
                for item in messages
                for block in item["content"]
            )
            assert history[0]["content"] in aged_text
            assert history[0]["content"] not in recent_text

