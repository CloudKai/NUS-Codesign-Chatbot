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
    is_stage_progression_request,
    looks_like_project_reasoning,
    is_private_attachment_question,
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
from backend.source_library import CHAT_ATTACHMENT_ORIGIN, add_file_sources, add_text_source
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
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
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
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
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


class _NoRetrieve:
    """Fail if a routing-only stage navigation reaches retrieval."""

    def retrieve(self, query: Any) -> Any:
        raise AssertionError(f"unexpected retrieval for {query.student_message!r}")


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    *,
    auto_advance_stages: bool = False,
    retriever: Any | None = None,
) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance_stages,
        retriever=retriever,
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


def test_hyphenated_selected_source_title_matches_spaced_question() -> None:
    """Filename tokens still ground a question when the student uses spaces."""
    policy = resolve_mode_policy(
        "what is in L2 Network Bootstrapping",
        selected_source_titles=["L2-Network Bootstrapping-ARP-DHCP.pdf"],
        selected_source_filenames=["L2-Network Bootstrapping-ARP-DHCP.pdf"],
        has_selected_sources=True,
    )
    assert policy.intent == INTENT_HIGH_CONFIDENCE_SOURCE
    assert policy.expected_mode == "qa"
    assert policy.retrieve is True


@pytest.mark.parametrize(
    "message",
    (
        "what is this pdf i attached about",
        "summarise the uploaded file",
        "help me understand this diagram",
        "what themes do you notice?",
    ),
)
def test_private_attachment_questions_scope_retrieval_to_attachment(
    message: str,
) -> None:
    """Attachment questions do not implicitly broaden to course retrieval."""
    assert is_private_attachment_question(message, attachment_count=1) is True


@pytest.mark.parametrize(
    "message",
    (
        "Can you outline the attached file",
        "Could you extract the key points from this PDF",
        "Please list the main claims in the upload",
        "Identify the assumptions in the document",
        "Review this attachment",
        "Analyze the image",
        "Summarize the attached file",
        "Outline this",
    ),
)
def test_private_attachment_file_action_phrasings_are_scoped(
    message: str,
) -> None:
    """Common polite and imperative file requests use current attachment evidence."""
    assert is_private_attachment_question(message, attachment_count=1) is True


def test_private_attachment_course_comparison_keeps_combined_retrieval() -> None:
    """Explicit course comparisons retain normal attachment + course RAG."""
    assert (
        is_private_attachment_question(
            "compare this attachment with Lecture 4",
            attachment_count=1,
        )
        is False
    )


def test_private_attachment_project_reasoning_is_not_forced_to_attachment_rag() -> None:
    """Ordinary project coaching remains on its existing path."""
    for message in (
        "Would this idea solve the problem?",
        "Analyze my idea and tell me whether it solves the problem",
        "Please review our concept before I submit it",
    ):
        assert is_private_attachment_question(message, attachment_count=1) is False


@pytest.mark.parametrize(
    "message",
    (
        "Nothing else. Can we move on to concept generation?",
        "Can we proceed to the next stage?",
        "I'm ready to advance.",
        "Are we ready to move on?",
        "Am I ready to proceed?",
    ),
)
def test_explicit_stage_progression_requests_are_narrowly_recognized(message: str) -> None:
    """Navigation commands route to coaching without making stage terms Q&A."""
    assert is_stage_progression_request(message) is True


@pytest.mark.parametrize(
    "message",
    (
        "what is concept generation?",
        "concept generation seems difficult",
        "How does concept generation relate to the lecture?",
        "Can we go over my evidence?",
        "Can we proceed with this idea?",
        "Can we advance this idea?",
        "Should I advance this proposal?",
    ),
)
def test_stage_discussion_is_not_a_navigation_command(message: str) -> None:
    """Ordinary stage discussion remains on the normal routing path."""
    assert is_stage_progression_request(message) is False


