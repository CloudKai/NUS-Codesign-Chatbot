"""Hybrid deterministic Q&A/coaching mode policy. No live model calls.

Table-driven classification uses paraphrases, not only canonical strings.
Behavioural tests go through ``CoachApplicationService`` with an injected
fake AgentCore runtime and assert exactly one ``phase=fast_chat`` invoke.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.coaching.mode_policy import (
    RUNTIME_HINT_COACHING,
    RUNTIME_HINT_QA,
    ModePolicy,
    enforce_model_mode,
    looks_like_project_reasoning,
    resolve_mode_policy,
    runtime_mode_hint,
)
from backend.domain import CoachRequest, EducationalAssessment, StageDecision
from backend.learning_service import LearningProgressService
from backend.prompts.composer import PromptComposer, PromptContext
from backend.providers import ProviderUnavailableError
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval_gate import (
    INTENT_AMBIGUOUS,
    INTENT_HIGH_CONFIDENCE_PERSONAL,
    INTENT_HIGH_CONFIDENCE_SOURCE,
)
from backend.specialists.review_orchestration import COUNTER_SETTINGS_KEY
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)

QA_LEANING: tuple[tuple[str, str], ...] = (
    ("what is in week 1 lecture?", "week + lecture question"),
    ("tell me about week 2", "bare week N"),
    ("summarise S1", "bare source label"),
    ("what does S1 say?", "what does S# say"),
    ("what did the course say about analogy?", "course said"),
    ("explain JTBD from lecture 2", "concept from lecture N"),
    ("according to the uploaded slides...", "according to slides"),
    ("what does this source mean?", "this source"),
    ("where in the readings is the bit about interviews", "readings + interviews noun"),
    ("what is the definition of a job story", "definition without lecture cue"),
)

COACHING_LEANING: tuple[tuple[str, str], ...] = (
    ("I think my target user is...", "I think + target user"),
    ("my problem statement is...", "my problem statement"),
    ("should I choose option A or B for my project?", "should I choose"),
    ("I interviewed three students and...", "I interviewed"),
    ("help me think through this trade-off", "help me think"),
)

ADVERSARIAL_MIXED: tuple[tuple[str, str], ...] = (
    (
        "I think my target user is first-year students who skip lecture "
        "because week 2 felt too abstract.",
        "project reasoning that mentions lecture and week 2",
    ),
    (
        "I interviewed three students after week 2 and I want to focus my "
        "problem on why they skip the lecture.",
        "interview evidence that mentions week 2 and lecture",
    ),
)


def _policy(message: str) -> ModePolicy:
    """Classify one message with no selected-source metadata."""
    return resolve_mode_policy(message)


def _qa_payload(*, text: str = "Week 1 covers stakeholder mapping [S1].") -> dict[str, Any]:
    """Return a lightweight fast-chat Q&A body."""
    return {
        "mode": "qa",
        "response_text": text,
        "citations": [],
        "needs_source_retrieval": False,
    }


def _coaching_payload(
    *,
    recommendation: str = "stay",
    text: str = "What assumption is carrying this preference?",
) -> dict[str, Any]:
    """Return a lightweight fast-chat coaching body, including ADVANCE."""
    return {
        "mode": "coaching",
        "response_text": text,
        "recommendation": recommendation,
        "recommendation_rationale": (
            "More evidence is still needed."
            if recommendation == "stay"
            else "The stage readiness bar is met."
        ),
        "citations": [],
        "needs_source_retrieval": False,
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _service(store: StudentStore, client: FakeAgentCoreRuntime) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _counter(store: StudentStore, thread_id: str) -> int:
    """Return the persisted Deep Review counter."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    try:
        return int(metadata.get(COUNTER_SETTINGS_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _submit(
    service: CoachApplicationService,
    thread_id: str,
    message: str,
    *,
    key: str,
    expected_response_mode: str | None = None,
) -> Any:
    """Submit one turn. Client mode hints must not survive prepare."""
    return service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key=key,
            expected_response_mode=expected_response_mode,
        )
    )


