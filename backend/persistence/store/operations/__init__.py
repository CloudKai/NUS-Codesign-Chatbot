"""Cohesive operation objects composed behind the ``StudentStore`` façade."""

from __future__ import annotations

from dataclasses import dataclass

from backend.persistence.store.contracts import StoreContext
from backend.persistence.store.operations.artifacts import ArtifactOperations
from backend.persistence.store.operations.canvases import CanvasOperations
from backend.persistence.store.operations.sources import SourceOperations


@dataclass(frozen=True)
class StoreOperations:
    """Bound operation groups for one SQLite or DSQL store instance."""

    sources: SourceOperations
    artifacts: ArtifactOperations
    canvases: CanvasOperations


def bind_store_operations(store: StoreContext) -> StoreOperations:
    """Bind every operation group to *store* without opening a connection."""
    return StoreOperations(sources=SourceOperations(store), artifacts=ArtifactOperations(store),
                           canvases=CanvasOperations(store))


__all__ = ["StoreOperations", "bind_store_operations"]
