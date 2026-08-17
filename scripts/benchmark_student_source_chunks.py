"""Informational probe: dynamic vs precomputed vs cached student-source chunks.

Not a pytest. Does not assert wall-clock latency. Uses in-memory storage and a
temporary SQLite file only — never production ``data/`` paths.

Example::

    .\\.venv\\Scripts\\python.exe scripts/benchmark_student_source_chunks.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _PROJECT_ROOT / "tests"
for extra in (_PROJECT_ROOT, _TESTS_DIR):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from backend.persistence.factory import reset_file_storage_cache  # noqa: E402
from backend.retrieval import (  # noqa: E402
    LocalChunkRetriever,
    RetrievalQuery,
    canonical_chunk_text,
)
from backend.settings import settings  # noqa: E402
from backend.source_library import (  # noqa: E402
    MAX_SOURCE_TEXT,
    add_text_source,
    list_visible_sources,
)
from backend.sources.chunk_cache import reset_student_source_chunk_cache  # noqa: E402
from backend.sources.chunk_load import hydrate_selected_retrieval_sources  # noqa: E402
from backend.student_store import StudentStore  # noqa: E402
from counting_file_storage import CountingFileStorage  # noqa: E402


def _text_of_size(n_chars: int) -> str:
    """Return deterministic filler that still contains a ranking term."""
    seed = (
        "Lecture notes on accessibility explain that older pedestrians need "
        "longer crossing times, audible signals, and step-free kerb design. "
    )
    if n_chars <= len(seed):
        return seed[:n_chars]
    repeats = (n_chars // len(seed)) + 1
    return (seed * repeats)[:n_chars]


class _CountingChunker:
    """Wrap ``canonical_chunk_text`` to count dynamic chunk-build calls."""

    def __init__(self) -> None:
        self.calls = 0
        self._original = canonical_chunk_text

    def __call__(
        self, text: str, *, chunk_chars: int, overlap_chars: int
    ) -> list[str]:
        """Count one chunk-build, then delegate to the production chunker."""
        self.calls += 1
        return self._original(
            text, chunk_chars=chunk_chars, overlap_chars=overlap_chars
        )


def main(argv: list[str] | None = None) -> int:
    """Run the in-memory probe and print a comparison table."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare dynamic vs precomputed uncached vs cached student-source "
            "chunk retrieval. In-memory only; not a latency SLO."
        )
    )
    parser.parse_args(argv)
    sizes = (
        ("10KiB", 10 * 1024),
        ("60KiB", 60 * 1024),
        ("MAX_SOURCE_TEXT", MAX_SOURCE_TEXT),
    )
    chunker = _CountingChunker()
    import backend.retrieval as retrieval_module

    retrieval_module.canonical_chunk_text = chunker
    print("Student source chunk probe (in-memory, informational wall time)")
    print(f"MAX_SOURCE_TEXT={MAX_SOURCE_TEXT}")
    query_text = "What does the lecture say about accessibility?"
    for label, size in sizes:
        print(f"\n=== {label} ({size} chars) ===")
        storage = CountingFileStorage()
        settings.file_storage_provider = "memory"
        reset_file_storage_cache()
        import backend.persistence.factory as factory_module

        factory_module.get_file_storage = lambda _storage=storage: _storage
        factory_module.get_course_file_storage = lambda _storage=storage: _storage
        reset_student_source_chunk_cache()
        with tempfile.TemporaryDirectory(prefix="chunk-bench-") as tmp:
            store = StudentStore(
                Path(tmp) / "bench.sqlite3", identifier="cognito:bench"
            )
            thread_id = store.create_thread(
                model_id="mock",
                support_mode="critical-thinking",
            )
            add_text_source(store, thread_id, f"notes-{label}", _text_of_size(size))
            selected = list_visible_sources(
                store, thread_id, selected_only=True, include_extracted_text=False
            )
            retriever = LocalChunkRetriever()

            def _row(name: str, sources: tuple) -> None:
                started = time.perf_counter()
                result = retriever.retrieve(
                    RetrievalQuery(
                        current_message=query_text,
                        current_stage="problem_identification",
                        sources=sources,
                    )
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                counts = storage.counts()
                candidates = len(retriever._candidates(sources))
                print(
                    f"{name:22} chunk_builds={chunker.calls:<4} "
                    f"storage_reads={counts.get_bytes:<4} "
                    f"chunks_gets={counts.chunks_gets:<3} "
                    f"extracted_gets={counts.extracted_gets:<3} "
                    f"candidates={candidates:<4} ranked={len(result.chunks):<3} "
                    f"wall_ms={elapsed_ms:8.2f} (informational)"
                )

            reset_student_source_chunk_cache()
            hydrated = hydrate_selected_retrieval_sources(
                selected,
                owner_id=store.owner_id,
                notebook_id=thread_id,
                storage=storage,
            )
            forced_dynamic = tuple(replace(item, chunks=None) for item in hydrated)
            storage.reset_counts()
            chunker.calls = 0
            _row("dynamic", forced_dynamic)

            reset_student_source_chunk_cache()
            storage.reset_counts()
            chunker.calls = 0
            uncached = hydrate_selected_retrieval_sources(
                selected,
                owner_id=store.owner_id,
                notebook_id=thread_id,
                storage=storage,
            )
            _row("precomputed_uncached", uncached)

            storage.reset_counts()
            chunker.calls = 0
            cached = hydrate_selected_retrieval_sources(
                selected,
                owner_id=store.owner_id,
                notebook_id=thread_id,
                storage=storage,
            )
            _row("precomputed_cached", cached)
    reset_file_storage_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
