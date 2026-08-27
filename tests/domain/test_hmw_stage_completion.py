"""How Might We completion for Problem Identification. Mock-only; no AWS."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore_runtime.models import FastChatTurnOutput
from backend.application import CoachApplicationService
from backend.domain import (
    CoachRequest,
    CoachTurn,
    ProviderAssessmentResult,
    StageDecision,
)
from backend.learning.hmw import hmw_scaffold_available
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.prompts import load_stage_prompt
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_journey import next_stage_id
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow

_HMW_FORMULA = (
    "How might we + [action / opportunity] + for [user] + so that "
    "[desired outcome / benefit]"
)

_HMW_BRITTLE_REGEX = r"^How might we .* for .* so that .*$"
_SATISFACTORY_HMW = (
    "How might we improve road crossings for older pedestrians so that they can "
    "cross safely and confidently?"
)
_SCREENSHOT_HMW = (
    "How might we improve the road-crossing experience for elderly pedestrians "
    "so that they can cross busy roads safely and confidently?"
)
_WORKING_HMW_CASES = (
    pytest.param(
        "How might we\n"
        "The main issue is that some older pedestrians cannot reach the other side\n"
        "before the pedestrian signal changes, especially those who walk more slowly.\n"
        "+ for Older pedestrians have difficulty crossing the road near a school.\n"
        "+ so that able to cross safely without worrying and also safely to where\n"
        "they want to go",
        id="live-rough-template-hmw",
    ),
    pytest.param(
        "How might we make crossing easier + for elderly people near the school + "
        "so that they can cross safely",
        id="rough-meaningful-hmw",
    ),
    pytest.param(
        "How might we improve crossing access for older pedestrians so that they "
        "can cross safely and reach nearby destinations without worrying",
        id="multiple-related-outcomes",
    ),
)
_INCOMPLETE_CASES = (
    pytest.param(
        "How might we improve crossing safety?",
        id="incomplete",
    ),
    pytest.param(
        "How might we improve road crossings for older pedestrians?",
        id="missing-outcome",
    ),
    pytest.param(
        "How might we improve crossing safety so that it is safer?",
        id="missing-user",
    ),
)
_STRUCTURAL_HMW_STAY_CASES = (
    pytest.param(
        "How might we do something for users so that it is better?",
        id="template-filling",
    ),
    pytest.param(
        "How might we install a 60-second pedestrian light for older pedestrians "
        "so that they have more time?",
        id="solution-locked",
    ),
    pytest.param(
        "How might we do something for people so that things are better?",
        id="empty-template",
    ),
)


def _service(
    store: StudentStore,
    recommendation: StageDecision,
    *,
    auto_advance: bool,
    hmw_scaffold_ready: bool = False,
) -> CoachApplicationService:
    """Return a mock coaching service with an explicit stay/advance decision."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(
            DeterministicCoachProvider(
                recommendation, hmw_scaffold_ready=hmw_scaffold_ready
            ),
            transitions,
        ),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance,
    )


def _submit(
    tmp_path: Path,
    message: str,
    *,
    recommendation: StageDecision,
    auto_advance: bool,
    hmw_scaffold_ready: bool = False,
) -> tuple[CoachTurn, StudentStore, str]:
    """Submit one Problem Identification turn and return the turn, store, and id."""
    store = StudentStore(tmp_path / "hmw.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(
        thread_id,
        metadata={
            "thinking_stage": "problem_identification",
            "learning_journey": {
                "current_stage": "problem_identification",
                "completed_stages": [],
                "stage_notes": {},
                "response_detail": "short",
            },
            "response_detail": "short",
        },
    )
    service = _service(
        store,
        recommendation,
        auto_advance=auto_advance,
        hmw_scaffold_ready=hmw_scaffold_ready,
    )
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    return turn, store, thread_id


