"""Shared coach welcome copy seeded into new notebook chat history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

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


def _is_skipped_transcript_message(message: Mapping[str, Any]) -> bool:
    """Return whether the chat log should omit this persisted row.

    Empty assistant turns are skipped by ``render_chat_panel`` so they must
    not count as a visible welcome or a conversation anchor.

    Args:
        message: One persisted chat message.

    Returns:
        True when the row is an empty assistant turn.
    """
    return (
        str(message.get("role") or "").strip().lower() == "assistant"
        and not str(message.get("content") or "").strip()
    )


def is_visible_coach_welcome(message: Mapping[str, Any]) -> bool:
    """Return whether this row is the persisted Coach welcome in the log.

    Identification uses ``metadata.kind == COACH_WELCOME_KIND`` only. Empty
    assistant rows are not visible and do not count.

    Args:
        message: One persisted chat message.

    Returns:
        True when the row will render as the Coach welcome.
    """
    if _is_skipped_transcript_message(message):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    metadata = message.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    return str(metadata.get("kind") or "").strip() == COACH_WELCOME_KIND


def transcript_hmw_render_plan(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    hmw_available: bool,
) -> list[tuple[Literal["message", "hmw"], Mapping[str, Any] | None]]:
    """Return chat-log steps with the HMW card after welcome when eligible.

    Eligibility is supplied by the caller from ``hmw_scaffold_available``.
    This helper only decides placement and guarantees at most one ``hmw``
    step. When a visible welcome exists, the card follows it. When eligible
    history has no welcome (legacy notebooks), the card is first. The card
    is omitted when ``hmw_available`` is false.

    Args:
        messages: Active-branch messages already loaded for the panel.
        hmw_available: Server-owned visibility flag.

    Returns:
        Ordered ``("message", row)`` and optional ``("hmw", None)`` steps.
        Skipped empty assistant rows are omitted.
    """
    visible = [
        item
        for item in (messages or ())
        if isinstance(item, Mapping) and not _is_skipped_transcript_message(item)
    ]
    has_welcome = any(is_visible_coach_welcome(item) for item in visible)
    steps: list[tuple[Literal["message", "hmw"], Mapping[str, Any] | None]] = []
    hmw_inserted = False
    if hmw_available and not has_welcome:
        steps.append(("hmw", None))
        hmw_inserted = True
    for item in visible:
        steps.append(("message", item))
        if (
            not hmw_inserted
            and hmw_available
            and is_visible_coach_welcome(item)
        ):
            steps.append(("hmw", None))
            hmw_inserted = True
    return steps


def render_hmw_scaffold() -> None:
    """Render the read-only How Might We guidance under the Coach welcome.

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
