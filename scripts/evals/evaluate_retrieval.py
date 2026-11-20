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
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Shared offline helpers live in scripts/evals/lib. The names below are re-exported here so
# tests and callers that import them from this module keep working.
from scripts.evals.lib.paths import (  # noqa: E402
    DATASET_DIR as DATASET_DIR,
    FOLLOWUPS_PATH,
    MATERIALS_PATH,
    MESSAGES_PATH,
    QUESTIONS_PATH,
)
from scripts.evals.lib.fixtures import (  # noqa: E402
    CERTAINTIES as CERTAINTIES,
    DatasetError as DatasetError,
    DECISIONS,
    eval_course_titles,
    load_followups,
    load_materials,
    load_messages,
    load_questions,
    MESSAGE_CATEGORIES as MESSAGE_CATEGORIES,
    MESSAGE_KEYS as MESSAGE_KEYS,
    MIN_MESSAGE_COUNT as MIN_MESSAGE_COUNT,
    QUESTION_COUNT_RANGE as QUESTION_COUNT_RANGE,
    QUESTION_KEYS as QUESTION_KEYS,
    QUESTION_KINDS as QUESTION_KINDS,
    _read_jsonl as _read_jsonl,
    SCOPES as SCOPES,
    validate_messages as validate_messages,
    validate_questions as validate_questions,
)
from scripts.evals.lib.metrics import (  # noqa: E402
    empty_result_rate,
    evenly_spaced_indices,
    false_retrieve_rate,
    format_rate,
    rate as rate,
    rate_record,
    wrong_skip_rate,
)
from scripts.evals.lib.gate import (  # noqa: E402
    eval_upload_entries as _eval_upload_entries,
    gate_decision,
    GateDecision,
    scope_inputs_for_row,
)
from scripts.evals.lib.offline import (  # noqa: E402
    accepted_targets,
    block_network as _block_network,
    extract_pdf_pages as extract_pdf_pages,
    OfflineCourseSearch,
    rank_hits,
    RankedHit,
)
from scripts.evals.lib.live import (  # noqa: E402
    AUTH_ACCESS_ERROR_CLASSES as AUTH_ACCESS_ERROR_CLASSES,
    AUTH_ACCESS_ERROR_CODES as AUTH_ACCESS_ERROR_CODES,
    build_live_request,
    check_live_model_request,
    _EVAL_RUNTIME_ARN as _EVAL_RUNTIME_ARN,
    exception_label,
    _inline_schema_refs as _inline_schema_refs,
    is_auth_or_access_error,
    live_eval_provider as _live_eval_provider,
    live_failure_detail,
    LIVE_MODEL_HARD_CALL_CAP,
    LIVE_MODEL_MAX_OUTPUT_TOKENS as LIVE_MODEL_MAX_OUTPUT_TOKENS,
    live_model_settings,
    LIVE_MODEL_TIMEOUT_SECONDS,
    LiveCallLimitExceeded,
    LiveFastChatBridge,
    LiveRunRefused,
    LiveStructuredOutputError as LiveStructuredOutputError,
    _refuse_unknown as _refuse_unknown,
    select_live_rows,
)
from scripts.evals.lib.output import (  # noqa: E402
    _git_run_metadata,
    write_json_output as _write_output,
)


TOP_K = 4
# One Retrieve call per question and the set has fewer than 100 questions, so
# a higher limit could never be used.
HARD_LIVE_CALL_CAP = 100


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


# ---------------------------------------------------------------------------
# Pure metric functions (no backend imports, no I/O)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Offline gate and course search (imports the backend lazily)
# ---------------------------------------------------------------------------


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


def _write_json_output(path: Path, result: Mapping[str, Any]) -> None:
    """Write ``result`` as JSON with a ``run`` block (git SHA, UTC timestamp).

    The run block comes from this module's ``_git_run_metadata`` so a test can
    patch it here. The writer itself is ``scripts.evals.lib.output``.
    """
    _write_output(path, result, run=_git_run_metadata())


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
