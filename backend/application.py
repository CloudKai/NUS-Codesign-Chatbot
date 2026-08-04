"""Application services that coordinate notebooks, workflows, and persistence."""

from __future__ import annotations

from .domain import CitationReference, CoachImageInput, CoachRequest, CoachTurn
from .learning_service import LearningProgressService
from .repositories import NotebookRepository
from .source_library import image_inputs_for_source_ids
from .student_journey import advanced_stage_response, personalized_stage_questions
from .student_store import StudentStore
from .title_service import NotebookTitleService
from .workflow import CoachWorkflow


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

        Always resolves selected image sources server-side from ``source_ids``
        (ignoring any client-supplied image payloads) so storage can later move
        to object storage without changing the Streamlit contract.

        The workflow always writes an auditable transition first. When automatic
        progression is enabled, the application resolves that transition before
        persisting the visible response. Otherwise it remains pending for the
        confirmation UI.
        """
        initial_thread = self._notebooks.get_thread(request.thread_id)
        if not initial_thread:
            raise ValueError("Notebook not found")
        should_generate_title = (
            str(initial_thread.get("name") or "") in {"", "Untitled notebook", "New assignment chat"}
            and not any(message.get("role") == "user" for message in request.history)
        )
        history = request.history or self._store.get_messages(request.thread_id)
        image_inputs = [
            CoachImageInput.model_validate(item)
            for item in image_inputs_for_source_ids(
                self._store,
                request.thread_id,
                request.source_ids,
            )
        ]
        prepared_request = request.model_copy(
            update={
                "history": history,
                # Always resolve images server-side from selected source IDs.
                "image_inputs": image_inputs,
            }
        )
        turn = self._workflow.run(prepared_request)
        citations = self._source_citations(prepared_request)
        if citations:
            turn = turn.model_copy(
                update={
                    "assessment": turn.assessment.model_copy(
                        update={"citations": citations}
                    )
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
                request.thread_id,
                turn.pending_transition.id,
                accepted=True,
            )
            questions = turn.assessment.guidance_questions or list(
                personalized_stage_questions(
                    next_stage_id,
                    request.student_message,
                    has_course_sources=bool(request.source_ids),
                )
            )
            turn = turn.model_copy(
                update={
                    "response_text": advanced_stage_response(
                        turn.response_text,
                        request.current_stage,
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
            request.thread_id,
            "user",
            request.student_message,
            metadata={
                "thinking_stage": request.current_stage,
                "source_ids": request.source_ids,
                "workflow": "langgraph",
            },
        )
        self._store.add_message(
            request.thread_id,
            "assistant",
            turn.response_text,
            metadata={
                "thinking_stage": turn.auto_advanced_to or request.current_stage,
                "assessment": turn.assessment.model_dump(mode="json"),
                "pending_transition_id": transition_id,
                "auto_advanced_to": turn.auto_advanced_to,
                "workflow": "langgraph",
                "source_ids": request.source_ids,
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
            request.thread_id,
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
                request.thread_id,
                name=NotebookTitleService.generate(turn.assessment.contribution_summary),
            )
        return turn

    def _source_citations(self, request: CoachRequest) -> list[CitationReference]:
        """Resolve only selected, persisted source IDs into stable citations."""
        citations: list[CitationReference] = []
        for index, source_id in enumerate(request.source_ids, start=1):
            source = self._store.get_source(request.thread_id, source_id)
            if not source:
                continue
            excerpt = " ".join(str(source.get("extractedText") or "").split())[:240]
            citations.append(
                CitationReference(
                    source_id=source_id,
                    label=f"S{index}",
                    title=str(source.get("title") or "Untitled source"),
                    excerpt=excerpt,
                )
            )
        return citations
