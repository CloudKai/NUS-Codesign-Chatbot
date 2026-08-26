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
    QA_EVIDENCE_GAP_RESPONSE,
    RUNTIME_HINT_COACHING,
    RUNTIME_HINT_QA,
    ModePolicy,
    enforce_model_mode,
    is_current_stage_status_request,
    is_exact_confirm_command,
    is_stage_progression_request,
    is_terminal_completion_request,
    looks_like_project_reasoning,
    is_private_attachment_question,
    manual_stage_selection_target,
    resolve_mode_policy,
    runtime_mode_hint,
)
from backend.domain import CoachRequest, EducationalAssessment, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
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
from backend.settings import settings
from backend.source_library import CHAT_ATTACHMENT_ORIGIN, add_file_sources, add_text_source
from backend.student_journey import STAGE_BY_ID, THINKING_STAGES, selectable_stage_ids
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
        message = getattr(query, "current_message", None) or getattr(
            query, "student_message", ""
        )
        raise AssertionError(f"unexpected retrieval for {message!r}")


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
        "Hi, can I move to Concept Generation?",
        "can i move to concept genration?",
        "Can I start concept generation?",
        "Can move on already?",
    ),
)
def test_explicit_stage_progression_requests_are_narrowly_recognized(message: str) -> None:
    """Navigation commands route to coaching without making stage terms Q&A."""
    assert is_stage_progression_request(message) is True


@pytest.mark.parametrize(
    "message",
    (
        "What is concept genration?",
        "Which lecture covers concept generation?",
        "Explain concept generation.",
    ),
)
def test_stage_terms_without_navigation_remain_normal_questions(message: str) -> None:
    """Stage nouns and the bounded typo do not force workflow routing."""
    assert is_stage_progression_request(message) is False


