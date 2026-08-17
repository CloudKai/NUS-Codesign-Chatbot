"""Durable coaching execution across workflow, retrieval, and persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.context_planner import memory_from_metadata
from backend.coaching.mode_policy import (
    qa_evidence_gap_turn,
    resolve_mode_policy,
    should_author_qa_evidence_gap,
)
from backend.coaching.progress import (
    PROGRESS_RETRIEVING,
    PROGRESS_SAVING,
    PROGRESS_THINKING,
    CoachProgressCallback,
    coach_progress,
    emit_coach_progress,
)
from backend.coaching.progress_fields import meaningful_progress_fields
from backend.coaching.turn_snapshot import TurnSnapshot
from backend.domain import (
    CitationReference,
    CoachImageInput,
    CoachRequest,
    CoachTurn,
    DeepReviewJob,
    DeepReviewJobStatus,
    ProvisionalResearchCoding,
    RESEARCH_CODING_VERSION,
    ResearchCodingStatus,
    RetrievalChunkReference,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.models import DEFAULT_CHAT_MODEL_ID, get_model, validate_reasoning
from backend.prompts.composer import COACH_PROMPT_VERSION
from backend.research.models import ResearchEvidenceSpan, ResearchObservationCreate
from backend.repositories import NotebookRepository
from backend.retrieval import (
    ContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalSource,
    bounded_retrieval_result,
    focused_excerpt,
    with_course_evidence_gap,
)
from backend.settings import settings as runtime_settings
from backend.providers import ProviderUnavailableError
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_ERROR_FAILED,
    DEEP_REVIEW_ERROR_TIMEOUT,
    DEEP_REVIEW_JOB_COMPLETED,
    DEEP_REVIEW_JOB_FAILED,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
    bound_deep_review_interval,
    deep_review_job_is_stale,
    deep_review_snapshot_payload,
    explicit_deep_review_available,
    parse_coaching_turns_since_deep_review,
    parse_deep_review_job,
)
from backend.source_library import (
    image_inputs_for_sources,
    list_visible_sources,
    selected_source_context,
    shared_course_catalog_scope,
)
from backend.sources.chunk_load import hydrate_selected_retrieval_sources
from backend.student_journey import (
    DEFAULT_RESPONSE_DETAIL,
    advanced_stage_response,
    current_stage,
    normalize_journey,
    personalized_stage_questions,
)
from backend.student_store import (
    AtomicAutoAdvance,
    CoachRequestInProgressError,
    StudentStore,
)
from backend.title_service import NotebookTitleService
from backend.turn_perf import (
    begin_coach_turn_perf,
    current_perf,
    elapsed_ms,
    emit_coach_turn_perf,
    record_count,
    record_failure,
    record_field,
    record_span,
    record_success,
)
from backend.workflow import CoachWorkflow

_CITATION_LABEL = re.compile(r"\[(S\d+)\]")
IDEMPOTENCY_SURFACE_COACH_TURN = "coach_turn"
IDEMPOTENCY_SURFACE_DEEP_REVIEW = "deep_review"

logger = logging.getLogger(__name__)


def _quote_offsets(text: str, quote: str) -> tuple[int, int] | None:
    """Locate one exact provider quotation in persisted student-message text."""
    bounded_text = str(text or "").strip()
    bounded_quote = str(quote or "").strip()
    if not bounded_quote:
        return None
    start = bounded_text.find(bounded_quote)
    if start < 0:
        return None
    return start, start + len(bounded_quote)


def _research_observation_from_coding(
    coding: ProvisionalResearchCoding | None,
    request: CoachRequest,
    *,
    provider: str,
    model_id: str | None = None,
) -> ResearchObservationCreate | None:
    """Convert transient provider quotes into offset-only persistence input.

    Exact matching deliberately fails closed: non-uncoded research with no
    evidence, or any quoted research evidence that cannot be located in the
    current student contribution, is not persisted. A malformed Reflection
    candidate is dropped independently so otherwise valid occurrence coding
    can still be retained. Raw quote text never crosses this boundary.
    """
    if coding is None:
        return None
    student_message = str(request.student_message or "").strip()
    evidence: list[ResearchEvidenceSpan] = []
    for item in coding.evidence:
        offsets = _quote_offsets(student_message, item.quote)
        if offsets is None:
            return None
        evidence.append(
            ResearchEvidenceSpan(
                start_offset=offsets[0],
                end_offset=offsets[1],
                rationale=" ".join(item.rationale.split())[:500],
                confidence=item.confidence,
            )
        )
    if coding.coding_status is not ResearchCodingStatus.UNCODED and not evidence:
        return None

    holistic_payload: dict[str, Any] | None = None
    candidate = coding.holistic_candidate
    if candidate is not None and request.current_stage == "reflection":
        holistic_spans: list[dict[str, int]] = []
        for quote in candidate.evidence_quotes:
            offsets = _quote_offsets(student_message, quote)
            if offsets is None:
                holistic_spans = []
                break
            holistic_spans.append(
                {"start_offset": offsets[0], "end_offset": offsets[1]}
            )
        if not candidate.evidence_quotes or holistic_spans:
            holistic_payload = {
                "score": candidate.score,
                "rationale": " ".join(candidate.rationale.split())[:1_000],
                "evidence_spans": holistic_spans,
            }

    return ResearchObservationCreate(
        coding_status=coding.coding_status.value,
        dominant_clear=(coding.dominant_clear.value if coding.dominant_clear else None),
        facione_behaviors=[value.value for value in coding.facione_behaviors],
        ethics_concepts=[value.value for value in coding.ethics_concepts],
        evidence=evidence,
        holistic_candidate=holistic_payload,
        coding_version=RESEARCH_CODING_VERSION,
        prompt_version=COACH_PROMPT_VERSION,
        provider=str(provider or "unknown").strip() or "unknown",
        model_id=str(model_id or request.model_id or "unknown").strip() or "unknown",
        coaching_profile=("strict" if request.response_detail == "long" else "quick"),
        phase_id=request.current_stage,
        metadata={"source": "coach_provider", "one_call": True},
    )


def _history_signature(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return a comparable role/content signature for canonical chat history."""
    signature: list[tuple[str, str]] = []
    for message in messages:
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        signature.append((str(message.get("role") or "").strip().lower(), content))
    return signature


def _coach_request_fingerprint(
    request: CoachRequest,
    *,
    surface: str = IDEMPOTENCY_SURFACE_COACH_TURN,
) -> str:
    """Return a stable digest for idempotency comparison without storing content.

    The marker keeps only this digest, never the raw request or source/image
    payload.  All request fields except the retry key and server-derived mode
    policy are included so reusing a key for a modified turn fails closed
    instead of returning a misleading earlier answer. Mode policy is
    recomputed from the student message and selected sources, which are
    already in the digest. Deep Review hashes a distinct surface so
    ``/coach/turn`` cannot complete a ``/deep-review`` key. The default
    coach-turn hash stays backward-compatible with existing markers.
    """
    payload = request.model_dump(
        mode="json",
        exclude={
            "idempotency_key",
            "expected_response_mode",
            "mode_policy_intent",
        },
    )
    cleaned = str(surface or IDEMPOTENCY_SURFACE_COACH_TURN).strip().lower()
    if cleaned and cleaned != IDEMPOTENCY_SURFACE_COACH_TURN:
        payload["idempotency_surface"] = cleaned
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coach_turn_from_payload(payload: dict[str, Any] | None) -> CoachTurn | None:
    """Validate a durable coach turn payload, or return ``None`` when unusable."""
    if not isinstance(payload, dict):
        return None
    try:
        return CoachTurn.model_validate(payload)
    except Exception:
        return None