def _persisted_assessment(store: StudentStore, thread_id: str) -> dict[str, Any]:
    """Return the latest assistant assessment mapping."""
    assistant = [
        message
        for message in store.get_messages(thread_id)
        if message.get("role") == "assistant"
    ][-1]
    payload = (assistant.get("metadata") or {}).get("assessment") or {}
    return payload if isinstance(payload, dict) else {}


def _decoded_payload(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded_payload(call).get("phase") or "") for call in client.calls]


def _trusted_instructions(client: FakeAgentCoreRuntime) -> str:
    """Return trusted_instructions from the first fake invoke."""
    return str(_decoded_payload(client.calls[0]).get("trusted_instructions") or "")


@pytest.mark.parametrize("message,note", QA_LEANING)
def test_qa_leaning_strings_are_not_forced_coaching(message: str, note: str) -> None:
    policy = _policy(message)
    assert policy.expected_mode != "coaching", note
    if policy.expected_mode == "qa":
        assert policy.intent == INTENT_HIGH_CONFIDENCE_SOURCE, note
        assert not policy.mixed, note
    else:
        assert policy.intent == INTENT_AMBIGUOUS, note
        assert policy.expected_mode is None, note


@pytest.mark.parametrize("message,note", COACHING_LEANING)
def test_coaching_leaning_strings_are_not_forced_qa(message: str, note: str) -> None:
    policy = _policy(message)
    assert policy.expected_mode != "qa", note
    assert policy.intent in {
        INTENT_HIGH_CONFIDENCE_PERSONAL,
        INTENT_AMBIGUOUS,
    }, note
    if policy.intent == INTENT_HIGH_CONFIDENCE_PERSONAL:
        assert policy.expected_mode == "coaching", note


@pytest.mark.parametrize("message,note", ADVERSARIAL_MIXED)
def test_mixed_project_plus_lecture_is_not_force_flattened(message: str, note: str) -> None:
    policy = _policy(message)
    assert looks_like_project_reasoning(message) is True, note
    assert policy.mixed is True, note
    assert policy.intent == INTENT_AMBIGUOUS, note
    assert policy.expected_mode is None, note
    assert policy.retrieve is True, note
    assert policy.retrieval_intent == INTENT_HIGH_CONFIDENCE_SOURCE, note


THIRD_PERSON_PROJECT_WITH_SOURCE_CUE = (
    (
        "The core problem is that first-year students skip the week 2 lecture "
        "because it feels abstract.",
        "declarative problem framing that cites a week",
    ),
    (
        "Let's refine the problem of students skipping lectures in week 2.",
        "collaborative framing with no first-person pronoun",
    ),
    (
        "Option A vs option B, after looking at the slides.",
        "design option comparison that mentions slides",
    ),
    (
        "Students skip the lecture; should we focus on wait time or visibility?",
        "question shaped but deliberating between design directions",
    ),
    (
        "We interviewed five students about the week 2 lecture and they were "
        "confused.",
        "first-person plural research report mentioning a week",
    ),
    (
        "Our problem statement is that students cannot find the readings.",
        "problem statement that names course readings",
    ),
)

IMPERSONAL_COURSE_CONCEPT = (
    ("what is the definition of a job story", "explicit definition request"),
    ("explain Jobs to Be Done", "explain a course concept"),
    ("what does JTBD mean", "meaning request"),
    (
        "what is the difference between a job story and a user story",
        "comparison of two course concepts",
    ),
)


@pytest.mark.parametrize("message,note", THIRD_PERSON_PROJECT_WITH_SOURCE_CUE)
def test_third_person_project_reasoning_is_never_forced_to_qa(
    message: str, note: str
) -> None:
    """Project deliberation keeps coaching authority even when it cites a week.

    Forcing these into Q&A would strip the stay/advance recommendation and
    deny the turn Deep Review credit, which is a pedagogy regression.
    """
    policy = _policy(message)
    assert policy.expected_mode is None, note
    assert policy.intent == INTENT_AMBIGUOUS, note
    assert policy.mixed is True, note
    assert policy.retrieve is True, note