def test_hmw_completion_criterion_lives_in_problem_identification_prompts() -> None:
    """Both mock and AgentCore PI files teach HMW readiness vs ADVANCE."""
    backend = load_stage_prompt("problem_identification")
    agentcore = Path(
        "agentcore_runtime/prompts/stages/problem_identification.md"
    ).read_text(encoding="utf-8")
    for text in (backend, agentcore):
        collapsed = " ".join(text.split())
        assert "HOW MIGHT WE READINESS AND COMPLETION" in collapsed
        assert "intermediate synthesis scaffold" in collapsed
        assert "TWO of these THREE signals" in collapsed
        assert "third signal may still need clarification" in collapsed
        assert _HMW_FORMULA in collapsed
        assert "hmw_scaffold_ready=true" in collapsed
        assert "recommendation=stay is NORMAL" in collapsed
        assert "Never convert this stay into recommendation=advance" in collapsed
        assert "Do not tell the student to use the HMW formula" in collapsed
        assert "Judge meaning, not punctuation" in collapsed
        assert "valid working HMW" in collapsed
        assert "working draft, not a polished final statement" in collapsed
        assert "opportunity is expressed as a problem or friction" in collapsed
        assert "refinement a progression gate" in collapsed
        assert "QUICK MODE — INFORMAL HMW COMPLETION" in collapsed
        assert "STRICT MODE — CLEARER ARTICULATION" in collapsed
        assert "NON-BLOCKING AFTER WORKABLE HMW" in collapsed
        assert "BAN PROGRESSION-HOLDING LANGUAGE" in collapsed
        assert "recommendation MUST be advance" in collapsed
        assert "hmw_scaffold_ready MUST be false" in collapsed
        assert "do NOT return STAY merely to" in collapsed
        assert "identify the \"real barrier\"" in collapsed
        assert "Before we move forward" in collapsed
        assert "recommendation=advance" in collapsed
        assert "Concept Generation" in collapsed
        assert "The application remains the stage authority" in collapsed
        assert "Do not write the finished HMW" in collapsed
        assert "solution-locked" in collapsed
        assert "GOOD ENOUGH TO PROGRESS" in collapsed
        assert "Do NOT require the student to prove the root cause" in collapsed
        assert "WHEN A WORKABLE HMW IS PRESENT" in collapsed
        assert "What evidence do you have?" in collapsed
        assert "EXPLICIT PROGRESSION REQUESTS" in collapsed
        assert "REPEATED HMW RULE" in collapsed
        assert "Workable Framing → Progress" in collapsed
        assert "must not override the HMW completion rule above" in collapsed
        assert (
            "hmw_scaffold_ready=true even if root cause, additional evidence, "
            "scope, or consequences still need refinement"
        ) in collapsed
        assert "NOT prerequisites for showing the HMW scaffold" in collapsed
        assert "must not block ADVANCE once the HMW completion contract is met" in collapsed
        assert _HMW_BRITTLE_REGEX not in text
    fast_chat = " ".join(
        Path("agentcore_runtime/prompts/fast_chat.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "hmw_scaffold_ready is internal" in fast_chat
    assert "set hmw_scaffold_ready to true" in fast_chat
    assert "valid working HMW" in fast_chat
    assert "stay does not imply hmw_scaffold_ready=false" in fast_chat
    shared = " ".join(
        Path("agentcore_runtime/prompts/shared_coaching.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "STAY does not imply hmw_scaffold_ready=false" in shared
    assert "recommendation=stay with hmw_scaffold_ready=true is normal" in shared
    concept = load_stage_prompt("concept_generation")
    assert "HOW MIGHT WE READINESS AND COMPLETION" not in concept


def test_quick_informal_hmw_contract_accepts_meaningful_shorthand() -> None:
    """Quick PI prompt treats informal A/B/C HMW as workable completion."""
    prompt = Path(
        "agentcore_runtime/prompts/stages/problem_identification.md"
    ).read_text(encoding="utf-8")
    collapsed = " ".join(prompt.split())
    assert "QUICK MODE — INFORMAL HMW COMPLETION" in collapsed
    assert "hmw help elderly cross busy roads safely / feel less stressed" in collapsed
    assert "meaning, not syntax" in collapsed
    assert "block informal HMW/shorthand" in collapsed
    assert "do NOT return STAY merely to" in collapsed
    assert "real barrier" in collapsed
    assert "recommendation MUST be advance" in collapsed
    assert "Before we move forward" in collapsed


def test_strict_retains_clearer_hmw_articulation_bar() -> None:
    """Strict PI still prefers clearer HMW wording and is not reduced to Quick."""
    prompt = Path(
        "agentcore_runtime/prompts/stages/problem_identification.md"
    ).read_text(encoding="utf-8")
    collapsed = " ".join(prompt.split())
    assert "STRICT MODE — CLEARER ARTICULATION" in collapsed
    assert "prefer a clearer working HMW using the preferred structure" in collapsed
    assert "research-validation gate" in collapsed
    assert (
        "equivalent prose that states user, problem, and outcome without a "
        "clearer working HMW articulation is not completion"
    ) in collapsed
    assert "solution-locked" in collapsed
    assert "Template filling" in collapsed


def test_composer_quick_pi_allows_informal_hmw_syntax() -> None:
    """Quick runtime PI minimum accepts informal HMW when A/B/C are clear."""
    from backend.prompts import PromptComposer, PromptContext

    guidance = PromptComposer().compose(
        PromptContext(
            current_stage="problem_identification",
            student_message="hmw help elderly cross busy roads safely / feel less stressed",
            response_detail="short",
        )
    ).runtime_instructions
    assert "Guidance mode: Quick" in guidance
    assert "informal HMW" in guidance
    assert "must not block ADVANCE" in guidance
    assert "Barrier/root-cause sharpening is non-blocking" in guidance
    assert "How might we / for / so that" in guidance


_PEDESTRIAN_TWO_OF_THREE = (
    "Older pedestrians have difficulty crossing the road near a school.\n\n"
    "The main issue is that some older pedestrians cannot reach the other side "
    "before the pedestrian signal changes, especially those who walk more slowly."
)


def test_older_pedestrians_two_of_three_is_scaffold_ready_contract() -> None:
    """User + signal-timing problem, no outcome: stay and hmw_scaffold_ready=true.

    This is a prompt/schema contract, not a live model call. Identifiable
    user (older pedestrians) and understandable problem (cannot finish
    crossing before the signal changes) are two of three framing signals.
    Missing desired outcome, extra evidence, root cause, or consequences
    must not keep the scaffold hidden.
    """
    prompt = " ".join(
        Path("agentcore_runtime/prompts/stages/problem_identification.md")
        .read_text(encoding="utf-8")
        .split()
    )
    description = FastChatTurnOutput.model_fields["hmw_scaffold_ready"].description or ""
    schema_description = " ".join(description.split())
    assert "TWO of these THREE signals" in prompt
    assert "must not override the HMW completion rule above" in prompt
    assert "consequences still need refinement" in prompt
    assert "at least two of identifiable user" in schema_description
    assert "does not prevent true" in schema_description
    assert "not yet ready to attempt" not in schema_description.lower()
    parsed = FastChatTurnOutput.model_validate(
        {
            "mode": "coaching",
            "response_text": "What happens if they cannot finish crossing in time?",
            "recommendation": "stay",
            "citations": [],
            "hmw_scaffold_ready": True,
        }
    )
    assert parsed.recommendation == "stay"
    assert parsed.hmw_scaffold_ready is True
    messages = [
        {"role": "user", "content": _PEDESTRIAN_TWO_OF_THREE},
        {
            "role": "assistant",
            "content": parsed.response_text,
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "response_mode": "coaching",
                    "recommendation": "stay",
                    "hmw_scaffold_ready": True,
                }
            },
        },
    ]
    assert hmw_scaffold_available("problem_identification", messages) is True


@pytest.mark.parametrize("message", _WORKING_HMW_CASES)
def test_rough_working_hmw_advances_without_polish_gate(
    tmp_path: Path, message: str
) -> None:
    """A substantive but rough HMW uses the existing advance machinery."""
    turn, store, thread_id = _submit(
        tmp_path,
        message,
        recommendation=StageDecision.ADVANCE,
        auto_advance=True,
    )
    assert turn.assessment.response_mode == "coaching"
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.assessment.hmw_scaffold_ready is False
    assert turn.auto_advanced_to == "concept_generation"
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "concept_generation"


def test_solution_locked_and_empty_hmw_remain_progression_gates() -> None:
    """Prompt semantics keep substantive gaps and prescribed solutions at STAY."""
    prompt = " ".join(
        Path("agentcore_runtime/prompts/stages/problem_identification.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "solution-locked" in prompt
    assert "Template filling" in prompt
    assert "meaningful desired outcome" in prompt


def test_no_brittle_hmw_regex_evaluator() -> None:
    """Authoritative completion must not be a character-by-character HMW regex."""
    paths = (
        Path("backend/mock_provider.py"),
        Path("backend/learning/hmw.py"),
        Path("backend/learning/journey.py"),
        Path("backend/coaching/execution.py"),
        Path("backend/workflow.py"),
        Path("ui/panels/chat.py"),
        Path("ui/coach_welcome.py"),
        Path("backend/prompts/stages/problem_identification.md"),
        Path("agentcore_runtime/prompts/stages/problem_identification.md"),
    )
    for path in paths:
        assert _HMW_BRITTLE_REGEX not in path.read_text(encoding="utf-8"), path


def test_legacy_keyword_fallback_is_not_an_hmw_evaluator() -> None:
    """contribution_supports_stage remains a generic keyword fallback, not HMW."""
    source = Path("backend/learning/journey.py").read_text(encoding="utf-8")
    assert "how might we" not in source.lower()
    assert _HMW_BRITTLE_REGEX not in source


@pytest.mark.parametrize("message", _INCOMPLETE_CASES)
def test_incomplete_hmw_stays_in_problem_identification(
    tmp_path: Path, message: str
) -> None:
    """Messages without both for and so that stay in Problem Identification."""
    turn, store, thread_id = _submit(
        tmp_path,
        message,
        recommendation=StageDecision.STAY,
        auto_advance=True,
    )
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.auto_advanced_to is None
    assert turn.pending_transition is None
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "problem_identification"
    journey = metadata.get("learning_journey") or {}
    assert journey.get("current_stage") == "problem_identification"


@pytest.mark.parametrize("message", _STRUCTURAL_HMW_STAY_CASES)
def test_structural_hmw_promotes_even_when_model_stays(
    tmp_path: Path, message: str
) -> None:
    """Structural for/so that HMWs advance without semantic quality judging."""
    turn, _, thread_id = _submit(
        tmp_path,
        message,
        recommendation=StageDecision.STAY,
        auto_advance=True,
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.auto_advanced_to == "concept_generation"


def test_workable_hmw_promotes_model_stay_to_advance(
    tmp_path: Path,
) -> None:
    """A structural HMW advances even when the model keeps probing in PI."""
    turn, store, thread_id = _submit(
        tmp_path,
        _SATISFACTORY_HMW,
        recommendation=StageDecision.STAY,
        auto_advance=True,
        hmw_scaffold_ready=True,
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.assessment.hmw_scaffold_ready is False
    assert turn.auto_advanced_to == "concept_generation"
    assert turn.response_text.startswith(
        "**[Problem identification] -> [Concept generation] Ready**"
    )
    assert "workable How Might We" in turn.response_text
    assert hmw_scaffold_available(
        "problem_identification", store.get_messages(thread_id)
    ) is False
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "concept_generation"


@pytest.mark.parametrize("message", (_SATISFACTORY_HMW, _SCREENSHOT_HMW))
def test_screenshot_hmw_promotes_when_model_stays(
    tmp_path: Path, message: str
) -> None:
    """Exact live-style HMW strings advance without model cooperation."""
    turn, store, thread_id = _submit(
        tmp_path,
        message,
        recommendation=StageDecision.STAY,
        auto_advance=True,
        hmw_scaffold_ready=True,
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.auto_advanced_to == "concept_generation"
    assert hmw_scaffold_available(
        "problem_identification", store.get_messages(thread_id)
    ) is False


def test_satisfactory_hmw_advances_with_feedback_via_existing_machinery(
    tmp_path: Path,
) -> None:
    """Advance uses StageDecision + auto-advance to canonical Concept Generation."""
    turn, store, thread_id = _submit(
        tmp_path,
        _SATISFACTORY_HMW,
        recommendation=StageDecision.ADVANCE,
        auto_advance=True,
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert next_stage_id("problem_identification") == "concept_generation"
    assert turn.auto_advanced_to == "concept_generation"
    assert turn.pending_transition is None
    assert "How Might We" in turn.response_text
    assert "people you are designing for" in turn.response_text
    assert "outcome you want to achieve" in turn.response_text
    assert "You have moved to Concept Generation" not in turn.response_text
    assert turn.response_text.startswith(
        "**[Problem identification] -> [Concept generation] Ready**"
    )
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "concept_generation"
    journey = metadata.get("learning_journey") or {}
    assert journey.get("current_stage") == "concept_generation"
    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["thinking_stage"] == "concept_generation"
    assert assistant["metadata"].get("auto_advanced_to") == "concept_generation"


def test_hmw_turn_uses_one_existing_provider_assess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HMW evaluation must not add a second model or provider call."""
    calls: list[str] = []
    original = DeterministicCoachProvider.assess

    def counting(
        self: DeterministicCoachProvider, request: CoachRequest
    ) -> ProviderAssessmentResult:
        calls.append(request.student_message)
        return original(self, request)

    monkeypatch.setattr(DeterministicCoachProvider, "assess", counting)
    _submit(
        tmp_path,
        _SATISFACTORY_HMW,
        recommendation=StageDecision.ADVANCE,
        auto_advance=True,
    )
    assert calls == [_SATISFACTORY_HMW]
