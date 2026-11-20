"""Offline setup: network block, local lecture-PDF search and ranked hits.

``OfflineCourseSearch`` is the lexical stand-in for the Knowledge Base. The
backend is imported lazily inside it; nothing here reaches a network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.evals.lib.fixtures import DatasetError
from scripts.evals.lib.paths import PROJECT_ROOT as _PROJECT_ROOT


@dataclass(frozen=True)
class RankedHit:
    """One retrieved result reduced to what scoring needs.

    ``page`` is ``None`` when the retriever does not report a page.
    """

    material_id: str
    page: int | None
    score: float
    source_index: int = 0
    chunk_index: int = 0
    text: str = ""


def rank_hits(hits: Iterable[RankedHit]) -> list[RankedHit]:
    """Sort hits by score descending; ties by source order, then chunk order."""
    return sorted(
        hits,
        key=lambda hit: (-hit.score, hit.source_index, hit.chunk_index, hit.material_id),
    )


def accepted_targets(
    expected_material: str,
    expected_pages: Sequence[int],
    alt_expected: Sequence[Mapping[str, Any]] = (),
) -> dict[str, frozenset[int]]:
    """Map each acceptable material to the set of acceptable pages."""
    targets: dict[str, set[int]] = {expected_material: set(expected_pages)}
    for alt in alt_expected:
        targets.setdefault(str(alt["material"]), set()).update(
            int(page) for page in alt["pages"]
        )
    return {material: frozenset(pages) for material, pages in targets.items()}


def extract_pdf_pages(path: Path) -> list[str]:
    """Return whitespace-normalised text for each PDF page (1 page = 1 chunk)."""
    import fitz  # PyMuPDF, pinned in requirements.txt

    fitz.TOOLS.mupdf_display_errors(False)
    with fitz.open(path) as document:
        return [" ".join(page.get_text().split()) for page in document]


class OfflineCourseSearch:
    """Lexical stand-in for the Knowledge Base over the local lecture PDFs."""

    def __init__(self, materials: Sequence[Mapping[str, Any]], root: Path = _PROJECT_ROOT):
        from backend.retrieval import LocalChunkRetriever, RetrievalSource

        self._sources = []
        self._material_by_source: dict[str, str] = {}
        for index, entry in enumerate(materials, start=1):
            pdf_path = root / entry["local_path"]
            if not pdf_path.is_file():
                raise FileNotFoundError(f"course PDF not found: {pdf_path}")
            pages = extract_pdf_pages(pdf_path)
            if len(pages) != int(entry["pdf_pages"]):
                raise DatasetError(
                    f"{entry['filename']}: manifest says {entry['pdf_pages']} pages, "
                    f"PDF has {len(pages)}"
                )
            self._sources.append(
                RetrievalSource(
                    source_id=entry["source_id"],
                    label=f"S{index}",
                    title=entry["filename"],
                    text="",
                    mime="application/pdf",
                    group=entry["group"],
                    object_key=entry["object_key"],
                    course_material_id=entry["material_id"],
                    virtual_course_source=True,
                    chunks=tuple(pages),
                )
            )
            self._material_by_source[entry["source_id"]] = entry["material_id"]
        # Large limits: every lexical match is returned and ranked here by
        # score, like the Knowledge Base adapter, instead of by the local
        # retriever's per-source diversity order.
        self._retriever = LocalChunkRetriever(
            max_chunks=100_000,
            max_chunks_per_source=100_000,
            max_context_chars=10**9,
        )

    def search(self, message: str, history: Sequence[Mapping[str, Any]] = ()) -> list[RankedHit]:
        """Return ranked results with score above zero."""
        from backend.retrieval import RetrievalQuery, prefer_session_matching_sources

        sources = prefer_session_matching_sources(tuple(self._sources), message)
        query = RetrievalQuery(
            current_message=message,
            current_stage="problem_identification",
            sources=sources,
            recent_messages=tuple(
                {"role": turn["role"], "content": turn["text"]} for turn in history
            ),
        )
        result = self._retriever.retrieve(query)
        return [
            RankedHit(
                material_id=self._material_by_source[chunk.source_id],
                page=chunk.chunk_index,
                score=float(chunk.score),
                source_index=chunk.source_index,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
            )
            for chunk in result.chunks
            if chunk.score > 0.0
        ]


def block_network() -> None:
    """Make any socket connection fail, so offline mode cannot reach a network."""
    import socket

    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network access is disabled in offline mode")

    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.getaddrinfo = _refuse  # type: ignore[assignment]