@pytest.mark.parametrize("message,note", IMPERSONAL_COURSE_CONCEPT)
def test_impersonal_course_concept_questions_expect_qa(
    message: str, note: str
) -> None:
    """Course-concept questions must not be able to advance the stage.

    Without a server expectation the model could label these coaching and
    increment the Deep Review counter or open a stage transition.
    """
    policy = _policy(message)
    assert policy.expected_mode == "qa", note
    assert policy.intent == INTENT_HIGH_CONFIDENCE_SOURCE, note
    assert policy.retrieve is True, note


def test_personal_reflection_phrased_as_a_question_is_not_qa() -> None:
    """A first-person reflective question stays with the coach."""
    for message in (
        "what assumption am I making here",
        "what should I do about my target user",
        "how do I know my problem statement is right",
    ):
        assert _policy(message).expected_mode != "qa", message


def test_enforcement_coerces_source_coaching_to_qa_and_keeps_personal() -> None:
    coerced = enforce_model_mode("qa", "coaching")
    assert coerced.effective_mode == "qa"
    assert coerced.overridden is True
    assert coerced.qualifying_coaching_turn is False
    kept = enforce_model_mode("coaching", "coaching")
    assert kept.effective_mode == "coaching"
    assert kept.overridden is False
    assert kept.qualifying_coaching_turn is True
    qa_kept = enforce_model_mode("coaching", "qa")
    assert qa_kept.effective_mode == "qa"
    assert qa_kept.overridden is False
    unconstrained = enforce_model_mode(None, "coaching")
    assert unconstrained.effective_mode == "coaching"
    assert unconstrained.overridden is False


def test_runtime_hint_is_one_sentence_and_silent_when_ambiguous() -> None:
    assert runtime_mode_hint("qa") == RUNTIME_HINT_QA
    assert runtime_mode_hint("coaching") == RUNTIME_HINT_COACHING
    assert runtime_mode_hint(None) == ""
    assert runtime_mode_hint("ambiguous") == ""
    assert RUNTIME_HINT_QA.count(".") == 1
    assert RUNTIME_HINT_COACHING.count(".") == 1
    unconstrained = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            student_message="hello",
            response_detail="long",
            context_policy="fast_chat",
        )
    )
    qa = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            student_message="what is in week 1 lecture?",
            response_detail="long",
            context_policy="fast_chat",
            expected_response_mode="qa",
        )
    )
    assert RUNTIME_HINT_QA in qa.runtime_instructions
    assert RUNTIME_HINT_QA not in unconstrained.runtime_instructions
    assert "Facione" not in qa.runtime_instructions
    assert "Do not call tools" not in qa.runtime_instructions
    assert "structured-output" not in qa.runtime_instructions
    assert "Return only the required one-call structured JSON" not in qa.runtime_instructions
    assert len(qa.runtime_instructions) == len(unconstrained.runtime_instructions) + len(
        RUNTIME_HINT_QA
    ) + 1


def test_high_confidence_source_wrong_coaching_does_not_increment_or_advance(
    tmp_path,
) -> None:
    store = StudentStore(tmp_path / "mode-source.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(
            recommendation="advance",
            text="What trade-off in week 1 still needs evidence?",
        )
    )
    service = _service(store, client)
    turn = _submit(
        service,
        thread_id,
        "what is in week 1 lecture?",
        key="source-mislabel",
    )
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert turn.response_text == "What trade-off in week 1 still needs evidence?"
    assert turn.assessment.response_mode == "qa"
    assert turn.assessment.recommendation is None
    assert turn.pending_transition is None
    assert turn.auto_advanced_to is None
    assert turn.assessment.review_strengths == []
    assert turn.assessment.review_improvements == []
    assert _counter(store, thread_id) == 0
    persisted = _persisted_assessment(store, thread_id)
    assert persisted.get("response_mode") == "qa"
    assert "recommendation" not in persisted
    assert RUNTIME_HINT_QA in _trusted_instructions(client)


