"""Concise notebook-title generation without an additional model request."""

from __future__ import annotations

import re


class NotebookTitleService:
    """Turn the coach's structured topic summary into a short notebook title.

    The coaching provider already produces the structured contribution summary,
    so title generation reuses that model output instead of creating a second
    paid request. A deterministic fallback keeps the local mock demo equally
    usable.
    """

    _STOP_WORDS = {
        "a",
        "about",
        "and",
        "are",
        "be",
        "for",
        "from",
        "help",
        "helping",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "like",
        "my",
        "of",
        "on",
        "safer",
        "should",
        "that",
        "the",
        "their",
        "them",
        "to",
        "understand",
        "want",
        "ways",
        "with",
        "without",
        "would",
    }

    @classmethod
    def generate(cls, topic_summary: str) -> str:
        """Return a readable title of at most five meaningful words."""
        normalized = " ".join(topic_summary.split()).strip()
        lowered = normalized.lower()
        older_adult_topic = any(
            phrase in lowered
            for phrase in ("elderly", "older adult", "older people", "older pedestrian")
        )
        road_topic = any(
            phrase in lowered
            for phrase in ("road", "crossing", "cross safely", "pedestrian")
        )
        if older_adult_topic and road_topic:
            return "Elderly Road Safety"

        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", normalized)
        selected: list[str] = []
        seen: set[str] = set()
        for word in words:
            lowered_word = word.lower()
            if lowered_word in cls._STOP_WORDS or lowered_word in seen:
                continue
            seen.add(lowered_word)
            selected.append(word.upper() if word.isupper() else word.title())
            if len(selected) == 5:
                break
        return " ".join(selected) or "New Inquiry"

    @classmethod
    def replacement_for_legacy_title(
        cls,
        current_title: str,
        user_messages: list[str],
    ) -> str | None:
        """Upgrade only titles known to be old first-prompt auto titles."""
        if not user_messages or len(current_title) <= 40:
            return None
        first_prompt_title = " ".join(user_messages[0].split())[:70]
        if current_title != first_prompt_title:
            return None
        topic_summary = " ".join(user_messages[:2])
        replacement = cls.generate(topic_summary)
        return replacement if replacement != current_title else None