def _project_context_from_metadata(metadata: dict[str, Any]) -> str:
    """Build a short server-side project context from notebook assignment fields."""
    assignment = metadata.get("assignment")
    if not isinstance(assignment, dict):
        assignment = {}
    parts: list[str] = []
    for key, label in (
        ("title", "Title"),
        ("course", "Course"),
        ("brief", "Brief"),
        ("rubric", "Rubric"),
    ):
        value = " ".join(str(assignment.get(key) or "").split()).strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


class CoachApplicationService:
    """Persist complete typed coaching turns without exposing infrastructure to callers."""

    def __init__(
        self,
        store: StudentStore,
        notebooks: NotebookRepository,
        workflow: CoachWorkflow,
        progress: LearningProgressService | None = None,
        *,
        auto_advance_stages: bool = False,
        retriever: ContextRetriever | None = None,
    ) -> None:
        self._store = store
        self._notebooks = notebooks
        self._workflow = workflow
        self._progress = progress
        self._auto_advance_stages = auto_advance_stages
        self._retriever = retriever or LocalChunkRetriever()

    def _rate_limit_user_key(self) -> str:
        """Return the authenticated store owner key for coach rate limiting.

        Identity comes from the owner-scoped store, never from a browser-supplied
        user identifier.
        """
        return str(getattr(self._store, "owner_id", "") or "").strip()

    def _rate_limit_thread_id(self, request: CoachRequest) -> str:
        """Return the authoritative notebook id already validated for this turn."""
        return str(getattr(request, "thread_id", "") or "").strip()

    def _execute_rate_limited(
        self,
        request: CoachRequest,
        *,
        idempotency_marker_id: str | None = None,
        idempotency_lease_token: str | None = None,
        idempotency_fingerprint: str | None = None,
        execution_lease_held: bool = False,
        server_owned_specialist: str | None = None,
    ) -> CoachTurn:
        """Run one provider-backed turn under the process-local coach limiter.

        Same-key waiters and completed replays never call this helper, so they
        do not consume active/RPM slots. Only a newly claimed execution (or a
        turn without an idempotency key) is limited. When *execution_lease_held*
        is true, the caller already owns the notebook/user/global slot and this
        helper must not acquire a second one.
        """
        from backend.rate_limit import get_coach_rate_limiter

        if execution_lease_held:
            return self._submit_once(
                request,
                idempotency_marker_id=idempotency_marker_id,
                idempotency_lease_token=idempotency_lease_token,
                idempotency_fingerprint=idempotency_fingerprint,
                server_owned_specialist=server_owned_specialist,
            )
        with get_coach_rate_limiter().limit(
            self._rate_limit_user_key(),
            self._rate_limit_thread_id(request),
        ):
            return self._submit_once(
                request,
                idempotency_marker_id=idempotency_marker_id,
                idempotency_lease_token=idempotency_lease_token,
                idempotency_fingerprint=idempotency_fingerprint,
                server_owned_specialist=server_owned_specialist,
            )

    def _recover_durable_coach_turn(
        self, thread_id: str, idempotency_key: str
    ) -> CoachTurn | None:
        """Replay a completed marker or a committed recorded coach turn.

        Called before any revise mutation so a retry after persist-before-complete
        cannot supersede another branch or bump ``conversation_revision``. The
        store lookup is authoritative for completed markers; active-message
        reconstruction covers a committed turn whose marker was not completed.
        Never queries identity fields on messages.
        """
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        recovered = _coach_turn_from_payload(
            self._store.lookup_completed_coach_request(
                thread_id, idempotency_key=key
            )
        )
        if recovered is not None:
            return recovered

        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            return None
        settings = dict(thread.get("metadata") or {})
        revoked = settings.get("revoked_coach_idempotency_keys") or []
        if isinstance(revoked, list) and key in {
            str(item).strip() for item in revoked if str(item).strip()
        }:
            return None

        for message in self._store.get_messages(thread_id):
            if str(message.get("role") or "") != "assistant":
                continue
            metadata = dict(message.get("metadata") or {})
            if str(metadata.get("coach_idempotency_key") or "").strip() != key:
                continue
            assessment = metadata.get("assessment")
            if not isinstance(assessment, dict):
                continue
            pending_transition: dict[str, Any] | None = None
            if (
                metadata.get("proposed_stage")
                and metadata.get("decision_status") == "pending"
                and metadata.get("from_stage")
            ):
                pending_transition = {
                    "id": str(message.get("id") or ""),
                    "thread_id": thread_id,
                    "from_stage": str(metadata["from_stage"]),
                    "to_stage": str(metadata["proposed_stage"]),
                    "assessment": assessment,
                    "status": "pending",
                    "created_at": str(message.get("created_at") or ""),
                    "resolved_at": None,
                }
            return _coach_turn_from_payload(
                {
                    "response_text": str(message.get("content") or ""),
                    "assessment": assessment,
                    "pending_transition": pending_transition,
                    "auto_advanced_to": metadata.get("auto_advanced_to"),
                }
            )
        return None

    def submit(
        self,
        request: CoachRequest,
        *,
        execution_lease_held: bool = False,
        server_owned_specialist: str | None = None,
        progress: CoachProgressCallback | None = None,
    ) -> CoachTurn:
        """Run and persist one turn, optionally applying its recommendation.

        Persisted notebook state is authoritative for stage, history, selected
        sources, source context, and image inputs. Client-supplied values that
        disagree are rejected. The workflow always writes an auditable
        transition first; automatic mode resolves it before the visible reply.

        Stamps the current notebook ``conversation_revision`` onto the request
        for store CAS/stamping; normal submit does not bump that revision.
        When *execution_lease_held* is true, the caller already owns the
        notebook execution slot and this method must not acquire another.
        *server_owned_specialist* is never taken from the HTTP coach-turn
        body; only ``enqueue_deep_review`` / the Deep Review worker may pass
        ``review``.
        *progress* receives execution-boundary phase names for NDJSON status
        events. It must not receive student text.
        """
        with coach_progress(progress):
            return self._submit_body(
                request,
                execution_lease_held=execution_lease_held,
                server_owned_specialist=server_owned_specialist,
            )

    def _submit_body(
        self,
        request: CoachRequest,
        *,
        execution_lease_held: bool = False,
        server_owned_specialist: str | None = None,
    ) -> CoachTurn:
        """Execute one turn after the progress callback is bound."""
        perf = current_perf() or begin_coach_turn_perf()
        record_field("notebook_load_count", 0)
        record_field("retrieval_count", 0)
        record_field("citation_source_resolution_count", 0)
        record_field("source_catalog_load_count", 0)
        try:
            with shared_course_catalog_scope():
                thread = self._notebooks.get_thread(request.thread_id)
                record_count("notebook_load_count")
                if not thread:
                    raise ValueError("Notebook not found")
                metadata = dict(thread.get("metadata") or {})
                revision = int(
                    metadata.get("conversation_revision")
                    if metadata.get("conversation_revision") is not None
                    else thread.get("conversation_revision")
                    or 0
                )
                request = request.model_copy(update={"conversation_revision": revision})
                record_field("stage", request.current_stage)

                idempotency_key = str(request.idempotency_key or "").strip()
                if not idempotency_key:
                    turn = self._execute_rate_limited(
                        request,
                        execution_lease_held=execution_lease_held,
                        server_owned_specialist=server_owned_specialist,
                    )
                    record_success()
                    return turn

                surface = (
                    IDEMPOTENCY_SURFACE_DEEP_REVIEW
                    if str(server_owned_specialist or "").strip().lower() == "review"
                    else IDEMPOTENCY_SURFACE_COACH_TURN
                )
                fingerprint = _coach_request_fingerprint(request, surface=surface)
                deadline = time.monotonic() + 125.0
                while True:
                    claim_started = time.perf_counter()
                    reservation = self._store.claim_coach_request(
                        request.thread_id,
                        idempotency_key=idempotency_key,
                        request_fingerprint=fingerprint,
                    )
                    record_field("idempotency_claim_ms", elapsed_ms(claim_started))
                    if reservation.state == "completed":
                        if not isinstance(reservation.turn_payload, dict):
                            raise ValueError(
                                "Completed coach idempotency result is invalid"
                            )
                        record_success()
                        return CoachTurn.model_validate(reservation.turn_payload)
                    if reservation.state == "claimed":
                        try:
                            turn = self._execute_rate_limited(
                                request,
                                idempotency_marker_id=reservation.marker_id,
                                idempotency_lease_token=reservation.lease_token,
                                idempotency_fingerprint=fingerprint,
                                execution_lease_held=execution_lease_held,
                                server_owned_specialist=server_owned_specialist,
                            )
                            complete_started = time.perf_counter()
                            self._store.complete_coach_request(
                                request.thread_id,
                                marker_id=reservation.marker_id,
                                idempotency_key=idempotency_key,
                                request_fingerprint=fingerprint,
                                lease_token=str(reservation.lease_token or ""),
                                turn_payload=turn.model_dump(mode="json"),
                            )
                            record_field(
                                "idempotency_complete_ms", elapsed_ms(complete_started)
                            )
                            record_success()
                            return turn
                        except Exception as error:
                            self._store.fail_coach_request(
                                request.thread_id,
                                marker_id=reservation.marker_id,
                                request_fingerprint=fingerprint,
                                lease_token=str(reservation.lease_token or ""),
                            )
                            category = str(getattr(error, "category", "") or "")
                            record_failure(category or "unavailable")
                            raise
                    if time.monotonic() >= deadline:
                        raise CoachRequestInProgressError(
                            "This coach request is still processing; retry with the same "
                            "idempotency key to recover its completed turn."
                        )
                    time.sleep(0.05)
        except Exception as error:
            category = str(getattr(error, "category", "") or "")
            if category:
                record_failure(category)
            elif current_perf() is not None and not current_perf().failure_category:
                record_failure("unavailable")
            raise
        finally:
            emit_coach_turn_perf(perf)

    def enqueue_deep_review(
        self,
        thread_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> DeepReviewJob:
        """Queue one server-owned explicit Deep Review without blocking on Sonnet.

        Eligibility, stage, history, and sources come from persisted state.
        The browser cannot choose Sonnet through ``CoachRequest.specialist``.
        An in-flight queued/running job is reused instead of starting a second
        worker. ``idempotency_key`` is accepted for HTTP compatibility and is
        not used to replay a transcript turn.

        Args:
            thread_id: Authenticated owner's notebook id.
            idempotency_key: Unused compatibility field from the HTTP body.

        Returns:
            The queued, running, or reused Deep Review job. Stage is unchanged.

        Raises:
            ValueError: Missing notebook or Deep Review is not yet eligible.
        """
        del idempotency_key
        from backend.coaching.deep_review_jobs import submit_deep_review_job

        existing = self.get_deep_review_job(thread_id)
        if existing is not None and existing.status in {
            DeepReviewJobStatus.QUEUED,
            DeepReviewJobStatus.RUNNING,
        }:
            return existing
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        counter = parse_coaching_turns_since_deep_review(
            metadata.get(COUNTER_SETTINGS_KEY)
        )
        interval = bound_deep_review_interval(
            runtime_settings.deep_review_interval_turns
        )
        if not explicit_deep_review_available(
            coaching_turns_since_deep_review=counter,
            interval=interval,
        ):
            raise ValueError(
                "Deep Review is not available yet. Complete more Coaching turns first."
            )
        reviewed_revision = int(thread.get("conversation_revision") or 0)
        messages = self._store.get_messages(thread_id)
        message_ids = [
            str(message.get("id") or "")
            for message in messages
            if str(message.get("id") or "").strip()
        ]
        visible_sources = list_visible_sources(
            self._store,
            thread_id,
            selected_only=True,
            include_extracted_text=False,
        )
        source_ids = [
            str(source.get("id") or "")
            for source in visible_sources
            if str(source.get("id") or "").strip()
        ]
        job_payload, created = self._store.start_or_get_deep_review_job(
            thread_id,
            review_id=str(uuid.uuid4()),
            reviewed_revision=reviewed_revision,
            stage_at_start=current_stage(journey).id,
            source_ids=source_ids,
            message_ids=message_ids,
        )
        if created:
            submit_deep_review_job(self, thread_id, str(job_payload["review_id"]))
        return self._deep_review_job_model(
            job_payload,
            metadata={**metadata, DEEP_REVIEW_JOB_KEY: job_payload},
            conversation_revision=reviewed_revision,
        )

    def get_deep_review_job(self, thread_id: str) -> DeepReviewJob | None:
        """Return the owner-scoped Deep Review job, failing stale in-flight work.

        Args:
            thread_id: Authenticated owner's notebook id.

        Returns:
            The job envelope, or ``None`` when this notebook has never queued
            a Deep Review.

        Raises:
            ValueError: When the notebook is missing.
        """
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
        timeout = runtime_settings.deep_review_job_timeout_seconds
        if job is not None and deep_review_job_is_stale(job, timeout):
            try:
                self._store.fail_deep_review_job(
                    thread_id,
                    review_id=str(job["review_id"]),
                    error_code=DEEP_REVIEW_ERROR_TIMEOUT,
                )
            except Exception:
                logger.exception(
                    "deep_review_stale_fail_failed review_id=%s",
                    job.get("review_id"),
                )
            thread = self._notebooks.get_thread(thread_id) or thread
            metadata = dict(thread.get("metadata") or {})
            job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
        if job is None:
            return None
        return self._deep_review_job_model(
            job,
            metadata=metadata,
            conversation_revision=int(thread.get("conversation_revision") or 0),
        )

    def execute_deep_review_job(self, thread_id: str, review_id: str) -> None:
        """Run one queued Deep Review against the frozen revision snapshot.

        Skips the notebook coaching lease and does not insert transcript rows.
        Completion writes the snapshot, job status, and counter only.

        Args:
            thread_id: Authenticated owner's notebook id.
            review_id: Job id persisted at enqueue.
        """
        from backend.rate_limit import get_deep_review_limiter

        cleaned_id = str(review_id or "").strip()
        timeout = runtime_settings.deep_review_job_timeout_seconds
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            return
        metadata = dict(thread.get("metadata") or {})
        job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
        if not job or str(job.get("review_id") or "") != cleaned_id:
            return
        if str(job.get("status") or "") in {
            DEEP_REVIEW_JOB_COMPLETED,
            DEEP_REVIEW_JOB_FAILED,
        }:
            return
        if deep_review_job_is_stale(job, timeout):
            self._store.fail_deep_review_job(
                thread_id,
                review_id=cleaned_id,
                error_code=DEEP_REVIEW_ERROR_TIMEOUT,
            )
            return
        if not self._store.mark_deep_review_job_running(thread_id, cleaned_id):
            return
        try:
            with get_deep_review_limiter().slot():
                thread = self._notebooks.get_thread(thread_id)
                if not thread:
                    return
                metadata = dict(thread.get("metadata") or {})
                job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
                if not job or str(job.get("review_id") or "") != cleaned_id:
                    return
                if deep_review_job_is_stale(job, timeout):
                    self._store.fail_deep_review_job(
                        thread_id,
                        review_id=cleaned_id,
                        error_code=DEEP_REVIEW_ERROR_TIMEOUT,
                    )
                    return
                journey = normalize_journey(metadata.get("learning_journey"))
                stage_id = str(job.get("stage_at_start") or "") or current_stage(
                    journey
                ).id
                request = CoachRequest(
                    thread_id=thread_id,
                    student_message=DEEP_REVIEW_TURN_MESSAGE,
                    current_stage=stage_id,
                    response_detail=str(
                        journey.get("response_detail") or DEFAULT_RESPONSE_DETAIL
                    ),
                    review_id=cleaned_id,
                )
                prepared, snapshot = self._prepare_authoritative_turn(
                    request,
                    force_retrieval=True,
                    frozen_history_revision=int(job.get("reviewed_revision") or 0),
                    frozen_stage=stage_id,
                    frozen_source_ids=list(job.get("source_ids") or []),
                    frozen_message_ids=list(job.get("message_ids") or []),
                )
                prepared = self._server_owned_deep_review_request(prepared)
                prepared = prepared.model_copy(update={"review_id": cleaned_id})
                turn = self._workflow.run(prepared)
                prepared, turn = self._maybe_rag_fallback(prepared, turn, snapshot)
                self._workflow.take_provisional_research_coding(thread_id)
                self._workflow.take_conversation_memory(thread_id)
                orchestration = self._workflow.take_review_orchestration(thread_id)
                if not orchestration.get("deep_review_succeeded"):
                    raise ProviderUnavailableError(
                        "Deep Review could not be completed",
                        category="malformed",
                    )
                snapshot_payload = deep_review_snapshot_payload(
                    conversation_revision=int(job.get("reviewed_revision") or 0),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    synthesis=turn.assessment.learning_summary
                    or turn.assessment.stage_assessment,
                    summary=turn.assessment.learning_summary,
                    strengths=list(turn.assessment.review_strengths),
                    areas_to_develop=list(turn.assessment.review_improvements),
                    facione_scores=turn.assessment.facione_scores.model_dump(
                        mode="json"
                    ),
                    working_conclusion=turn.assessment.working_conclusion,
                    readiness_candidate=bool(turn.assessment.readiness_candidate),
                    readiness_evidence=list(turn.assessment.evidence_identified),
                    missing_requirements=list(
                        turn.assessment.missing_reasoning_elements
                    ),
                    model_id=str(turn.assessment.review_model or "").strip()
                    or "global.anthropic.claude-sonnet-4-6",
                )
                self._store.complete_deep_review_job(
                    thread_id,
                    review_id=cleaned_id,
                    snapshot=snapshot_payload,
                )
        except Exception:
            logger.exception("deep_review_execute_failed review_id=%s", cleaned_id)
            try:
                self._store.fail_deep_review_job(
                    thread_id,
                    review_id=cleaned_id,
                    error_code=DEEP_REVIEW_ERROR_FAILED,
                )
            except Exception:
                logger.exception(
                    "deep_review_fail_write_failed review_id=%s", cleaned_id
                )

    def run_deep_review(
        self,
        thread_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> DeepReviewJob:
        """Compatibility alias for :meth:`enqueue_deep_review`."""
        return self.enqueue_deep_review(
            thread_id, idempotency_key=idempotency_key
        )

    @staticmethod
    def _deep_review_job_model(
        job: dict[str, Any],
        *,
        metadata: dict[str, Any],
        conversation_revision: int,
    ) -> DeepReviewJob:
        """Build the API/UI job envelope from a persisted settings blob."""
        snapshot = None
        if str(job.get("status") or "") == DEEP_REVIEW_JOB_COMPLETED:
            raw = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
            snapshot = raw if isinstance(raw, dict) else None
        return DeepReviewJob(
            review_id=str(job["review_id"]),
            status=DeepReviewJobStatus(str(job["status"])),
            reviewed_revision=int(job.get("reviewed_revision") or 0),
            stage_at_start=job.get("stage_at_start"),
            started_at=job.get("started_at"),
            updated_at=job.get("updated_at"),
            error_code=job.get("error_code"),
            snapshot=snapshot,
            conversation_revision=int(conversation_revision),
        )

    def _submit_once(
        self,
        request: CoachRequest,
        *,
        idempotency_marker_id: str | None = None,
        idempotency_lease_token: str | None = None,
        idempotency_fingerprint: str | None = None,
        server_owned_specialist: str | None = None,
    ) -> CoachTurn:
        """Execute the original authoritative workflow path exactly once."""
        if current_perf() is None:
            begin_coach_turn_perf()
        contract_ready = getattr(
            self._store, "research_workflow_contract_ready", None
        )
        if callable(contract_ready) and not contract_ready():
            raise ValueError(
                "Research workflow contract is not ready; use explicit reset/bootstrap"
            )
        owned_review = str(server_owned_specialist or "").strip().lower() == "review"
        if owned_review:
            record_field("deep_review_invoked", True)
            record_field("deep_review_model_role", "review_deep")
        prepared_request, snapshot = self._prepare_authoritative_turn(
            request, force_retrieval=owned_review
        )
        if owned_review:
            prepared_request = self._server_owned_deep_review_request(prepared_request)
        should_generate_title = str(snapshot.thread.get("name") or "") in {
            "",
            "Untitled notebook",
            "New assignment chat",
        } and not any(
            message.get("role") == "user" for message in prepared_request.history
        )
        if (
            not owned_review
            and should_author_qa_evidence_gap(prepared_request)
        ):
            record_field("qa_evidence_gap_authored", True)
            record_field("agentcore_call_count", 0)
            record_field("agent_ms", 0)
            turn = qa_evidence_gap_turn(prepared_request)
        else:
            emit_coach_progress(PROGRESS_THINKING)
            with record_span("agent_ms"):
                turn = self._workflow.run(prepared_request)
            prepared_request, turn = self._maybe_rag_fallback(
                prepared_request, turn, snapshot
            )
        if owned_review:
            should_generate_title = False
        research_observation = _research_observation_from_coding(
            self._workflow.take_provisional_research_coding(
                prepared_request.thread_id
            ),
            prepared_request,
            provider=self._workflow.provider_id,
            model_id=self._workflow.model_id_for(prepared_request),
        )
        citations = self._relevant_citations(prepared_request, turn, snapshot)
        if owned_review:
            research_observation = None
        turn = turn.model_copy(
            update={
                "assessment": turn.assessment.model_copy(update={"citations": citations})
            }
        )
        transition_id = turn.pending_transition.id if turn.pending_transition else None
        source_refs = [
            {
                "id": citation.source_id,
                "label": citation.label,
                "title": citation.title,
            }
            for citation in turn.assessment.citations
        ]
        retrieval_refs = [
            chunk.model_dump(mode="json") for chunk in prepared_request.retrieved_chunks
        ]
        generated_title = (
            NotebookTitleService.generate(
                turn.assessment.contribution_summary
                or prepared_request.student_message
            )
            if should_generate_title
            else None
        )
        from backend.settings import settings as runtime_settings

        orchestration = self._workflow.take_review_orchestration(
            prepared_request.thread_id
        )
        if owned_review:
            if not orchestration.get("deep_review_succeeded"):
                raise ProviderUnavailableError(
                    "Deep Review could not be completed",
                    category="malformed",
                )
            stay_assessment = turn.assessment.model_copy(
                update={"recommendation": StageDecision.STAY}
            )
            turn = turn.model_copy(
                update={
                    "assessment": stay_assessment,
                    "pending_transition": None,
                    "auto_advanced_to": None,
                }
            )

        auto_advance: AtomicAutoAdvance | None = None
        if (
            not owned_review
            and self._auto_advance_stages
            and not runtime_settings.student_stage_selection
            and self._progress is not None
            and turn.pending_transition is not None
        ):
            pending = turn.pending_transition
            questions = turn.assessment.guidance_questions or list(
                personalized_stage_questions(
                    pending.to_stage,
                    prepared_request.student_message,
                    has_course_sources=bool(prepared_request.source_ids),
                )
            )
            auto_advance = AtomicAutoAdvance(
                transition_id=pending.id,
                from_stage=pending.from_stage,
                to_stage=pending.to_stage,
                contribution_summary=turn.assessment.contribution_summary,
            )
            turn = turn.model_copy(
                update={
                    "response_text": advanced_stage_response(
                        turn.response_text,
                        pending.from_stage,
                        pending.to_stage,
                        questions,
                    ),
                    "assessment": turn.assessment.model_copy(
                        update={"guidance_questions": questions}
                    ),
                    "pending_transition": None,
                    "auto_advanced_to": pending.to_stage,
                }
            )
        persist_started = time.perf_counter()
        emit_coach_progress(PROGRESS_SAVING)
        self._store.persist_coach_turn(
            prepared_request.thread_id,
            expected_stage=prepared_request.current_stage,
            expected_conversation_revision=int(
                prepared_request.conversation_revision or 0
            ),
            expected_response_detail=prepared_request.response_detail,
            user_content=prepared_request.student_message,
            user_metadata={
                "thinking_stage": prepared_request.current_stage,
                "source_ids": prepared_request.source_ids,
                "workflow": "langgraph",
                **(
                    {"coach_idempotency_key": prepared_request.idempotency_key}
                    if prepared_request.idempotency_key
                    else {}
                ),
            },
            assistant_content=turn.response_text,
            assistant_message_id=transition_id,
            assistant_metadata={
                "thinking_stage": (
                    auto_advance.to_stage
                    if auto_advance is not None
                    else prepared_request.current_stage
                ),
                "assessment": turn.assessment.persisted_mapping(),
                "pending_transition_id": transition_id,
                "proposed_stage": (
                    auto_advance.to_stage
                    if auto_advance is not None
                    else (
                        turn.pending_transition.to_stage
                        if turn.pending_transition
                        else None
                    )
                ),
                "decision_status": (
                    "confirmed"
                    if auto_advance is not None
                    else ("pending" if turn.pending_transition else None)
                ),
                "from_stage": (
                    auto_advance.from_stage
                    if auto_advance is not None
                    else (
                        turn.pending_transition.from_stage
                        if turn.pending_transition
                        else None
                    )
                ),
                **(
                    {"auto_advanced_to": auto_advance.to_stage}
                    if auto_advance is not None
                    else {}
                ),
                "workflow": "langgraph",
                "coaching_profile": (
                    "strict" if prepared_request.response_detail == "long" else "quick"
                ),
                "source_ids": prepared_request.source_ids,
                "retrieval_refs": retrieval_refs,
                "source_refs": source_refs,
                **(
                    {"coach_idempotency_key": prepared_request.idempotency_key}
                    if prepared_request.idempotency_key
                    else {}
                ),
            },
            summary_metadata=self._summary_metadata_for_persist(
                turn,
                prepared_request=prepared_request,
                owned_review=owned_review,
            ),
            generated_title=generated_title,
            existing_user_message_id=prepared_request.revise_user_message_id,
            idempotency_marker_id=idempotency_marker_id,
            idempotency_key=prepared_request.idempotency_key,
            idempotency_lease_token=idempotency_lease_token,
            idempotency_fingerprint=idempotency_fingerprint,
            research_observation=research_observation,
            auto_advance=auto_advance,
            review_counter_qualifying=bool(
                orchestration.get("qualifying_coaching_turn")
            ),
            review_counter_deep_succeeded=bool(
                orchestration.get("deep_review_succeeded")
            ),
        )
        record_field("persist_turn_ms", elapsed_ms(persist_started))
        return turn

    def _summary_metadata_for_persist(
        self,
        turn: CoachTurn,
        *,
        prepared_request: CoachRequest,
        owned_review: bool,
    ) -> dict[str, Any]:
        """Build notebook summary fields for one persisted turn.

        Fast Chat assessments are slim and must not blank historical
        ``learning_summary`` / working-conclusion keys. Deep Review still
        writes the full review snapshot, but empty progress strings from a
        degraded review are omitted so they cannot blank stored notebook
        progress.
        """
        summary: dict[str, Any] = {
            "conversation_memory": self._workflow.take_conversation_memory(
                prepared_request.thread_id
            )
        }
        progress_fields = {
            "learning_summary": turn.assessment.learning_summary,
            "working_conclusion": turn.assessment.working_conclusion,
            "understanding_change": turn.assessment.understanding_change,
            "critical_understanding": turn.assessment.critical_understanding_level,
        }
        summary.update(meaningful_progress_fields(progress_fields))
        if owned_review:
            summary[DEEP_REVIEW_SNAPSHOT_KEY] = deep_review_snapshot_payload(
                conversation_revision=int(
                    prepared_request.conversation_revision or 0
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
                synthesis=turn.assessment.learning_summary
                or turn.assessment.stage_assessment,
                summary=turn.assessment.learning_summary,
                strengths=list(turn.assessment.review_strengths),
                areas_to_develop=list(turn.assessment.review_improvements),
                facione_scores=turn.assessment.facione_scores.model_dump(
                    mode="json"
                ),
                working_conclusion=turn.assessment.working_conclusion,
                readiness_candidate=bool(turn.assessment.readiness_candidate),
                readiness_evidence=list(turn.assessment.evidence_identified),
                missing_requirements=list(
                    turn.assessment.missing_reasoning_elements
                ),
                model_id=str(turn.assessment.review_model or "").strip()
                or "global.anthropic.claude-sonnet-4-6",
            )
        return summary

    def _retrieve_for_turn(
        self,
        *,
        student_message: str,
        current_stage: str,
        retrieval_sources: tuple[RetrievalSource, ...] | list[RetrievalSource],
        project_context: str,
        conversation_summary: str,
        recent_messages: list[dict[str, Any]],
        timing_field: str = "retrieval_total_ms",
    ) -> tuple[list[RetrievalChunkReference], str]:
        """Run authoritative selected-source retrieval for one coaching turn.

        Args:
            student_message: Current student contribution.
            current_stage: Server-authoritative Thinking Path stage.
            retrieval_sources: Selected, ownership-checked retrieval sources.
            project_context: Bounded project/assignment context.
            conversation_summary: Bounded learning summary.
            recent_messages: Stored transcript turns for lexical retrieval.
            timing_field: Performance field that records this retrieve duration.

        Returns:
            Validated chunk references and prompt context. Ownership mismatches
            raise ``ValueError``. Retriever exceptions propagate after timing
            is recorded.

        Raises:
            ValueError: When the retriever returns a source outside the
                selected notebook catalog.
        """
        record_count("retrieval_count")
        retrieval_started = time.perf_counter()
        try:
            retrieval_result = self._retriever.retrieve(
                RetrievalQuery(
                    current_message=student_message,
                    current_stage=current_stage,
                    sources=tuple(retrieval_sources),
                    project_context=project_context,
                    conversation_summary=conversation_summary,
                    recent_messages=tuple(recent_messages),
                )
            )
        except Exception as error:
            duration = elapsed_ms(retrieval_started)
            record_field(timing_field, duration)
            if timing_field != "retrieval_total_ms":
                current = current_perf()
                if current is not None:
                    current.add_ms("retrieval_total_ms", duration)
            record_failure(str(getattr(error, "category", "") or "retrieval_failed"))
            raise
        duration = elapsed_ms(retrieval_started)
        record_field(timing_field, duration)
        if timing_field != "retrieval_total_ms":
            current = current_perf()
            if current is not None:
                current.add_ms("retrieval_total_ms", duration)
        expected_labels = {
            source.source_id: source.label for source in retrieval_sources
        }
        for chunk in retrieval_result.chunks:
            if expected_labels.get(chunk.source_id) != chunk.label:
                record_failure("retrieval_failed")
                raise ValueError(
                    "Retriever returned a source outside the selected notebook scope"
                )
        course_status = str(retrieval_result.course_retrieval_status or "ok")
        retrieval_result = bounded_retrieval_result(
            retrieval_result.chunks,
            max_context_chars=int(runtime_settings.fast_chat_retrieval_max_chars),
            max_chunks=int(runtime_settings.fast_chat_retrieval_max_chunks),
        )
        if course_status in {"unavailable", "empty"}:
            retrieval_result = with_course_evidence_gap(
                retrieval_result, status=course_status
            )
        retrieved_chunks: list[RetrievalChunkReference] = []
        for chunk in retrieval_result.chunks:
            excerpt = focused_excerpt(
                chunk.text,
                student_message,
                limit=600,
            )
            retrieved_chunks.append(
                RetrievalChunkReference(
                    source_id=chunk.source_id,
                    label=chunk.label,
                    title=chunk.title,
                    chunk_id=chunk.chunk_id,
                    excerpt=excerpt,
                    score=chunk.score,
                    retrieval_origin=str(chunk.retrieval_origin or ""),
                )
            )
        return retrieved_chunks, retrieval_result.context

    def _hydrate_retrieval_sources(self, snapshot: TurnSnapshot) -> TurnSnapshot:
        """Load selected student chunk artifacts once for this request.

        Idle first passes skip this so selected files do not pay ``get_bytes``.
        RAG fallback calls it when the first pass left ``retrieval_sources``
        empty. Cache and storage I/O happen only here; this method does not
        authorize sources.

        Args:
            snapshot: Authoritative notebook snapshot after source
                authorization.

        Returns:
            The same snapshot when retrieval sources are already attached,
            otherwise a copy with hydrated selected student sources.
        """
        if snapshot.retrieval_sources:
            return snapshot
        return replace(
            snapshot,
            retrieval_sources=hydrate_selected_retrieval_sources(
                snapshot.selected_sources,
                owner_id=self._store.owner_id,
                notebook_id=snapshot.thread_id,
            ),
        )

    def _maybe_rag_fallback(
        self,
        request: CoachRequest,
        turn: CoachTurn,
        snapshot: TurnSnapshot,
    ) -> tuple[CoachRequest, CoachTurn]:
        """Retry once with application RAG when Haiku reports missing evidence.

        The first model result is not persisted. The retry stays inside the
        same notebook execution lease and idempotency claim. A second
        ``needs_source_retrieval`` flag cannot trigger another retrieve.
        Hydrated retrieval sources come from the request-scoped snapshot
        when the first pass already retrieved. Idle first passes skip
        hydration, so this retry hydrates selected student sources once.
        """
        record_field("rag_fallback_used", False)
        record_field("rag_fallback_model_calls", 1)
        if str(request.specialist or "").strip().lower() == "review":
            return request, turn
        if request.retrieval_required:
            return request, turn
        if request.retrieved_chunks:
            return request, turn
        if not request.source_ids:
            return request, turn
        if not self._workflow.peek_needs_source_retrieval(request.thread_id):
            return request, turn
        snapshot = self._hydrate_retrieval_sources(snapshot)
        retrieval_sources = snapshot.retrieval_sources
        if not retrieval_sources:
            return request, turn
        record_field("rag_fallback_used", True)
        emit_coach_progress(PROGRESS_RETRIEVING)
        chunks, context = self._retrieve_for_turn(
            student_message=request.student_message,
            current_stage=request.current_stage,
            retrieval_sources=retrieval_sources,
            project_context=request.student_project_context,
            conversation_summary=request.conversation_summary,
            recent_messages=list(request.history),
            timing_field="rag_fallback_retrieval_ms",
        )
        retried = request.model_copy(
            update={
                "retrieved_chunks": chunks,
                "source_context": context,
                "retrieval_required": True,
            }
        )
        emit_coach_progress(PROGRESS_THINKING)
        agent_started = time.perf_counter()
        turn = self._workflow.run(retried)
        perf = current_perf()
        if perf is not None:
            perf.add_ms("agent_ms", elapsed_ms(agent_started))
        record_field("rag_fallback_model_calls", 2)
        record_field("retrieved_chunk_count", len(chunks))
        record_field("retrieved_context_chars", len(context))
        record_field("rag_used", bool(chunks))
        return retried, turn

    def _authoritative_request(
        self, request: CoachRequest, *, force_retrieval: bool = False
    ) -> CoachRequest:
        """Reload trusted coaching inputs from the notebook store.

        Returns only the prepared request so existing tests that call this
        helper keep working. Production ``submit`` uses
        :meth:`_prepare_authoritative_turn` to also keep the request-scoped
        source snapshot.

        Raises:
            ValueError: When the notebook is missing or client hints disagree
                with persisted stage, history, or selected sources.
        """
        prepared, _snapshot = self._prepare_authoritative_turn(
            request, force_retrieval=force_retrieval
        )
        return prepared

    def _prepare_authoritative_turn(
        self,
        request: CoachRequest,
        *,
        force_retrieval: bool = False,
        frozen_history_revision: int | None = None,
        frozen_stage: str | None = None,
        frozen_source_ids: list[str] | None = None,
        frozen_message_ids: list[str] | None = None,
    ) -> tuple[CoachRequest, TurnSnapshot]:
        """Reload trusted coaching inputs and the request-scoped source snapshot.

        Args:
            request: Incoming coach request. Client history/stage hints are
                checked against the store unless a frozen Deep Review snapshot
                is supplied.
            force_retrieval: When True, retrieve against selected sources.
            frozen_history_revision: Deep Review revision to reconstruct.
            frozen_stage: Thinking Path stage at Deep Review enqueue.
            frozen_source_ids: Selected source ids at Deep Review enqueue.
            frozen_message_ids: Active message ids at Deep Review enqueue.

        Raises:
            ValueError: When the notebook is missing or client hints disagree
                with persisted stage, history, or selected sources.
        """
        load_started = time.perf_counter()
        thread = self._notebooks.get_thread(request.thread_id)
        record_count("notebook_load_count")
        record_field("notebook_load_ms", elapsed_ms(load_started))
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        live_stage = current_stage(journey).id
        if frozen_stage:
            authoritative_stage = str(frozen_stage).strip() or live_stage
        else:
            authoritative_stage = live_stage
            if request.current_stage != authoritative_stage:
                raise ValueError(
                    "current_stage does not match the notebook Thinking Path stage"
                )

        def _load_history() -> list[dict[str, Any]]:
            if frozen_history_revision is not None:
                store_history = self._store.get_messages_at_revision(
                    request.thread_id, int(frozen_history_revision)
                )
                allowed_ids = {
                    str(item).strip()
                    for item in (frozen_message_ids or [])
                    if str(item).strip()
                }
                if allowed_ids:
                    store_history = [
                        message
                        for message in store_history
                        if str(message.get("id") or "") in allowed_ids
                    ]
                return store_history
            store_history = self._store.get_messages(request.thread_id)
            revise_message_id = str(request.revise_user_message_id or "").strip()
            if revise_message_id:
                store_history = [
                    message
                    for message in store_history
                    if str(message.get("id") or "") != revise_message_id
                ]
            return store_history

        def _load_sources() -> list[dict[str, Any]]:
            visible_sources = list_visible_sources(
                self._store,
                request.thread_id,
                selected_only=False,
                include_extracted_text=False,
            )
            if frozen_source_ids is not None:
                frozen_set = {
                    str(item).strip() for item in frozen_source_ids if str(item).strip()
                }
                visible_sources = [
                    {**dict(source), "selected": str(source.get("id") or "") in frozen_set}
                    for source in visible_sources
                ]
            return visible_sources

        from concurrent.futures import ThreadPoolExecutor

        history_started = time.perf_counter()
        source_started = history_started
        with ThreadPoolExecutor(max_workers=2) as pool:
            history_future = pool.submit(_load_history)
            source_future = pool.submit(_load_sources)
            store_history = history_future.result()
            visible_sources = source_future.result()
        record_field("history_load_ms", elapsed_ms(history_started))
        record_field("source_load_ms", elapsed_ms(source_started))
        if (
            frozen_history_revision is None
            and request.history
            and _history_signature(request.history) != _history_signature(store_history)
        ):
            raise ValueError("history does not match the notebook conversation")
        snapshot = TurnSnapshot.from_authoritative_state(
            thread=thread,
            current_stage=authoritative_stage,
            visible_sources=visible_sources,
        )
        selected_sources = list(snapshot.selected_sources)
        authoritative_ids = [str(source["id"]) for source in selected_sources]
        authoritative_id_set = set(authoritative_ids)
        if frozen_source_ids is None and request.source_ids:
            unknown = [
                source_id
                for source_id in request.source_ids
                if source_id not in snapshot.sources_by_id
            ]
            if unknown:
                raise ValueError("One or more source_ids are unknown for this notebook")
            unselected = [
                source_id
                for source_id in request.source_ids
                if source_id not in authoritative_id_set
            ]
            if unselected:
                raise ValueError("One or more source_ids are not selected")
            if set(request.source_ids) != authoritative_id_set:
                raise ValueError(
                    "source_ids must match the notebook's currently selected sources"
                )

        # Metadata-only listings leave extractedText empty, so they cannot
        # reproduce the historical full-text snapshot. The server still
        # overwrites source_context with query-ranked evidence below.
        listed_has_extracted = any(
            str(source.get("extractedText") or "").strip()
            for source in selected_sources
        )
        legacy_source_context, _ = selected_source_context(selected_sources)
        if (
            request.source_context
            and listed_has_extracted
            and request.source_context.strip() != legacy_source_context
        ):
            raise ValueError("source_context does not match the selected notebook sources")
        if request.retrieved_chunks:
            raise ValueError("retrieved_chunks must be resolved server-side")
        if request.image_inputs:
            raise ValueError("image_inputs must be resolved server-side from source_ids")

        selected_image_sources = [
            source
            for source in selected_sources
            if str(source.get("kind") or "").lower() == "image"
            or str(source.get("mime") or "").lower().startswith("image/")
        ]
        if len(selected_image_sources) > 5:
            raise ValueError(
                "Select at most 5 image sources for one coaching turn"
            )
        image_inputs = [
            CoachImageInput.model_validate(item)
            for item in image_inputs_for_sources(selected_image_sources)
        ]
        selected_model = get_model(
            str(metadata.get("selected_model") or request.model_id or DEFAULT_CHAT_MODEL_ID)
        )
        selected_effort = validate_reasoning(
            selected_model,
            request.reasoning_effort
            if request.reasoning_effort is not None
            else metadata.get("reasoning_effort"),
        )
        project_context = _project_context_from_metadata(metadata)
        conversation_summary = " ".join(
            str(metadata.get("learning_summary") or "").split()
        ).strip()
        gate_started = time.perf_counter()
        mode_policy = resolve_mode_policy(
            request.student_message,
            selected_source_titles=[
                str(source.get("title") or "") for source in selected_sources
            ],
            selected_source_filenames=[
                str(source.get("filename") or source.get("name") or "")
                for source in selected_sources
            ],
            has_selected_sources=bool(selected_sources),
        )
        needs_retrieval = bool(mode_policy.retrieve)
        if force_retrieval and selected_sources:
            needs_retrieval = True
        record_field("retrieval_gate_ms", elapsed_ms(gate_started))
        record_field("retrieval_required", bool(needs_retrieval))
        record_field("mode_policy_intent", mode_policy.intent)
        retrieved_chunks: list[RetrievalChunkReference] = []
        retrieval_result_context = ""
        if needs_retrieval:
            snapshot = self._hydrate_retrieval_sources(snapshot)
        retrieval_sources = snapshot.retrieval_sources
        if needs_retrieval and retrieval_sources:
            emit_coach_progress(PROGRESS_RETRIEVING)
            retrieved_chunks, retrieval_result_context = self._retrieve_for_turn(
                student_message=request.student_message,
                current_stage=authoritative_stage,
                retrieval_sources=retrieval_sources,
                project_context=project_context,
                conversation_summary=conversation_summary,
                recent_messages=store_history,
            )
        else:
            record_field("retrieval_total_ms", 0)
            record_field("course_kb_retrieval_ms", 0)
            record_field("student_source_retrieval_ms", 0)
        record_field("retrieved_chunk_count", len(retrieved_chunks))
        record_field("retrieved_context_chars", len(retrieval_result_context))
        record_field("rag_used", bool(retrieved_chunks))
        response_language = " ".join(
            str(metadata.get("response_language") or "English").split()
        )[:50]
        # The selected-source set is server-authoritative. It is the only
        # grounding switch exposed by the current UI, so stale compatibility
        # metadata must not leave a source-free notebook in source-only mode.
        # Conversely, a client cannot enable broader knowledge while any
        # selected source exists.
        allow_model_knowledge = not authoritative_ids
        if frozen_history_revision is not None:
            conversation_revision = max(0, int(frozen_history_revision))
        else:
            conversation_revision = int(
                metadata.get("conversation_revision")
                if metadata.get("conversation_revision") is not None
                else thread.get("conversation_revision")
                or 0
            )
        memory_started = time.perf_counter()
        conversation_memory = memory_from_metadata(
            metadata, conversation_revision=conversation_revision
        )
        record_field("memory_load_ms", elapsed_ms(memory_started))
        prepared = request.model_copy(
            update={
                "current_stage": authoritative_stage,
                "history": store_history,
                "source_ids": authoritative_ids,
                "source_context": retrieval_result_context,
                "student_project_context": project_context,
                "conversation_summary": conversation_summary,
                "conversation_memory": (
                    None
                    if conversation_memory is None
                    else conversation_memory.model_dump(mode="json")
                ),
                "retrieved_chunks": retrieved_chunks,
                "image_inputs": image_inputs,
                "model_id": selected_model.id,
                "reasoning_effort": selected_effort,
                "response_language": response_language or "English",
                "response_detail": journey["response_detail"],
                "allow_model_knowledge": allow_model_knowledge,
                "conversation_revision": conversation_revision,
                "student_id": str(getattr(self._store, "identifier", "") or "").strip()
                or None,
                # Drop client specialist and mode-policy hints. Mock uses
                # regex fallback; AgentCore uses one-call fast_chat unless a
                # server-owned specialist is stamped after this method.
                "specialist": None,
                "retrieval_required": bool(needs_retrieval),
                "expected_response_mode": mode_policy.expected_mode,
                "mode_policy_intent": mode_policy.intent,
                COUNTER_SETTINGS_KEY: parse_coaching_turns_since_deep_review(
                    metadata.get(COUNTER_SETTINGS_KEY)
                ),
                "deep_review_interval_turns": bound_deep_review_interval(
                    runtime_settings.deep_review_interval_turns
                ),
                "review_id": (
                    request.review_id if frozen_history_revision is not None else None
                ),
            }
        )
        return prepared, snapshot

    def _server_owned_deep_review_request(self, request: CoachRequest) -> CoachRequest:
        """Stamp ``specialist=review`` after client-controlled fields were dropped.

        Args:
            request: Output of :meth:`_authoritative_request` with ``specialist``
                already cleared.

        Returns:
            The same request with a server-owned Deep Review specialist.
        """
        return request.model_copy(update={"specialist": "review"})

    def revise_and_resubmit(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        idempotency_key: str,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        response_detail: str | None = None,
        response_language: str | None = None,
    ) -> CoachTurn:
        """Append-only revise a user turn, then generate a replacement coach reply.

        Before any revision mutation, recovers either a completed idempotency
        marker or a committed recorded coach turn for ``idempotency_key``. That
        keeps a retry after persist-before-complete from superseding another
        branch or bumping ``conversation_revision`` again.

        The notebook/user/global execution lease is acquired before any
        conversation mutation so an overlapping send cannot leave a revised
        transcript after a 429. ``submit`` is then invoked with that lease
        already held so the provider path is not double-acquired.

        The revision transaction commits before the provider call. If the
        provider fails afterward, the append-only supersede remains. Clients
        must retry with the **same** idempotency key so durable-turn recovery
        and ``try_resume_revision_result`` can resume without bumping
        ``conversation_revision`` again.
        """
        cleaned_key = str(idempotency_key or "").strip()
        if not cleaned_key:
            raise ValueError("idempotency_key is required for revise-and-resubmit")
        cached = self._recover_durable_coach_turn(thread_id, cleaned_key)
        if cached is not None:
            return cached
        from backend.rate_limit import get_coach_rate_limiter

        with get_coach_rate_limiter().limit(
            self._rate_limit_user_key(),
            str(thread_id or "").strip(),
        ):
            cached = self._recover_durable_coach_turn(thread_id, cleaned_key)
            if cached is not None:
                return cached
            thread = self._notebooks.get_thread(thread_id)
            if not thread:
                raise ValueError("Notebook not found")
            metadata = dict(thread.get("metadata") or {})
            detail = (
                response_detail
                if response_detail in {"short", "long"}
                else str(
                    (metadata.get("learning_journey") or {}).get("response_detail")
                    or metadata.get("response_detail")
                    or DEFAULT_RESPONSE_DETAIL
                )
            )
            if detail not in {"short", "long"}:
                detail = DEFAULT_RESPONSE_DETAIL
            resumed = None
            resume_fn = getattr(self._store, "try_resume_revision_result", None)
            if callable(resume_fn):
                resumed = resume_fn(thread_id, message_id, content)
            if resumed is not None:
                revision = resumed
            else:
                revision = self._store.revise_conversation_from_user_message(
                    thread_id,
                    message_id,
                    content,
                    model_id=model_id or str(metadata.get("selected_model") or ""),
                    metadata={
                        "response_detail": detail,
                        **(
                            {"response_language": response_language}
                            if response_language
                            else {}
                        ),
                    },
                )
            # Store returns the replacement user row id as edited_message_id.
            replacement_user_message_id = str(revision.edited_message_id)
            request = CoachRequest(
                thread_id=thread_id,
                student_message=content.strip(),
                current_stage=revision.current_stage,
                response_detail=detail,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                response_language=response_language or "English",
                idempotency_key=cleaned_key,
                conversation_revision=revision.conversation_revision,
                revise_user_message_id=replacement_user_message_id,
            )
            return self.submit(request, execution_lease_held=True)

    def _selected_citation_catalog(
        self,
        request: CoachRequest,
        sources_by_id: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, CitationReference]:
        """Map ``S#`` labels to selected notebook sources for citation resolution.

        Labels use the position in the full selected ``source_ids`` list, matching
        retrieval/context-planner numbering. Metadata is resolved only for
        sources that contributed a retrieved chunk, using the request-scoped
        visible-source map rather than per-id store/catalog lookups.
        """
        catalog: dict[str, CitationReference] = {}
        retrieved_by_source: dict[str, RetrievalChunkReference] = {}
        for chunk in request.retrieved_chunks:
            # Retrieval order is relevance order; keep the strongest excerpt
            # for the student-visible citation preview.
            retrieved_by_source.setdefault(chunk.source_id, chunk)
        resolved = 0
        for index, source_id in enumerate(request.source_ids, start=1):
            retrieved = retrieved_by_source.get(source_id)
            if retrieved is None:
                continue
            resolved += 1
            source = sources_by_id.get(source_id)
            if not source:
                continue
            catalog[f"S{index}"] = CitationReference(
                source_id=source_id,
                label=f"S{index}",
                title=str(source.get("title") or "Untitled source"),
                excerpt=focused_excerpt(
                    retrieved.excerpt,
                    request.student_message,
                    limit=240,
                ),
            )
        record_field("citation_source_resolution_count", resolved)
        return catalog

    def _relevant_citations(
        self,
        request: CoachRequest,
        turn: CoachTurn,
        snapshot: TurnSnapshot,
    ) -> list[CitationReference]:
        """Keep only citations the coach actually cited or focused in this reply.

        Selected sources alone do not create a Sources-used footer. Citations come
        from the assessment payload and from explicit ``[S#]`` markers in the reply.
        """
        catalog = self._selected_citation_catalog(request, snapshot.sources_by_id)
        if not catalog:
            return []
        by_source_id = {item.source_id: item for item in catalog.values()}
        ordered: list[CitationReference] = []
        seen: set[str] = set()

        def add(citation: CitationReference) -> None:
            if citation.source_id in seen:
                return
            seen.add(citation.source_id)
            ordered.append(citation)

        for citation in turn.assessment.citations:
            resolved = by_source_id.get(citation.source_id) or catalog.get(citation.label)
            if resolved:
                add(resolved)
        for label in _CITATION_LABEL.findall(turn.response_text or ""):
            resolved = catalog.get(label)
            if resolved:
                add(resolved)
        return ordered
