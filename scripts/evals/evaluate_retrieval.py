"""Measure course retrieval: recall@4, wrong-skip rate and empty-result rate.

Default mode is OFFLINE. It uses no network, no AWS, no model and no API key:

* The retrieval gate is the repo's own rules-based gate, composed the same way
  ``CoachingExecution._prepare_authoritative_turn`` composes it.
* Course search uses the repo's ``LocalChunkRetriever`` (lexical, BM25-style)
  over the local lecture PDFs, one chunk per PDF page. This is a stand-in for
  the Bedrock Knowledge Base. Offline numbers do not describe the Knowledge
  Base.

LIVE mode (real Bedrock Knowledge Base ``Retrieve`` calls) is off by default.
It runs only with ``--live-kb`` AND ``--max-live-calls N`` (1 to 100). Without
both the script refuses and makes no call. Pytest never uses the live path.
Run it only with the user's approval.

Metric definitions (also in ``scripts/evals/datasets/README.md``):

* recall@4: questions whose expected material is in the top 4 results, divided
  by all questions evaluated. Page-level recall also needs a matching page.
* wrong-skip rate: messages labelled ``retrieve`` that the gate did not search
  for, divided by all messages labelled ``retrieve``.
* empty-result rate: retrieval attempts that returned zero results, divided by
  completed attempts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DATASET_DIR = _PROJECT_ROOT / "scripts" / "evals" / "datasets"
QUESTIONS_PATH = DATASET_DIR / "retrieval_questions.jsonl"
MESSAGES_PATH = DATASET_DIR / "retrieval_gate_messages.synthetic.jsonl"
MATERIALS_PATH = DATASET_DIR / "course_materials.json"

TOP_K = 4
# One Retrieve call per question and the set has fewer than 100 questions, so
# a higher limit could never be used.
HARD_LIVE_CALL_CAP = 100
QUESTION_COUNT_RANGE = (60, 100)
MIN_MESSAGE_COUNT = 200

QUESTION_KEYS = frozenset(
    {
        "id",
        "question",
        "expected_material",
        "expected_pages",
        "alt_expected",
        "evidence",
        "kind",
        "note",
    }
)
QUESTION_KINDS = frozenset(
    {"definition", "list", "procedure", "example", "detail", "logistics"}
)
MESSAGE_KEYS = frozenset(
    {
        "id",
        "message",
        "stage",
        "selected_sources",
        "attachments",
        "history",
        "expected_decision",
        "expected_scope",
        "category",
        "certainty",
        "follow_up",
        "question_id",
        "expected_material",
        "rationale",
        "synthetic",
    }
)
DECISIONS = frozenset({"retrieve", "skip"})
SCOPES = frozenset({"course", "student_upload", "both", "none"})
CERTAINTIES = frozenset({"clear", "borderline"})
MESSAGE_CATEGORIES = frozenset(
    {
        "course_content",
        "course_logistics",
        "named_material",
        "informal_or_multilingual",
        "mixed_project_and_course",
        "upload_question",
        "attachment_question",
        "upload_and_course",
        "course_with_unrelated_upload",
        "follow_up",
        "greeting_thanks_chitchat",
        "procedural_ui",
        "stage_navigation",
        "stage_meta_guidance",
        "project_reasoning",
        "project_mentions_course",
        "ambiguous_generic",
        "out_of_scope",
        "not_in_course_material",
    }
)

DEFINITIONS = {
    "recall_at_4": (
        "Numerator: questions with at least one of the top 4 ranked results in "
        "the expected material or in an alt_expected material. Denominator: "
        "questions evaluated. The page-level variant also requires the result "
        "page to be one of the tagged pages for that material (any one page of "
        "a multi-page tag counts) and uses only questions whose results carry "
        "a page. Ranking: score descending, ties by material order in the "
        "manifest then page number."
    ),
    "wrong_skip_rate": (
        "Numerator: messages labelled 'retrieve' for which the gate searched "
        "no source (effective decision 'skip'). Denominator: all messages "
        "labelled 'retrieve'. The effective decision is 'retrieve' if and only "
        "if at least one source (course catalog or student file) is searched."
    ),
    "empty_result_rate": (
        "Numerator: completed retrieval attempts that returned zero results. "
        "Denominator: completed attempts (failed live calls are counted "
        "separately). Offline, a chunk with no lexical match (score 0) is not "
        "a result."
    ),
}


class DatasetError(ValueError):
    """Raised when a data file does not match its documented format."""


class LiveRunRefused(RuntimeError):
    """Raised when the live Knowledge Base path is requested without approval."""


class LiveCallLimitExceeded(RuntimeError):
    """Raised by the call counter when the approved call limit is reached."""


# ---------------------------------------------------------------------------
# Pure metric functions (no backend imports, no I/O)
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class QuestionOutcome:
    """Scoring result for one question."""

    question_id: str
    expected_material: str
    result_count: int
    material_hit: bool
    page_hit: bool | None
    first_material_rank: int | None
    tie_at_cutoff: bool
    top_materials: tuple[str, ...]


def rate(numerator: int, denominator: int) -> float | None:
    """Return numerator/denominator, or ``None`` when the denominator is 0."""
    if denominator <= 0:
        return None
    return numerator / denominator


def rate_record(numerator: int, denominator: int) -> dict[str, Any]:
    """Return a JSON-ready ``{numerator, denominator, rate}`` record."""
    value = rate(numerator, denominator)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": None if value is None else round(value, 4),
    }


def format_rate(record: Mapping[str, Any]) -> str:
    """Render a rate record as ``n/d (p%)`` or ``n/a``."""
    value = record.get("rate")
    if value is None:
        return f"n/a ({record['numerator']}/{record['denominator']})"
    return f"{record['numerator']}/{record['denominator']} ({value * 100:.1f}%)"


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


def score_question(
    question_id: str,
    hits: Iterable[RankedHit],
    *,
    expected_material: str,
    expected_pages: Sequence[int],
    alt_expected: Sequence[Mapping[str, Any]] = (),
    k: int = TOP_K,
    page_aware: bool = False,
) -> QuestionOutcome:
    """Score one question against its ranked results.

    Material hit: any of the top ``k`` hits is in an accepted material.
    Page hit: any of the top ``k`` hits is in an accepted material and on one
    of that material's accepted pages (one page of a multi-page tag is
    enough). ``page_hit`` is ``None`` unless ``page_aware`` is true, which the
    caller sets only for retrievers that report pages. An empty result is then
    a page miss, not an exclusion.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    ranked = rank_hits(hits)
    top = ranked[:k]
    targets = accepted_targets(expected_material, expected_pages, alt_expected)
    first_rank: int | None = None
    page_hit: bool | None = False if page_aware else None
    for position, hit in enumerate(top, start=1):
        if hit.material_id not in targets:
            continue
        if first_rank is None:
            first_rank = position
        if page_aware and hit.page is not None and hit.page in targets[hit.material_id]:
            page_hit = True
    tie = len(ranked) > k and ranked[k - 1].score == ranked[k].score
    return QuestionOutcome(
        question_id=question_id,
        expected_material=expected_material,
        result_count=len(ranked),
        material_hit=first_rank is not None,
        page_hit=page_hit,
        first_material_rank=first_rank,
        tie_at_cutoff=tie,
        top_materials=tuple(hit.material_id for hit in top),
    )


