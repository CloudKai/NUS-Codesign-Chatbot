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

LIVE MODEL mode (real Bedrock ``converse`` calls to the fast-chat Haiku model)
is also off by default. It runs only with ``--live-model`` AND
``--max-live-calls N``. It sends each gate message through the first Fast Chat
call with ``needs_sources`` on and reports flag rate, wrong-skip, false-retrieve
and extra model calls by category. Tests use a stub client only.

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
    second_chance: bool = False
    # Fields the live model mode copies onto the request it builds. They
    # mirror what ``_prepare_authoritative_turn`` stamps for the same turn.
    expected_mode: str | None = None
    intent: str = ""
    needs_retrieval: bool = False
    scope_cleared: bool = False
    attachment_only: bool = False


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
        # Mirrors ``_wants_source_need_check``: nothing searched and no gate
        # override fixed the evidence scope.
        second_chance=bool(
            not (include_course or student) and not cleared and not attachment_only
        ),
        expected_mode=(
            "qa"
            if status
            else "coaching"
            if progression or workflow_no_retrieve
            else policy.expected_mode
        ),
        intent=str(policy.intent or ""),
        needs_retrieval=bool(needs or include_course),
        scope_cleared=bool(cleared),
        attachment_only=bool(attachment_only),
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
        raise LiveRunRefused(
            "--max-live-calls only applies together with --live-kb or --live-model"
        )
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


NEEDS_SOURCES_DEFINITION = (
    "Models the second chance given by the first-call 'needs_sources' flag "
    "(FAST_CHAT_NEEDS_SOURCES_ENABLED) with three STUBS in place of the model. "
    "A message is eligible when the gate searched nothing and no gate override "
    "fixed its evidence scope. 'oracle' flags exactly the messages labelled "
    "'retrieve' (a perfect model: best case). 'mock_rule' flags eligible "
    "messages phrased as a question or information request (the mock "
    "provider's rule: a deterministic stand-in). 'flag_all' flags every "
    "eligible message (a model that over-flags: worst case for false "
    "retrieves). A flagged message is searched on the second pass (selected "
    "sources plus the course catalog). None of this measures a real model."
)


def _needs_sources_stubs(
    scored: Sequence[tuple[Mapping[str, Any], GateDecision]],
    search: OfflineCourseSearch | None,
) -> dict[str, Any]:
    """Apply three stub models of ``needs_sources`` on top of the gate.

    Args:
        scored: ``(message row, first-pass gate decision)`` per message.
        search: Offline course search, used to count empty second-pass results.
    """
    from backend.mock_provider import mock_flags_needs_sources

    stubs = {
        "oracle": lambda row: row["expected_decision"] == "retrieve",
        "mock_rule": lambda row: mock_flags_needs_sources(str(row["message"])),
        "flag_all": lambda row: True,
    }
    first_pass_empty = 0
    first_pass_attempts = 0
    for row, decision in scored:
        if decision.course and search is not None:
            first_pass_attempts += 1
            if not search.search(row["message"], row["history"]):
                first_pass_empty += 1
    eligible = [(row, d) for row, d in scored if d.second_chance]
    wrong_skips = [
        row for row, d in scored if row["expected_decision"] == "retrieve" and not d.retrieve
    ]
    eligible_wrong_skips = sum(1 for row, d in eligible if row["expected_decision"] == "retrieve")
    out: dict[str, Any] = {
        "definition": NEEDS_SOURCES_DEFINITION,
        "eligible_messages": len(eligible),
        "wrong_skips_before": len(wrong_skips),
        "wrong_skips_eligible_for_second_chance": eligible_wrong_skips,
        "stubs": {},
    }
    for name, flags in stubs.items():
        decisions: list[tuple[str, bool]] = []
        attempts = first_pass_attempts
        empty = first_pass_empty
        second_calls = 0
        for row, decision in scored:
            retrieved = decision.retrieve
            if decision.second_chance and flags(row):
                retrieved = True
                second_calls += 1
                if search is not None:
                    attempts += 1
                    if not search.search(row["message"], row["history"]):
                        empty += 1
            decisions.append((row["expected_decision"], retrieved))
        out["stubs"][name] = {
            "wrong_skip_rate": wrong_skip_rate(decisions),
            "false_retrieve_rate": false_retrieve_rate(decisions),
            "empty_result_rate_course_attempts": rate_record(empty, attempts),
            "second_model_calls": second_calls,
        }
    return out


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
    scored: list[tuple[Mapping[str, Any], GateDecision]] = []
    for row in messages:
        decision = gate_decision(row)
        scored.append((row, decision))
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
        "needs_sources_stubs": _needs_sources_stubs(scored, search),
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
# Live model path: the first Fast Chat call with needs_sources (opt-in)
# ---------------------------------------------------------------------------

