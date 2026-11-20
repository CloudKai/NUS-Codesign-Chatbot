"""Measure course retrieval: recall@4, wrong-skip rate and empty-result rate.

Default mode is OFFLINE. It uses no network, no AWS, no model and no API key:

* The retrieval gate is the repo's own rules-based gate. ``gate_decision``
  calls ``backend.coaching.evidence_scope.decide_first_pass_scope``, the same
  function ``CoachApplicationService._prepare_authoritative_turn`` calls.
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
and extra model calls by category. ``--ids``, ``--categories``,
``--expected-decision`` and ``--skip-sample`` limit it to chosen rows
(``--max-live-calls`` applies after them), and ``--compare-source-check`` sends
each chosen row with the SOURCE CHECK rule on and then off (two calls per row,
both counted by ``--max-live-calls``). Tests use a stub client only.

Every ``--json-output`` file (all modes) carries a ``run`` block with the git
SHA, a dirty flag and a UTC timestamp.

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
FOLLOWUPS_PATH = DATASET_DIR / "retrieval_gate_followups.synthetic.jsonl"
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

FOLLOWUP_DEFINITION = (
    "Follow-up cases are reported apart from the gate messages. gate_ok: the "
    "gate searched the course (retrieve cases) or searched nothing (skip "
    "cases). query_ok: one of the top 4 offline results for the query the "
    "Knowledge Base adapter builds from the message and history is in the "
    "expected material (the search gets no history, like the Knowledge Base). "
    "end_to_end_pass: gate_ok and query_ok. standalone_ok: the linked "
    "standalone question passes the gate and its top 4 hold the expected "
    "material. Rewriting is justified only when at least 5 retrieve cases "
    "fail end to end and at least 5 of those failures have standalone_ok."
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
    text: str = ""


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


# Phase 3b item C: threshold for "clearly fail", fixed in
# .agents/tasks/phase3b-work/item-c-notes.md before any case was measured.
FOLLOWUP_MIN_FAILURES = 5
FOLLOWUP_MIN_ATTRIBUTABLE = 5


def followup_verdict(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the recorded "clearly fail" rule to per-case follow-up results.

    Only ``retrieve`` cases count. A case fails when its end-to-end result is
    false. A failure is attributable to the follow-up form when the linked
    standalone question passes. Rewriting is justified only when at least
    ``FOLLOWUP_MIN_FAILURES`` cases fail and at least
    ``FOLLOWUP_MIN_ATTRIBUTABLE`` of those failures are attributable.
    """
    retrieve_cases = [c for c in cases if c["expected_decision"] == "retrieve"]
    failures = [c for c in retrieve_cases if not c["end_to_end_pass"]]
    attributable = [c for c in failures if c["standalone_ok"]]
    return {
        "retrieve_cases": len(retrieve_cases),
        "end_to_end_failures": len(failures),
        "attributable_failures": len(attributable),
        "min_failures": FOLLOWUP_MIN_FAILURES,
        "min_attributable": FOLLOWUP_MIN_ATTRIBUTABLE,
        "clearly_fail": len(failures) >= FOLLOWUP_MIN_FAILURES
        and len(attributable) >= FOLLOWUP_MIN_ATTRIBUTABLE,
    }


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


