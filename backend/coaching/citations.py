"""Pure citation projection from selected retrieval evidence and coach output."""

from __future__ import annotations

import re
from collections.abc import Callable

from backend.domain import (
    CitationReference,
    CoachRequest,
    CoachTurn,
    RetrievalChunkReference,
)


_CITATION_LABEL = re.compile(r"\[(S\d+)\]")


def selected_citation_catalog(
    request: CoachRequest,
    *,
    get_source: Callable[[str, str], dict | None],
    excerpt: Callable[..., str],
) -> dict[str, CitationReference]:
    """Map stable S-labels to authorized, selected notebook sources."""
    catalog: dict[str, CitationReference] = {}
    retrieved_by_source: dict[str, RetrievalChunkReference] = {}
    for chunk in request.retrieved_chunks:
        retrieved_by_source.setdefault(chunk.source_id, chunk)
    for index, source_id in enumerate(request.source_ids, start=1):
        source = get_source(request.thread_id, source_id)
        if not source:
            continue
        retrieved = retrieved_by_source.get(source_id)
        if retrieved is None:
            continue
        catalog[f"S{index}"] = CitationReference(
            source_id=source_id,
            label=f"S{index}",
            title=str(source.get("title") or "Untitled source"),
            excerpt=excerpt(
                retrieved.excerpt,
                request.student_message,
                limit=240,
            ),
        )
    return catalog


def relevant_citations(
    request: CoachRequest,
    turn: CoachTurn,
    *,
    catalog: dict[str, CitationReference],
) -> list[CitationReference]:
    """Return cited/mentioned evidence in stable response order without duplicates."""
    if not catalog:
        return []
    by_source_id = {item.source_id: item for item in catalog.values()}
    ordered: list[CitationReference] = []
    seen: set[str] = set()

    def add(citation: CitationReference) -> None:
        if citation.source_id in seen:
            return
        seen.add(citation.source_id)
        ordered.append(citation)

    for citation in turn.assessment.citations:
        resolved = by_source_id.get(citation.source_id) or catalog.get(citation.label)
        if resolved:
            add(resolved)
    for label in _CITATION_LABEL.findall(turn.response_text or ""):
        resolved = catalog.get(label)
        if resolved:
            add(resolved)
    return ordered
