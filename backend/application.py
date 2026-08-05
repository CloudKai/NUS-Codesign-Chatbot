"""Application services that coordinate notebooks, workflows, and persistence."""

from __future__ import annotations

import re
from typing import Any

from .domain import CitationReference, CoachImageInput, CoachRequest, CoachTurn
from .learning_service import LearningProgressService
from .repositories import NotebookRepository
from .source_library import image_inputs_for_source_ids, selected_source_context
from .student_journey import (
    advanced_stage_response,
    current_stage,
    normalize_journey,
    personalized_stage_questions,
)
from .student_store import StudentStore
from .title_service import NotebookTitleService
from .workflow import CoachWorkflow

_CITATION_LABEL = re.compile(r"\[(S\d+)\]")


def _history_signature(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return a comparable role/content signature for canonical chat history."""
    signature: list[tuple[str, str]] = []
    for message in messages:
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        signature.append((str(message.get("role") or "").strip().lower(), content))
    return signature


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
    ) -> None:
        self._store = store
        self._notebooks = notebooks
        self._workflow = workflow
        self._progress = progress
        self._auto_advance_stages = auto_advance_stages

    def submit(self, request: CoachRequest) -> CoachTurn:
        """Run and persist one turn, optionally applying its recommendation.

        Persisted notebook state is authoritative for stage, history, selected
        sources, source context, and image inputs. Client-supplied values that
        disagree are rejected. The workflow always writes an auditable
        transition first; automatic mode resolves it before the visible reply.
        """
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
        transition_id = turn.pending_transition.id if turn.pending_transition else None
        if (
            self._auto_advance_stages
            and self._progress is not None
            and turn.pending_transition is not None
        ):
            next_stage_id = turn.pending_transition.to_stage
            self._progress.resolve(
                prepared_request.thread_id,
                turn.pending_transition.id,
                accepted=True,
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
        user_id = self._store.add_message(
            prepared_request.thread_id,
            "user",
            prepared_request.student_message,
            metadata={
                "thinking_stage": prepared_request.current_stage,
                "source_ids": prepared_request.source_ids,
                "workflow": "langgraph",
            },
        )
        self._store.add_message(
            prepared_request.thread_id,
            "assistant",
            turn.response_text,
            metadata={
                "thinking_stage": turn.auto_advanced_to or prepared_request.current_stage,
                "assessment": turn.assessment.model_dump(mode="json"),
                "pending_transition_id": transition_id,
                "auto_advanced_to": turn.auto_advanced_to,
                "workflow": "langgraph",
                "source_ids": prepared_request.source_ids,
                "source_refs": [
                    {
                        "id": citation.source_id,
                        "label": citation.label,
                        "title": citation.title,
                    }
                    for citation in turn.assessment.citations
                ],
            },
        )
        self._store.update_thread(
            prepared_request.thread_id,
            metadata={
                "learning_summary": turn.assessment.learning_summary,
                "working_conclusion": turn.assessment.working_conclusion,
                "understanding_change": turn.assessment.understanding_change,
                "critical_understanding": turn.assessment.critical_understanding_level,
                "last_workflow_user_message_id": user_id,
            },
        )
        if should_generate_title:
            self._store.update_thread(
                prepared_request.thread_id,
                name=NotebookTitleService.generate(turn.assessment.contribution_summary),
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
        if request.current_stage != authoritative_stage:
            raise ValueError(
                "current_stage does not match the notebook Thinking Path stage"
            )

        store_history = self._store.get_messages(request.thread_id)
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

        source_context, _ = selected_source_context(selected_sources)
        if request.source_context and request.source_context.strip() != source_context:
            raise ValueError("source_context does not match the selected notebook sources")
        if request.image_inputs:
            raise ValueError("image_inputs must be resolved server-side from source_ids")

        image_inputs = [
            CoachImageInput.model_validate(item)
            for item in image_inputs_for_source_ids(
                self._store,
                request.thread_id,
                authoritative_ids,
            )
        ]
        return request.model_copy(
            update={
                "current_stage": authoritative_stage,
                "history": store_history,
                "source_ids": authoritative_ids,
                "source_context": source_context,
                "image_inputs": image_inputs,
            }
        )

    def _selected_citation_catalog(
        self, request: CoachRequest
    ) -> dict[str, CitationReference]:
        """Map ``S#`` labels to selected notebook sources for citation resolution."""
        catalog: dict[str, CitationReference] = {}
        for index, source_id in enumerate(request.source_ids, start=1):
            source = self._store.get_source(request.thread_id, source_id)
            if not source:
                continue
            excerpt = " ".join(str(source.get("extractedText") or "").split())[:240]
            catalog[f"S{index}"] = CitationReference(
                source_id=source_id,
                label=f"S{index}",
                title=str(source.get("title") or "Untitled source"),
                excerpt=excerpt,
            )
        return catalog

    def _relevant_citations(
        self, request: CoachRequest, turn: CoachTurn
    ) -> list[CitationReference]:
        """Keep only citations the coach actually cited or focused in this reply.

        Selected sources alone do not create a Sources-used footer. Citations come
        from the assessment payload and from explicit ``[S#]`` markers in the reply.
        """
        catalog = self._selected_citation_catalog(request)
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