def load_followups(
    path: Path = FOLLOWUPS_PATH,
    materials: Sequence[Mapping[str, Any]] | None = None,
    question_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Load the synthetic follow-up cases (same row format as the gate messages).

    The file is kept apart from the 295 gate messages so their numbers stay
    comparable. Every row must be a follow-up with prior history, and ids must
    not collide with the gate messages.
    """
    manifest = list(materials) if materials is not None else load_materials()
    ids = list(question_ids) if question_ids is not None else [q["id"] for q in load_questions(materials=manifest)]
    rows = _read_jsonl(path)
    validate_messages(rows, manifest, ids, min_count=1)
    gate_ids = {row["id"] for row in _read_jsonl(MESSAGES_PATH)}
    for row in rows:
        if row["id"] in gate_ids:
            raise DatasetError(f"{row['id']}: id also used in the gate messages")
        if row["category"] != "follow_up" or row["follow_up"] is not True or not row["history"]:
            raise DatasetError(f"{row['id']}: not a follow-up with history")
        if row["expected_decision"] == "retrieve" and (
            row["question_id"] is None or row["expected_material"] is None
        ):
            raise DatasetError(f"{row['id']}: retrieve follow-up needs question_id and expected_material")
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


def scope_inputs_for_row(
    row: Mapping[str, Any], *, upload_retrieval_enabled: bool = False
) -> Any:
    """Build ``backend.coaching.evidence_scope.ScopeInputs`` from a dataset row.

    The offline eval cannot supply four things production reads, so each is an
    explicit input held at the value the pre-refactor gate assumed:

    * image bytes: every file counts as loaded (``image_bytes_resolved=True``),
      so missing image Q&A never fires;
    * ``force_retrieval``: False (a Deep Review path, not a chat turn);
    * the locked-course flag: False (a row has no course-library source);
    * ``frozen_history``: False, and the course-intent model second chance
      stays outside the gate (see ``evaluate_combined_gate``).

    ``upload_retrieval_enabled`` stays False for the gate itself. The upload
    policy block (``_upload_retrieval_policy``) turns it on to measure the
    opt-in rule.

    Source ids are ``eval-source-N`` then ``eval-attachment-N``, the ids
    ``build_live_request`` stamps. ``is_image`` follows the filename extension,
    the same guess ``_eval_upload_entries`` makes.
    """
    from backend.coaching.evidence_scope import ScopeInputs, ScopeSource

    entries = _eval_upload_entries(row)
    selected = list(row["selected_sources"])
    attachments = list(row["attachments"])
    sources = []
    for index, (raw, entry) in enumerate(zip([*selected, *attachments], entries)):
        is_attachment = index >= len(selected)
        number = index - len(selected) + 1 if is_attachment else index + 1
        sources.append(
            ScopeSource(
                source_id=f"eval-{'attachment' if is_attachment else 'source'}-{number}",
                title=str(raw.get("title") or ""),
                filename=str(raw.get("filename") or ""),
                is_attachment=is_attachment,
                is_course_library=False,
                is_image=entry["kind"] == "image",
                image_bytes_resolved=True,
            )
        )
    return ScopeInputs(
        message=str(row["message"]),
        current_stage=str(row["stage"]),
        sources=tuple(sources),
        attachment_count=len(attachments),
        interaction_intent=row.get("explicit_mode"),
        force_retrieval=False,
        frozen_history=False,
        upload_retrieval_enabled=upload_retrieval_enabled,
    )


def gate_decision(row: Mapping[str, Any]) -> GateDecision:
    """Run the production first-pass scope rules for one message row.

    A thin adapter: it builds the inputs (``scope_inputs_for_row``), calls
    ``backend.coaching.evidence_scope.decide_first_pass_scope``, the same
    function ``_prepare_authoritative_turn`` calls, and maps the result onto
    ``GateDecision``. Image bytes, forced retrieval and the model-driven
    second-chance retrieval path are held at the values ``scope_inputs_for_row``
    documents.

    The effective decision is 'retrieve' only when a source is searched: the
    course catalog (``include_course_catalog``) or at least one personal file.
    """
    from backend.coaching.evidence_scope import decide_first_pass_scope

    scope = decide_first_pass_scope(scope_inputs_for_row(row))
    return GateDecision(
        retrieve=bool(scope.include_course_catalog or scope.searches_personal_files),
        course=bool(scope.include_course_catalog),
        student=bool(scope.searches_personal_files),
        classifier_retrieve=scope.classifier_retrieve,
        second_chance=scope.second_chance,
        expected_mode=scope.expected_mode,
        intent=scope.classifier_intent,
        needs_retrieval=scope.needs_retrieval,
        scope_cleared=scope.scope_cleared,
        attachment_only=scope.attachment_only,
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
                text=chunk.text,
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


UPLOAD_POLICY_DEFINITION = (
    "Models FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED (default off) on top of the "
    "gate, with the production rule _wants_student_upload_retrieval: a row "
    "the gate searched nothing for is searched locally when it still has a "
    "non-image student upload in scope, no gate override fixed its evidence "
    "scope, and it is not chit-chat. The course catalog is never added. A "
    "row 'retrieves' when a source is searched (the gate's definition), so a "
    "course-scope row that only searches an unrelated upload counts as "
    "retrieved; 'fixed_wrong_skips_course_scope_only' lists those. Student "
    "file text is not in the gate set, so no search runs: extra prompt "
    "characters are an ESTIMATE (upper bound), the payload growth when "
    "min(FAST_CHAT_RETRIEVAL_MAX_CHUNKS, 2 x non-image uploads) full-size "
    "local chunks with the row's real titles are attached, measured on the "
    "provider payload builder. Tokens use 4 and 3 characters per token."
)


def _eval_upload_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project the row's selected and attached files into source dicts.

    Rows hold only a title and a filename, so ``mime`` is guessed from the
    filename extension (``.png`` is an image).
    """
    import mimetypes

    entries: list[dict[str, Any]] = []
    for entry in [*row["selected_sources"], *row["attachments"]]:
        filename = str(entry.get("filename") or "")
        mime = mimetypes.guess_type(filename)[0] or ""
        entries.append(
            {
                "title": str(entry.get("title") or filename),
                "filename": filename,
                "kind": "image" if mime.startswith("image/") else "file",
                "mime": mime,
            }
        )
    return entries


def _payload_text_chars(payload: Mapping[str, Any]) -> int:
    """Characters the model reads from one provider payload.

    Counts ``trusted_instructions``, every string inside ``messages`` and the
    compact JSON of ``runtime_context`` (where the allowed citation labels
    go).
    """

    def strings(value: Any) -> int:
        if isinstance(value, str):
            return len(value)
        if isinstance(value, Mapping):
            return sum(strings(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return sum(strings(item) for item in value)
        return 0

    return (
        len(str(payload.get("trusted_instructions") or ""))
        + strings(payload.get("messages") or [])
        + len(json.dumps(payload.get("runtime_context") or {}, separators=(",", ":")))
    )


def upload_policy_prompt_estimate(
    row: Mapping[str, Any],
    decision: GateDecision,
    uploads: Sequence[Mapping[str, Any]],
    *,
    provider: Any = None,
) -> dict[str, Any]:
    """ESTIMATE the extra prompt characters one policy search adds.

    Builds the request production would send without excerpts, then the same
    request with ``min(max_chunks, 2 x uploads)`` full-size chunks
    (``LocalChunkRetriever`` defaults) formatted by the production
    ``bounded_retrieval_result`` with the real titles, and measures both
    payloads with the provider's payload builder (never invoked). Upper
    bound: real files can be shorter or match fewer chunks.
    """
    from backend.agentcore_provider import _FAST_CHAT_CONTRACT, _FAST_CHAT_PHASE
    from backend.context_planner import CONTEXT_POLICY_FAST_CHAT
    from backend.domain import RetrievalChunkReference
    from backend.retrieval import LocalChunkRetriever, RetrievedChunk, bounded_retrieval_result
    from backend.settings import settings

    local = LocalChunkRetriever()
    max_chunks = int(settings.fast_chat_retrieval_max_chunks)
    chunks: list[RetrievedChunk] = []
    for index, upload in enumerate(uploads, 1):
        for chunk_index in range(local.max_chunks_per_source):
            text = (f"excerpt {index}.{chunk_index} " * local.chunk_chars)[: local.chunk_chars]
            chunks.append(
                RetrievedChunk(
                    source_id=f"eval-upload-{index}",
                    label=f"S{index}",
                    title=" ".join(str(upload.get("title") or "").split())[:180],
                    chunk_id=f"S{index}-C{chunk_index}",
                    text=text,
                    score=1.0,
                    source_index=index - 1,
                    chunk_index=chunk_index,
                )
            )
    # Best-first order interleaves files, as the per-source cap would.
    chunks.sort(key=lambda chunk: (chunk.chunk_index, chunk.source_index))
    bounded = bounded_retrieval_result(
        chunks,
        max_context_chars=int(settings.fast_chat_retrieval_max_chars),
        max_chunks=max_chunks,
    )
    base = build_live_request(row, decision, source_check=False)
    with_excerpts = base.model_copy(
        update={
            "retrieval_required": True,
            "source_context": bounded.context,
            "retrieved_chunks": [
                RetrievalChunkReference(
                    source_id=chunk.source_id,
                    label=chunk.label,
                    title=chunk.title,
                    chunk_id=chunk.chunk_id,
                    excerpt=chunk.text[:600],
                    score=chunk.score,
                )
                for chunk in bounded.chunks
            ],
        }
    )
    provider = provider if provider is not None else _live_eval_provider()

    def size(request: Any) -> int:
        payload, _plan = provider._invoke_payload(
            request,
            _FAST_CHAT_PHASE,
            context_policy=CONTEXT_POLICY_FAST_CHAT,
            phase=_FAST_CHAT_PHASE,
            output_contract=_FAST_CHAT_CONTRACT,
        )
        return _payload_text_chars(payload)

    extra = size(with_excerpts) - size(base)
    return {
        "chunks": len(bounded.chunks),
        "context_chars": len(bounded.context),
        "extra_prompt_chars": extra,
        "extra_tokens_4cpt": round(extra / 4),
        "extra_tokens_3cpt": round(extra / 3),
    }


def _upload_retrieval_policy(
    scored: Sequence[tuple[Mapping[str, Any], GateDecision]],
    *,
    estimate: bool = True,
) -> dict[str, Any]:
    """Apply the upload retrieval policy rule to every gate row (no search).

    Args:
        scored: ``(message row, first-pass gate decision)`` per message.
        estimate: When False, skip the prompt-size estimate (tests).
    """
    from backend.coaching.evidence_scope import (
        decide_first_pass_scope,
        is_searchable_student_upload,
    )

    before: list[tuple[str, bool]] = []
    after: list[tuple[str, bool]] = []
    per_category: dict[str, dict[str, Any]] = {}
    fired_rows: list[dict[str, Any]] = []
    fixed: list[str] = []
    fixed_course_only: list[str] = []
    new_false: list[str] = []
    lost_second_chance: list[str] = []
    lost_course_scope: list[str] = []
    provider = _live_eval_provider() if estimate else None
    for row, decision in scored:
        uploads = (
            []
            if decision.scope_cleared
            else [
                entry
                for entry in _eval_upload_entries(row)
                if is_searchable_student_upload(
                    is_course_library=False, is_image=entry["kind"] == "image"
                )
            ]
        )
        # The production rule, with the setting on: the same module call the
        # gate makes, so the policy cannot drift from ``execution.py``.
        fired = decide_first_pass_scope(
            scope_inputs_for_row(row, upload_retrieval_enabled=True)
        ).upload_policy_only
        label = row["expected_decision"]
        retrieved = bool(decision.retrieve or fired)
        before.append((label, decision.retrieve))
        after.append((label, retrieved))
        bucket = per_category.setdefault(
            row["category"],
            {
                "retrieve_rows": 0,
                "skip_rows": 0,
                "wrong_skips_before": 0,
                "wrong_skips_after": 0,
                "false_retrieves_before": 0,
                "false_retrieves_after": 0,
                "policy_fired": 0,
                "extra_prompt_chars_estimate": 0,
            },
        )
        if label == "retrieve":
            bucket["retrieve_rows"] += 1
            bucket["wrong_skips_before"] += int(not decision.retrieve)
            bucket["wrong_skips_after"] += int(not retrieved)
        else:
            bucket["skip_rows"] += 1
            bucket["false_retrieves_before"] += int(decision.retrieve)
            bucket["false_retrieves_after"] += int(retrieved)
        if not fired:
            continue
        bucket["policy_fired"] += 1
        scope = str(row.get("expected_scope") or "")
        record: dict[str, Any] = {
            "id": row["id"],
            "category": row["category"],
            "expected_decision": label,
            "expected_scope": scope,
            "uploads": len(uploads),
        }
        if provider is not None:
            record.update(
                upload_policy_prompt_estimate(row, decision, uploads, provider=provider)
            )
            bucket["extra_prompt_chars_estimate"] += record["extra_prompt_chars"]
        fired_rows.append(record)
        if label == "retrieve":
            fixed.append(row["id"])
            if scope == "course":
                fixed_course_only.append(row["id"])
        else:
            new_false.append(row["id"])
        if decision.second_chance:
            lost_second_chance.append(row["id"])
            if scope in {"course", "both"}:
                lost_course_scope.append(row["id"])
    upload_misses_before = per_category.get("upload_question", {}).get("wrong_skips_before", 0)
    upload_misses_after = per_category.get("upload_question", {}).get("wrong_skips_after", 0)
    total_chars = sum(int(item.get("extra_prompt_chars") or 0) for item in fired_rows)
    out: dict[str, Any] = {
        "definition": UPLOAD_POLICY_DEFINITION,
        "rows_fired": len(fired_rows),
        "wrong_skip_rate_before": wrong_skip_rate(before),
        "wrong_skip_rate_after": wrong_skip_rate(after),
        "false_retrieve_rate_before": false_retrieve_rate(before),
        "false_retrieve_rate_after": false_retrieve_rate(after),
        "fixed_wrong_skips": fixed,
        "fixed_wrong_skips_course_scope_only": fixed_course_only,
        "new_false_retrieves": new_false,
        "upload_question_misses_fixed": {
            "fixed": upload_misses_before - upload_misses_after,
            "misses_before": upload_misses_before,
        },
        "second_chance_eligible_lost": {
            "rows": len(lost_second_chance),
            "ids": lost_second_chance,
            "expected_scope_course_or_both": len(lost_course_scope),
            "expected_scope_course_or_both_ids": lost_course_scope,
        },
        "by_category": dict(sorted(per_category.items())),
        "fired_rows": fired_rows,
    }
    if provider is not None:
        out["extra_prompt_estimate"] = {
            "total_chars": total_chars,
            "per_fired_row_chars_max": max(
                (int(item["extra_prompt_chars"]) for item in fired_rows), default=0
            ),
            "per_fired_row_chars_mean": round(total_chars / len(fired_rows), 1)
            if fired_rows
            else 0.0,
            "total_tokens_4cpt": round(total_chars / 4),
            "total_tokens_3cpt": round(total_chars / 3),
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
        # Additive: the numbers above are with the policy off (its default).
        "upload_retrieval_policy": _upload_retrieval_policy(scored),
    }


class _RecordingRetrieveClient:
    """Stand-in ``bedrock-agent-runtime`` client: records the query, returns nothing."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(str(kwargs["retrievalQuery"]["text"]))
        return {"retrievalResults": []}


def captured_kb_query(
    message: str, history: Sequence[Mapping[str, Any]], course_source: Any
) -> str:
    """Return the query text the Knowledge Base adapter sends for one turn.

    Runs ``BedrockKnowledgeBaseRetriever`` with a recording client, so the
    text comes from the production query building and not from a copy. No
    network call is made.
    """
    from backend.bedrock_retrieve import BedrockKnowledgeBaseRetriever
    from backend.retrieval import RetrievalQuery

    client = _RecordingRetrieveClient()
    BedrockKnowledgeBaseRetriever(
        "OFFLINE-EVAL",
        course_bucket="offline-eval-bucket",
        client=client,
        metadata_filter_mode="required",
        knowledge_base_type="managed",
    ).retrieve(
        RetrievalQuery(
            current_message=message,
            current_stage="problem_identification",
            sources=(course_source,),
            recent_messages=tuple(
                {"role": turn["role"], "content": turn["text"]} for turn in history
            ),
        )
    )
    if len(client.queries) != 1:
        raise RuntimeError(f"expected one Retrieve call, saw {len(client.queries)}")
    return client.queries[0]


def _top_materials(hits: Iterable[RankedHit]) -> list[str]:
    return [hit.material_id for hit in rank_hits(hits)[:TOP_K]]


def evaluate_followups(
    followups: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    search: OfflineCourseSearch,
) -> dict[str, Any]:
    """Measure the gate and the built query on the follow-up cases.

    Reported apart from the gate messages. See
    ``.agents/tasks/phase3b-work/item-c-notes.md`` for the definitions.
    """
    from backend.retrieval import expand_session_query_text

    question_text = {q["id"]: q["question"] for q in questions}
    course_source = search._sources[0]
    cases: list[dict[str, Any]] = []
    for row in followups:
        decision = gate_decision(row)
        message = str(row["message"])
        built = captured_kb_query(message, row["history"], course_source)
        bare = expand_session_query_text(message)
        record: dict[str, Any] = {
            "id": row["id"],
            "message": message,
            "expected_decision": row["expected_decision"],
            "gate_course": decision.course,
            "gate_retrieve": decision.retrieve,
            "gate_second_chance": decision.second_chance,
            "built_query": built,
            "query_uses_history": built != bare,
        }
        if row["expected_decision"] == "skip":
            record["gate_ok"] = not decision.retrieve
            record["end_to_end_pass"] = record["gate_ok"]
            record["standalone_ok"] = None
            cases.append(record)
            continue
        expected = str(row["expected_material"])
        built_top = _top_materials(search.search(built))
        contrast_top = _top_materials(search.search(message, row["history"]))
        standalone = str(question_text[row["question_id"]])
        standalone_row = {
            "message": standalone,
            "stage": "problem_identification",
            "selected_sources": [],
            "attachments": [],
        }
        standalone_decision = gate_decision(standalone_row)
        standalone_top = _top_materials(search.search(standalone))
        record.update(
            {
                "expected_material": expected,
                "gate_ok": bool(decision.course),
                "built_query_top4": built_top,
                "query_ok": expected in built_top,
                "bare_message_top4": _top_materials(search.search(message)),
                "history_weighted_search_top4_contrast": contrast_top,
                "history_weighted_search_ok_contrast": expected in contrast_top,
                "standalone_question_id": row["question_id"],
                "standalone_question": standalone,
                "standalone_gate_course": bool(standalone_decision.course),
                "standalone_top4": standalone_top,
                "standalone_ok": bool(standalone_decision.course) and expected in standalone_top,
            }
        )
        record["end_to_end_pass"] = record["gate_ok"] and record["query_ok"]
        cases.append(record)
    retrieve = [c for c in cases if c["expected_decision"] == "retrieve"]
    skip = [c for c in cases if c["expected_decision"] == "skip"]
    gate_failures = [c for c in retrieve if not c["gate_ok"]]
    return {
        "definition": FOLLOWUP_DEFINITION,
        "cases": len(cases),
        "retrieve_cases": len(retrieve),
        "skip_cases": len(skip),
        "gate_wrong_skip": rate_record(len(gate_failures), len(retrieve)),
        "gate_wrong_skip_recoverable_by_second_chance": sum(
            1 for c in gate_failures if c["gate_second_chance"]
        ),
        "gate_false_retrieve": rate_record(sum(1 for c in skip if not c["gate_ok"]), len(skip)),
        "query_uses_history": rate_record(
            sum(1 for c in retrieve if c["query_uses_history"]), len(retrieve)
        ),
        "query_ok": rate_record(sum(1 for c in retrieve if c["query_ok"]), len(retrieve)),
        "query_ok_among_gate_passed": rate_record(
            sum(1 for c in retrieve if c["gate_ok"] and c["query_ok"]),
            sum(1 for c in retrieve if c["gate_ok"]),
        ),
        "end_to_end_pass": rate_record(sum(1 for c in retrieve if c["end_to_end_pass"]), len(retrieve)),
        # Informational, not part of the verdict: a perfect needs_sources model
        # would recover every gate miss that is eligible for the second call.
        "end_to_end_pass_if_second_chance_recovers_gate": rate_record(
            sum(1 for c in retrieve if (c["gate_ok"] or c["gate_second_chance"]) and c["query_ok"]),
            len(retrieve),
        ),
        "attributable_failures_if_second_chance_recovers_gate": sum(
            1
            for c in retrieve
            if not ((c["gate_ok"] or c["gate_second_chance"]) and c["query_ok"])
            and c["standalone_ok"]
        ),
        "standalone_control_ok": rate_record(
            sum(1 for c in retrieve if c["standalone_ok"]), len(retrieve)
        ),
        "history_weighted_search_ok_contrast": rate_record(
            sum(1 for c in retrieve if c["history_weighted_search_ok_contrast"]), len(retrieve)
        ),
        "verdict": followup_verdict(cases),
        "per_case": cases,
    }


def run_offline(
    materials: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
    followups: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full offline evaluation.

    ``followups`` adds a separate ``followups`` block. It never changes the
    ``retrieval`` or ``gate`` numbers.
    """
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
    result: dict[str, Any] = {
        "mode": "offline",
        "course_search": "LocalChunkRetriever over local lecture PDFs, one chunk per page (not the Knowledge Base)",
        "network_calls": 0,
        "definitions": DEFINITIONS,
        "retrieval": _question_summary(outcomes, questions),
        "gate": evaluate_gate(messages, search),
    }
    if followups:
        result["followups"] = evaluate_followups(followups, questions, search)
    return result


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
        # Measure what the Knowledge Base returns, whatever the production
        # KNOWLEDGE_BASE_PAGE_CITATIONS_ENABLED switch says.
        page_citations=True,
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
    results_total = 0
    results_with_page = 0
    questions_with_page = 0
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
                page=chunk.page,
                score=float(chunk.score),
                source_index=chunk.source_index,
                chunk_index=chunk.chunk_index,
            )
            for chunk in result.chunks
        ]
        # A question is scored at page level only when at least one of its
        # results carries a page. A question whose results carry none is left
        # out of the page denominator, not counted as a miss.
        page_aware = any(hit.page is not None for hit in hits)
        results_total += len(hits)
        results_with_page += sum(1 for hit in hits if hit.page is not None)
        questions_with_page += int(page_aware)
        outcomes.append(
            score_question(
                q["id"],
                hits,
                expected_material=q["expected_material"],
                expected_pages=q["expected_pages"],
                alt_expected=q["alt_expected"],
                page_aware=page_aware,
            )
        )
    summary = _question_summary(outcomes, questions)
    summary["page_coverage"] = {
        "results": results_total,
        "results_with_page": results_with_page,
        "questions_with_page": questions_with_page,
        "questions_evaluated": len(outcomes),
    }
    summary["failed_attempts"] = failed
    summary["live_calls_made"] = client.calls
    summary["live_call_limit"] = limit
    return {
        "mode": "live",
        "course_search": (
            "Bedrock Knowledge Base Retrieve (page-level scoring only for "
            "questions whose results carry a page)"
        ),
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
    "failed are not scored in 'overall' and 'by_category'; "
    "'overall_failed_in_denominator' keeps them in two readings: "
    "failed_as_gate_only (a failed call raises no flag, the gate result "
    "stands) and failed_as_error (a failed retrieve row is a wrong skip, a "
    "failed skip row is a false retrieve). Eligible rows are the only rows "
    "whose flag changes a metric; the flag on other rows is reported as raw "
    "flag rate only. With FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED on, the "
    "course material titles from the manifest are added to the rule "
    "(see source_check_titles)."
)

LIVE_MODEL_COMPARE_DEFINITION = (
    "Sends each chosen gate message twice through the first Fast Chat call, "
    "built as in live_model: once with the SOURCE CHECK rule on "
    "(source_need_check=True, as with FAST_CHAT_NEEDS_SOURCES_ENABLED on) and "
    "once with it off (source_need_check=False, as production sends every "
    "turn with the setting off). Each arm is scored as live_model. Each "
    "message costs two model calls; --max-live-calls counts calls, so "
    "floor(limit / 2) messages are sent, evenly spaced. The run stops after "
    "the first auth or access error in either arm."
)


class LiveStructuredOutputError(RuntimeError):
    """The model returned no usable ``FastChatTurnOutput`` tool call.

    ``detail`` holds only safe, structural facts (failure kind, stop reason,
    pydantic error locations and types); never message, reply or tool input
    values.
    """

    def __init__(self, message: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail: dict[str, Any] = dict(detail or {})


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
        # Bedrock ``stopReason`` of the last call (an enum value, not text).
        self.last_stop_reason: str | None = None
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
        from pydantic import ValidationError

        from agentcore_runtime.models import parse_fast_chat_turn_output
        from agentcore_runtime.structured_coach import structured_wire_payload

        self.last_stop_reason = None
        response = self._client.converse(**self.request_kwargs(payload))
        stop_reason = response.get("stopReason")
        self.last_stop_reason = None if stop_reason is None else str(stop_reason)[:40]
        message = ((response.get("output") or {}).get("message")) or {}
        content = message.get("content") or []
        tool_input = None
        for block in content:
            tool_use = block.get("toolUse") if isinstance(block, Mapping) else None
            if isinstance(tool_use, Mapping) and isinstance(tool_use.get("input"), Mapping):
                tool_input = tool_use["input"]
                break
        if tool_input is None:
            raise LiveStructuredOutputError(
                f"no tool call in reply (stopReason={response.get('stopReason')!r})",
                {
                    "kind": "no_tool_call",
                    "stop_reason": self.last_stop_reason,
                    "text_blocks": sum(
                        1 for block in content if isinstance(block, Mapping) and "text" in block
                    ),
                },
            )
        try:
            output = parse_fast_chat_turn_output(dict(tool_input))
        except ValueError as error:
            errors: list[dict[str, Any]] = []
            if isinstance(error, ValidationError):
                # Locations, types and pydantic's static messages only: no input values.
                errors = [
                    {
                        "loc": [str(part) for part in item.get("loc", ())],
                        "type": str(item.get("type") or ""),
                        "msg": str(item.get("msg") or ""),
                    }
                    for item in error.errors(
                        include_url=False, include_context=False, include_input=False
                    )
                ]
            raise LiveStructuredOutputError(
                f"tool input failed validation ({type(error).__name__})",
                {
                    "kind": "tool_input_invalid",
                    "stop_reason": self.last_stop_reason,
                    "errors": errors,
                },
            ) from error
        return structured_wire_payload(output)


def eval_course_titles(materials: Sequence[Mapping[str, Any]]) -> list[str]:
    """Course titles for the SOURCE CHECK rule, built from the eval manifest.

    Each manifest entry is projected into the locked course source shape
    production lists for a notebook, then passed to the production helper
    ``source_check_course_titles``, so the eval and production share the
    title rules (order, clipping, de-duplication).
    """
    from backend.coaching.execution import source_check_course_titles

    return source_check_course_titles(
        [
            {
                "title": str(entry["filename"]),
                "metadata": {
                    "origin": "lecture_notes_folder",
                    "locked_source": True,
                    "course_material_group": str(entry.get("group") or ""),
                },
            }
            for entry in materials
        ]
    )


def live_source_check_titles(
    materials: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[str], dict[str, Any]]:
    """Return (titles, record) for a live run.

    Titles are used only when ``FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED`` is on,
    as in production. The record goes into the result's
    ``source_check_titles`` block.
    """
    from backend.prompts.composer import source_check_titles_block
    from backend.settings import settings

    enabled = bool(settings.fast_chat_source_check_titles_enabled)
    titles: list[str] = []
    if enabled:
        titles = eval_course_titles(materials if materials is not None else load_materials())
    return titles, {
        "enabled": enabled,
        "count": len(titles),
        "block_chars": len(source_check_titles_block(titles)),
    }


def build_live_request(
    row: Mapping[str, Any],
    decision: GateDecision,
    *,
    source_check: bool = True,
    course_titles: Sequence[str] = (),
) -> Any:
    """Build the ``CoachRequest`` production would hand the provider.

    Mirrors the fields ``_prepare_authoritative_turn`` stamps that change the
    first call's prompt. Retrieved excerpts are never attached: a row the gate
    searched for is sent without them (see ``LIVE_MODEL_DEFINITION``).
    ``source_need_check`` is on by default so every row measures the flag;
    ``source_check=False`` sends the turn as production does with
    ``FAST_CHAT_NEEDS_SOURCES_ENABLED`` off (the compare mode's off arm).
    ``course_titles`` are attached only when ``source_check`` is on, as
    production stamps them only on turns with ``source_need_check``.
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
        source_need_check=bool(source_check),
        course_material_titles=list(course_titles) if source_check else [],
        expected_response_mode=decision.expected_mode,
        mode_policy_intent=decision.intent,
    )


def live_failure_detail(error: BaseException) -> dict[str, Any]:
    """Return safe, structural facts about one failed live call.

    Kinds: ``no_tool_call`` and ``tool_input_invalid`` (from the bridge),
    ``fast_chat_contract`` (the wire adapter's fixed reason token),
    ``contract_rejected`` (``_validated_fast_chat`` category), ``other``
    (for example an AWS error; ``error`` on the row names its class).
    Never message, reply or tool input text.
    """
    from agentcore_runtime.models import FastChatContractError
    from backend.providers import ProviderUnavailableError

    if isinstance(error, LiveStructuredOutputError) and error.detail:
        return dict(error.detail)
    if isinstance(error, FastChatContractError):
        return {"kind": "fast_chat_contract", "reason": str(error.reason)}
    if isinstance(error, ProviderUnavailableError):
        return {"kind": "contract_rejected", "category": str(error.category or "")}
    return {"kind": "other"}


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


def _failed_in_denominator(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Wrong-skip and false-retrieve with every sent row in the denominator.

    ``failed_as_gate_only``: a failed call raises no flag, so the gate result
    stands. ``failed_as_error``: a failed retrieve row counts as a wrong skip
    and a failed skip row as a false retrieve.
    """
    gate_only: list[tuple[str, bool]] = []
    as_error: list[tuple[str, bool]] = []
    for item in outcomes:
        expected = item["expected_decision"]
        if item["status"] == "ok":
            retrieved = bool(item["gate_retrieve"] or (item["eligible"] and item["honoured"]))
            gate_only.append((expected, retrieved))
            as_error.append((expected, retrieved))
        else:
            gate_only.append((expected, bool(item["gate_retrieve"])))
            as_error.append((expected, expected == "skip"))
    return {
        "calls_failed": sum(1 for item in outcomes if item["status"] != "ok"),
        "failed_as_gate_only": {
            "wrong_skip": wrong_skip_rate(gate_only),
            "false_retrieve": false_retrieve_rate(gate_only),
        },
        "failed_as_error": {
            "wrong_skip": wrong_skip_rate(as_error),
            "false_retrieve": false_retrieve_rate(as_error),
        },
    }


def _failures_by_kind(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count failed rows per ``failure_detail.kind``, overall and per category."""
    overall: dict[str, int] = defaultdict(int)
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in outcomes:
        if item["status"] == "ok":
            continue
        kind = str((item.get("failure_detail") or {}).get("kind") or "other")
        overall[kind] += 1
        by_category[item["category"]][kind] += 1
    return {
        "overall": dict(sorted(overall.items())),
        "by_category": {
            category: dict(sorted(kinds.items()))
            for category, kinds in sorted(by_category.items())
        },
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
        "recommendation_defaulted": {
            "count": sum(1 for o in scored if o.get("recommendation_defaulted")),
            "ids": [o["id"] for o in scored if o.get("recommendation_defaulted")],
        },
        "overall_failed_in_denominator": _failed_in_denominator(outcomes),
        "failures_by_kind": _failures_by_kind(outcomes),
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


def _refuse_unknown(flag: str, unknown: Sequence[str]) -> None:
    if unknown:
        more = f" and {len(unknown) - 5} more" if len(unknown) > 5 else ""
        raise LiveRunRefused(f"unknown value(s) in {flag}: {', '.join(unknown[:5])}{more}")


def select_live_rows(
    messages: Sequence[Mapping[str, Any]],
    *,
    ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    expected_decision: str | None = None,
    skip_sample: int = 0,
) -> list[Mapping[str, Any]]:
    """Select the gate rows a live-model run sends, in file order.

    Order: (a) with neither ``ids`` nor ``categories`` start from all rows,
    else keep rows whose id **or** category is listed (union); (b)
    ``expected_decision`` keeps only rows with that label; (c) ``skip_sample``
    adds that many ``skip`` rows not already selected, chosen with
    ``evenly_spaced_indices`` over that pool in file order. ``None`` for a
    filter means "not given"; ``--max-live-calls`` applies later.

    Raises:
        LiveRunRefused: On an unknown id or category, an empty ``ids`` or
            ``categories`` list, a bad ``expected_decision``, a negative
            ``skip_sample``, or an empty selection.
    """
    if ids is not None and not ids:
        raise LiveRunRefused("--ids was given but names no id")
    if categories is not None and not categories:
        raise LiveRunRefused("--categories was given but names no category")
    if expected_decision is not None and expected_decision not in DECISIONS:
        raise LiveRunRefused(f"--expected-decision must be one of {', '.join(sorted(DECISIONS))}")
    if skip_sample < 0:
        raise LiveRunRefused("--skip-sample must be 0 or more")
    wanted_ids = set(ids or ())
    wanted_categories = set(categories or ())
    known_ids = {str(row["id"]) for row in messages}
    _refuse_unknown("--ids", [item for item in dict.fromkeys(ids or ()) if item not in known_ids])
    _refuse_unknown(
        "--categories",
        [item for item in dict.fromkeys(categories or ()) if item not in MESSAGE_CATEGORIES],
    )
    if ids is None and categories is None:
        selected = list(messages)
    else:
        selected = [
            row
            for row in messages
            if str(row["id"]) in wanted_ids or str(row["category"]) in wanted_categories
        ]
    if expected_decision is not None:
        selected = [row for row in selected if row["expected_decision"] == expected_decision]
    if skip_sample:
        taken = {str(row["id"]) for row in selected}
        pool = [
            row for row in messages if row["expected_decision"] == "skip" and str(row["id"]) not in taken
        ]
        taken |= {str(pool[i]["id"]) for i in evenly_spaced_indices(len(pool), skip_sample)}
        selected = [row for row in messages if str(row["id"]) in taken]
    if not selected:
        raise LiveRunRefused("the row filters selected no rows")
    return selected


def check_compare_limit(limit: int) -> int:
    """Return the message count a compare run sends: ``limit // 2``.

    Raises:
        LiveRunRefused: When the limit is below 2 (one message costs 2 calls).
    """
    if limit < 2:
        raise LiveRunRefused(
            "--compare-source-check sends each message twice; --max-live-calls must be at least 2"
        )
    return limit // 2


def _live_eval_provider() -> Any:
    """Build the provider only to reuse its payload builder (never invoked)."""
    from backend.agentcore_provider import AgentCoreCoachProvider

    class _NoRuntime:
        def invoke_agent_runtime(self, **_kwargs: Any) -> Any:
            raise AssertionError("AgentCore Runtime must not be invoked by the eval")

    return AgentCoreCoachProvider(_EVAL_RUNTIME_ARN, client=_NoRuntime())


def _live_model_outcome(
    row: Mapping[str, Any],
    *,
    provider: Any,
    bridge: LiveFastChatBridge,
    source_check: bool = True,
    course_titles: Sequence[str] = (),
) -> tuple[dict[str, Any], BaseException | None]:
    """Send one row through the first fast-chat call; return (outcome, error).

    ``LiveCallLimitExceeded`` propagates so the caller can stop the run.
    """
    from backend.agentcore_provider import (
        _FAST_CHAT_CONTRACT,
        _FAST_CHAT_PHASE,
        _validated_fast_chat,
    )
    from agentcore_runtime.models import adapt_fast_chat_turn_payload
    from backend.context_planner import CONTEXT_POLICY_FAST_CHAT

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
        request = build_live_request(
            row, decision, source_check=source_check, course_titles=course_titles
        )
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
        raise
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed
        return (
            {
                **base,
                "status": "failed",
                "error": exception_label(error),
                "failure_detail": live_failure_detail(error),
            },
            error,
        )
    return (
        {
            **base,
            "status": "ok",
            "flag_raw": bool(raw.needs_sources),
            "honoured": bool(result.needs_sources),
            "mode": str(result.specialist),
            "out_of_scope": bool(raw.out_of_scope),
            # True when a coaching reply carried no recommendation and the
            # contract recorded ``stay`` (counted, not scored as a failure).
            "recommendation_defaulted": bool(wire.get("recommendation_defaulted")),
            "stop_reason": bridge.last_stop_reason,
        },
        None,
    )


def _calls_record(
    limit: int,
    client: Any,
    outcomes: Sequence[Mapping[str, Any]],
    messages: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any] | None,
    messages_attempted: int,
) -> dict[str, Any]:
    succeeded = sum(1 for o in outcomes if o["status"] == "ok")
    in_set = (selection or {}).get("messages_in_set", len(messages))
    return {
        "limit": limit,
        "made": client.calls,
        "succeeded": succeeded,
        "failed": len(outcomes) - succeeded,
        "messages_in_set": int(in_set),
        "messages_selected": len(messages),
        "messages_attempted": messages_attempted,
    }


def run_live_model(
    messages: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    client: Any,
    model_id: str,
    region: str,
    selection: Mapping[str, Any] | None = None,
    materials: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send up to ``limit`` gate messages through the first fast-chat call.

    Args:
        messages: Validated gate rows (already filtered by ``select_live_rows``).
        limit: Approved call limit. Below the row count, an evenly spaced,
            deterministic subset is sent.
        client: A ``CountingConverseClient`` (tests pass one over a stub).
        model_id: Fast-chat model id from settings.
        region: Model region from settings.
        selection: Optional record of the row filter (copied into the result;
            ``messages_in_set`` there is the size of the unfiltered set).
        materials: Course manifest for the SOURCE CHECK titles (used only
            when ``FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED`` is on; defaults to
            the eval manifest).

    Stops after the first auth or access error. Never retries a call.
    """
    provider = _live_eval_provider()
    bridge = LiveFastChatBridge(client, model_id)
    titles, titles_record = live_source_check_titles(materials)
    chosen = [messages[i] for i in evenly_spaced_indices(len(messages), limit)]
    outcomes: list[dict[str, Any]] = []
    first_failure: dict[str, Any] | None = None
    stopped_on: dict[str, Any] | None = None
    for row in chosen:
        try:
            outcome, error = _live_model_outcome(
                row, provider=provider, bridge=bridge, course_titles=titles
            )
        except LiveCallLimitExceeded:
            break
        outcomes.append(outcome)
        if error is None:
            continue
        failure = {"id": row["id"], "error": outcome["error"]}
        if first_failure is None:
            first_failure = failure
        if is_auth_or_access_error(error):
            stopped_on = failure
            break
    summary = summarize_live_model(outcomes)
    result = {
        "mode": "live_model",
        "definition": LIVE_MODEL_DEFINITION,
        "model": {"provider": "bedrock", "model_id": model_id, "region": region},
        "calls": _calls_record(limit, client, outcomes, messages, selection, len(outcomes)),
        "tokens": {
            "input": client.input_tokens,
            "output": client.output_tokens,
        },
        "first_failure": first_failure,
        "stopped_early_on_auth_or_access_error": stopped_on,
        "source_check_titles": titles_record,
        **summary,
        "rows": outcomes,
    }
    if selection is not None:
        result["selection"] = dict(selection)
    return result


_COMPARE_ARMS = (("source_check_on", True), ("source_check_off", False))


def run_live_model_compare(
    messages: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    client: Any,
    model_id: str,
    region: str,
    selection: Mapping[str, Any] | None = None,
    materials: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send each chosen message with the SOURCE CHECK rule on, then off.

    ``limit`` counts model calls: ``limit // 2`` messages are chosen with
    ``evenly_spaced_indices`` and the client never makes more than ``limit``
    calls. Stops after the first auth or access error in either arm.

    Raises:
        LiveRunRefused: When ``limit`` is below 2.
    """
    pair_limit = check_compare_limit(limit)
    provider = _live_eval_provider()
    bridge = LiveFastChatBridge(client, model_id)
    titles, titles_record = live_source_check_titles(materials)
    chosen = [messages[i] for i in evenly_spaced_indices(len(messages), pair_limit)]
    arms: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in _COMPARE_ARMS}
    pairs: list[dict[str, Any]] = []
    first_failure: dict[str, Any] | None = None
    stopped_on: dict[str, Any] | None = None
    stop = False
    for row in chosen:
        pair: dict[str, Any] = {"id": row["id"], "category": row["category"]}
        for name, source_check in _COMPARE_ARMS:
            try:
                outcome, error = _live_model_outcome(
                    row,
                    provider=provider,
                    bridge=bridge,
                    source_check=source_check,
                    course_titles=titles,
                )
            except LiveCallLimitExceeded:
                stop = True
                break
            arms[name].append(outcome)
            pair[name] = {
                "status": outcome["status"],
                "mode": outcome.get("mode"),
                "failure_detail": outcome.get("failure_detail"),
            }
            if error is None:
                continue
            failure = {"id": row["id"], "arm": name, "error": outcome["error"]}
            if first_failure is None:
                first_failure = failure
            if is_auth_or_access_error(error):
                stopped_on = failure
                stop = True
                break
        if any(name in pair for name, _ in _COMPARE_ARMS):
            pairs.append(pair)
        if stop:
            break

    def _ids(on_failed: bool, off_failed: bool) -> list[str]:
        return [
            pair["id"]
            for pair in pairs
            if "source_check_on" in pair
            and "source_check_off" in pair
            and (pair["source_check_on"]["status"] != "ok") == on_failed
            and (pair["source_check_off"]["status"] != "ok") == off_failed
        ]

    all_outcomes = [o for name, _ in _COMPARE_ARMS for o in arms[name]]
    result: dict[str, Any] = {
        "mode": "live_model_compare",
        "definition": LIVE_MODEL_COMPARE_DEFINITION,
        "model": {"provider": "bedrock", "model_id": model_id, "region": region},
        "calls": {
            **_calls_record(limit, client, all_outcomes, messages, selection, len(pairs)),
            "calls_per_message": 2,
        },
        "tokens": {"input": client.input_tokens, "output": client.output_tokens},
        "first_failure": first_failure,
        "stopped_early_on_auth_or_access_error": stopped_on,
        "source_check_titles": titles_record,
        "arms": {
            name: {**summarize_live_model(arms[name]), "rows": arms[name]}
            for name, _ in _COMPARE_ARMS
        },
        "pairs": pairs,
        "failed_on_only": _ids(True, False),
        "failed_off_only": _ids(False, True),
        "failed_both": _ids(True, True),
    }
    if selection is not None:
        result["selection"] = dict(selection)
    return result


def live_model_exit_code(result: Mapping[str, Any]) -> int:
    """0 = ran; 1 = every call failed; 3 = stopped early on an auth/access error."""
    if int(result["calls"]["succeeded"]) == 0:
        return 1
    if result.get("stopped_early_on_auth_or_access_error"):
        return 3
    return 0


def _failure_lines(summary: Mapping[str, Any]) -> list[str]:
    """Failed calls in the denominator (both readings) and failure kinds."""
    full = summary["overall_failed_in_denominator"]
    gate_only = full["failed_as_gate_only"]
    as_error = full["failed_as_error"]
    kinds = summary["failures_by_kind"]["overall"]
    kind_text = ", ".join(f"{kind} {count}" for kind, count in kinds.items()) or "none"
    return [
        f"with failed calls in the denominator ({full['calls_failed']} failed): "
        f"failed_as_gate_only wrong-skip {format_rate(gate_only['wrong_skip'])}, "
        f"false-retrieve {format_rate(gate_only['false_retrieve'])}; "
        f"failed_as_error wrong-skip {format_rate(as_error['wrong_skip'])}, "
        f"false-retrieve {format_rate(as_error['false_retrieve'])}",
        f"failure kinds: {kind_text}",
        "coaching replies with no recommendation, recorded as stay: "
        f"{(summary.get('recommendation_defaulted') or {}).get('count', 0)}",
    ]


def _selection_line(selection: Mapping[str, Any]) -> str:
    def _list(key: str) -> str:
        values = selection.get(key)
        return "-" if values is None else ",".join(values)

    return (
        f"selection: ids {_list('ids')}; categories {_list('categories')}; "
        f"expected decision {selection.get('expected_decision') or 'any'}; "
        f"skip sample {selection.get('skip_sample', 0)}; "
        f"rows selected {selection.get('rows_selected', 'n/a')}; "
        f"rows after cap {selection.get('rows_after_cap', 'n/a')}"
    )


def _calls_lines(result: Mapping[str, Any]) -> list[str]:
    calls = result["calls"]
    model = result["model"]
    lines = [
        f"model: {model['model_id']} in {model['region']} ({model['provider']})",
        f"calls: made {calls['made']} of limit {calls['limit']}; succeeded "
        f"{calls['succeeded']}; failed {calls['failed']}; messages attempted "
        f"{calls['messages_attempted']} of {calls['messages_selected']} selected "
        f"({calls['messages_in_set']} in set)",
        f"tokens: input {result['tokens']['input']}, output {result['tokens']['output']}",
    ]
    selection = result.get("selection")
    if selection:
        lines.insert(1, _selection_line(selection))
    titles = result.get("source_check_titles")
    if titles:
        lines.append(
            f"source check titles: {'on' if titles['enabled'] else 'off'} "
            f"({titles['count']} titles, block {titles['block_chars']} chars)"
        )
    if result["first_failure"]:
        failure = result["first_failure"]
        arm = f" ({failure['arm']})" if failure.get("arm") else ""
        lines.append(f"first failure: {failure['error']} on {failure['id']}{arm}")
    if result["stopped_early_on_auth_or_access_error"]:
        lines.append("stopped early: auth or access error (no further calls made)")
    return lines


def format_live_model_compare_report(result: Mapping[str, Any]) -> str:
    """Render the SOURCE CHECK on/off compare result as plain text."""
    lines = [
        "mode: live_model_compare (SOURCE CHECK on vs off, first fast-chat call)",
        *_calls_lines(result),
        f"calls per message: {result['calls']['calls_per_message']} (on, then off)",
    ]
    for name, arm in result["arms"].items():
        overall = arm["overall"]
        lines += [
            "",
            f"{name}: messages scored {overall['messages_scored']}; "
            f"flag rate (eligible, honoured) {format_rate(overall['flag_rate_eligible'])}",
            f"  wrong-skip with model {format_rate(overall['wrong_skip_with_model'])}; "
            f"false-retrieve with model {format_rate(overall['false_retrieve_with_model'])}",
            *(f"  {line}" for line in _failure_lines(arm)),
        ]
        for category, kinds in arm["failures_by_kind"]["by_category"].items():
            text = ", ".join(f"{kind} {count}" for kind, count in kinds.items())
            lines.append(f"  failed in {category}: {text}")
    lines += [
        "",
        f"failed with SOURCE CHECK on only: {', '.join(result['failed_on_only']) or 'none'}",
        f"failed with SOURCE CHECK off only: {', '.join(result['failed_off_only']) or 'none'}",
        f"failed in both arms: {', '.join(result['failed_both']) or 'none'}",
    ]
    return "\n".join(lines)


def format_live_model_report(result: Mapping[str, Any]) -> str:
    """Render the live model result as plain text."""
    overall = result["overall"]
    lines = [
        "mode: live_model (needs_sources on the first fast-chat call)",
        *_calls_lines(result),
    ]
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
        *_failure_lines(result),
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


def _git_run_metadata() -> dict[str, Any]:
    """Return the checkout's commit and a UTC timestamp for a JSON output file.

    ``git_dirty`` is true when tracked files have uncommitted changes
    (untracked files are ignored). Both git fields are ``None`` when git is
    unavailable. Local subprocess only; never raises.
    """
    import subprocess
    from datetime import datetime, timezone

    def _git(*command: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *command],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "git_sha": (sha.strip() or None) if sha is not None else None,
        "git_dirty": bool(status.strip()) if status is not None else None,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _write_json_output(path: Path, result: Mapping[str, Any]) -> None:
    """Write ``result`` as JSON with a ``run`` block (git SHA, UTC timestamp).

    Shared by the offline, ``--live-kb`` and ``--live-model`` modes. ``run`` is
    added only to the file, so the printed report is unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**result, "run": _git_run_metadata()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    if "page_coverage" in retrieval:
        coverage = retrieval["page_coverage"]
        lines.append(
            f"results with a page: {coverage['results_with_page']}/{coverage['results']}; "
            f"questions scored at page level: {coverage['questions_with_page']}/{coverage['questions_evaluated']}"
        )
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
    policy = gate.get("upload_retrieval_policy")
    if policy:
        lost = policy["second_chance_eligible_lost"]
        misses = policy["upload_question_misses_fixed"]
        lines += [
            "",
            "upload retrieval policy (FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED, rule only, no file search):",
            f"  rows fired: {policy['rows_fired']}; "
            f"upload_question misses fixed: {misses['fixed']} of {misses['misses_before']}",
            f"  wrong-skip: {format_rate(policy['wrong_skip_rate_before'])} -> "
            f"{format_rate(policy['wrong_skip_rate_after'])}",
            f"  false-retrieve: {format_rate(policy['false_retrieve_rate_before'])} -> "
            f"{format_rate(policy['false_retrieve_rate_after'])}",
            f"  fixed wrong skips: {', '.join(policy['fixed_wrong_skips']) or 'none'}"
            f" (course scope only, searched an unrelated upload: "
            f"{', '.join(policy['fixed_wrong_skips_course_scope_only']) or 'none'})",
            f"  new false retrieves: {', '.join(policy['new_false_retrieves']) or 'none'}",
            f"  needs_sources second chance lost (both settings on): {lost['rows']} rows, "
            f"{lost['expected_scope_course_or_both']} with course or both scope",
        ]
        estimate = policy.get("extra_prompt_estimate")
        if estimate:
            lines.append(
                f"  extra prompt chars (ESTIMATE, upper bound): mean {estimate['per_fired_row_chars_mean']}, "
                f"max {estimate['per_fired_row_chars_max']} per fired row; total {estimate['total_chars']} "
                f"(~{estimate['total_tokens_4cpt']} to {estimate['total_tokens_3cpt']} tokens)"
            )
        for category, record in policy["by_category"].items():
            if not record["policy_fired"]:
                continue
            lines.append(
                f"  {category}: wrong-skip {record['wrong_skips_before']} -> {record['wrong_skips_after']}"
                f" of {record['retrieve_rows']}; false-retrieve {record['false_retrieves_before']} -> "
                f"{record['false_retrieves_after']} of {record['skip_rows']}; fired {record['policy_fired']}; "
                f"extra chars (estimate) {record['extra_prompt_chars_estimate']}"
            )
    followups = result.get("followups")
    if followups:
        verdict = followups["verdict"]
        lines += [
            "",
            f"follow-up cases (SYNTHETIC, reported apart from the {gate['messages']} gate messages): "
            f"{followups['cases']} (retrieve {followups['retrieve_cases']}, skip {followups['skip_cases']})",
            f"  gate wrong-skip: {format_rate(followups['gate_wrong_skip'])}; "
            f"recoverable by needs_sources second chance: {followups['gate_wrong_skip_recoverable_by_second_chance']}",
            f"  gate false-retrieve: {format_rate(followups['gate_false_retrieve'])}",
            f"  built query uses history: {format_rate(followups['query_uses_history'])}",
            f"  query_ok (built query, top 4 has expected material): {format_rate(followups['query_ok'])}",
            f"  end-to-end pass (gate and query): {format_rate(followups['end_to_end_pass'])}",
            f"  end-to-end pass if a perfect needs_sources model recovered every eligible gate miss (informational): "
            f"{format_rate(followups['end_to_end_pass_if_second_chance_recovers_gate'])}; "
            f"attributable failures then: {followups['attributable_failures_if_second_chance_recovers_gate']}",
            f"  standalone control ok: {format_rate(followups['standalone_control_ok'])}",
            f"  contrast, history-weighted local search ok: {format_rate(followups['history_weighted_search_ok_contrast'])}",
            f"  verdict: {verdict['end_to_end_failures']} failures, {verdict['attributable_failures']} attributable "
            f"(rule: {verdict['min_failures']} and {verdict['min_attributable']}); clearly fail: {verdict['clearly_fail']}",
        ]
        for case in followups["per_case"]:
            lines.append(
                f"  {case['id']} [{case['expected_decision']}] gate_ok={case['gate_ok']} "
                f"query_ok={case.get('query_ok', 'n/a')} standalone_ok={case['standalone_ok']} "
                f"query={case['built_query']!r}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline retrieval eval (recall@4, wrong-skip, empty-result). "
        "Live Knowledge Base use needs --live-kb and --max-live-calls."
    )
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--messages", type=Path, default=MESSAGES_PATH)
    parser.add_argument(
        "--followups",
        type=Path,
        default=FOLLOWUPS_PATH,
        help="synthetic follow-up cases, reported apart from the gate messages (offline mode)",
    )
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
    parser.add_argument(
        "--ids",
        action="append",
        default=None,
        metavar="ID[,ID...]",
        help="--live-model only: send only these gate message ids (comma-separated, "
        "may be repeated; kept in file order). An unknown id is refused. "
        "With --categories, rows matching either are kept. "
        "--max-live-calls applies after all filters.",
    )
    parser.add_argument(
        "--categories",
        action="append",
        default=None,
        metavar="CATEGORY[,CATEGORY...]",
        help="--live-model only: send only rows of these categories (comma-separated, "
        "may be repeated). An unknown category is refused. With --ids, rows "
        "matching either are kept.",
    )
    parser.add_argument(
        "--expected-decision",
        choices=sorted(DECISIONS),
        default=None,
        help="--live-model only: after --ids/--categories, keep only rows with this label.",
    )
    parser.add_argument(
        "--skip-sample",
        type=int,
        default=0,
        metavar="N",
        help="--live-model only: then add N skip-labelled rows not already selected, "
        "evenly spaced over the remaining skip rows in file order (deterministic).",
    )
    parser.add_argument(
        "--compare-source-check",
        action="store_true",
        help="--live-model only: send each chosen message twice, with the SOURCE "
        "CHECK rule on and then off. --max-live-calls counts calls, so "
        "floor(N / 2) messages are sent; N must be at least 2.",
    )
    return parser


def parse_ids(values: Sequence[str] | None) -> list[str] | None:
    """Flatten repeated, comma-separated ``--ids`` or ``--categories`` values (``None`` if absent)."""
    if values is None:
        return None
    return [part.strip() for value in values for part in value.split(",") if part.strip()]


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
    ids = parse_ids(args.ids)
    categories = parse_ids(args.categories)
    # Select and check before the client exists: a refusal makes no client.
    try:
        selected = select_live_rows(
            messages,
            ids=ids,
            categories=categories,
            expected_decision=args.expected_decision,
            skip_sample=args.skip_sample,
        )
        rows_to_send = check_compare_limit(limit) if args.compare_source_check else limit
    except LiveRunRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    selection = {
        "ids": list(dict.fromkeys(ids)) if ids is not None else None,
        "categories": list(dict.fromkeys(categories)) if categories is not None else None,
        "expected_decision": args.expected_decision,
        "skip_sample": args.skip_sample,
        "compare_source_check": bool(args.compare_source_check),
        "messages_in_set": len(messages),
        "rows_selected": len(selected),
        "rows_after_cap": min(len(selected), rows_to_send),
    }
    client = _build_bedrock_runtime_client(region, limit)
    if args.compare_source_check:
        result = run_live_model_compare(
            selected,
            limit,
            client=client,
            model_id=model_id,
            region=region,
            selection=selection,
            materials=materials,
        )
        print(format_live_model_compare_report(result))
    else:
        result = run_live_model(
            selected,
            limit,
            client=client,
            model_id=model_id,
            region=region,
            selection=selection,
            materials=materials,
        )
        print(format_live_model_report(result))
    if result["first_failure"]:
        print(
            f"first failure class: {result['first_failure']['error']}",
            file=sys.stderr,
        )
    if args.json_output:
        _write_json_output(args.json_output, result)
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
    if (
        args.ids is not None
        or args.categories is not None
        or args.expected_decision is not None
        or args.skip_sample
        or args.compare_source_check
    ):
        print(
            "refused: --ids, --categories, --expected-decision, --skip-sample and "
            "--compare-source-check need --live-model",
            file=sys.stderr,
        )
        return 2
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
        followups = load_followups(args.followups, materials, [q["id"] for q in questions])
        result = run_offline(materials, questions, messages, followups)
    print(format_report(result))
    if args.json_output:
        _write_json_output(args.json_output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
