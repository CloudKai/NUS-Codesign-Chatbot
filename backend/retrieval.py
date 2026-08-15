"""Provider-neutral retrieval contracts and local selected-source retrieval.

The local adapter chunks the text already stored for selected notebook sources
and ranks those chunks deterministically. Production can inject a Bedrock
Knowledge Base ``Retrieve`` adapter behind the same :class:`ContextRetriever`
port. Prompt composition, coaching, and citations do not need to change.

Retrieval is deliberately read-only. Callers must pass only sources already
authorized and selected for the active notebook.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import math
import re
from typing import Any, Iterable, Protocol, Sequence


_TOKEN = re.compile(r"[^\W_]+(?:['’-][^\W_]+)?|\d+(?:\.\d+)?", re.UNICODE)
_WHITESPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")

# Query terms that add little lexical signal. This is intentionally compact:
# domain nouns and stage vocabulary remain searchable.
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "say",
        "should",
        "source",
        "tell",
        "that",
        "the",
        "their",
        "this",
        "to",
        "us",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
    }
)


@dataclass(frozen=True)
class RetrievalSource:
    """One authorized, selected notebook source available for retrieval."""

    source_id: str
    label: str
    title: str
    text: str
    kind: str = "file"
    mime: str = "application/octet-stream"
    url: str | None = None
    group: str | None = None
    object_key: str | None = None
    course_material_id: str | None = None


@dataclass(frozen=True)
class RetrievalQuery:
    """Server-built retrieval query for one coaching turn."""

    current_message: str
    current_stage: str
    sources: tuple[RetrievalSource, ...]
    project_context: str = ""
    conversation_summary: str = ""
    recent_messages: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RetrievedChunk:
    """A ranked source excerpt with stable source and chunk identifiers."""

    source_id: str
    label: str
    title: str
    chunk_id: str
    text: str
    score: float
    source_index: int
    chunk_index: int
    url: str | None = None
    group: str | None = None
    retrieval_origin: str = "extracted_text"


@dataclass(frozen=True)
class RetrievalResult:
    """Prompt-ready context plus structured retrieval evidence for auditing."""

    context: str
    chunks: tuple[RetrievedChunk, ...]


class ContextRetriever(Protocol):
    """Port implemented by local retrieval today and Bedrock KB later."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return bounded chunks drawn only from ``query.sources``."""


_COURSE_MATERIAL_GROUPS = frozenset({"lecturenotes", "readings"})
_COURSE_MATERIAL_ID_SAFE = re.compile(r"[^a-z0-9]+")


