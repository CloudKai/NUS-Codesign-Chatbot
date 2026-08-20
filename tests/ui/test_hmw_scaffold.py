"""AppTest coverage for the progressive Problem Identification How Might We scaffold."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from backend.learning.hmw import HMW_SCAFFOLD_STAGE_ID, hmw_scaffold_available
from backend.student_journey import DEFAULT_STAGE, next_stage_id
from backend.student_store import StudentStore
from ui.coach_welcome import (
    COACH_WELCOME_TITLE,
    HMW_FORMULA,
    HMW_FORMULA_INTRO,
    HMW_FORMULA_OUTRO,
    HMW_PROMPT_LINE,
    HMW_SCAFFOLD_LEAD,
    HMW_SCAFFOLD_TITLE,
)


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


def _seed_ready_coaching(store: StudentStore, thread_id: str) -> None:
    """Persist two Problem Identification Coaching turns with HMW readiness."""
    store.add_message(
        thread_id,
        "user",
        "Older pedestrians struggle at the school crossing.",
    )
    store.add_message(
        thread_id,
        "assistant",
        "What specifically is hardest at the crossing?",
        metadata={
            "assessment": {
                "current_stage": "problem_identification",
                "response_mode": "coaching",
                "recommendation": "stay",
                "citations": [],
            }
        },
    )
    store.add_message(
        thread_id,
        "user",
        (
            "They cannot reach the other side before the signal changes. "
            "I want them to cross safely without rushing."
        ),
    )
    store.add_message(
        thread_id,
        "assistant",
        "What outcome matters most for those pedestrians?",
        metadata={
            "assessment": {
                "current_stage": "problem_identification",
                "response_mode": "coaching",
                "recommendation": "stay",
                "citations": [],
                "hmw_scaffold_ready": True,
            }
        },
    )


def test_hmw_stage_id_is_canonical_problem_identification() -> None:
    assert HMW_SCAFFOLD_STAGE_ID == DEFAULT_STAGE
    assert HMW_SCAFFOLD_STAGE_ID == "problem_identification"
    assert next_stage_id(HMW_SCAFFOLD_STAGE_ID) == "concept_generation"


def test_empty_notebook_hides_hmw_scaffold() -> None:
    """A new Problem Identification notebook keeps the welcome and hides HMW."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == DEFAULT_STAGE
    visible = _visible_text(app)
    assert COACH_WELCOME_TITLE in visible
    assert HMW_FORMULA not in visible
    assert HMW_PROMPT_LINE not in visible
    assert HMW_SCAFFOLD_TITLE not in visible
    assert _formula_code_count(app) == 0
    assert len(app.chat_input) == 1


def test_hmw_scaffold_renders_once_when_eligible() -> None:
    """Server-owned readiness plus two Coaching turns shows one card near the composer."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    _seed_ready_coaching(store, thread_id)
    assert hmw_scaffold_available(
        "problem_identification", store.get_messages(thread_id)
    )
    app.run()
    assert not app.exception
    visible = _visible_text(app)
    assert HMW_SCAFFOLD_TITLE in visible
    assert HMW_SCAFFOLD_LEAD in visible
    assert HMW_PROMPT_LINE in visible
    assert HMW_FORMULA_INTRO in visible
    assert HMW_FORMULA in visible
    assert HMW_FORMULA_OUTRO in visible
    assert _formula_code_count(app) == 1
    app.run()
    assert not app.exception
    assert _formula_code_count(app) == 1
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
    assert "complete_and_advance(" not in chat_source
    assert "turn.auto_advanced_to" in chat_source
    messages = store.get_messages(thread_id)
    assert not any(
        HMW_FORMULA in str(item.get("content") or "") for item in messages
    )
    assert not any(
        (item.get("metadata") or {}).get("kind") == "hmw_scaffold"
        for item in messages
    )


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
    assert HMW_PROMPT_LINE not in visible
    assert HMW_SCAFFOLD_TITLE not in visible
    assert _formula_code_count(app) == 0
    assert len(app.chat_input) == 1


def test_chat_panel_does_not_manually_mutate_stage() -> None:
    """Stage changes must come from the existing auto-advance payload, not a UI setter."""
    chat_source = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert "complete_and_advance(" not in chat_source
    assert "select-stage" not in chat_source
    assert "turn.auto_advanced_to" in chat_source
