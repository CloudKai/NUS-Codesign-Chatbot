"""AppTest coverage for the progressive Problem Identification How Might We scaffold."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from backend.learning.hmw import HMW_SCAFFOLD_STAGE_ID, hmw_scaffold_available
from backend.student_journey import DEFAULT_STAGE, next_stage_id
from backend.student_store import StudentStore
from ui.coach_welcome import (
    COACH_WELCOME_KIND,
    COACH_WELCOME_TITLE,
    HMW_FORMULA,
    HMW_FORMULA_OUTRO,
    HMW_SCAFFOLD_LEAD,
    HMW_SCAFFOLD_TITLE,
    transcript_hmw_render_plan,
)


_FIRST_USER = "Older pedestrians struggle at the school crossing."
_FIRST_COACH = "What specifically is hardest at the crossing?"
_SECOND_USER = (
    "Some older pedestrians cannot reach the other side before the signal changes."
)
_SECOND_COACH = "What outcome would you want to improve?"
_THIRD_COACH = "What evidence makes that outcome matter most?"
_QA_USER = "What does the Week 1 lecture say about crossings?"
_QA_ASSISTANT = "Week 1 describes pedestrian crossing times."
_REVIEW_ASSISTANT = "Formative review of the crossing problem."


def _visible_text(app: AppTest) -> str:
    """Return concatenated markdown, code, and chat-message text."""
    parts = [str(item.value or "") for item in app.markdown]
    code = getattr(app, "code", None)
    if code:
        for block in code:
            parts.append(str(getattr(block, "value", "") or ""))
    for message in app.chat_message:
        parts.extend(str(getattr(block, "value", "") or "") for block in message)
        markdowns = getattr(message, "markdown", None) or []
        parts.extend(str(getattr(item, "value", "") or "") for item in markdowns)
        codes = getattr(message, "code", None) or []
        parts.extend(str(getattr(item, "value", "") or "") for item in codes)
    return "\n".join(parts)


def _widget_values(widgets: list[object]) -> list[str]:
    """Return string values from an AppTest widget list."""
    return [str(getattr(item, "value", "") or "") for item in widgets]


def _formula_code_count(app: AppTest) -> int:
    """Return how many st.code blocks show the HMW formula."""
    count = 0
    code = getattr(app, "code", None) or []
    count += sum(
        1 for block in code if HMW_FORMULA == str(getattr(block, "value", "") or "")
    )
    for message in app.chat_message:
        codes = getattr(message, "code", None) or []
        count += sum(
            1
            for block in codes
            if HMW_FORMULA == str(getattr(block, "value", "") or "")
        )
    return count


def _hmw_inside_chat_messages(app: AppTest) -> bool:
    """Return whether the HMW card leaked into an assistant chat bubble."""
    for message in app.chat_message:
        markdowns = getattr(message, "markdown", None) or []
        if any(
            HMW_SCAFFOLD_TITLE in str(getattr(item, "value", "") or "")
            for item in markdowns
        ):
            return True
        codes = getattr(message, "code", None) or []
        if any(
            HMW_FORMULA == str(getattr(block, "value", "") or "") for block in codes
        ):
            return True
    return False


def _pi_coaching(*, ready: bool = False) -> dict[str, object]:
    """Return a Problem Identification Coaching assessment mapping."""
    assessment: dict[str, object] = {
        "current_stage": "problem_identification",
        "response_mode": "coaching",
        "recommendation": "stay",
        "citations": [],
    }
    if ready:
        assessment["hmw_scaffold_ready"] = True
    return assessment


def _welcome_row() -> dict[str, object]:
    """Return a visible Coach welcome message mapping."""
    return {
        "role": "assistant",
        "content": f"**{COACH_WELCOME_TITLE}**\n\nHello.",
        "metadata": {"kind": COACH_WELCOME_KIND, "workflow": "welcome"},
    }


def _plan_tokens(
    messages: list[dict[str, object]],
    *,
    hmw_available: bool,
) -> list[str]:
    """Return render-plan tokens for welcome, HMW, and message contents."""
    tokens: list[str] = []
    for kind, message in transcript_hmw_render_plan(
        messages, hmw_available=hmw_available
    ):
        if kind == "hmw":
            tokens.append("hmw")
            continue
        assert message is not None
        if str((message.get("metadata") or {}).get("kind") or "") == COACH_WELCOME_KIND:
            tokens.append("welcome")
        elif str(message.get("role") or "") == "user":
            tokens.append("user")
        else:
            tokens.append(str(message.get("content") or "assistant"))
    return tokens


def _seed_ready_coaching(store: StudentStore, thread_id: str) -> None:
    """Persist one Problem Identification Coaching turn with HMW readiness."""
    store.add_message(thread_id, "user", _FIRST_USER)
    store.add_message(
        thread_id,
        "assistant",
        _FIRST_COACH,
        metadata={"assessment": _pi_coaching(ready=True)},
    )


def test_hmw_stage_id_is_canonical_problem_identification() -> None:
    assert HMW_SCAFFOLD_STAGE_ID == DEFAULT_STAGE
    assert HMW_SCAFFOLD_STAGE_ID == "problem_identification"
    assert next_stage_id(HMW_SCAFFOLD_STAGE_ID) == "concept_generation"


def test_plan_hides_hmw_when_not_available() -> None:
    """Placement helper must not insert the card when the gate is false."""
    messages = [
        _welcome_row(),
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _FIRST_COACH,
            "metadata": {"assessment": _pi_coaching()},
        },
    ]
    assert _plan_tokens(messages, hmw_available=False) == [
        "welcome",
        "user",
        _FIRST_COACH,
    ]


def test_plan_places_hmw_after_unlocking_coach_response() -> None:
    """Eligible notebooks insert exactly one card after the unlocking Coach turn."""
    first_coach = {
        "role": "assistant",
        "content": _FIRST_COACH,
        "metadata": {"assessment": _pi_coaching(ready=True)},
    }
    second_coach = {
        "role": "assistant",
        "content": _SECOND_COACH,
        "metadata": {"assessment": _pi_coaching(ready=True)},
    }
    messages = [
        {"role": "assistant", "content": "", "metadata": {"kind": COACH_WELCOME_KIND}},
        _welcome_row(),
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        first_coach,
        {"role": "user", "content": _SECOND_USER, "metadata": {}},
        second_coach,
        {"role": "user", "content": _QA_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _QA_ASSISTANT,
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "response_mode": "qa",
                    "citations": [],
                }
            },
        },
    ]
    assert _plan_tokens(messages, hmw_available=True) == [
        "welcome",
        "user",
        _FIRST_COACH,
        "hmw",
        "user",
        _SECOND_COACH,
        "user",
        _QA_ASSISTANT,
    ]


def test_plan_keeps_sticky_anchor_after_later_ready_stay() -> None:
    """A later stay/ready Coaching turn must not move the card."""
    messages = [
        _welcome_row(),
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _FIRST_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
        {"role": "user", "content": _SECOND_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _SECOND_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
        {"role": "user", "content": "I want them to cross without rushing.", "metadata": {}},
        {
            "role": "assistant",
            "content": _THIRD_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
    ]
    assert _plan_tokens(messages, hmw_available=True) == [
        "welcome",
        "user",
        _FIRST_COACH,
        "hmw",
        "user",
        _SECOND_COACH,
        "user",
        _THIRD_COACH,
    ]


def test_plan_places_hmw_after_first_visible_ready_without_welcome() -> None:
    """Legacy notebooks without a welcome still anchor after the unlocking Coach."""
    messages = [
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _FIRST_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
        {"role": "user", "content": _SECOND_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _SECOND_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
    ]
    assert _plan_tokens(messages, hmw_available=True) == [
        "user",
        _FIRST_COACH,
        "hmw",
        "user",
        _SECOND_COACH,
    ]
    assert "hmw" not in _plan_tokens(messages, hmw_available=False)


def test_deep_review_does_not_move_hmw_anchor() -> None:
    """Deep Review after unlock must not become the HMW anchor."""
    messages = [
        _welcome_row(),
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _FIRST_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
        {"role": "user", "content": _SECOND_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _SECOND_COACH,
            "metadata": {"assessment": _pi_coaching(ready=True)},
        },
        {
            "role": "assistant",
            "content": _REVIEW_ASSISTANT,
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "recommendation": "stay",
                    "hmw_scaffold_ready": True,
                    "review_depth": "deep",
                    "review_trigger": "explicit",
                    "review_model": "global.anthropic.claude-sonnet-4-6",
                }
            },
        },
    ]
    assert _plan_tokens(messages, hmw_available=True) == [
        "welcome",
        "user",
        _FIRST_COACH,
        "hmw",
        "user",
        _SECOND_COACH,
        _REVIEW_ASSISTANT,
    ]


def test_three_weak_coaching_turns_hide_hmw() -> None:
    """Turn count alone never unlocks the scaffold."""
    messages = [
        _welcome_row(),
        {"role": "user", "content": _FIRST_USER, "metadata": {}},
        {
            "role": "assistant",
            "content": _FIRST_COACH,
            "metadata": {"assessment": _pi_coaching()},
        },
        {"role": "user", "content": "People have problems.", "metadata": {}},
        {
            "role": "assistant",
            "content": _SECOND_COACH,
            "metadata": {"assessment": _pi_coaching()},
        },
        {"role": "user", "content": "I want things to be better.", "metadata": {}},
        {
            "role": "assistant",
            "content": _THIRD_COACH,
            "metadata": {"assessment": _pi_coaching()},
        },
    ]
    assert hmw_scaffold_available("problem_identification", messages) is False
    assert "hmw" not in _plan_tokens(messages, hmw_available=False)


def test_valid_hmw_advance_never_shows_scaffold() -> None:
    """A completed student HMW hides the construction card even while still on PI."""
    messages = [
        _welcome_row(),
        {
            "role": "user",
            "content": (
                "How might we improve road crossings near schools for older "
                "pedestrians so that they can cross safely without rushing?"
            ),
            "metadata": {},
        },
        {
            "role": "assistant",
            "content": "That is specific enough to guide ideation.",
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "response_mode": "coaching",
                    "recommendation": "advance",
                    "hmw_scaffold_ready": False,
                    "citations": [],
                }
            },
        },
    ]
    assert hmw_scaffold_available("problem_identification", messages) is False
    assert "hmw" not in _plan_tokens(messages, hmw_available=False)


def test_empty_notebook_hides_hmw_scaffold() -> None:
    """A new Problem Identification notebook keeps the welcome and hides HMW."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == DEFAULT_STAGE
    visible = _visible_text(app)
    assert COACH_WELCOME_TITLE in visible
    assert HMW_FORMULA not in visible
    assert HMW_SCAFFOLD_TITLE not in visible
    assert _formula_code_count(app) == 0
    assert len(app.chat_input) == 1