def recall_at_k(outcomes: Sequence[QuestionOutcome]) -> dict[str, Any]:
    """Material-level recall: hits over all outcomes."""
    hits = sum(1 for outcome in outcomes if outcome.material_hit)
    return rate_record(hits, len(outcomes))


def page_recall_at_k(outcomes: Sequence[QuestionOutcome]) -> dict[str, Any]:
    """Page-level recall over outcomes whose results report pages."""
    scored = [outcome for outcome in outcomes if outcome.page_hit is not None]
    hits = sum(1 for outcome in scored if outcome.page_hit)
    return rate_record(hits, len(scored))


def wrong_skip_rate(decisions: Iterable[tuple[str, bool]]) -> dict[str, Any]:
    """Share of 'should retrieve' messages the gate skipped.

    Args:
        decisions: ``(expected_decision, gate_retrieved)`` per message.
    """
    expected_retrieve = [
        retrieved for expected, retrieved in decisions if expected == "retrieve"
    ]
    skipped = sum(1 for retrieved in expected_retrieve if not retrieved)
    return rate_record(skipped, len(expected_retrieve))


def false_retrieve_rate(decisions: Iterable[tuple[str, bool]]) -> dict[str, Any]:
    """Share of 'should skip' messages the gate searched for (reported extra)."""
    expected_skip = [
        retrieved for expected, retrieved in decisions if expected == "skip"
    ]
    searched = sum(1 for retrieved in expected_skip if retrieved)
    return rate_record(searched, len(expected_skip))