# One model call per message, sequential, no retries. The gate set has fewer
# than 500 messages, so a higher limit could never be used.
LIVE_MODEL_HARD_CALL_CAP = 500
# Same read timeout as ``AgentCoreCoachProvider`` (``timeout_seconds=110``).
LIVE_MODEL_TIMEOUT_SECONDS = 110.0
# Same output reserve as the fast-chat context planner
# (``_fast_chat_planner_from_settings``: ``output_reserve_tokens=4_000``).
LIVE_MODEL_MAX_OUTPUT_TOKENS = 4_000
# Never invoked: the provider is built only to reuse its payload builder.
_EVAL_RUNTIME_ARN = "eval:runtime-never-invoked"

# Codes and exception classes that mean "credentials or permission": the run
# stops after the first one, because every later call would fail the same way.
AUTH_ACCESS_ERROR_CODES = frozenset(
    {
        "AccessDeniedException",
        "AccessDenied",
        "UnrecognizedClientException",
        "InvalidClientTokenId",
        "ExpiredTokenException",
        "ExpiredToken",
        "AuthFailure",
        "InvalidSignatureException",
        "SignatureDoesNotMatch",
        "UnauthorizedOperation",
        "UnauthorizedException",
    }
)
AUTH_ACCESS_ERROR_CLASSES = frozenset(
    {
        "NoCredentialsError",
        "PartialCredentialsError",
        "TokenRetrievalError",
        "CredentialRetrievalError",
        "NoAuthTokenError",
    }
)

LIVE_MODEL_DEFINITION = (
    "Sends each gate message through the first Fast Chat call as production "
    "builds it (AgentCoreCoachProvider._invoke_payload: same composed runtime "
    "rules, history planner and Converse messages; the runtime system prompt "
    "from agentcore_runtime.structured_coach.specialist_system_prompt; the "
    "FastChatTurnOutput tool schema; the response checked by "
    "backend.agentcore_provider._validated_fast_chat) with the SOURCE CHECK "
    "rule on (request.source_need_check). Composition as in needs_sources_stubs: "
    "a message counts as retrieved when the gate searched a source, or when it "
    "is eligible for the second chance and the model's honoured needs_sources "
    "flag is true. The flag is honoured only on a Q&A turn. Rows whose call "
    "failed are not scored. Eligible rows are the only rows whose flag changes "
    "a metric; the flag on other rows is reported as raw flag rate only."
)


class LiveStructuredOutputError(RuntimeError):
    """The model returned no usable ``FastChatTurnOutput`` tool call."""


def check_live_model_request(
    live_model: bool,
    live_kb: bool,
    max_live_calls: int | None,
    *,
    provider: str,
    model_id: str,
    region: str,
) -> int:
    """Validate the live model opt-in and return the approved call limit.

    Makes no network call and imports no AWS library.

    Args:
        live_model: ``--live-model``.
        live_kb: ``--live-kb`` (cannot be combined with the model mode).
        max_live_calls: ``--max-live-calls``.
        provider: Fast-chat provider from settings (``COACHING_MODEL_PROVIDER``).
        model_id: Fast-chat model id from settings (``COACHING_MODEL_ID``).
        region: Model region from settings.

    Raises:
        LiveRunRefused: When the limit is missing or out of range, the mode is
            combined with ``--live-kb``, or the model settings are not a Haiku
            model on the ``bedrock`` provider.
    """
    if live_kb:
        raise LiveRunRefused("--live-model cannot be combined with --live-kb")
    if not live_model:
        raise LiveRunRefused("live model mode was not requested")
    if max_live_calls is None:
        raise LiveRunRefused(
            "--live-model requires --max-live-calls N (1 to "
            f"{LIVE_MODEL_HARD_CALL_CAP}); no call limit was given"
        )
    if not 1 <= max_live_calls <= LIVE_MODEL_HARD_CALL_CAP:
        raise LiveRunRefused(
            f"--max-live-calls must be between 1 and {LIVE_MODEL_HARD_CALL_CAP}"
        )
    if str(provider or "").strip().lower() != "bedrock":
        raise LiveRunRefused(
            "COACHING_MODEL_PROVIDER must be 'bedrock' for the fast-chat model "
            f"(got {provider or 'empty'!r})"
        )
    if "haiku" not in str(model_id or "").lower():
        raise LiveRunRefused(
            "COACHING_MODEL_ID is not set to a Haiku model "
            f"(got {model_id or 'empty'!r}); the fast-chat role is Haiku"
        )
    if not str(region or "").strip():
        raise LiveRunRefused("AGENTCORE_MODEL_REGION (or AWS_REGION) is not set")
    return max_live_calls