def test_one_ready_coaching_turn_shows_hmw_scaffold() -> None:
    """A first useful Coaching assessment shows the card after that Coach reply."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    store.add_message(thread_id, "user", _FIRST_USER)
    store.add_message(
        thread_id,
        "assistant",
        _FIRST_COACH,
        metadata={"assessment": _pi_coaching(ready=True)},
    )
    assert hmw_scaffold_available(
        "problem_identification", store.get_messages(thread_id)
    ) is True
    app.run()
    assert not app.exception
    visible = _visible_text(app)
    assert COACH_WELCOME_TITLE in visible
    assert HMW_SCAFFOLD_TITLE in visible
    assert _formula_code_count(app) == 1
    assert _hmw_inside_chat_messages(app) is False


def test_hmw_scaffold_renders_once_when_eligible() -> None:
    """Server-owned readiness on the first useful Coach turn shows one card."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    _seed_ready_coaching(store, thread_id)
    messages = store.get_messages(thread_id)
    assert hmw_scaffold_available("problem_identification", messages)
    assert _plan_tokens(messages, hmw_available=True) == [
        "welcome",
        "user",
        _FIRST_COACH,
        "hmw",
    ]
    app.run()
    assert not app.exception
    visible = _visible_text(app)
    assert COACH_WELCOME_TITLE in visible
    assert HMW_SCAFFOLD_TITLE in visible
    assert HMW_SCAFFOLD_LEAD in visible
    assert HMW_FORMULA in visible
    assert HMW_FORMULA_OUTRO in visible
    assert _FIRST_USER in visible
    assert _FIRST_COACH in visible
    assert _formula_code_count(app) == 1
    assert _hmw_inside_chat_messages(app) is False
    app.run()
    assert not app.exception
    assert _formula_code_count(app) == 1
    assert _hmw_inside_chat_messages(app) is False
    assert len(app.chat_input) == 1
    assert HMW_FORMULA not in _widget_values(app.text_input)
    assert HMW_FORMULA not in _widget_values(app.text_area)
    welcome = Path("ui/coach_welcome.py").read_text(encoding="utf-8")
    assert "st.code(" in welcome
    assert "st.text_input" not in welcome
    assert "st.text_area" not in welcome
    assert "st.chat_input" not in welcome
    chat_source = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert "learning-state" not in chat_source
    assert "hmw_scaffold_available(" in chat_source
    assert "transcript_hmw_render_plan(" in chat_source
    assert "complete_and_advance(" not in chat_source
    assert "turn.auto_advanced_to" in chat_source
    persisted = store.get_messages(thread_id)
    assert not any(
        HMW_FORMULA in str(item.get("content") or "") for item in persisted
    )
    assert not any(
        (item.get("metadata") or {}).get("kind") == "hmw_scaffold"
        for item in persisted
    )


