"""Shared coach welcome copy seeded into new notebook chat history."""

from __future__ import annotations

from typing import Any, Protocol

import streamlit as st


COACH_WELCOME_KIND = "coach_welcome"

COACH_WELCOME_TITLE = "Welcome to your critical-thinking coach"

COACH_WELCOME_BODY = (
    "I'm here to help you think through a design or research challenge with "
    "clearer questions, stronger evidence, and more careful reasoning.\n\n"
    "What design challenge or problem are you working on today?"
)

COACH_WELCOME_MARKDOWN = (
    f"**{COACH_WELCOME_TITLE}**\n\n{COACH_WELCOME_BODY}"
)

HMW_SCAFFOLD_TITLE = "Ready to frame your design opportunity?"

HMW_SCAFFOLD_LEAD = (
    "You've clarified enough of the problem to start bringing your ideas "
    "together."
)

HMW_PROMPT_LINE = "Try framing your problem as a How Might We statement."

HMW_FORMULA_INTRO = (
    'A "How Might We" (HMW) statement follows this core structure:'
)

HMW_FORMULA = (
    "How might we + [action/intervention] + for [user] + so that "
    "[desired outcome/benefit]"
)

HMW_FORMULA_OUTRO = (
    "When you're ready, use this structure to draft a working HMW statement "
    "in the chat. Your coach can help you refine it before you move on to "
    "the next stage."
)


def render_hmw_scaffold() -> None:
    """Render the read-only How Might We guidance near the chat composer.

    Uses ``st.code`` so the formula looks like a code block but is not an
    input widget. Students still reply in the existing chat composer. This
    card is UI guidance only and is never persisted as a chat message.
    """
    with st.container(key="hmw_scaffold"):
        st.markdown(f"**{HMW_SCAFFOLD_TITLE}**")
        st.markdown(HMW_SCAFFOLD_LEAD)
        st.markdown(HMW_PROMPT_LINE)
        st.markdown(HMW_FORMULA_INTRO)
        st.code(HMW_FORMULA, language=None, wrap_lines=True)
        st.markdown(HMW_FORMULA_OUTRO)


def render_hmw_scaffold_if_needed(*, available: bool) -> None:
    """Render the How Might We scaffold when the server projection allows it.

    Args:
        available: Server-owned ``hmw_scaffold.available`` projection.
    """
    if available:
        render_hmw_scaffold()


class _MessageStore(Protocol):
    """Minimal store surface used to seed the coach welcome message."""

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return persisted messages for ``thread_id``."""

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist one chat message and return its id."""


def seed_coach_welcome(store: _MessageStore, thread_id: str) -> bool:
    """Persist the opening coach prompt once when a notebook has no messages.

    Returns:
        True when a welcome message was added; False when history already exists
        or a welcome was already present.
    """
    messages = store.get_messages(thread_id)
    if messages:
        return False
    store.add_message(
        thread_id,
        "assistant",
        COACH_WELCOME_MARKDOWN,
        metadata={"kind": COACH_WELCOME_KIND, "workflow": "welcome"},
    )
    return True
