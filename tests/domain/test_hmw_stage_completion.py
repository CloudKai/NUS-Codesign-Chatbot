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
    store: StudentStore, recommendation: StageDecision, *, auto_advance: bool
) -> CoachApplicationService:
    """Return a mock coaching service with an explicit stay/advance decision."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(recommendation), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance,
    )


def _submit(
    tmp_path: Path,
    message: str,
    *,
    recommendation: StageDecision,
    auto_advance: bool,
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
    service = _service(store, recommendation, auto_advance=auto_advance)
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
        assert "Equivalent prose that states user, problem, and outcome" in collapsed
        assert "recommendation=advance" in collapsed
        assert "Concept Generation" in collapsed
        assert "The application remains the stage authority" in collapsed
        assert "Do not write the finished HMW" in collapsed
        assert "solution-locked" in collapsed
        assert "must not override the HMW readiness rule above" in collapsed
        assert (
            "hmw_scaffold_ready=true even if root cause, additional evidence, "
            "scope, or consequences still need refinement"
        ) in collapsed
        assert "NOT prerequisites for showing the HMW scaffold" in collapsed
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
    assert "must not override the HMW readiness rule above" in prompt
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
    """Stay recommendations leave the notebook on Problem Identification."""
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


def test_satisfactory_hmw_does_not_advance_without_coach_recommendation(
    tmp_path: Path,
) -> None:
    """A well-formed HMW string is not enough; the coach recommendation is authority."""
    turn, store, thread_id = _submit(
        tmp_path,
        _SATISFACTORY_HMW,
        recommendation=StageDecision.STAY,
        auto_advance=True,
    )
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.auto_advanced_to is None
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "problem_identification"


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
    assert turn.response_text.startswith("**Concept generation**")
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