def live_model_settings() -> tuple[str, str, str]:
    """Return ``(provider, model_id, region)`` the fast-chat role uses.

    Mirrors ``AgentCoreCoachProvider._role_provider_model("fast_chat")`` and
    the runtime region rule (``AGENTCORE_MODEL_REGION``, then ``AWS_REGION``).
    """
    from backend.settings import settings

    provider = str(settings.coaching_model_provider or "").strip().lower()
    model_id = str(settings.coaching_model_id or "").strip()
    if not (provider and model_id):
        provider = str(settings.agentcore_model_provider or "").strip().lower()
        model_id = str(settings.agentcore_model_id or "").strip()
    region = (
        str(settings.agentcore_model_region or "").strip()
        or str(settings.aws_region or "").strip()
    )
    return provider, model_id, region


class CountingConverseClient:
    """Wrap a ``bedrock-runtime`` client: stop after ``limit`` calls, sum tokens."""

    def __init__(self, client: Any, limit: int) -> None:
        self._client = client
        self._limit = limit
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def converse(self, **kwargs: Any) -> Any:
        if self.calls >= self._limit:
            raise LiveCallLimitExceeded(f"call limit {self._limit} reached")
        self.calls += 1
        response = self._client.converse(**kwargs)
        usage = response.get("usage") if isinstance(response, Mapping) else None
        if isinstance(usage, Mapping):
            self.input_tokens += int(usage.get("inputTokens") or 0)
            self.output_tokens += int(usage.get("outputTokens") or 0)
        return response


def _build_bedrock_runtime_client(region: str, limit: int) -> CountingConverseClient:
    """Create the real Bedrock Runtime client. Only called after the checks."""
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            read_timeout=LIVE_MODEL_TIMEOUT_SECONDS,
            connect_timeout=10,
        ),
    )
    return CountingConverseClient(client, limit)