@pytest.mark.parametrize(
    "message",
    (
        "Hi, can I move to Concept Generation?",
        "can i move to concept genration?",
        "Can I start concept generation?",
        "Can move on already?",
    ),
)
def test_explicit_navigation_variants_skip_retrieval_without_stage_mutation(
    tmp_path,
    message: str,
) -> None:
    """Bounded navigation variants route to Coaching without mutating state."""
    store = StudentStore(tmp_path / "navigation-variant.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(service, thread_id, message, key="navigation-variant")

    assert len(client.calls) == 1
    assert turn.assessment.response_mode == "coaching"
    assert turn.pending_transition is None
    journey = ((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
        "learning_journey", {}
    )
    assert journey["current_stage"] == "problem_identification"
    assert journey["completed_stages"] == []


def test_embedded_navigation_and_explicit_path_completion_are_workflow_intent() -> None:
    """Reasoning before a readiness question cannot make it fall into course Q&A."""
    assert is_stage_progression_request(
        "My constraints include safety and accessibility. Is this enough to move on to Ethics and Critical Thinking?"
    )
    assert is_stage_progression_request("Can I finish the Thinking Path now?")
    assert is_stage_progression_request("Is my Reflection complete?")
    assert not is_stage_progression_request("Am I done now?")
    assert not is_terminal_completion_request(
        "Can I finish the Thinking Path now?", current_stage="concept_generation"
    )
    assert is_terminal_completion_request(
        "Can I finish the Thinking Path now?", current_stage="reflection"
    )


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


@pytest.mark.parametrize(
    ("message", "stage_id"),
    (
        ("move me to problem_identification", "problem_identification"),
        ("move me to Problem identification", "problem_identification"),
        ("move me to concept_generation", "concept_generation"),
        (" Move   Me to Concept Generation!!! ", "concept_generation"),
        ("move me to design_specification", "design_specification"),
        ("move me to design specification.", "design_specification"),
        ("move me to deep_analysis", "deep_analysis"),
        ("move me to Ethics & Critical Thinking", "deep_analysis"),
        ("move me to ethics and critical thinking?", "deep_analysis"),
        ("move me to reflection", "reflection"),
        ("move me to Reflection!", "reflection"),
    ),
)
def test_manual_stage_command_parser_is_strict_and_canonical(
    message: str, stage_id: str
) -> None:
    assert manual_stage_selection_target(message) == stage_id
    assert is_stage_progression_request(message) is True


@pytest.mark.parametrize(
    "message",
    (
        "Concept generation",
        "What is Concept generation?",
        "Move this idea to concept generation",
        "Please move me to reflection",
        "Move me to ethical consideration",
        "Move me to the next stage",
    ),
)
def test_manual_stage_command_parser_rejects_fuzzy_or_broad_phrasing(
    message: str,
) -> None:
    assert manual_stage_selection_target(message) is None


@pytest.mark.parametrize(
    ("command", "target_stage", "label"),
    (
        (
            "move me to problem identification",
            "problem_identification",
            "Problem identification",
        ),
        ("move me to concept_generation", "concept_generation", "Concept generation"),
        (
            "move me to design specification",
            "design_specification",
            "Design specification",
        ),
        (
            "move me to Ethics and Critical Thinking",
            "deep_analysis",
            "Ethics & Critical Thinking",
        ),
        ("move me to Reflection", "reflection", "Reflection"),
    ),
)
def test_enabled_manual_stage_command_persists_without_model_or_retrieval(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    target_stage: str,
    label: str,
) -> None:
    store = StudentStore(tmp_path / f"manual-{target_stage}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, thread_id, "Selected evidence", "Course material")
    target_index = next(
        index for index, stage in enumerate(THINKING_STAGES) if stage.id == target_stage
    )
    if target_index:
        metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
        journey = dict(metadata.get("learning_journey") or {})
        journey["completed_stages"] = [
            stage.id for stage in THINKING_STAGES[:target_index]
        ]
        journey["current_stage"] = "problem_identification"
        metadata["learning_journey"] = journey
        metadata["thinking_stage"] = "problem_identification"
        store.update_thread(thread_id, metadata=metadata)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())
    request = CoachRequest(
        thread_id=thread_id,
        student_message=command,
        current_stage="problem_identification",
        response_detail="short",
        source_ids=[source["id"]],
        idempotency_key=f"manual-{target_stage}",
    )

    turn = service.submit(request)
    replay = service.submit(request)

    expected = (
        f"You are already in Stage: {label}."
        if target_stage == "problem_identification"
        else f"Moved to Stage: {label}."
    )
    assert replay == turn
    assert turn.response_text == expected
    assert turn.assessment.current_stage == target_stage
    assert turn.assessment.recommendation is None
    assert turn.assessment.citations == []
    assert turn.pending_transition is None
    assert turn.auto_advanced_to is None
    assert client.calls == []
    assert _counter(store, thread_id) == 0
    assert store.get_pending_phase_transition(thread_id) is None
    thread = store.get_thread(thread_id) or {}
    journey = thread["metadata"]["learning_journey"]
    assert journey["current_stage"] == target_stage
    assert journey["completed_stages"] == [
        stage.id for stage in THINKING_STAGES[:target_index]
    ]
    assert thread["metadata"]["thinking_stage"] == target_stage
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assistant = messages[-1]
    assert assistant["content"] == expected
    assert assistant["metadata"]["thinking_stage"] == target_stage
    assert "auto_advanced_to" not in assistant["metadata"]
    assert store.get_source(thread_id, source["id"], include_extracted_text=False)[
        "selected"
    ] is True


def test_illegal_manual_stage_jump_fails_before_pending_or_chat_side_effects(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked exact command cannot reject pending or write a chat turn."""
    store = StudentStore(tmp_path / "manual-locked-reflection.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    transitions.create(pending)
    messages_before = store.get_messages(thread_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())

    with pytest.raises(ValueError, match="locked"):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="move me to Reflection",
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key="manual-locked-reflection",
            )
        )

    journey = (store.get_thread(thread_id) or {}).get("metadata", {}).get(
        "learning_journey", {}
    )
    assert journey["current_stage"] == "problem_identification"
    assert journey["completed_stages"] == []
    assert store.get_messages(thread_id) == messages_before
    assert client.calls == []
    assert transitions.get_pending(thread_id) is not None


@pytest.mark.parametrize(
    ("message", "current_stage", "completed_before"),
    (
        (
            "How might we improve road crossings for older pedestrians so that they can cross safely without rushing?",
            "problem_identification",
            [],
        ),
        ("Can I move on?", "concept_generation", ["problem_identification"]),
    ),
)
def test_phase2_validated_advance_completes_current_without_changing_focus(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    current_stage: str,
    completed_before: list[str],
) -> None:
    """A validated Coaching ADVANCE unlocks only the immediate next stage."""
    store = StudentStore(tmp_path / "phase2-completion.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    if completed_before:
        metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
        journey = dict(metadata.get("learning_journey") or {})
        journey["completed_stages"] = completed_before
        journey["current_stage"] = current_stage
        metadata["learning_journey"] = journey
        metadata["thinking_stage"] = current_stage
        store.update_thread(thread_id, metadata=metadata)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())
    request = CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage=current_stage,
        response_detail="short",
        idempotency_key="phase2-advance",
    )

    turn = service.submit(request)
    assert turn.pending_transition is not None
    thread = store.get_thread(thread_id) or {}
    journey = thread["metadata"]["learning_journey"]
    assert journey["current_stage"] == current_stage
    assert journey["completed_stages"] == [
        *completed_before,
        current_stage,
    ]
    assert store.get_pending_phase_transition(thread_id) is not None
    assert current_stage in selectable_stage_ids(journey)
    messages_before = store.get_messages(thread_id)
    replay = service.submit(request)
    assert replay == turn
    assert store.get_messages(thread_id) == messages_before

    next_stage = {
        "problem_identification": "concept_generation",
        "concept_generation": "design_specification",
    }[current_stage]
    store.select_learning_stage(thread_id, next_stage)
    selected = store.get_thread(thread_id) or {}
    selected_journey = selected["metadata"]["learning_journey"]
    assert selected_journey["current_stage"] == next_stage
    assert selected_journey["completed_stages"] == [
        *completed_before,
        current_stage,
    ]
    assert store.get_pending_phase_transition(thread_id) is None


def test_phase2_stay_does_not_complete_current_stage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "phase2-stay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="stay"))
    monkeypatch.setattr(settings, "student_stage_selection", True)
    turn = _service(store, client, retriever=_NoRetrieve()).submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I am still comparing the needs and constraints.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="phase2-stay",
        )
    )
    assert turn.pending_transition is None
    journey = (store.get_thread(thread_id) or {})["metadata"]["learning_journey"]
    assert journey["completed_stages"] == []
    assert selectable_stage_ids(journey) == ("problem_identification",)


def test_manual_stage_command_rejects_stale_client_stage_without_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "manual-stale-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    metadata["learning_journey"] = journey
    store.update_thread(thread_id, metadata=metadata)
    store.select_learning_stage(thread_id, "concept_generation")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())

    with pytest.raises(
        ValueError,
        match="current_stage does not match the notebook Thinking Path stage",
    ):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="move me to reflection",
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key="manual-stale-stage",
            )
        )

    assert client.calls == []
    assert store.get_messages(thread_id) == []
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "concept_generation"
    assert thread["metadata"]["learning_journey"]["current_stage"] == (
        "concept_generation"
    )


def test_manual_stage_command_cannot_cross_owner_boundary(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "manual-owner-isolation.sqlite3"
    owner = StudentStore(database, identifier="owner-a")
    attacker = StudentStore(database, identifier="owner-b")
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(attacker, client, retriever=_NoRetrieve())

    with pytest.raises(ValueError, match="Notebook not found"):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="move me to reflection",
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key="manual-foreign-owner",
            )
        )

    assert client.calls == []
    assert owner.get_messages(thread_id) == []
    thread = owner.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "problem_identification"
    assert thread["metadata"]["learning_journey"]["current_stage"] == (
        "problem_identification"
    )


def test_disabled_manual_stage_command_uses_immediate_next_confirmation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StudentStore(tmp_path / "manual-disabled.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    metadata["learning_journey"] = journey
    store.update_thread(thread_id, metadata=metadata)
    store.select_learning_stage(thread_id, "concept_generation")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    monkeypatch.setattr(settings, "student_stage_selection", False)
    service = _service(
        store,
        client,
        auto_advance_stages=True,
        retriever=_NoRetrieve(),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="move me to reflection",
            current_stage="concept_generation",
            response_detail="short",
            idempotency_key="manual-disabled",
        )
    )

    assert len(client.calls) == 1
    assert turn.auto_advanced_to is None
    assert turn.pending_transition is not None
    assert turn.pending_transition.from_stage == "concept_generation"
    assert turn.pending_transition.to_stage == "design_specification"
    assert "Type exact `confirm` to advance." in turn.response_text
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "concept_generation"
    assert thread["metadata"]["learning_journey"]["current_stage"] == (
        "concept_generation"
    )


@pytest.mark.parametrize(
    "message",
    (
        "What stage am I in?",
        "Which journey phase am I on?",
        "What is my current Thinking Path stage?",
    ),
)
def test_current_stage_status_requests_are_narrowly_recognized(message: str) -> None:
    """Only direct current-stage lookups use the deterministic answer path."""
    assert is_current_stage_status_request(message) is True


@pytest.mark.parametrize(
    "message",
    (
        "What does Ethics & Critical Thinking mean?",
        "How does Concept Generation relate to this lecture?",
        "Which stage should we use for stakeholder mapping?",
    ),
)
def test_stage_definition_questions_remain_normal_fast_chat(message: str) -> None:
    """A named stage alone must not suppress ordinary course Q&A."""
    assert is_current_stage_status_request(message) is False


@pytest.mark.parametrize(
    "stage_id",
    (
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    ),
)
def test_current_stage_status_is_persisted_without_model_or_retrieval(
    tmp_path, stage_id: str
) -> None:
    """The displayed stage must come from the persisted Journey, not Haiku prose."""
    store = StudentStore(tmp_path / f"stage-status-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    target_index = next(
        index for index, stage in enumerate(THINKING_STAGES) if stage.id == stage_id
    )
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["current_stage"] = stage_id
    journey["completed_stages"] = [
        stage.id for stage in THINKING_STAGES[:target_index]
    ]
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = stage_id
    store.update_thread(thread_id, metadata=metadata)
    source = add_text_source(store, thread_id, "Week 1", "Course material")
    client = FakeAgentCoreRuntime(payload=_qa_payload())
    service = _service(store, client, retriever=_NoRetrieve())
    request = CoachRequest(
        thread_id=thread_id,
        student_message="What is my current Thinking Path stage?",
        current_stage=stage_id,
        response_detail="short",
        source_ids=[source["id"]],
        idempotency_key=f"status-{stage_id}",
    )

    turn = service.submit(request)
    replay = service.submit(request)

    stage = STAGE_BY_ID[stage_id]
    assert replay == turn
    assert client.calls == []
    assert turn.assessment.current_stage == stage_id
    assert turn.assessment.response_mode == "qa"
    assert turn.assessment.recommendation is None
    assert turn.pending_transition is None
    assert stage.label in turn.response_text
    assert stage.description in turn.response_text
    assert _counter(store, thread_id) == 0

    thread = store.get_thread(thread_id) or {}
    metadata = thread.get("metadata") or {}
    assert metadata["thinking_stage"] == stage_id
    assert metadata["learning_journey"]["current_stage"] == stage_id
    assert store.get_pending_phase_transition(thread_id) is None
    assert store.get_source(thread_id, source["id"], include_extracted_text=False)[
        "selected"
    ] is True
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assessment = (messages[-1].get("metadata") or {}).get("assessment") or {}
    assert assessment["current_stage"] == stage_id
    assert assessment["response_mode"] == "qa"
    assert assessment.get("citations") == []


def test_stage_definition_question_keeps_normal_fast_chat_behavior(tmp_path) -> None:
    """Asking what a stage means remains model-owned Q&A, not a status lookup."""
    store = StudentStore(tmp_path / "stage-definition-qa.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_qa_payload(text="It examines design trade-offs."))
    turn = _submit(
        _service(store, client),
        thread_id,
        "What does Ethics & Critical Thinking mean?",
        key="stage-definition-qa",
    )

    assert len(client.calls) == 1
    assert turn.response_text == "It examines design trade-offs."
    assert turn.assessment.response_mode == "qa"


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


def test_embedded_navigation_skips_retrieval_and_keeps_immediate_confirm_flow(tmp_path) -> None:
    """A long substantive turn ending in navigation stays in coaching mode."""
    store = StudentStore(tmp_path / "embedded-navigation.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Ethics and Critical Thinking", "Course text")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    turn = _submit(
        _service(store, client, retriever=_NoRetrieve()),
        thread_id,
        "My non-negotiable constraints are accessibility and safe operation. "
        "Is this enough to move on to concept generation? How might we help "
        "older pedestrians cross safely without rushing?",
        key="embedded-navigation",
    )

    assert len(client.calls) == 1
    assert turn.assessment.response_mode == "coaching"
    assert turn.pending_transition is not None
    assert turn.pending_transition.to_stage == "concept_generation"
    assert "Type exact `confirm` to advance." in turn.response_text


def test_reflection_completion_request_skips_retrieval_and_suppresses_advance(tmp_path) -> None:
    """Deferred terminal completion remains a non-mutating Reflection coaching turn."""
    store = StudentStore(tmp_path / "reflection-completion-deferred.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    metadata["learning_journey"] = {
        "current_stage": "reflection",
        "completed_stages": [
            "problem_identification",
            "concept_generation",
            "design_specification",
            "deep_analysis",
        ],
    }
    metadata["thinking_stage"] = "reflection"
    store.update_thread(thread_id, metadata=metadata)
    add_text_source(store, thread_id, "Reflection lecture", "Course text")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="advance"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Can I finish?",
            current_stage="reflection",
            response_detail="short",
            idempotency_key="reflection-completion-deferred",
        )
    )

    assert len(client.calls) == 1
    assert turn.assessment.response_mode == "coaching"
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    current = (store.get_thread(thread_id) or {}).get("metadata") or {}
    journey = current["learning_journey"]
    assert journey["current_stage"] == "reflection"
    assert journey["completed_stages"] == [
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
    ]


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


@pytest.mark.parametrize(
    "message",
    (
        "Can I move to Concept Generation?",
        "Hi, can I move to Concept Generation?",
        "Okay, can I move into Concept Generation?",
        "I think I'm done here. Can I move to Concept Generation?",
        "Can we proceed to Design Specification?",
        "Can I continue to the next stage?",
        "Can I switch to Ethics & Critical Thinking?",
        "Am I ready to move on?",
        "Is this enough for the next stage?",
        (
            "I compared the sensor and button approaches and I think the sensor "
            "better addresses the user need while keeping interaction simple. "
            "Can I move to Design Specification now?"
        ),
        "can i move to concept genration?",
        "can i move to design specifcation?",
        "can i move to refelction?",
        "Can move to concept generation anot?",
    ),
)
def test_natural_navigation_phrases_are_workflow_intent(message: str) -> None:
    """Conversational prefixes, readiness, typos, and embedded asks stay workflow."""
    assert is_stage_progression_request(message) is True


@pytest.mark.parametrize(
    ("message", "stage_id"),
    (
        ("Can I move to Concept Generation?", "concept_generation"),
        ("Hi, can I move to Concept Generation?", "concept_generation"),
        ("Okay, can I move into Concept Generation?", "concept_generation"),
        ("can i move to concept genration?", "concept_generation"),
        ("Can we proceed to Design Specification?", "design_specification"),
        ("can i move to design specifcation?", "design_specification"),
        ("Can I switch to Ethics & Critical Thinking?", "deep_analysis"),
        ("can i move to refelction?", "reflection"),
        (
            "I compared the sensor and button approaches and I think the sensor "
            "better addresses the user need while keeping interaction simple. "
            "Can I move to Design Specification now?",
            "design_specification",
        ),
    ),
)
def test_natural_navigation_extracts_named_stage_targets(
    message: str, stage_id: str
) -> None:
    """Named destinations resolve only after strong navigation intent."""
    assert manual_stage_selection_target(message) == stage_id


@pytest.mark.parametrize(
    "message",
    (
        "What is Concept Generation?",
        "Can you explain Concept Generation?",
        "How does Concept Generation work?",
        "How do I generate more concepts?",
        "Which lecture covers Concept Generation?",
        "What does Design Specification mean?",
        "What should I do during Design Specification?",
        "What does the reading say about Design Specification?",
        "What is Ethics & Critical Thinking?",
        "How does Reflection work?",
        "Which reading talks about Reflection?",
        "What is concept genration?",
        "Concept generation now?",
    ),
)
def test_stage_name_questions_are_not_navigation(message: str) -> None:
    """A stage noun or typo alone never becomes a stage command."""
    assert is_stage_progression_request(message) is False
    assert manual_stage_selection_target(message) is None


@pytest.mark.parametrize(
    "message",
    (
        "What stage am I in?",
        "Hi, what stage am I in?",
        "Where are we now?",
        "Where am I in the Thinking Path?",
        "Which phase am I currently working on?",
        "What stage are we at?",
    ),
)
def test_current_stage_status_natural_variants(message: str) -> None:
    """Status lookups tolerate prefixes without becoming course Q&A."""
    assert is_current_stage_status_request(message) is True
    assert is_stage_progression_request(message) is False


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("confirm", True),
        ("Confirm", True),
        ("CONFIRM", True),
        ("confirm.", True),
        ("confirm!", True),
        ("yes", False),
        ("yeah", False),
        ("okay", False),
        ("ok", False),
        ("sure", False),
        ("sounds good", False),
        ("go ahead", False),
    ),
)
def test_confirm_normalization_rejects_vague_acknowledgements(
    message: str, expected: bool
) -> None:
    """Only explicit confirm (with harmless punctuation) resolves pending."""
    assert is_exact_confirm_command(message) is expected


def test_navigation_with_selected_lecture_notes_still_skips_retrieval(tmp_path) -> None:
    """Selected stage-named sources must not retrieve for pure navigation."""
    store = StudentStore(tmp_path / "nav-selected-source.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(
        store, thread_id, "Lecture Notes: Concept Generation", "Course material"
    )
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="stay"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Hi, can I move to Concept Generation?",
            current_stage="problem_identification",
            response_detail="short",
            source_ids=[source["id"]],
            idempotency_key="nav-selected",
        )
    )

    assert len(client.calls) == 1
    assert turn.assessment.response_mode == "coaching"
    assert QA_EVIDENCE_GAP_RESPONSE.split(",")[0] not in turn.response_text
    assert "couldn't retrieve" not in turn.response_text.casefold()


def test_punctuated_confirm_resolves_pending_without_model(tmp_path) -> None:
    """confirm! reuses the atomic confirmation path."""
    store = StudentStore(tmp_path / "confirm-bang.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    transitions.create(pending)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, retriever=_NoRetrieve())
    calls_before = len(client.calls)

    confirmed = _submit(service, thread_id, "confirm!", key="confirm-bang")

    assert len(client.calls) == calls_before
    assert confirmed.assessment.current_stage == "concept_generation"


def test_vague_okay_does_not_resolve_pending_transition(tmp_path) -> None:
    """okay must never silently confirm a pending stage change."""
    store = StudentStore(tmp_path / "okay-not-confirm.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    transitions.create(pending)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(recommendation="stay"))
    service = _service(store, client, retriever=_NoRetrieve())

    turn = _submit(service, thread_id, "okay", key="okay-not-confirm")

    assert transitions.get_pending(thread_id) is not None
    journey = ((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
        "learning_journey", {}
    )
    assert journey["current_stage"] == "problem_identification"
    assert turn.assessment.current_stage == "problem_identification"


def test_phase2_natural_language_immediate_next_succeeds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlocked next-stage NL commands use the same store authorization as buttons."""
    store = StudentStore(tmp_path / "phase2-nl-next.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    journey["current_stage"] = "problem_identification"
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = "problem_identification"
    store.update_thread(thread_id, metadata=metadata)
    assert "concept_generation" in selectable_stage_ids(journey)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Hi, can I move to Concept Generation?",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="phase2-nl-next",
        )
    )

    assert client.calls == []
    assert turn.response_text == "Moved to Stage: Concept generation."
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "concept_generation"


def test_phase2_natural_language_locked_jump_is_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NL stage commands cannot bypass the linear unlocked frontier."""
    store = StudentStore(tmp_path / "phase2-nl-locked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    messages_before = store.get_messages(thread_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())

    with pytest.raises(ValueError, match="locked"):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="Hi, move me to Ethics and Critical Thinking",
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key="phase2-nl-locked",
            )
        )

    assert client.calls == []
    assert store.get_messages(thread_id) == messages_before
    journey = ((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
        "learning_journey", {}
    )
    assert journey["current_stage"] == "problem_identification"


def test_phase2_natural_language_revisit_unlocked_stage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Earlier unlocked stages remain reachable by natural-language commands."""
    store = StudentStore(tmp_path / "phase2-nl-revisit.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    journey["current_stage"] = "concept_generation"
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = "concept_generation"
    store.update_thread(thread_id, metadata=metadata)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _service(store, client, retriever=_NoRetrieve())

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Can I switch to Problem Identification?",
            current_stage="concept_generation",
            response_detail="short",
            idempotency_key="phase2-nl-revisit",
        )
    )

    assert client.calls == []
    assert turn.response_text == "Moved to Stage: Problem identification."
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "problem_identification"


def test_genuine_course_qa_still_retrieves_after_navigation_hardening() -> None:
    """Course lookup about a stage name remains retrieval-eligible."""
    message = "Which lecture covers Concept Generation?"
    assert is_stage_progression_request(message) is False
    assert manual_stage_selection_target(message) is None
    policy = resolve_mode_policy(
        message,
        has_selected_sources=True,
        selected_source_titles=["Week 2 lecture"],
    )
    assert policy.retrieve is True
    assert policy.expected_mode == "qa"
