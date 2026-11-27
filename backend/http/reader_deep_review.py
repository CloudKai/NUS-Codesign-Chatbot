"""Student-facing Deep Review status and controls over the durable coach service."""

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import DeepReviewJob, DeepReviewJobStatus
from backend.http.reader_workspace import ReaderError
from backend.owner_context import OwnerServices
from backend.persistence.store.contracts import ConversationRevisionConflictError


class ReaderReviewJob(BaseModel):
    """Saved Deep Review information needed by the student workspace."""

    review_id: str
    status: DeepReviewJobStatus
    reviewed_revision: int
    conversation_revision: int | None
    summary: str | None


class ReaderDeepReview(BaseModel):
    """Owner-bound Deep Review eligibility and the latest durable job, if any."""

    owner_id: str
    thread_id: str
    eligible: bool
    job: ReaderReviewJob | None


class ReaderDeepReviewCancel(BaseModel):
    """Cancel only the review job shown to the student at the time of the action."""

    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(min_length=1, max_length=64)


def _project(owner: OwnerServices, thread_id: str, eligible: bool,
             job: DeepReviewJob | None) -> ReaderDeepReview:
    snapshot = job.snapshot or {} if job else {}
    summary = snapshot.get("synthesis") or snapshot.get("summary")
    return ReaderDeepReview(
        owner_id=owner.user_id, thread_id=thread_id, eligible=eligible,
        job=ReaderReviewJob(
            review_id=job.review_id, status=job.status, reviewed_revision=job.reviewed_revision,
            conversation_revision=job.conversation_revision,
            summary=summary if isinstance(summary, str) else None,
        ) if job else None,
    )


def register_reader_deep_review(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
) -> None:
    """Register the exact student status, start and cancel operations."""
    base = "/api/v1/reader/threads/{thread_id}/deep-review"
    errors = {401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}}

    def eligibility(owner: OwnerServices, thread_id: str) -> bool:
        try:
            return owner.workspace.deep_review_available(thread_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Notebook not found") from error

    @app.get(base, operation_id="readerDeepReview", response_model=ReaderDeepReview, responses=errors)
    def read(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderDeepReview:
        """Recover and show the latest Deep Review job for this owned chat."""
        eligible = eligibility(owner, thread_id)
        return _project(owner, thread_id, eligible, owner.coach.get_deep_review_job(thread_id))

    @app.post(base, operation_id="readerDeepReviewStart", response_model=ReaderDeepReview,
              responses={**errors, 400: {"model": ReaderError}, 409: {"model": ReaderError}})
    def start(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderDeepReview:
        """Explicitly enqueue a review under the normal server gate and generation allowance."""
        eligible = eligibility(owner, thread_id)
        if not eligible:
            raise HTTPException(status_code=400, detail="Finish the Thinking Path to start Deep Review")
        try:
            job = owner.coach.enqueue_deep_review(thread_id)
        except ConversationRevisionConflictError as error:
            raise HTTPException(status_code=409, detail="Refresh the saved review and try again") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Deep Review is not currently available") from error
        return _project(owner, thread_id, eligible, job)

    @app.post(f"{base}/cancel", operation_id="readerDeepReviewCancel", response_model=ReaderDeepReview,
              responses={**errors, 409: {"model": ReaderError}})
    def cancel(thread_id: str, payload: ReaderDeepReviewCancel,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderDeepReview:
        """Request cancellation without affecting a replacement review job."""
        eligible = eligibility(owner, thread_id)
        try:
            job = owner.coach.cancel_deep_review(thread_id, expected_review_id=payload.review_id)
        except ConversationRevisionConflictError as error:
            raise HTTPException(status_code=409, detail="The review changed. Check its current status") from error
        if job is None:
            raise HTTPException(status_code=404, detail="Deep Review job not found")
        if job.review_id != payload.review_id:
            raise HTTPException(status_code=409, detail="The review changed. Check its current status")
        return _project(owner, thread_id, eligible, job)
