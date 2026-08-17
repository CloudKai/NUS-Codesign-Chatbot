"""Request-scoped authoritative notebook state for one coaching submit."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from backend.retrieval import RetrievalSource


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a shallow immutable view of *value*."""
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class TurnSnapshot:
    """Authoritative notebook row, stage, and visible sources for one turn.

    Built after the security re-read in
    ``CoachApplicationService._authoritative_request``. Callers must create a
    new instance per ``submit()`` and must not store it on
    ``CoachApplicationService``; HTTP runs ``submit`` on a per-request thread.

    Attributes:
        thread_id: Owned notebook id.
        thread: Notebook row from the authoritative store re-read.
        conversation_revision: CAS revision from that row.
        current_stage: Server-authoritative Thinking Path stage.
        metadata: Metadata mapping from that row.
        visible_sources: Personal plus shared-catalog sources visible now.
        selected_sources: Visible sources selected for grounding.
        sources_by_id: Id-keyed view of ``visible_sources``.
        retrieval_sources: Hydrated selected retrieval sources. Empty until
            the application service attaches them after authorization and
            the retrieval gate (or RAG fallback) requires evidence.
            This class never performs storage I/O.
    """

    thread_id: str
    thread: Mapping[str, Any]
    conversation_revision: int
    current_stage: str
    metadata: Mapping[str, Any]
    visible_sources: tuple[Mapping[str, Any], ...]
    selected_sources: tuple[Mapping[str, Any], ...]
    sources_by_id: Mapping[str, Mapping[str, Any]]
    retrieval_sources: tuple[RetrievalSource, ...] = ()

    @classmethod
    def from_authoritative_state(
        cls,
        *,
        thread: Mapping[str, Any],
        current_stage: str,
        visible_sources: list[dict[str, Any]],
    ) -> "TurnSnapshot":
        """Build a snapshot from one authoritative notebook re-read.

        Args:
            thread: Store row returned by ``get_thread``.
            current_stage: Authoritative Thinking Path stage id.
            visible_sources: Result of ``list_visible_sources`` (all visible).

        Returns:
            Frozen request-local snapshot.

        Raises:
            ValueError: When the thread id is missing.
        """
        thread_id = str(thread.get("id") or "").strip()
        if not thread_id:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        revision = int(
            metadata.get("conversation_revision")
            if metadata.get("conversation_revision") is not None
            else thread.get("conversation_revision")
            or 0
        )
        visible_tuple = tuple(dict(source) for source in visible_sources)
        selected_tuple = tuple(
            source for source in visible_tuple if source.get("selected")
        )
        by_id = {
            str(source.get("id") or ""): source
            for source in visible_tuple
            if str(source.get("id") or "").strip()
        }
        return cls(
            thread_id=thread_id,
            thread=_freeze_mapping(thread),
            conversation_revision=revision,
            current_stage=current_stage,
            metadata=_freeze_mapping(metadata),
            visible_sources=visible_tuple,
            selected_sources=selected_tuple,
            sources_by_id=MappingProxyType(by_id),
        )