def _inline_schema_refs(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Inline ``$ref`` targets and drop ``$defs`` (a tool schema must be flat)."""
    defs = dict(schema.get("$defs") or {})

    def walk(node: Any) -> Any:
        if isinstance(node, Mapping):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return walk(defs[ref.rsplit("/", 1)[-1]])
            return {key: walk(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(dict(schema))


class LiveFastChatBridge:
    """Run the AgentCore runtime's fast-chat model call straight on Bedrock.

    The runtime (``agentcore_runtime/main.py::fast_chat_invoke``) builds a
    Strands ``Agent`` with ``tools=[]`` and ``structured_output_model=
    FastChatTurnOutput``; Strands forwards that model to Bedrock Converse as
    one forced tool. This class sends the same system prompt, messages and
    tool through ``bedrock-runtime`` ``converse`` without Strands or an
    AgentCore hop. Differences from production, all recorded in the docs: no
    Bedrock guardrail, no prompt-cache point, no structured-output recovery
    turn (a reply without the tool call is a failure), no SDK retries.
    """

    def __init__(self, client: Any, model_id: str) -> None:
        from agentcore_runtime.models import FastChatTurnOutput

        self._client = client
        self._model_id = model_id
        self._schema = _inline_schema_refs(FastChatTurnOutput.model_json_schema())
        self._description = " ".join(
            (FastChatTurnOutput.__doc__ or "").split("\n\n")[0].split()
        )

    def request_kwargs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Build the Converse arguments for one runtime payload."""
        from agentcore_runtime.structured_coach import (
            conversation_for_invoke,
            specialist_system_prompt,
        )

        prior, prompt = conversation_for_invoke(payload)
        current = [{"text": prompt}] if isinstance(prompt, str) else list(prompt)
        return {
            "modelId": self._model_id,
            "system": [{"text": specialist_system_prompt(payload)}],
            "messages": [*prior, {"role": "user", "content": current}],
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "FastChatTurnOutput",
                            "description": self._description,
                            "inputSchema": {"json": self._schema},
                        }
                    }
                ],
                # First-cycle forced tool use, as the runtime middleware sets.
                "toolChoice": {"any": {}},
            },
            "inferenceConfig": {"maxTokens": LIVE_MODEL_MAX_OUTPUT_TOKENS},
        }

    def invoke(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the runtime wire payload for one fast-chat turn.

        Raises:
            LiveStructuredOutputError: When the reply has no valid tool call.
        """
        from agentcore_runtime.models import parse_fast_chat_turn_output
        from agentcore_runtime.structured_coach import structured_wire_payload

        response = self._client.converse(**self.request_kwargs(payload))
        message = ((response.get("output") or {}).get("message")) or {}
        tool_input = None
        for block in message.get("content") or []:
            tool_use = block.get("toolUse") if isinstance(block, Mapping) else None
            if isinstance(tool_use, Mapping) and isinstance(tool_use.get("input"), Mapping):
                tool_input = tool_use["input"]
                break
        if tool_input is None:
            raise LiveStructuredOutputError(
                f"no tool call in reply (stopReason={response.get('stopReason')!r})"
            )
        try:
            output = parse_fast_chat_turn_output(dict(tool_input))
        except ValueError as error:
            raise LiveStructuredOutputError(
                f"tool input failed validation ({type(error).__name__})"
            ) from error
        return structured_wire_payload(output)


def build_live_request(row: Mapping[str, Any], decision: GateDecision) -> Any:
    """Build the ``CoachRequest`` production would hand the provider.

    Mirrors the fields ``_prepare_authoritative_turn`` stamps that change the
    first call's prompt. Retrieved excerpts are never attached: a row the gate
    searched for is sent without them (see ``LIVE_MODEL_DEFINITION``).
    ``source_need_check`` is forced on so every row measures the flag.
    """
    from backend.domain import CoachRequest

    selected = list(row["selected_sources"])
    attachments = list(row["attachments"])
    attachment_ids = [f"eval-attachment-{i}" for i, _ in enumerate(attachments, 1)]
    selected_ids = [f"eval-source-{i}" for i, _ in enumerate(selected, 1)]
    if decision.scope_cleared:
        source_ids: list[str] = []
    elif decision.attachment_only:
        source_ids = list(attachment_ids)
    else:
        source_ids = selected_ids + attachment_ids
    return CoachRequest(
        thread_id=f"eval-{row['id']}",
        student_message=str(row["message"]),
        current_stage=str(row["stage"]),
        response_detail="short",
        source_ids=source_ids,
        attachment_source_ids=attachment_ids,
        attachment_titles=[str(item.get("title") or "") for item in attachments],
        allow_model_knowledge=not source_ids and not decision.course,
        history=[
            {"role": turn["role"], "content": turn["text"]} for turn in row["history"]
        ],
        retrieval_required=bool(decision.needs_retrieval),
        source_need_check=True,
        expected_response_mode=decision.expected_mode,
        mode_policy_intent=decision.intent,
    )


def exception_label(error: BaseException) -> str:
    """Return ``module.Class`` plus the AWS error code when there is one."""
    name = f"{type(error).__module__}.{type(error).__qualname__}"
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping) and isinstance(response.get("Error"), Mapping):
        code = str(response["Error"].get("Code") or "")
    return f"{name} (code {code})" if code else name


def is_auth_or_access_error(error: BaseException) -> bool:
    """Return whether *error* is a credential or permission failure."""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping) and isinstance(response.get("Error"), Mapping):
        if str(response["Error"].get("Code") or "") in AUTH_ACCESS_ERROR_CODES:
            return True
    return type(error).__name__ in AUTH_ACCESS_ERROR_CLASSES


def _live_block(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Metrics for scored live rows (successful calls)."""
    composed: list[tuple[str, bool]] = []
    gate_only: list[tuple[str, bool]] = []
    composed_clear: list[tuple[str, bool]] = []
    eligible = [item for item in items if item["eligible"]]
    flagged = [item for item in eligible if item["honoured"]]
    for item in items:
        expected = item["expected_decision"]
        retrieved = bool(item["gate_retrieve"] or (item["eligible"] and item["honoured"]))
        composed.append((expected, retrieved))
        gate_only.append((expected, bool(item["gate_retrieve"])))
        if item["certainty"] == "clear":
            composed_clear.append((expected, retrieved))
    return {
        "messages_scored": len(items),
        "eligible_messages": len(eligible),
        "flag_rate_eligible": rate_record(len(flagged), len(eligible)),
        "flag_rate_raw_all_rows": rate_record(
            sum(1 for item in items if item["flag_raw"]), len(items)
        ),
        "raw_flags_not_honoured": sum(
            1 for item in items if item["flag_raw"] and not item["honoured"]
        ),
        "wrong_skip_gate_only": wrong_skip_rate(gate_only),
        "wrong_skip_with_model": wrong_skip_rate(composed),
        "false_retrieve_gate_only": false_retrieve_rate(gate_only),
        "false_retrieve_with_model": false_retrieve_rate(composed),
        "false_retrieve_with_model_clear_rows_only": false_retrieve_rate(composed_clear),
        "extra_model_calls": len(flagged),
    }


def summarize_live_model(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Turn per-message outcomes into overall and per-category metrics."""
    scored = [o for o in outcomes if o["status"] == "ok"]
    by_category: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in scored:
        by_category[item["category"]].append(item)
    sent_by_category: dict[str, int] = defaultdict(int)
    failed_by_category: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        sent_by_category[outcome["category"]] += 1
        if outcome["status"] != "ok":
            failed_by_category[outcome["category"]] += 1
    categories: dict[str, Any] = {}
    for category in sorted(sent_by_category):
        block = _live_block(by_category.get(category, []))
        block["messages_sent"] = sent_by_category[category]
        block["calls_failed"] = failed_by_category.get(category, 0)
        categories[category] = block
    return {
        "overall": _live_block(scored),
        "by_category": categories,
        # Skip-labelled, eligible messages the model flagged: each one is a
        # false retrieve and an extra model call.
        "false_flags": [
            {"id": o["id"], "category": o["category"], "certainty": o["certainty"]}
            for o in scored
            if o["eligible"] and o["honoured"] and o["expected_decision"] == "skip"
        ],
        # Retrieve-labelled, eligible messages the model did not flag: the
        # wrong skips that remain.
        "missed_flags": [
            {"id": o["id"], "category": o["category"], "certainty": o["certainty"]}
            for o in scored
            if o["eligible"] and not o["honoured"] and o["expected_decision"] == "retrieve"
        ],
        # Eligible, flagged but returned as coaching or out of scope: the
        # application ignores the flag.
        "flag_ignored": [
            {"id": o["id"], "mode": o["mode"], "out_of_scope": o["out_of_scope"]}
            for o in scored
            if o["flag_raw"] and not o["honoured"]
        ],
    }


def run_live_model(
    messages: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    client: Any,
    model_id: str,
    region: str,
) -> dict[str, Any]:
    """Send up to ``limit`` gate messages through the first fast-chat call.

    Args:
        messages: Validated gate rows.
        limit: Approved call limit. Below the row count, an evenly spaced,
            deterministic subset is sent.
        client: A ``CountingConverseClient`` (tests pass one over a stub).
        model_id: Fast-chat model id from settings.
        region: Model region from settings.

    Stops after the first auth or access error. Never retries a call.
    """
    from backend.agentcore_provider import (
        _FAST_CHAT_CONTRACT,
        _FAST_CHAT_PHASE,
        AgentCoreCoachProvider,
        _validated_fast_chat,
    )
    from agentcore_runtime.models import adapt_fast_chat_turn_payload
    from backend.context_planner import CONTEXT_POLICY_FAST_CHAT

    class _NoRuntime:
        def invoke_agent_runtime(self, **_kwargs: Any) -> Any:
            raise AssertionError("AgentCore Runtime must not be invoked by the eval")

    provider = AgentCoreCoachProvider(_EVAL_RUNTIME_ARN, client=_NoRuntime())
    bridge = LiveFastChatBridge(client, model_id)
    chosen = [messages[i] for i in evenly_spaced_indices(len(messages), limit)]
    outcomes: list[dict[str, Any]] = []
    first_failure: dict[str, Any] | None = None
    stopped_on: dict[str, Any] | None = None
    for row in chosen:
        decision = gate_decision(row)
        base = {
            "id": row["id"],
            "category": row["category"],
            "certainty": row["certainty"],
            "expected_decision": row["expected_decision"],
            "eligible": bool(decision.second_chance),
            "gate_retrieve": bool(decision.retrieve),
        }
        try:
            request = build_live_request(row, decision)
            payload, _plan = provider._invoke_payload(
                request,
                _FAST_CHAT_PHASE,
                context_policy=CONTEXT_POLICY_FAST_CHAT,
                phase=_FAST_CHAT_PHASE,
                output_contract=_FAST_CHAT_CONTRACT,
            )
            wire = bridge.invoke(payload)
            raw = adapt_fast_chat_turn_payload(wire)
            result = _validated_fast_chat(wire, request)
        except LiveCallLimitExceeded:
            break
        except Exception as error:  # noqa: BLE001 - recorded, never swallowed
            failure = {"id": row["id"], "error": exception_label(error)}
            if first_failure is None:
                first_failure = failure
            outcomes.append({**base, "status": "failed", "error": failure["error"]})
            if is_auth_or_access_error(error):
                stopped_on = failure
                break
            continue
        outcomes.append(
            {
                **base,
                "status": "ok",
                "flag_raw": bool(raw.needs_sources),
                "honoured": bool(result.needs_sources),
                "mode": str(result.specialist),
                "out_of_scope": bool(raw.out_of_scope),
            }
        )
    succeeded = sum(1 for o in outcomes if o["status"] == "ok")
    summary = summarize_live_model(outcomes)
    return {
        "mode": "live_model",
        "definition": LIVE_MODEL_DEFINITION,
        "model": {"provider": "bedrock", "model_id": model_id, "region": region},
        "calls": {
            "limit": limit,
            "made": client.calls,
            "succeeded": succeeded,
            "failed": len(outcomes) - succeeded,
            "messages_in_set": len(messages),
            "messages_attempted": len(outcomes),
        },
        "tokens": {
            "input": client.input_tokens,
            "output": client.output_tokens,
        },
        "first_failure": first_failure,
        "stopped_early_on_auth_or_access_error": stopped_on,
        **summary,
        "rows": outcomes,
    }


def live_model_exit_code(result: Mapping[str, Any]) -> int:
    """0 = ran; 1 = every call failed; 3 = stopped early on an auth/access error."""
    if int(result["calls"]["succeeded"]) == 0:
        return 1
    if result.get("stopped_early_on_auth_or_access_error"):
        return 3
    return 0


def format_live_model_report(result: Mapping[str, Any]) -> str:
    """Render the live model result as plain text."""
    calls = result["calls"]
    model = result["model"]
    overall = result["overall"]
    lines = [
        "mode: live_model (needs_sources on the first fast-chat call)",
        f"model: {model['model_id']} in {model['region']} ({model['provider']})",
        f"calls: made {calls['made']} of limit {calls['limit']}; succeeded "
        f"{calls['succeeded']}; failed {calls['failed']}; messages attempted "
        f"{calls['messages_attempted']} of {calls['messages_in_set']}",
        f"tokens: input {result['tokens']['input']}, output {result['tokens']['output']}",
    ]
    if result["first_failure"]:
        failure = result["first_failure"]
        lines.append(f"first failure: {failure['error']} on {failure['id']}")
    if result["stopped_early_on_auth_or_access_error"]:
        lines.append("stopped early: auth or access error (no further calls made)")
    lines += [
        "",
        f"messages scored: {overall['messages_scored']}; eligible for the second chance: "
        f"{overall['eligible_messages']}",
        f"flag rate (eligible, honoured): {format_rate(overall['flag_rate_eligible'])}",
        f"flag rate (raw, all rows sent): {format_rate(overall['flag_rate_raw_all_rows'])}; "
        f"raw flags not honoured: {overall['raw_flags_not_honoured']}",
        f"wrong-skip: gate only {format_rate(overall['wrong_skip_gate_only'])}; "
        f"with model {format_rate(overall['wrong_skip_with_model'])}",
        f"false-retrieve: gate only {format_rate(overall['false_retrieve_gate_only'])}; "
        f"with model {format_rate(overall['false_retrieve_with_model'])}; "
        f"clear rows only {format_rate(overall['false_retrieve_with_model_clear_rows_only'])}",
        f"extra model calls (second calls): {overall['extra_model_calls']}",
        "",
        "by category (sent / failed; flag rate on eligible; wrong-skip gate->model; "
        "false-retrieve gate->model; extra calls):",
    ]
    for category, block in result["by_category"].items():
        lines.append(
            f"  {category}: {block['messages_sent']} / {block['calls_failed']}; "
            f"flag {format_rate(block['flag_rate_eligible'])}; "
            f"wrong-skip {format_rate(block['wrong_skip_gate_only'])} -> "
            f"{format_rate(block['wrong_skip_with_model'])}; "
            f"false-retrieve {format_rate(block['false_retrieve_gate_only'])} -> "
            f"{format_rate(block['false_retrieve_with_model'])}; "
            f"extra {block['extra_model_calls']}"
        )
    lines.append(
        f"skip-labelled eligible messages flagged (false flags): {len(result['false_flags'])}; "
        f"retrieve-labelled eligible messages not flagged: {len(result['missed_flags'])}"
    )
    return "\n".join(lines)


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
    stubs = gate.get("needs_sources_stubs")
    if stubs:
        lines += [
            "",
            "needs_sources second chance (STUB models, not a real model):",
            f"  eligible messages: {stubs['eligible_messages']}; "
            f"wrong skips eligible: {stubs['wrong_skips_eligible_for_second_chance']}"
            f" of {stubs['wrong_skips_before']}",
        ]
        for name, record in stubs["stubs"].items():
            lines.append(
                f"  {name}: wrong-skip {format_rate(record['wrong_skip_rate'])}; "
                f"false-retrieve {format_rate(record['false_retrieve_rate'])}; "
                f"empty {format_rate(record['empty_result_rate_course_attempts'])}; "
                f"second model calls {record['second_model_calls']}"
            )
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
        "--live-model",
        action="store_true",
        help="OPT-IN. Send each gate message through the first fast-chat call on "
        "the real Bedrock model with needs_sources on (costs money). Needs "
        "--max-live-calls. Cannot be combined with --live-kb.",
    )
    parser.add_argument(
        "--max-live-calls",
        type=int,
        default=None,
        help="Mandatory with --live-kb or --live-model: hard limit on calls "
        f"(--live-kb: 1 to {HARD_LIVE_CALL_CAP} Retrieve calls; --live-model: "
        f"1 to {LIVE_MODEL_HARD_CALL_CAP} model calls).",
    )
    return parser


def _main_live_model(args: argparse.Namespace) -> int:
    """Run ``--live-model``: refuse without a valid call limit, else call Bedrock."""
    try:
        provider, model_id, region = live_model_settings()
        limit = check_live_model_request(
            args.live_model,
            args.live_kb,
            args.max_live_calls,
            provider=provider,
            model_id=model_id,
            region=region,
        )
    except LiveRunRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    materials = load_materials(args.materials)
    questions = load_questions(args.questions, materials)
    messages = load_messages(args.messages, materials, [q["id"] for q in questions])
    client = _build_bedrock_runtime_client(region, limit)
    result = run_live_model(
        messages, limit, client=client, model_id=model_id, region=region
    )
    print(format_live_model_report(result))
    if result["first_failure"]:
        print(
            f"first failure class: {result['first_failure']['error']}",
            file=sys.stderr,
        )
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    code = live_model_exit_code(result)
    if code == 1:
        print("every call failed", file=sys.stderr)
    elif code == 3:
        print("stopped early on an auth or access error", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live_model:
        return _main_live_model(args)
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
