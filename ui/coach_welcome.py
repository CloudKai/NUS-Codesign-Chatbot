"""Shared coach welcome copy seeded into new notebook chat history."""

from __future__ import annotations

from typing import Any, Protocol


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