def test_exact_confirm_resolves_a_pending_transition_without_agentcore(tmp_path) -> None:
    """Typed confirmation reuses the atomic transition path and never invokes Fast Chat."""
    store = StudentStore(tmp_path / "typed-confirm.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client)
    pending_turn = _submit(
        service,
        thread_id,
        "How might we help older pedestrians cross safely without rushing?",
        key="pending-for-confirm",
    )
    assert pending_turn.pending_transition is not None
    calls_before_confirm = len(client.calls)

    confirmed = _submit(service, thread_id, "confirm", key="exact-confirm")

    assert len(client.calls) == calls_before_confirm
    assert confirmed.assessment.current_stage == "concept_generation"
    assert store.get_pending_phase_transition(thread_id) is None
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "concept_generation"


def test_navigation_with_stage_named_source_skips_retrieval_and_waits_for_confirm(tmp_path) -> None:
    """Explicit navigation is coaching even when selected source metadata matches it."""
    store = StudentStore(tmp_path / "navigation-source-title.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Concept generation", "Unrelated course text")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())
    message = (
        "Can we move on to concept generation? How might we help older pedestrians "
        "cross safely without rushing?"
    )
    request = CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key="navigation-source-title",
    )
    prepared, _ = service._prepare_authoritative_turn(request)
    assert prepared.source_ids == []
    assert prepared.allow_model_knowledge is True
    turn = service.submit(request)

    assert len(client.calls) == 1
    assert turn.assessment.response_mode == "coaching"
    assert turn.pending_transition is not None
    assert turn.pending_transition.to_stage == "concept_generation"
    assert "Next: Concept generation" in turn.response_text
    assert "Generate and compare plausible concepts" in turn.response_text
    assert "The stage has not changed yet" in turn.response_text
    assert "Type exact `confirm` to advance." in turn.response_text
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "problem_identification"
    payload = _decoded_payload(client.calls[0])
    trusted = str(payload["trusted_instructions"])
    assert "hold the recommendation pending" in trusted
    assert "exact `confirm`" in trusted
    assert "automatically move" not in trusted


def test_navigation_opt_out_preserves_normal_auto_advance(tmp_path) -> None:
    """Only explicit navigation waits; ordinary HMW advancement remains automatic."""
    store = StudentStore(tmp_path / "navigation-auto-advance.sqlite3")
    nav_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    ordinary_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, auto_advance_stages=True)
    navigation = _submit(
        service,
        nav_id,
        "Can we move on? How might we help older pedestrians cross safely without rushing?",
        key="navigation-auto",
    )
    ordinary = _submit(
        service,
        ordinary_id,
        "How might we help older pedestrians cross safely without rushing?",
        key="ordinary-auto",
    )

    assert navigation.pending_transition is not None
    assert navigation.auto_advanced_to is None
    assert ordinary.pending_transition is None
    assert ordinary.auto_advanced_to == "concept_generation"


def test_navigation_stay_with_stage_named_source_skips_retrieval(tmp_path) -> None:
    """A not-ready navigation request remains a single coaching call."""
    store = StudentStore(tmp_path / "navigation-stay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Concept generation", "Unrelated course text")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="stay"))
    turn = _submit(
        _service(store, client, retriever=_NoRetrieve()),
        thread_id,
        "Can we move on to concept generation?",
        key="navigation-stay",
    )
    assert len(client.calls) == 1
    assert turn.pending_transition is None
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "problem_identification"


def test_navigation_pi_guard_blocks_premature_advance(tmp_path) -> None:
    """Navigation does not bypass the student-authored HMW provenance guard."""
    store = StudentStore(tmp_path / "navigation-pi-guard.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    turn = _submit(
        _service(store, client, retriever=_NoRetrieve()),
        thread_id,
        "Nothing else. Can we move on to concept generation?",
        key="navigation-pi-guard",
    )
    assert len(client.calls) == 1
    assert turn.pending_transition is None
    assert turn.assessment.recommendation is StageDecision.STAY
    assert "How Might We" in turn.response_text
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "problem_identification"


def test_confirm_without_pending_uses_authoritative_stage_without_agentcore(tmp_path) -> None:
    """A stale client stage cannot affect an otherwise inert exact confirmation."""
    store = StudentStore(tmp_path / "confirm-no-pending.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client)
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="confirm",
            current_stage="concept_generation",
            response_detail="short",
            idempotency_key="confirm-no-pending",
        )
    )
    assert client.calls == []
    assert turn.assessment.current_stage == "problem_identification"
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "problem_identification"