def test_high_confidence_personal_keeps_coaching_recommendation(tmp_path) -> None:
    store = StudentStore(tmp_path / "mode-personal.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client)
    turn = _submit(
        service,
        thread_id,
        "I think my target user is elderly pedestrians who wait too long.",
        key="personal-coach",
        expected_response_mode="qa",
    )
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert turn.assessment.response_mode == "coaching"
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert _counter(store, thread_id) == 1
    persisted = _persisted_assessment(store, thread_id)
    assert persisted.get("recommendation") == "stay"
    assert RUNTIME_HINT_COACHING in _trusted_instructions(client)
    context = _decoded_payload(client.calls[0]).get("runtime_context") or {}
    assert context.get("specialist") == "fast_chat"
    assert context.get("expected_response_mode") == "coaching"


def test_ambiguous_respects_model_qa_and_coaching(tmp_path) -> None:
    store = StudentStore(tmp_path / "mode-ambiguous.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    qa_client = FakeAgentCoreRuntime(payload=_qa_payload())
    qa_turn = _submit(
        _service(store, qa_client),
        thread_id,
        "Can you help me with this?",
        key="amb-qa",
    )
    assert len(qa_client.calls) == 1
    assert _phases(qa_client) == ["fast_chat"]
    assert qa_turn.assessment.response_mode == "qa"
    assert qa_turn.assessment.recommendation is None
    assert qa_turn.pending_transition is None
    assert _counter(store, thread_id) == 0
    coaching_client = FakeAgentCoreRuntime(payload=_coaching_payload())
    coaching_turn = _submit(
        _service(store, coaching_client),
        thread_id,
        "Can you help me with this next step?",
        key="amb-coach",
    )
    assert len(coaching_client.calls) == 1
    assert _phases(coaching_client) == ["fast_chat"]
    assert coaching_turn.assessment.response_mode == "coaching"
    assert coaching_turn.assessment.recommendation is StageDecision.STAY
    assert _counter(store, thread_id) == 1
    assert RUNTIME_HINT_QA not in _trusted_instructions(qa_client)
    assert RUNTIME_HINT_COACHING not in _trusted_instructions(qa_client)


def test_mixed_adversarial_keeps_coaching_semantics(tmp_path) -> None:
    store = StudentStore(tmp_path / "mode-mixed.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(recommendation="advance")
    )
    message = ADVERSARIAL_MIXED[0][0]
    turn = _submit(_service(store, client), thread_id, message, key="mixed-keep")
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert turn.assessment.response_mode == "coaching"
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.pending_transition is not None
    assert turn.pending_transition.to_stage == "concept_generation"
    assert _counter(store, thread_id) == 1
    assert RUNTIME_HINT_QA not in _trusted_instructions(client)


def test_qa_mode_persists_no_review_fields_or_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "mode-qa-invariants.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_qa_payload())
    turn = _submit(
        _service(store, client),
        thread_id,
        "what is in week 1 lecture?",
        key="qa-invariants",
    )
    assert len(client.calls) == 1
    assert turn.assessment.recommendation is None
    assert turn.pending_transition is None
    assert turn.assessment.review_depth is None
    persisted = _persisted_assessment(store, thread_id)
    assert persisted.get("response_mode") == "qa"
    assert "recommendation" not in persisted
    assert "review_strengths" not in persisted
    assert "facione_scores" not in persisted
    assert _counter(store, thread_id) == 0
    slim = EducationalAssessment(
        current_stage="problem_identification",
        response_mode="qa",
        recommendation=None,
    ).persisted_mapping()
    assert slim["response_mode"] == "qa"
    assert "recommendation" not in slim


def test_coaching_mode_requires_stay_or_advance_on_provider() -> None:
    client = FakeAgentCoreRuntime(
        payload={"mode": "coaching", "response_text": "Hello without a recommendation."}
    )
    with pytest.raises(ProviderUnavailableError):
        _provider(client).assess(
            CoachRequest(
                thread_id="thread-demo",
                student_message="I think option B is better for my users.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )
    assert len(client.calls) == 1


def test_idle_inputs_stay_unconstrained_and_skip_retrieve() -> None:
    """Trivial acknowledgements must not become Q&A or start a router."""
    for message in ("testing", "hello", "?", "ok", "thanks"):
        policy = _policy(message)
        assert policy.expected_mode != "qa", message
        assert policy.retrieve is False, message
        assert policy.intent in {
            INTENT_AMBIGUOUS,
            INTENT_HIGH_CONFIDENCE_PERSONAL,
        }, message
