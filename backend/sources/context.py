"""Provider-neutral projection of selected sources into bounded coach context."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def selected_source_context(
    sources: Iterable[dict[str, Any]],
    *,
    limit: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Return bounded labeled context and source references.

    Args:
        sources: Ordered source dictionaries selected for the notebook.
        limit: Maximum number of characters across rendered context sections.

    Returns:
        A context string and matching reference dictionaries in stable order.
    """
    sections: list[str] = []
    references: list[dict[str, Any]] = []
    remaining = max(0, limit)
    for index, source in enumerate(sources, start=1):
        label = f"S{index}"
        title = str(source.get("title") or "Untitled source")
        text = str(source.get("extractedText") or "").strip()
        if not text and source.get("kind") == "image":
            text = "[Image source. Inspect the accompanying image input.]"
        elif not text:
            text = "[This source is stored but has no analyzable text.]"
        header = f"--- [{label}] {title} ---"
        if source.get("sourceUrl"):
            header += f"\nURL: {source['sourceUrl']}"
        separator_size = 2 if sections else 0
        available = max(0, remaining - separator_size - len(header) - 1)
        body = text[:available]
        section = f"{header}\n{body}".strip()
        if section and remaining:
            sections.append(section)
            remaining -= len(section) + separator_size
        references.append(
            {
                "id": source["id"],
                "label": label,
                "title": title,
                "kind": source.get("kind", "file"),
                "mime": source.get("mime", "application/octet-stream"),
                "url": source.get("sourceUrl"),
            }
        )
        if remaining <= 0:
            break
    return "\n\n".join(sections), references