def test_direct_image_attachment_excludes_selected_course_scope(tmp_path) -> None:
    """A current private image question reaches Fast Chat, not a course evidence gap."""
    store = StudentStore(tmp_path / "direct-image-scope.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Unrelated course evidence")
    course_image = add_file_sources(
        store,
        thread_id,
        [("lecture-diagram.png", b"course-image", "image/png")],
    )[0]
    image = add_file_sources(
        store,
        thread_id,
        [("diagram.png", b"not-a-real-image", "image/png")],
        origin=CHAT_ATTACHMENT_ORIGIN,
        selected=False,
    )[0]
    client = FakeAgentCoreRuntime(payload=_qa_payload(text="The image is a diagram."))
    service = _service(store, client)
    request = CoachRequest(
        thread_id=thread_id,
        student_message="What is this image about?",
        current_stage="problem_identification",
        response_detail="short",
        attachment_source_ids=[image["id"]],
        idempotency_key="direct-image-scope",
    )
    prepared, _ = service._prepare_authoritative_turn(request)
    assert prepared.source_ids == [image["id"]]
    assert prepared.image_inputs and prepared.image_inputs[0].source_id == image["id"]
    assert [item.source_id for item in prepared.image_inputs] == [image["id"]]
    assert course_image["id"] not in prepared.source_ids
    turn = service.submit(request)
    assert len(client.calls) == 1
    assert turn.response_text != "I couldn't retrieve a validated excerpt from the selected course material for this turn, so I can't reliably summarise it from the course sources right now."


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


def test_should_author_qa_evidence_gap_skips_image_only_turns() -> None:
    """Image-only Q&A still invokes the model; course-gap context does not."""
    from types import SimpleNamespace

    from backend.coaching.mode_policy import should_author_qa_evidence_gap
    from backend.retrieval import COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT

    image_only = SimpleNamespace(
        expected_response_mode="qa",
        allow_model_knowledge=False,
        retrieved_chunks=[],
        source_ids=["img-1"],
        retrieved_course_context="",
        image_inputs=[{"source_id": "img-1", "media_type": "image/png"}],
    )
    assert should_author_qa_evidence_gap(image_only) is False
    course_gap = SimpleNamespace(
        expected_response_mode="qa",
        allow_model_knowledge=False,
        retrieved_chunks=[],
        source_ids=["src-1"],
        retrieved_course_context=COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
        image_inputs=[],
    )
    assert should_author_qa_evidence_gap(course_gap) is True

    mixed = SimpleNamespace(
        expected_response_mode="qa",
        allow_model_knowledge=False,
        retrieved_chunks=[],
        source_ids=["img-1", "pdf-1"],
        retrieved_course_context="",
        image_inputs=[SimpleNamespace(source_id="img-1")],
    )
    assert should_author_qa_evidence_gap(mixed) is True


def test_runtime_hint_is_silent_when_ambiguous_and_qa_skips_coaching_guidance() -> None:
    assert runtime_mode_hint("qa") == RUNTIME_HINT_QA
    assert runtime_mode_hint("coaching") == RUNTIME_HINT_COACHING
    assert runtime_mode_hint(None) == ""
    assert runtime_mode_hint("ambiguous") == ""
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
            allow_model_knowledge=False,
        )
    )
    assert RUNTIME_HINT_QA in qa.runtime_instructions
    assert RUNTIME_HINT_QA not in unconstrained.runtime_instructions
    assert "Guidance mode: Strict" not in qa.runtime_instructions
    assert "recommend stay or advance" in qa.runtime_instructions.casefold()
    assert "not authoritative course evidence" in qa.runtime_instructions
    assert "could not retrieve a validated excerpt" in qa.runtime_instructions
    assert "Facione" not in qa.runtime_instructions
    assert "Do not call tools" not in qa.runtime_instructions
    assert "structured-output" not in qa.runtime_instructions
    assert "Return only the required one-call structured JSON" not in qa.runtime_instructions


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
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
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
