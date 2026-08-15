"""Cohesive operation objects composed behind the ``StudentStore`` façade."""

from __future__ import annotations

from dataclasses import dataclass

from backend.persistence.store.contracts import StoreContext
from backend.persistence.store.operations.sources import SourceOperations


@dataclass(frozen=True)
class StoreOperations:
    """Bound operation groups for one SQLite or DSQL store instance."""

    sources: SourceOperations


def bind_store_operations(store: StoreContext) -> StoreOperations:
    """Bind every operation group to *store* without opening a connection."""
    return StoreOperations(sources=SourceOperations(store))


__all__ = ["StoreOperations", "bind_store_operations"]
