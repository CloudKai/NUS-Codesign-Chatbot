"""Durable coaching execution across workflow, retrieval, and persistence."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from backend.domain import (
    CitationReference,
    CoachImageInput,
    CoachRequest,
    CoachTurn,
    RetrievalChunkReference,
)
from backend.coaching.citations import relevant_citations, selected_citation_catalog
from backend.learning_service import LearningProgressService
from backend.models import DEFAULT_CHAT_MODEL_ID, get_model, validate_reasoning
from backend.repositories import NotebookRepository
from backend.retrieval import (
    ContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    bounded_retrieval_result,
    focused_excerpt,
    retrieval_sources_from_notebook,
)
from backend.source_library import image_inputs_for_source_ids, selected_source_context
from backend.student_journey import (
    advanced_stage_response,
    coaching_profile_for_response_detail,
    current_stage,
    normalize_journey,
    personalized_stage_questions,
)
from backend.student_store import (
    AutoAdvancePersistence,
    CoachRequestInProgressError,
    StudentStore,
)
from backend.title_service import NotebookTitleService
from backend.workflow import CoachWorkflow

def _history_signature(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return a comparable role/content signature for canonical chat history."""
    signature: list[tuple[str, str]] = []
    for message in messages:
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        signature.append((str(message.get("role") or "").strip().lower(), content))
    return signature