def test_qa_turn_keeps_hmw_after_unlocking_coach() -> None:
    """A later Q&A exchange must not move or duplicate the HMW card."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    _seed_ready_coaching(store, thread_id)
    store.add_message(thread_id, "user", _QA_USER)
    store.add_message(
        thread_id,
        "assistant",
        _QA_ASSISTANT,
        metadata={
            "assessment": {
                "current_stage": "problem_identification",
                "response_mode": "qa",
                "citations": [],
            }
        },
    )
    messages = store.get_messages(thread_id)
    assert hmw_scaffold_available("problem_identification", messages)
    assert _plan_tokens(messages, hmw_available=True) == [
        "welcome",
        "user",
        _FIRST_COACH,
        "hmw",
        "user",
        _QA_ASSISTANT,
    ]
    app.run()
    assert not app.exception
    visible = _visible_text(app)
    assert HMW_SCAFFOLD_TITLE in visible
    assert _QA_ASSISTANT in visible
    assert _formula_code_count(app) == 1
    assert _hmw_inside_chat_messages(app) is False


def test_legacy_notebook_without_welcome_places_hmw_after_unlocking_coach() -> None:
    """Eligible history without COACH_WELCOME_KIND still anchors after the unlocking Coach."""
    from backend.models import LOCKED_CHAT_MODEL_ID
    from backend.student_support import DEFAULT_SUPPORT_MODE

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    store = StudentStore()
    legacy_id = store.create_thread(
        name="Legacy notebook",
        model_id=LOCKED_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
    )
    _seed_ready_coaching(store, legacy_id)
    messages = store.get_messages(legacy_id)
    assert not any(
        (item.get("metadata") or {}).get("kind") == COACH_WELCOME_KIND
        for item in messages
    )
    assert hmw_scaffold_available("problem_identification", messages)
    assert _plan_tokens(messages, hmw_available=True) == [
        "user",
        _FIRST_COACH,
        "hmw",
    ]
    store.update_user_preferences({"active_thread_id": legacy_id})
    app.session_state["thread_id"] = None
    app.run()
    assert not app.exception
    assert str(app.session_state["thread_id"]) == legacy_id
    visible = _visible_text(app)
    assert HMW_SCAFFOLD_TITLE in visible
    assert _FIRST_USER in visible
    assert _formula_code_count(app) == 1
    assert _hmw_inside_chat_messages(app) is False


def test_hmw_scaffold_hides_after_concept_generation() -> None:
    """Concept Generation uses the persisted stage and must not keep the PI scaffold."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    _seed_ready_coaching(store, thread_id)
    journey = dict(app.session_state["learning_journey"])
    journey["current_stage"] = "concept_generation"
    journey["completed_stages"] = ["problem_identification"]
    app.session_state["learning_journey"] = journey
    app.run()
    assert not app.exception
    visible = _visible_text(app)
    assert HMW_FORMULA not in visible
    assert HMW_SCAFFOLD_TITLE not in visible
    assert _formula_code_count(app) == 0
    assert len(app.chat_input) == 1


def test_chat_panel_does_not_manually_mutate_stage() -> None:
    """Stage changes must come from the existing auto-advance payload, not a UI setter."""
    chat_source = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert "complete_and_advance(" not in chat_source
    assert "select-stage" not in chat_source
    assert "turn.auto_advanced_to" in chat_source
    fragment = chat_source[
        chat_source.index("def _render_composer_submit_fragment") : chat_source.index(
            "def render_chat_panel"
        )
    ]
    assert "hmw_scaffold" not in fragment
    assert "get_messages(" not in fragment
    assert "learning-state" not in fragment
