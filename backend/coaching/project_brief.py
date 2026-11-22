"""Whole-chat project brief generation and revision-bound reuse, without educational side effects."""
from __future__ import annotations

import hashlib
import json
from threading import Lock
from typing import Any, Protocol

from pydantic import ValidationError

from backend.domain import CoachRequest, ProjectBrief, ProjectBriefResult, ProviderAssessmentResult
from backend.generation_admission import GenerationAdmission
from backend.providers import ProviderUnavailableError
from backend.rate_limit import get_coach_rate_limiter
from backend.usage import usage_operation, assessed
from backend.prompts.project_brief import PROJECT_BRIEF_TASK


class BriefRepository(Protocol):
    """Owner-scoped active transcript and metadata port used by the brief service."""

    owner_id: str

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Read the owned chat or return None."""
        ...

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Read the complete active conversation in order."""
        ...

    def update_thread(self, thread_id: str, *, metadata: dict[str, Any]) -> None:
        """Atomically merge only supplied metadata; reject a missing owned chat."""
        ...


class BriefModel(Protocol):
    """Existing typed model adapter; review requests use its full-history policy."""

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Return validated model output, including a project brief when requested."""
        ...


def _messages(store: BriefRepository, thread_id: str) -> list[dict[str, str]]:
    """Return active visible dialogue without private metadata or internal marker rows."""
    return [
        {key: str(row[key]) for key in ('id', 'role', 'content')}
        for row in store.get_messages(thread_id)
        if row.get('role') in {'user', 'assistant'} and str(row.get('content') or '').strip()
        and not (row.get('metadata') or {}).get('_internal_type')
        and not row.get('is_error')
    ]


def _fingerprint(messages: list[dict[str, str]]) -> str:
    """Bind a cached brief to every active message's identity, role, content and order."""
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ProjectBriefService:
    """Generate a grounded brief once per unchanged chat, independently of stage decisions."""

    def __init__(self, store: BriefRepository, model: BriefModel, admission: GenerationAdmission | None) -> None:
        """Inject owner-scoped storage, the configured model and shared generation allowance."""
        self._store, self._model, self._admission = store, model, admission
        self._lock = Lock()

    def read(self, thread_id: str) -> ProjectBriefResult:
        """Read a valid whole-chat cache without invoking a model; reject unowned chats."""
        thread = self._store.get_thread(thread_id)
        if thread is None:
            raise ValueError('Chat not found')
        messages = _messages(self._store, thread_id)
        version = _fingerprint(messages)
        if not any(row['role'] == 'user' for row in messages):
            return ProjectBriefResult(status='empty', version=version)
        cached = (thread.get('metadata') or {}).get('project_brief_v1')
        if isinstance(cached, dict) and cached.get('fingerprint') == version:
            if cached.get('failed') is True:
                return ProjectBriefResult(status='failed', version=version)
            try:
                return ProjectBriefResult(status='current', version=version, brief=ProjectBrief.model_validate(cached['brief']))
            except (KeyError, TypeError, ValidationError):
                pass
        if getattr(self._model, 'provider_id', '') == 'mock':
            return ProjectBriefResult(status='preview', version=version)
        return ProjectBriefResult(status='missing', version=version)

    def generate(self, thread_id: str, *, retry: bool = False) -> ProjectBriefResult:
        """Summarise all active dialogue; validate student evidence and discard work if the chat changes.

        Reuse unchanged cached results. Only this optional brief metadata is written;
        transcript, stage, feedback and recommendations are untouched. Model failures
        or ungrounded claims raise ProviderUnavailableError, concurrent edits raise
        RuntimeError. Mock mode returns an explicit preview state, never fabricated facts.
        """
        with self._lock:
            saved = self.read(thread_id)
            if saved.status != 'missing' and not (saved.status == 'failed' and retry):
                return saved
            if getattr(self._model, 'provider_id', '') == 'mock':
                return ProjectBriefResult(status='preview', version=saved.version)
            messages = _messages(self._store, thread_id)
            if any(len(row['content']) > 12_000 for row in messages):
                raise ProviderUnavailableError('Whole-chat summary context limit exceeded', category='context_limit')
            fingerprint = _fingerprint(messages)
            thread = self._store.get_thread(thread_id)
            if thread is None:
                raise ValueError('Chat not found')
            request = CoachRequest(
                thread_id=thread_id, current_stage=str(thread.get('current_stage') or 'problem_identification'),
                specialist='review', response_detail='long', history=messages,
                student_message=PROJECT_BRIEF_TASK,
                student_id=self._store.owner_id,
            )
            with get_coach_rate_limiter().limit(self._store.owner_id, thread_id), usage_operation(
                'project_brief', thread_id, admission=self._admission,
            ) as usage:
                try:
                    result = assessed(self._model, request)
                    brief = result.assessment.project_brief
                    if brief is None:
                        raise ProviderUnavailableError('Project summary unavailable', category='malformed')
                    student_text = [' '.join(row['content'].split()) for row in messages if row['role'] == 'user']
                    for point in brief.model_dump().values():
                        text, quotes = point['text'], point['evidence']
                        if text is None and not quotes:
                            continue
                        if not text or not text.strip() or not quotes or any(
                            len(' '.join(quote.split())) < 8 or not any(' '.join(quote.split()) in turn for turn in student_text)
                            for quote in quotes
                        ):
                            raise ProviderUnavailableError('Project summary evidence unavailable', category='malformed')
                except (ProviderUnavailableError, ValueError):
                    if _fingerprint(_messages(self._store, thread_id)) == fingerprint:
                        self._store.update_thread(thread_id, metadata={'project_brief_v1': {
                            'fingerprint': fingerprint, 'failed': True,
                        }})
                    raise
                if _fingerprint(_messages(self._store, thread_id)) != fingerprint:
                    raise RuntimeError('Chat changed')
                self._store.update_thread(thread_id, metadata={'project_brief_v1': {
                    'fingerprint': fingerprint, 'brief': brief.model_dump(mode='json'),
                }})
                if _fingerprint(_messages(self._store, thread_id)) != fingerprint:
                    raise RuntimeError('Chat changed')
                usage.success = True
                return ProjectBriefResult(status='current', version=fingerprint, brief=brief)