def _coach_request_fingerprint(request: CoachRequest) -> str:
    """Return a stable digest for idempotency comparison without storing content.

    The marker keeps only this digest, never the raw request or source/image
    payload.  All request fields except the retry key are included so reusing a
    key for a modified turn fails closed instead of returning a misleading
    earlier answer.
    """
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
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
        """Return the authenticated store owner key for coach rate limiting."""
        return str(getattr(self._store, "owner_id", "") or "").strip()

    def _execute_rate_limited(
        self,
        request: CoachRequest,
        *,
        idempotency_marker_id: str | None = None,
        idempotency_lease_token: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> CoachTurn:
        """Run one provider-backed turn under the process-local coach limiter.

        Same-key waiters and completed replays never call this helper, so they
        do not consume active/RPM slots. Only a newly claimed execution (or a
        turn without an idempotency key) is limited.
        """
        from backend.rate_limit import get_coach_rate_limiter

        with get_coach_rate_limiter().limit(self._rate_limit_user_key()):
            return self._submit_once(
                request,
                idempotency_marker_id=idempotency_marker_id,
                idempotency_lease_token=idempotency_lease_token,
                idempotency_fingerprint=idempotency_fingerprint,
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

    def submit(self, request: CoachRequest) -> CoachTurn:
        """Run and persist one turn, optionally applying its recommendation.

        Persisted notebook state is authoritative for stage, history, selected
        sources, source context, and image inputs. Client-supplied values that
        disagree are rejected. Confirmation mode writes a pending audit
        recommendation. Automatic mode commits the final confirmed audit,
        response, and next stage atomically.

        Stamps the current notebook ``conversation_revision`` onto the request
        for store CAS/stamping; normal submit does not bump that revision.
        """
        thread = self._notebooks.get_thread(request.thread_id)
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

        idempotency_key = str(request.idempotency_key or "").strip()
        if not idempotency_key:
            return self._execute_rate_limited(request)

        fingerprint = _coach_request_fingerprint(request)
        deadline = time.monotonic() + 125.0
        while True:
            reservation = self._store.claim_coach_request(
                request.thread_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
            if reservation.state == "completed":
                if not isinstance(reservation.turn_payload, dict):
                    raise ValueError("Completed coach idempotency result is invalid")
                return CoachTurn.model_validate(reservation.turn_payload)
            if reservation.state == "claimed":
                try:
                    turn = self._execute_rate_limited(
                        request,
                        idempotency_marker_id=reservation.marker_id,
                        idempotency_lease_token=reservation.lease_token,
                        idempotency_fingerprint=fingerprint,
                    )
                    self._store.complete_coach_request(
                        request.thread_id,
                        marker_id=reservation.marker_id,
                        idempotency_key=idempotency_key,
                        request_fingerprint=fingerprint,
                        lease_token=str(reservation.lease_token or ""),
                        turn_payload=turn.model_dump(mode="json"),
                    )
                    return turn
                except Exception:
                    # A provider/validation/persistence failure is deliberately
                    # not cached as a completed reply. A retry with this same
                    # key can acquire the released reservation. Rate-limit
                    # rejection also releases the lease so a later retry can
                    # execute when capacity returns.
                    self._store.fail_coach_request(
                        request.thread_id,
                        marker_id=reservation.marker_id,
                        request_fingerprint=fingerprint,
                        lease_token=str(reservation.lease_token or ""),
                    )
                    raise
            if time.monotonic() >= deadline:
                raise CoachRequestInProgressError(
                    "This coach request is still processing; retry with the same "
                    "idempotency key to recover its completed turn."
                )
            time.sleep(0.05)

    def _submit_once(
        self,
        request: CoachRequest,
        *,
        idempotency_marker_id: str | None = None,
        idempotency_lease_token: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> CoachTurn:
        """Execute the original authoritative workflow path exactly once."""
        prepared_request = self._authoritative_request(request)
        initial_thread = self._notebooks.get_thread(prepared_request.thread_id)
        if not initial_thread:
            raise ValueError("Notebook not found")
        should_generate_title = str(initial_thread.get("name") or "") in {
            "",
            "Untitled notebook",
            "New assignment chat",
        } and not any(
            message.get("role") == "user" for message in prepared_request.history
        )
        turn = self._workflow.run(prepared_request)
        citations = self._relevant_citations(prepared_request, turn)
        turn = turn.model_copy(
            update={
                "assessment": turn.assessment.model_copy(update={"citations": citations})
            }
        )
        recommended_transition = turn.pending_transition
        # Selection mode disables auto-advance even if the coach service was
        # constructed with auto_advance_stages=True.
        from backend.settings import settings as runtime_settings

        auto_advance: AutoAdvancePersistence | None = None
        if (
            self._auto_advance_stages
            and not runtime_settings.student_stage_selection
            and self._progress is not None
            and recommended_transition is not None
        ):
            next_stage_id = recommended_transition.to_stage
            journey = normalize_journey(
                dict(initial_thread.get("metadata") or {}).get("learning_journey")
            )
            if current_stage(journey).id != recommended_transition.from_stage:
                raise ValueError(
                    "The notebook stage changed; request a new recommendation"
                )
            questions = turn.assessment.guidance_questions or list(
                personalized_stage_questions(
                    next_stage_id,
                    prepared_request.student_message,
                    has_course_sources=bool(prepared_request.source_ids),
                )
            )
            turn = turn.model_copy(
                update={
                    "response_text": advanced_stage_response(
                        turn.response_text,
                        prepared_request.current_stage,
                        next_stage_id,
                        questions,
                    ),
                    "assessment": turn.assessment.model_copy(
                        update={"guidance_questions": questions}
                    ),
                    "pending_transition": None,
                    "auto_advanced_to": next_stage_id,
                }
            )
            auto_advance = AutoAdvancePersistence(
                from_stage=prepared_request.current_stage,
                to_stage=next_stage_id,
                contribution_note=turn.assessment.contribution_summary,
            )
        transition_id = recommended_transition.id if recommended_transition else None
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
            NotebookTitleService.generate(turn.assessment.contribution_summary)
            if should_generate_title
            else None
        )
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
                "assessment": turn.assessment.model_dump(mode="json"),
                "coaching_profile": coaching_profile_for_response_detail(
                    prepared_request.response_detail
                ),
                "pending_transition_id": transition_id,
                "proposed_stage": (
                    recommended_transition.to_stage
                    if recommended_transition
                    else None
                ),
                "decision_status": (
                    "confirmed"
                    if auto_advance is not None
                    else ("pending" if recommended_transition else None)
                ),
                "from_stage": (
                    recommended_transition.from_stage
                    if recommended_transition
                    else None
                ),
                **(
                    {"auto_advanced_to": auto_advance.to_stage}
                    if auto_advance is not None
                    else {}
                ),
                "workflow": "langgraph",
                "source_ids": prepared_request.source_ids,
                "retrieval_refs": retrieval_refs,
                "source_refs": source_refs,
                **(
                    {"coach_idempotency_key": prepared_request.idempotency_key}
                    if prepared_request.idempotency_key
                    else {}
                ),
            },
            summary_metadata={
                "learning_summary": turn.assessment.learning_summary,
                "working_conclusion": turn.assessment.working_conclusion,
                "understanding_change": turn.assessment.understanding_change,
                "critical_understanding": turn.assessment.critical_understanding_level,
            },
            generated_title=generated_title,
            existing_user_message_id=prepared_request.revise_user_message_id,
            idempotency_marker_id=idempotency_marker_id,
            idempotency_key=prepared_request.idempotency_key,
            idempotency_lease_token=idempotency_lease_token,
            idempotency_fingerprint=idempotency_fingerprint,
            auto_advance=auto_advance,
        )
        return turn

    def _authoritative_request(self, request: CoachRequest) -> CoachRequest:
        """Reload trusted coaching inputs from the notebook store.

        Raises:
            ValueError: When the notebook is missing or client hints disagree
                with persisted stage, history, or selected sources.
        """
        thread = self._notebooks.get_thread(request.thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        authoritative_stage = current_stage(journey).id
        authoritative_detail = journey["response_detail"]
        if request.current_stage != authoritative_stage:
            raise ValueError(
                "current_stage does not match the notebook Thinking Path stage"
            )

        store_history = self._store.get_messages(request.thread_id)
        # Append-only revise persists the replacement user row before the
        # provider runs. Exclude that id so history is prefix-only; the revised
        # student_message remains the active turn input to the provider.
        revise_message_id = str(request.revise_user_message_id or "").strip()
        if revise_message_id:
            store_history = [
                message
                for message in store_history
                if str(message.get("id") or "") != revise_message_id
            ]
        if request.history and _history_signature(request.history) != _history_signature(
            store_history
        ):
            raise ValueError("history does not match the notebook conversation")

        selected_sources = self._store.list_sources(
            request.thread_id, selected_only=True
        )
        authoritative_ids = [str(source["id"]) for source in selected_sources]
        authoritative_id_set = set(authoritative_ids)
        if request.source_ids:
            unknown = [
                source_id
                for source_id in request.source_ids
                if not self._store.get_source(request.thread_id, source_id)
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

        # Preserve compatibility with older clients that sent the full selected-
        # source snapshot only as an integrity hint. The query-aware context used
        # by the provider is always generated server-side below.
        legacy_source_context, _ = selected_source_context(selected_sources)
        if (
            request.source_context
            and request.source_context.strip() != legacy_source_context
        ):
            raise ValueError("source_context does not match the selected notebook sources")
        if request.retrieved_chunks:
            raise ValueError("retrieved_chunks must be resolved server-side")
        if request.image_inputs:
            raise ValueError("image_inputs must be resolved server-side from source_ids")

        selected_image_ids = [
            str(source["id"])
            for source in selected_sources
            if str(source.get("kind") or "").lower() == "image"
            or str(source.get("mime") or "").lower().startswith("image/")
        ]
        if len(selected_image_ids) > 5:
            raise ValueError(
                "Select at most 5 image sources for one coaching turn"
            )
        image_inputs = [
            CoachImageInput.model_validate(item)
            for item in image_inputs_for_source_ids(
                self._store,
                request.thread_id,
                selected_image_ids,
            )
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
        retrieval_sources = retrieval_sources_from_notebook(selected_sources)
        retrieval_result = self._retriever.retrieve(
            RetrievalQuery(
                current_message=request.student_message,
                current_stage=authoritative_stage,
                sources=retrieval_sources,
                project_context=project_context,
                conversation_summary=conversation_summary,
                recent_messages=tuple(store_history),
            )
        )
        expected_labels = {
            source.source_id: source.label for source in retrieval_sources
        }
        retrieved_chunks: list[RetrievalChunkReference] = []
        for chunk in retrieval_result.chunks:
            if expected_labels.get(chunk.source_id) != chunk.label:
                raise ValueError(
                    "Retriever returned a source outside the selected notebook scope"
                )
        # Rebuild context solely from the validated chunks. Do not trust an
        # adapter-provided opaque context string, even from future Bedrock code.
        retrieval_result = bounded_retrieval_result(retrieval_result.chunks)
        for chunk in retrieval_result.chunks:
            excerpt = focused_excerpt(
                chunk.text,
                request.student_message,
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
                )
            )
        # The selected-source set is server-authoritative. It is the only
        # grounding switch exposed by the current UI, so stale compatibility
        # metadata must not leave a source-free notebook in source-only mode.
        # Conversely, a client cannot enable broader knowledge while any
        # selected source exists.
        allow_model_knowledge = not authoritative_ids
        conversation_revision = int(
            metadata.get("conversation_revision")
            if metadata.get("conversation_revision") is not None
            else thread.get("conversation_revision")
            or 0
        )
        return request.model_copy(
            update={
                "current_stage": authoritative_stage,
                "response_detail": authoritative_detail,
                "history": store_history,
                "source_ids": authoritative_ids,
                "source_context": retrieval_result.context,
                "student_project_context": project_context,
                "conversation_summary": conversation_summary,
                "retrieved_chunks": retrieved_chunks,
                "image_inputs": image_inputs,
                "model_id": selected_model.id,
                "reasoning_effort": selected_effort,
                "response_language": "English",
                "allow_model_knowledge": allow_model_knowledge,
                "conversation_revision": conversation_revision,
            }
        )

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
                or "short"
            )
        )
        if detail not in {"short", "long"}:
            detail = "short"
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
                    "response_language": "English",
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
            response_language="English",
            idempotency_key=cleaned_key,
            conversation_revision=revision.conversation_revision,
            revise_user_message_id=replacement_user_message_id,
        )
        return self.submit(request)

    def _selected_citation_catalog(
        self, request: CoachRequest
    ) -> dict[str, CitationReference]:
        """Map ``S#`` labels to selected notebook sources for citation resolution."""
        return selected_citation_catalog(
            request,
            get_source=self._store.get_source,
            excerpt=focused_excerpt,
        )

    def _relevant_citations(
        self, request: CoachRequest, turn: CoachTurn
    ) -> list[CitationReference]:
        """Keep only citations the coach actually cited or focused in this reply.

        Selected sources alone do not create a Sources-used footer. Citations come
        from the assessment payload and from explicit ``[S#]`` markers in the reply.
        """
        return relevant_citations(
            request,
            turn,
            catalog=self._selected_citation_catalog(request),
        )