def empty_result_rate(result_counts: Iterable[int]) -> dict[str, Any]:
    """Share of completed attempts that returned zero results.

    Args:
        result_counts: Number of results per completed attempt.
    """
    counts = list(result_counts)
    empty = sum(1 for count in counts if count == 0)
    return rate_record(empty, len(counts))


def evenly_spaced_indices(total: int, limit: int) -> list[int]:
    """Pick ``min(limit, total)`` deterministic, evenly spread indices."""
    if total <= 0 or limit <= 0:
        return []
    if limit >= total:
        return list(range(total))
    return [index * total // limit for index in range(limit)]


# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise DatasetError(f"{path.name}:{line_number}: blank line")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path.name}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise DatasetError(f"{path.name}:{line_number}: not an object")
            rows.append(value)
    return rows


def load_materials(path: Path = MATERIALS_PATH) -> list[dict[str, Any]]:
    """Load the course-material manifest."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise DatasetError("course_materials.json must be a non-empty list")
    required = {"material_id", "object_key", "local_path", "filename", "group", "source_id", "pdf_pages"}
    ids: set[str] = set()
    for entry in manifest:
        missing = required - set(entry)
        if missing:
            raise DatasetError(f"manifest entry missing {sorted(missing)}")
        if entry["material_id"] in ids:
            raise DatasetError(f"duplicate material_id {entry['material_id']}")
        ids.add(entry["material_id"])
    return manifest


def validate_questions(
    rows: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    *,
    count_range: tuple[int, int] = QUESTION_COUNT_RANGE,
) -> None:
    """Raise :class:`DatasetError` if the question rows break the format."""
    low, high = count_range
    if not low <= len(rows) <= high:
        raise DatasetError(f"question count {len(rows)} outside {low}..{high}")
    pages_by_material = {m["material_id"]: int(m["pdf_pages"]) for m in materials}
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id"))
        if set(row) != QUESTION_KEYS:
            raise DatasetError(f"{row_id}: keys {sorted(set(row) ^ QUESTION_KEYS)} differ")
        if not re.fullmatch(r"rq\d{3}", row_id) or row_id in seen:
            raise DatasetError(f"{row_id}: bad or duplicate id")
        seen.add(row_id)
        if not str(row["question"]).strip() or not str(row["evidence"]).strip():
            raise DatasetError(f"{row_id}: empty question or evidence")
        if row["kind"] not in QUESTION_KINDS:
            raise DatasetError(f"{row_id}: unknown kind {row['kind']!r}")
        targets = [(row["expected_material"], row["expected_pages"])]
        if not isinstance(row["alt_expected"], list):
            raise DatasetError(f"{row_id}: alt_expected must be a list")
        for alt in row["alt_expected"]:
            if set(alt) != {"material", "pages", "evidence"}:
                raise DatasetError(f"{row_id}: bad alt_expected entry")
            targets.append((alt["material"], alt["pages"]))
        for material, pages in targets:
            if material not in pages_by_material:
                raise DatasetError(f"{row_id}: unknown material {material}")
            ok = (
                isinstance(pages, list)
                and pages
                and pages == sorted(set(pages))
                and all(isinstance(p, int) and 1 <= p <= pages_by_material[material] for p in pages)
            )
            if not ok:
                raise DatasetError(f"{row_id}: bad pages {pages} for {material}")


def validate_messages(
    rows: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    question_ids: Iterable[str],
    *,
    min_count: int = MIN_MESSAGE_COUNT,
    require_synthetic: bool = True,
) -> None:
    """Raise :class:`DatasetError` if the message rows break the format."""
    from backend.domain import VALID_STAGE_IDS

    if len(rows) < min_count:
        raise DatasetError(f"message count {len(rows)} below {min_count}")
    material_ids = {m["material_id"] for m in materials}
    known_questions = set(question_ids)
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id"))
        if set(row) != MESSAGE_KEYS:
            raise DatasetError(f"{row_id}: keys {sorted(set(row) ^ MESSAGE_KEYS)} differ")
        if not re.fullmatch(r"gm\d{3}", row_id) or row_id in seen:
            raise DatasetError(f"{row_id}: bad or duplicate id")
        seen.add(row_id)
        if row["synthetic"] is not True and require_synthetic:
            raise DatasetError(f"{row_id}: synthetic marker is not true")
        if not str(row["message"]).strip():
            raise DatasetError(f"{row_id}: empty message")
        if row["stage"] not in VALID_STAGE_IDS:
            raise DatasetError(f"{row_id}: unknown stage {row['stage']!r}")
        if row["expected_decision"] not in DECISIONS:
            raise DatasetError(f"{row_id}: bad expected_decision")
        if row["expected_scope"] not in SCOPES:
            raise DatasetError(f"{row_id}: bad expected_scope")
        if (row["expected_scope"] == "none") != (row["expected_decision"] == "skip"):
            raise DatasetError(f"{row_id}: scope 'none' must match decision 'skip'")
        if row["category"] not in MESSAGE_CATEGORIES:
            raise DatasetError(f"{row_id}: unknown category {row['category']!r}")
        if row["certainty"] not in CERTAINTIES:
            raise DatasetError(f"{row_id}: bad certainty")
        for field in ("selected_sources", "attachments"):
            for entry in row[field]:
                if set(entry) != {"title", "filename"}:
                    raise DatasetError(f"{row_id}: bad {field} entry")
        for turn in row["history"]:
            if set(turn) != {"role", "text"} or turn["role"] not in {"user", "assistant"}:
                raise DatasetError(f"{row_id}: bad history entry")
        if row["question_id"] is not None and row["question_id"] not in known_questions:
            raise DatasetError(f"{row_id}: unknown question_id {row['question_id']}")
        if row["expected_material"] is not None and row["expected_material"] not in material_ids:
            raise DatasetError(f"{row_id}: unknown expected_material")


def load_questions(
    path: Path = QUESTIONS_PATH, materials: Sequence[Mapping[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Load and validate the retrieval questions."""
    manifest = list(materials) if materials is not None else load_materials()
    rows = _read_jsonl(path)
    validate_questions(rows, manifest)
    return rows


def load_messages(
    path: Path = MESSAGES_PATH,
    materials: Sequence[Mapping[str, Any]] | None = None,
    question_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and validate the gate messages."""
    manifest = list(materials) if materials is not None else load_materials()
    ids = question_ids if question_ids is not None else [q["id"] for q in load_questions(materials=manifest)]
    rows = _read_jsonl(path)
    validate_messages(rows, manifest, ids)
    return rows


# ---------------------------------------------------------------------------
# Offline gate and course search (imports the backend lazily)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    """What the gate would do for one message."""

    retrieve: bool
    course: bool
    student: bool
    classifier_retrieve: bool


def _titles_and_names(entries: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    return (
        [str(entry.get("title") or "") for entry in entries],
        [str(entry.get("filename") or "") for entry in entries],
    )


def gate_decision(row: Mapping[str, Any]) -> GateDecision:
    """Compose the repo's retrieval gate for one message row.

    Mirrors ``CoachingExecution._prepare_authoritative_turn`` (``execution.py``,
    about lines 2832 to 3034) for a normal chat turn (no ``lecture_help``, no
    forced retrieval). Not modelled: image bytes, and the second-call
    ``needs_source_retrieval`` fallback, which needs a model.

    The effective decision is 'retrieve' only when a source is searched: the
    course catalog (``include_course_catalog``) or at least one personal file.
    """
    from backend.coaching.execution import _wants_course_catalog_retrieval
    from backend.coaching.mode_policy import (
        is_current_stage_status_request,
        is_private_attachment_question,
        is_stage_progression_request,
        is_terminal_completion_request,
        resolve_mode_policy,
        workflow_skips_retrieval,
    )

    message = str(row["message"])
    stage = str(row["stage"])
    selected = list(row["selected_sources"])
    attachments = list(row["attachments"])
    everything = selected + attachments
    titles, filenames = _titles_and_names(everything)
    policy = resolve_mode_policy(
        message,
        selected_source_titles=titles,
        selected_source_filenames=filenames,
        has_selected_sources=bool(everything),
    )
    status = is_current_stage_status_request(message)
    progression = is_stage_progression_request(message) or is_terminal_completion_request(
        message, current_stage=stage
    )
    workflow_no_retrieve = workflow_skips_retrieval(message, current_stage=stage)
    cleared = status or progression or workflow_no_retrieve
    mode_retrieve = bool(policy.retrieve) and not cleared
    attachment_only = is_private_attachment_question(
        message, attachment_count=len(attachments)
    )
    needs = mode_retrieve or attachment_only
    if cleared:
        personal: list[Mapping[str, Any]] = []
    elif attachment_only:
        personal = attachments
    else:
        personal = everything
    include_course = (
        needs
        and not attachment_only
        and not cleared
        and _wants_course_catalog_retrieval(message, mode_retrieve=mode_retrieve)
    )
    student = needs and bool(personal)
    return GateDecision(
        retrieve=bool(include_course or student),
        course=bool(include_course),
        student=bool(student),
        classifier_retrieve=bool(policy.retrieve),
    )


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
            )
            for chunk in result.chunks
            if chunk.score > 0.0
        ]


# ---------------------------------------------------------------------------
# Live Knowledge Base path (opt-in, never used by tests)
# ---------------------------------------------------------------------------


def check_live_request(live_kb: bool, max_live_calls: int | None, environ: Mapping[str, str]) -> int:
    """Validate the live opt-in and return the approved call limit.

    Makes no network call and imports no AWS library.

    Raises:
        LiveRunRefused: If the live flag is missing, the call limit is missing
            or out of range, or the Knowledge Base is not configured.
    """
    if max_live_calls is not None and not live_kb:
        raise LiveRunRefused("--max-live-calls only applies together with --live-kb")
    if not live_kb:
        raise LiveRunRefused("live mode was not requested")
    if max_live_calls is None:
        raise LiveRunRefused(
            "--live-kb requires --max-live-calls N (1 to "
            f"{HARD_LIVE_CALL_CAP}); no call limit was given"
        )
    if not 1 <= max_live_calls <= HARD_LIVE_CALL_CAP:
        raise LiveRunRefused(
            f"--max-live-calls must be between 1 and {HARD_LIVE_CALL_CAP}"
        )
    for name in ("KNOWLEDGE_BASE_ID", "COURSE_MATERIALS_BUCKET"):
        if not str(environ.get(name, "")).strip():
            raise LiveRunRefused(f"{name} is not set; the live Knowledge Base is not configured")
    return max_live_calls


class CountingClient:
    """Wrap a ``bedrock-agent-runtime`` client and stop after ``limit`` calls."""

    def __init__(self, client: Any, limit: int) -> None:
        self._client = client
        self._limit = limit
        self.calls = 0

    def retrieve(self, **kwargs: Any) -> Any:
        if self.calls >= self._limit:
            raise LiveCallLimitExceeded(f"call limit {self._limit} reached")
        self.calls += 1
        return self._client.retrieve(**kwargs)


def _build_live_client(region: str, limit: int) -> CountingClient:
    """Create the real AWS client. Only called after ``check_live_request``."""
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "bedrock-agent-runtime",
        region_name=region,
        config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
    )
    return CountingClient(client, limit)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _by_material(outcomes: Sequence[QuestionOutcome]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[QuestionOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.expected_material].append(outcome)
    return {material: recall_at_k(items) for material, items in sorted(grouped.items())}


def _question_summary(outcomes: Sequence[QuestionOutcome], questions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    text_by_id = {q["id"]: q["question"] for q in questions}
    return {
        "questions_evaluated": len(outcomes),
        "recall_at_4_material": recall_at_k(outcomes),
        "recall_at_4_page": page_recall_at_k(outcomes),
        "empty_result_rate": empty_result_rate(o.result_count for o in outcomes),
        "tie_at_cutoff_questions": sum(1 for o in outcomes if o.tie_at_cutoff),
        "recall_by_material": _by_material(outcomes),
        "misses": [
            {
                "id": o.question_id,
                "question": text_by_id[o.question_id],
                "expected_material": o.expected_material,
                "result_count": o.result_count,
                "top_materials": list(o.top_materials),
            }
            for o in outcomes
            if not o.material_hit
        ],
    }


def evaluate_gate(
    messages: Sequence[Mapping[str, Any]], search: OfflineCourseSearch | None
) -> dict[str, Any]:
    """Run the gate on every message; search the course for course-scope passes."""
    decisions: list[tuple[str, bool]] = []
    classifier_decisions: list[tuple[str, bool]] = []
    clear_only: list[tuple[str, bool]] = []
    by_category: dict[str, list[bool]] = defaultdict(list)
    course_attempt_counts: list[int] = []
    student_only_passes = 0
    for row in messages:
        decision = gate_decision(row)
        decisions.append((row["expected_decision"], decision.retrieve))
        classifier_decisions.append((row["expected_decision"], decision.classifier_retrieve))
        if row["certainty"] == "clear":
            clear_only.append((row["expected_decision"], decision.retrieve))
        if row["expected_decision"] == "retrieve":
            by_category[row["category"]].append(not decision.retrieve)
        if decision.course and search is not None:
            course_attempt_counts.append(len(search.search(row["message"], row["history"])))
        elif decision.student:
            student_only_passes += 1
    return {
        "messages": len(messages),
        "expected_retrieve": sum(1 for r in messages if r["expected_decision"] == "retrieve"),
        "expected_skip": sum(1 for r in messages if r["expected_decision"] == "skip"),
        "wrong_skip_rate": wrong_skip_rate(decisions),
        "wrong_skip_rate_clear_rows_only": wrong_skip_rate(clear_only),
        "wrong_skip_rate_classifier_only": wrong_skip_rate(classifier_decisions),
        "false_retrieve_rate": false_retrieve_rate(decisions),
        "wrong_skip_by_category": {
            category: rate_record(sum(skips), len(skips))
            for category, skips in sorted(by_category.items())
        },
        "course_attempts": len(course_attempt_counts),
        "empty_result_rate_course_attempts": empty_result_rate(course_attempt_counts),
        "student_file_only_passes_not_searched": student_only_passes,
    }


def run_offline(materials: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]], messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run the full offline evaluation."""
    search = OfflineCourseSearch(materials)
    outcomes = [
        score_question(
            q["id"],
            search.search(q["question"]),
            expected_material=q["expected_material"],
            expected_pages=q["expected_pages"],
            alt_expected=q["alt_expected"],
            page_aware=True,
        )
        for q in questions
    ]
    return {
        "mode": "offline",
        "course_search": "LocalChunkRetriever over local lecture PDFs, one chunk per page (not the Knowledge Base)",
        "network_calls": 0,
        "definitions": DEFINITIONS,
        "retrieval": _question_summary(outcomes, questions),
        "gate": evaluate_gate(messages, search),
    }


def run_live(
    materials: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
    limit: int,
) -> dict[str, Any]:
    """Run recall@4 and empty-result against the real Knowledge Base.

    One ``Retrieve`` call per question, at most ``limit`` calls, on a
    deterministic evenly spaced subset of the questions. The gate part stays
    offline (no calls).
    """
    from backend.bedrock_retrieve import BedrockKnowledgeBaseRetriever
    from backend.retrieval import RetrievalQuery, RetrievalSource, prefer_session_matching_sources
    from backend.settings import settings

    region = (
        str(settings.knowledge_base_region or "").strip()
        or str(settings.aws_region or "").strip()
        or "us-west-2"
    )
    client = _build_live_client(region, limit)
    retriever = BedrockKnowledgeBaseRetriever(
        str(settings.knowledge_base_id),
        region=region,
        course_bucket=str(settings.course_materials_bucket or "").strip(),
        client=client,
        knowledge_base_type=str(settings.normalized_knowledge_base_type),
    )
    sources = tuple(
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
        )
        for index, entry in enumerate(materials, start=1)
    )
    material_by_source = {entry["source_id"]: entry["material_id"] for entry in materials}
    chosen = [questions[i] for i in evenly_spaced_indices(len(questions), limit)]
    outcomes: list[QuestionOutcome] = []
    failed = 0
    for q in chosen:
        narrowed = prefer_session_matching_sources(sources, q["question"])
        result = retriever.retrieve(
            RetrievalQuery(
                current_message=q["question"],
                current_stage="problem_identification",
                sources=narrowed,
            )
        )
        if result.course_retrieval_status == "unavailable":
            failed += 1
            continue
        hits = [
            RankedHit(
                material_id=material_by_source.get(chunk.source_id, ""),
                page=None,
                score=float(chunk.score),
                source_index=chunk.source_index,
                chunk_index=chunk.chunk_index,
            )
            for chunk in result.chunks
        ]
        outcomes.append(
            score_question(
                q["id"],
                hits,
                expected_material=q["expected_material"],
                expected_pages=q["expected_pages"],
                alt_expected=q["alt_expected"],
            )
        )
    summary = _question_summary(outcomes, questions)
    summary["failed_attempts"] = failed
    summary["live_calls_made"] = client.calls
    summary["live_call_limit"] = limit
    return {
        "mode": "live",
        "course_search": "Bedrock Knowledge Base Retrieve (page-level scoring unavailable)",
        "definitions": DEFINITIONS,
        "retrieval": summary,
        "gate": evaluate_gate(messages, None),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _block_network() -> None:
    """Make any socket connection fail, so offline mode cannot reach a network."""
    import socket

    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network access is disabled in offline mode")

    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.getaddrinfo = _refuse  # type: ignore[assignment]


def format_report(result: Mapping[str, Any]) -> str:
    """Render the result as plain text."""
    retrieval = result["retrieval"]
    gate = result["gate"]
    lines = [
        f"mode: {result['mode']}",
        f"course search: {result['course_search']}",
        "",
        f"questions evaluated: {retrieval['questions_evaluated']}",
        f"recall@4 (material): {format_rate(retrieval['recall_at_4_material'])}",
        f"recall@4 (page):     {format_rate(retrieval['recall_at_4_page'])}",
        f"empty-result rate (questions): {format_rate(retrieval['empty_result_rate'])}",
        f"questions with a score tie at the rank-4 cutoff: {retrieval['tie_at_cutoff_questions']}",
        "recall@4 by expected material:",
    ]
    for material, record in retrieval["recall_by_material"].items():
        lines.append(f"  {material}: {format_rate(record)}")
    if "live_calls_made" in retrieval:
        lines.append(
            f"live calls made: {retrieval['live_calls_made']} of limit {retrieval['live_call_limit']}; "
            f"failed attempts: {retrieval['failed_attempts']}"
        )
    lines += [
        "",
        f"gate messages: {gate['messages']} (retrieve {gate['expected_retrieve']}, skip {gate['expected_skip']}; all SYNTHETIC)",
        f"wrong-skip rate: {format_rate(gate['wrong_skip_rate'])}",
        f"wrong-skip rate, clear rows only: {format_rate(gate['wrong_skip_rate_clear_rows_only'])}",
        f"wrong-skip rate, classifier only (before catalog step): {format_rate(gate['wrong_skip_rate_classifier_only'])}",
        f"false-retrieve rate (extra): {format_rate(gate['false_retrieve_rate'])}",
        f"empty-result rate (gate-passed course searches): {format_rate(gate['empty_result_rate_course_attempts'])}",
        "wrong-skip by category:",
    ]
    for category, record in gate["wrong_skip_by_category"].items():
        lines.append(f"  {category}: {format_rate(record)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline retrieval eval (recall@4, wrong-skip, empty-result). "
        "Live Knowledge Base use needs --live-kb and --max-live-calls."
    )
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--messages", type=Path, default=MESSAGES_PATH)
    parser.add_argument("--materials", type=Path, default=MATERIALS_PATH)
    parser.add_argument("--json-output", type=Path, default=None, help="also write the full result as JSON")
    parser.add_argument(
        "--live-kb",
        action="store_true",
        help="OPT-IN. Call the real Bedrock Knowledge Base (costs money). Needs --max-live-calls.",
    )
    parser.add_argument(
        "--max-live-calls",
        type=int,
        default=None,
        help=f"Mandatory with --live-kb: hard limit on Retrieve calls (1 to {HARD_LIVE_CALL_CAP}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    live_requested = args.live_kb or args.max_live_calls is not None
    limit = 0
    if live_requested:
        try:
            limit = check_live_request(args.live_kb, args.max_live_calls, os.environ)
        except LiveRunRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    else:
        # Mock providers and no keys: nothing in this process may reach AWS or OpenAI.
        for name, value in (
            ("MOCK_OPENAI", "true"),
            ("MODEL_PROVIDER", "mock"),
            ("OPENAI_API_KEY", ""),
            ("USE_LOCAL_API", "false"),
            ("AUTO_ADVANCE_STAGES", "false"),
            ("APP_ENV", "development"),
        ):
            os.environ.setdefault(name, value)
        _block_network()
    materials = load_materials(args.materials)
    questions = load_questions(args.questions, materials)
    messages = load_messages(args.messages, materials, [q["id"] for q in questions])
    if live_requested:
        result = run_live(materials, questions, messages, limit)
    else:
        result = run_offline(materials, questions, messages)
    print(format_report(result))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