def course_material_id_from_object_key(object_key: str) -> str:
    """Return a stable unique application-owned course-material id.

    Direct files keep the historical prefix+stem form::

        course/lectureNotes/week_02_jtbd.pdf -> lecture_week_02_jtbd
        course/readings/pixar.pdf -> reading_pixar

    Nested directories are included so the same filename in two folders cannot
    collide::

        course/readings/week1.pdf -> reading_week1
        course/readings/archive/week1.pdf -> reading_archive_week1
    """
    key = str(object_key or "").strip().lstrip("/")
    if not key:
        return ""
    parts = [part for part in key.replace("\\", "/").split("/") if part]
    filename = parts[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    slug = _COURSE_MATERIAL_ID_SAFE.sub("_", stem.casefold()).strip("_")
    folder = ""
    if len(parts) >= 2:
        folder = parts[1].replace(" ", "").replace("_", "").casefold()
    if folder == "lecturenotes":
        prefix = "lecture"
        nested = parts[2:-1]
    elif folder == "readings":
        prefix = "reading"
        nested = parts[2:-1]
    else:
        prefix = "course"
        nested = parts[1:-1] if len(parts) > 1 else []
    nested_slug = "_".join(
        _COURSE_MATERIAL_ID_SAFE.sub("_", part.casefold()).strip("_")
        for part in nested
        if _COURSE_MATERIAL_ID_SAFE.sub("_", part.casefold()).strip("_")
    )
    body = "_".join(item for item in (nested_slug, slug) if item)
    return f"{prefix}_{body}" if body else prefix


def course_material_id_collisions(
    object_keys: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Return derived ids that map to more than one distinct object key.

    Used to detect filename-normalization collisions (case, punctuation, or
    directory differences that still slug to the same identifier).
    """
    grouped: dict[str, list[str]] = {}
    for raw in object_keys:
        key = str(raw or "").strip()
        material_id = course_material_id_from_object_key(key)
        if not material_id:
            continue
        grouped.setdefault(material_id, [])
        if key not in grouped[material_id]:
            grouped[material_id].append(key)
    return {
        material_id: tuple(keys)
        for material_id, keys in grouped.items()
        if len(keys) > 1
    }


def is_course_retrieval_source(source: RetrievalSource) -> bool:
    """Return whether *source* is a locked Lecture Notes or Readings object.

    Student uploads stay on the local retriever. Course objects are identified
    by ``course_material_group`` or a ``course/`` object key.
    """
    group = str(source.group or "").replace(" ", "").replace("_", "").casefold()
    if group in _COURSE_MATERIAL_GROUPS:
        return True
    key = str(source.object_key or "").strip().lstrip("/")
    return key.startswith("course/")


class CompositeContextRetriever:
    """Split course sources onto a Knowledge Base retriever and the rest locally.

    When the knowledge-base adapter is absent, every selected source uses the
    local retriever. Knowledge Base misses stay empty for course sources
    (evidence-gap composer rules) instead of dumping whole PDFs locally.
    """

    def __init__(
        self,
        *,
        knowledge_base: ContextRetriever | None,
        local: ContextRetriever | None = None,
        max_context_chars: int = 16_000,
    ) -> None:
        """Compose two retrievers behind one selected-source port.

        Args:
            knowledge_base: Optional Bedrock ``Retrieve`` adapter for course
                Lecture Notes/Readings.
            local: Retriever for student uploads (defaults to
                :class:`LocalChunkRetriever`).
            max_context_chars: Combined prompt budget after both adapters run.
        """
        self._knowledge_base = knowledge_base
        self._local = local or LocalChunkRetriever()
        self._max_context_chars = max_context_chars

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve course hits from the KB adapter and uploads from local."""
        if self._knowledge_base is None:
            return self._local.retrieve(query)
        course = tuple(
            source for source in query.sources if is_course_retrieval_source(source)
        )
        uploads = tuple(
            source
            for source in query.sources
            if not is_course_retrieval_source(source)
        )
        chunks: list[RetrievedChunk] = []
        if course:
            kb_result = self._knowledge_base.retrieve(replace(query, sources=course))
            chunks.extend(kb_result.chunks)
        if uploads:
            local_result = self._local.retrieve(replace(query, sources=uploads))
            chunks.extend(local_result.chunks)
        return bounded_retrieval_result(
            chunks, max_context_chars=self._max_context_chars
        )


@dataclass(frozen=True)
class _Candidate:
    source: RetrievalSource
    source_index: int
    chunk_index: int
    text: str
    terms: Counter[str]
    score: float = 0.0


def retrieval_sources_from_notebook(
    sources: Iterable[dict[str, Any]],
) -> tuple[RetrievalSource, ...]:
    """Normalize selected store rows into stable retrieval sources.

    Labels follow the selected-source ordering used by the citation UI. Image
    sources retain a short marker because their bytes travel separately as
    model image inputs.
    """
    normalized: list[RetrievalSource] = []
    for index, source in enumerate(sources, start=1):
        kind = str(source.get("kind") or "file").strip().lower()
        text = str(source.get("extractedText") or "").strip()
        if not text and kind == "image":
            text = "[Image source. Inspect the accompanying image input.]"
        elif not text:
            text = "[This source is stored but has no analyzable text.]"
        metadata = source.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        group = " ".join(
            str(metadata.get("course_material_group") or "").split()
        ).strip()
        object_key = " ".join(
            str(
                source.get("object_key")
                or metadata.get("object_key")
                or source.get("path")
                or ""
            ).split()
        ).strip()
        material_id = " ".join(
            str(metadata.get("course_material_id") or "").split()
        ).strip()
        if not material_id and object_key:
            derived = course_material_id_from_object_key(object_key)
            if object_key.replace("\\", "/").lstrip("/").startswith("course/"):
                material_id = derived
        normalized.append(
            RetrievalSource(
                source_id=str(source.get("id") or "").strip(),
                label=f"S{index}",
                title=" ".join(
                    str(source.get("title") or "Untitled source").split()
                )[:180],
                text=text,
                kind=kind,
                mime=str(
                    source.get("mime")
                    or source.get("content_type")
                    or "application/octet-stream"
                ),
                url=str(source.get("sourceUrl") or "").strip() or None,
                group=group or None,
                object_key=object_key or None,
                course_material_id=material_id or None,
            )
        )
    return tuple(source for source in normalized if source.source_id)


def _stem(token: str) -> str:
    """Apply conservative English suffix normalization for lexical matching."""
    value = token.casefold().replace("’", "'").strip("'")
    if len(value) > 5 and value.endswith("ies"):
        return value[:-3] + "y"
    if len(value) > 6 and value.endswith("ing"):
        return value[:-3]
    if len(value) > 5 and value.endswith("ed"):
        return value[:-2]
    if len(value) > 5 and value.endswith("es"):
        return value[:-2]
    if len(value) > 4 and value.endswith("s"):
        return value[:-1]
    return value


def _terms(text: str, *, remove_stop_words: bool = False) -> list[str]:
    """Tokenize text into case-folded, lightly normalized search terms."""
    terms = [_stem(match.group(0)) for match in _TOKEN.finditer(str(text or ""))]
    if remove_stop_words:
        return [term for term in terms if len(term) > 1 and term not in _STOP_WORDS]
    return [term for term in terms if term]


def _normalized_text(text: str) -> str:
    """Normalize extraction whitespace while preserving paragraph boundaries."""
    lines = [_WHITESPACE.sub(" ", line).strip() for line in str(text or "").splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
    """Split source text at nearby whitespace with bounded character overlap."""
    cleaned = _normalized_text(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        target_end = min(len(cleaned), start + chunk_chars)
        end = target_end
        if target_end < len(cleaned):
            search_start = start + chunk_chars // 2
            sentence_boundary = max(
                cleaned.rfind(marker, search_start, target_end)
                for marker in (". ", "? ", "! ", "\n")
            )
            if sentence_boundary >= search_start:
                end = sentence_boundary + 1
            else:
                end = cleaned.rfind(" ", search_start, target_end)
            if end <= start:
                end = target_end
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        next_start = max(start + 1, end - overlap_chars)
        while next_start < end and not cleaned[next_start].isspace():
            next_start += 1
        start = min(end, next_start + 1)
    return chunks


def _query_weights(query: RetrievalQuery) -> Counter[str]:
    """Weight the current turn above short continuity and project context."""
    weights: Counter[str] = Counter()
    weights.update(
        {
            term: 3.0
            for term in _terms(query.current_message, remove_stop_words=True)
        }
    )
    recent_user = [
        str(message.get("content") or "")
        for message in query.recent_messages
        if str(message.get("role") or "").lower() == "user"
    ][-2:]
    for text in recent_user:
        weights.update({term: 0.75 for term in _terms(text, remove_stop_words=True)})
    for text, weight in (
        (query.project_context, 0.5),
        (query.conversation_summary, 0.35),
    ):
        weights.update({term: weight for term in _terms(text, remove_stop_words=True)})
    return weights


def _bigrams(text: str) -> set[tuple[str, str]]:
    """Return informative adjacent query terms for phrase-overlap scoring."""
    values = _terms(text, remove_stop_words=True)
    return set(zip(values, values[1:]))


def focused_excerpt(text: str, query: str, *, limit: int = 600) -> str:
    """Return a bounded excerpt centered near the strongest query-term window."""
    cleaned = " ".join(str(text or "").split()).strip()
    if limit <= 0 or not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    lowered = cleaned.casefold()
    query_terms = list(dict.fromkeys(_terms(query, remove_stop_words=True)))
    positions = [
        lowered.find(term)
        for term in query_terms
        if len(term) >= 3 and lowered.find(term) >= 0
    ]
    if not positions:
        return cleaned[: max(1, limit - 1)].rstrip() + "…"
    best_start = 0
    best_score = -1
    for position in positions:
        start = max(0, position - limit // 8)
        end = min(len(cleaned), start + limit)
        window = lowered[start:end]
        score = sum(1 for term in query_terms if term in window)
        if score > best_score:
            best_score = score
            best_start = start
    if best_start:
        boundary = cleaned.find(" ", best_start)
        if 0 <= boundary < best_start + 40:
            best_start = boundary + 1
    excerpt = cleaned[best_start : best_start + limit].rstrip()
    prefix = "…" if best_start else ""
    suffix = "…" if best_start + limit < len(cleaned) else ""
    return f"{prefix}{excerpt}{suffix}"


def _normalized_excerpt(text: str, *, limit: int = 400) -> str:
    """Return a comparable excerpt prefix used for near-duplicate suppression."""
    return " ".join(str(text or "").split()).casefold()[:limit]


def bounded_retrieval_result(
    chunks: Iterable[RetrievedChunk],
    *,
    max_context_chars: int = 16_000,
) -> RetrievalResult:
    """Build canonical prompt context from structured, already-scoped chunks.

    The application re-runs this formatter for every adapter result. Therefore
    provider context can contain only the validated chunk text, never extra
    opaque text returned alongside a future infrastructure adapter result.
    Near-duplicate excerpts from the same source are skipped so repeated KB
    chunks do not waste the prompt budget.
    """
    sections: list[str] = []
    included: list[RetrievedChunk] = []
    seen_excerpts: dict[str, set[str]] = {}
    used = 0
    for chunk in chunks:
        fingerprint = _normalized_excerpt(chunk.text)
        source_seen = seen_excerpts.setdefault(str(chunk.source_id), set())
        if fingerprint and fingerprint in source_seen:
            continue
        if fingerprint:
            source_seen.add(fingerprint)
        header = f"--- [{chunk.label}] {chunk.title} · excerpt {chunk.chunk_id} ---"
        metadata_lines: list[str] = []
        if chunk.group:
            metadata_lines.append(f"Collection: {chunk.group}")
        if chunk.url:
            metadata_lines.append(f"URL: {chunk.url}")
        prefix = "\n".join([header, *metadata_lines])
        separator = 2 if sections else 0
        available = max_context_chars - used - separator - len(prefix) - 1
        if available <= 0:
            break
        body = str(chunk.text or "")[:available].rstrip()
        if not body:
            continue
        section = f"{prefix}\n{body}"
        sections.append(section)
        used += separator + len(section)
        included.append(
            RetrievedChunk(
                source_id=chunk.source_id,
                label=chunk.label,
                title=chunk.title,
                chunk_id=chunk.chunk_id,
                text=body,
                score=chunk.score,
                source_index=chunk.source_index,
                chunk_index=chunk.chunk_index,
                url=chunk.url,
                group=chunk.group,
                retrieval_origin=chunk.retrieval_origin,
            )
        )
        if used >= max_context_chars:
            break
    return RetrievalResult(context="\n\n".join(sections), chunks=tuple(included))


class LocalChunkRetriever:
    """Deterministic lexical retriever over selected notebook source text.

    This adapter has no embedding/model/network dependency. It uses weighted
    BM25-style term scoring, phrase and title boosts, per-source diversity, and
    a bounded generic-query fallback. That makes local development and mock CI
    deterministic while keeping the port ready for Bedrock Knowledge Bases.
    """

    def __init__(
        self,
        *,
        chunk_chars: int = 1_800,
        overlap_chars: int = 220,
        max_chunks: int = 8,
        max_chunks_per_source: int = 2,
        max_context_chars: int = 16_000,
    ) -> None:
        if chunk_chars < 400:
            raise ValueError("chunk_chars must be at least 400")
        if overlap_chars < 0 or overlap_chars >= chunk_chars:
            raise ValueError("overlap_chars must be between 0 and chunk_chars")
        if max_chunks < 1 or max_chunks_per_source < 1 or max_context_chars < 1:
            raise ValueError("retrieval limits must be positive")
        self.chunk_chars = chunk_chars
        self.overlap_chars = overlap_chars
        self.max_chunks = max_chunks
        self.max_chunks_per_source = max_chunks_per_source
        self.max_context_chars = max_context_chars

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Rank and format bounded excerpts from authorized selected sources."""
        candidates = self._candidates(query.sources)
        if not candidates:
            return RetrievalResult(context="", chunks=())
        ranked = self._rank(candidates, query)
        chosen = self._select(ranked)
        return self._format(chosen)

    def _candidates(self, sources: Sequence[RetrievalSource]) -> list[_Candidate]:
        """Create deterministic overlapping candidates from all selected sources."""
        candidates: list[_Candidate] = []
        for source_index, source in enumerate(sources, start=1):
            chunks = _chunk_text(
                source.text,
                chunk_chars=self.chunk_chars,
                overlap_chars=self.overlap_chars,
            )
            for chunk_index, text in enumerate(chunks, start=1):
                candidates.append(
                    _Candidate(
                        source=source,
                        source_index=source_index,
                        chunk_index=chunk_index,
                        text=text,
                        terms=Counter(_terms(text)),
                    )
                )
        return candidates

    def _rank(
        self,
        candidates: list[_Candidate],
        query: RetrievalQuery,
    ) -> list[_Candidate]:
        """Return candidates ordered by weighted lexical relevance."""
        query_weights = _query_weights(query)
        if not query_weights:
            return candidates
        document_frequency: Counter[str] = Counter()
        for term in query_weights:
            document_frequency[term] = sum(
                1 for candidate in candidates if term in candidate.terms
            )
        query_bigrams = _bigrams(query.current_message)
        total = len(candidates)
        scored: list[_Candidate] = []
        for candidate in candidates:
            score = 0.0
            length_factor = max(0.7, len(candidate.terms) / 180.0)
            for term, weight in query_weights.items():
                frequency = candidate.terms.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency.get(term, 0)
                inverse_frequency = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                normalized_tf = frequency / (frequency + 1.2 * length_factor)
                score += float(weight) * inverse_frequency * normalized_tf
            title_terms = set(_terms(candidate.source.title, remove_stop_words=True))
            score += 0.8 * sum(
                float(query_weights[term]) for term in title_terms & query_weights.keys()
            )
            ordered_terms = _terms(candidate.text)
            candidate_bigrams = set(zip(ordered_terms, ordered_terms[1:]))
            score += 1.25 * len(query_bigrams & candidate_bigrams)
            scored.append(
                _Candidate(
                    source=candidate.source,
                    source_index=candidate.source_index,
                    chunk_index=candidate.chunk_index,
                    text=candidate.text,
                    terms=candidate.terms,
                    score=score,
                )
            )
        return sorted(
            scored,
            key=lambda item: (-item.score, item.source_index, item.chunk_index),
        )

    def _select(self, ranked: list[_Candidate]) -> list[_Candidate]:
        """Choose relevant chunks with source diversity and a generic fallback."""
        relevant = [candidate for candidate in ranked if candidate.score > 0.0]
        if not relevant:
            # Generic questions such as “What do these say?” have no content
            # terms. Return representative beginnings without injecting every
            # selected document.
            first_by_source: list[_Candidate] = []
            seen_sources: set[str] = set()
            for candidate in ranked:
                if candidate.source.source_id in seen_sources:
                    continue
                seen_sources.add(candidate.source.source_id)
                first_by_source.append(candidate)
                if len(first_by_source) >= self.max_chunks:
                    break
            if len(first_by_source) == 1:
                same_source = [
                    item
                    for item in ranked
                    if item.source.source_id == first_by_source[0].source.source_id
                    and item.chunk_index != first_by_source[0].chunk_index
                ]
                first_by_source.extend(same_source[: self.max_chunks_per_source - 1])
            return first_by_source[: self.max_chunks]

        # Selected images travel as separate model inputs, but their marker must
        # remain in text context so the model can map image bytes to [S#].
        image_markers: list[_Candidate] = []
        seen_images: set[str] = set()
        for candidate in ranked:
            source_id = candidate.source.source_id
            if candidate.source.kind != "image" or source_id in seen_images:
                continue
            seen_images.add(source_id)
            image_markers.append(candidate)

        chosen: list[_Candidate] = image_markers[: self.max_chunks]
        chosen_keys: set[tuple[str, int]] = {
            (candidate.source.source_id, candidate.chunk_index)
            for candidate in chosen
        }
        counts: defaultdict[str, int] = defaultdict(int)
        for candidate in chosen:
            counts[candidate.source.source_id] += 1
        if len(chosen) >= self.max_chunks:
            return chosen

        # First pass gives every relevant source its best excerpt.
        for candidate in relevant:
            source_id = candidate.source.source_id
            if counts[source_id]:
                continue
            chosen.append(candidate)
            chosen_keys.add((source_id, candidate.chunk_index))
            counts[source_id] += 1
            if len(chosen) >= self.max_chunks:
                return chosen

        # Second pass fills remaining capacity with the strongest evidence.
        for candidate in relevant:
            source_id = candidate.source.source_id
            key = (source_id, candidate.chunk_index)
            if key in chosen_keys or counts[source_id] >= self.max_chunks_per_source:
                continue
            chosen.append(candidate)
            chosen_keys.add(key)
            counts[source_id] += 1
            if len(chosen) >= self.max_chunks:
                break
        return chosen

    def _format(self, chosen: list[_Candidate]) -> RetrievalResult:
        """Render ranked chunks with stable labels within the prompt budget."""
        chunks: list[RetrievedChunk] = []
        for candidate in chosen:
            source = candidate.source
            chunk_id = f"{source.label}-C{candidate.chunk_index}"
            chunks.append(
                RetrievedChunk(
                    source_id=source.source_id,
                    label=source.label,
                    title=source.title,
                    chunk_id=chunk_id,
                    text=candidate.text,
                    score=round(candidate.score, 6),
                    source_index=candidate.source_index,
                    chunk_index=candidate.chunk_index,
                    url=source.url,
                    group=source.group,
                    retrieval_origin="extracted_text",
                )
            )
        return bounded_retrieval_result(
            chunks,
            max_context_chars=self.max_context_chars,
        )
