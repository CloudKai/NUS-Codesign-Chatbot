"""Empty slim progress fields must not blank stored notebook progress."""

from __future__ import annotations

from typing import Any

from backend.application import CoachApplicationService
from backend.coaching.progress_fields import (
    meaningful_progress_fields,
    overlay_progress_fields,
    progress_value_is_meaningful,
)
from backend.domain import (
    CoachRequest,
    CoachTurn,
    EducationalAssessment,
    FacioneDimensionScores,
    StageDecision,
    TransitionStatus,
)
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.specialists.review_orchestration import DEEP_REVIEW_SNAPSHOT_KEY
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow

_PRIOR = {
    "learning_summary": "previous summary",
    "working_conclusion": "previous conclusion",
    "understanding_change": "previous change",
    "critical_understanding": "Developing",
}
_REPLACEMENT = {
    "learning_summary": "new summary",
    "working_conclusion": "new conclusion",
    "understanding_change": "new change",
    "critical_understanding": "Strong",
}


def _service(store: StudentStore) -> LearningProgressService:
    """Return a confirmation service bound to *store*."""
    return LearningProgressService(
        store,
        SQLiteNotebookRepository(store),
        SQLitePhaseTransitionRepository(store),
    )


def _coach_service(store: StudentStore) -> CoachApplicationService:
    """Return a coach application service with the mock provider."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _seed_progress(store: StudentStore, thread_id: str) -> None:
    """Write all four notebook progress fields to a prior non-empty state."""
    store.update_thread(thread_id, metadata=dict(_PRIOR))


def _slim_assessment(**overrides: Any) -> EducationalAssessment:
    """Return a Fast Chat ADVANCE assessment with empty progress by default."""
    payload: dict[str, Any] = {
        "current_stage": "problem_identification",
        "contribution_summary": "The student named a focused question.",
        "recommendation": StageDecision.ADVANCE,
        "recommendation_rationale": "Ready to generate concepts.",
        "learning_summary": "",
        "working_conclusion": "",
        "understanding_change": "",
        "critical_understanding_level": "",
    }
    payload.update(overrides)
    return EducationalAssessment.model_validate(payload)


def _rich_assessment() -> EducationalAssessment:
    """Return a historical full assessment that still parses today."""
    return EducationalAssessment.model_validate(
        {
            "current_stage": "problem_identification",
            "contribution_summary": "The student compared two constraints.",
            "stage_assessment": "The contribution is ready to advance.",
            "evidence_identified": ["Manpower shortage"],
            "assumptions_identified": ["Families cannot fill the gap"],
            "missing_reasoning_elements": [],
            "critical_understanding_level": "Strong",
            "confidence": 0.8,
            "recommendation": "advance",
            "recommendation_rationale": "The stage readiness bar is met.",
            "guidance_questions": ["What concept should be tried first?"],
            "learning_summary": "Rich summary from review.",
            "working_conclusion": "Rich conclusion.",
            "understanding_change": "Rich change.",
            "citations": [],
            "facione_scores": {
                "analysis": 3,
                "interpretation": 3,
                "inference": 3,
                "evaluation": 3,
                "explanation": 3,
                "self_regulation": 3,
            },
            "review_strengths": ["Named a real constraint"],
            "review_improvements": ["Name who is affected"],
        }
    )


def _create_pending(
    store: StudentStore,
    thread_id: str,
    assessment: EducationalAssessment,
) -> str:
    """Persist one pending ADVANCE recommendation and return its id."""
    created = store.create_phase_transition(
        {
            "thread_id": thread_id,
            "from_stage": "problem_identification",
            "to_stage": "concept_generation",
            "assessment": assessment.model_dump(mode="json"),
        }
    )
    return str(created["id"])


def _progress(store: StudentStore, thread_id: str) -> dict[str, Any]:
    """Return top-level notebook progress fields from the stored thread."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    return {
        "learning_summary": metadata.get("learning_summary"),
        "working_conclusion": metadata.get("working_conclusion"),
        "understanding_change": metadata.get("understanding_change"),
        "critical_understanding": metadata.get("critical_understanding"),
        "thinking_stage": metadata.get("thinking_stage"),
        "current_stage": (metadata.get("learning_journey") or {}).get("current_stage"),
    }


def test_helper_drops_blank_strings_and_keeps_zero_false() -> None:
    """Whitespace-only strings are empty; 0 and False stay meaningful."""
    assert progress_value_is_meaningful("") is False
    assert progress_value_is_meaningful("   ") is False
    assert progress_value_is_meaningful(None) is False
    assert progress_value_is_meaningful("Not assessed") is True
    assert progress_value_is_meaningful(0) is True
    assert progress_value_is_meaningful(False) is True
    filtered = meaningful_progress_fields(
        {
            "learning_summary": "  kept  ",
            "working_conclusion": "\n",
            "understanding_change": 0,
            "critical_understanding": False,
            "thinking_stage": "ignored",
        }
    )
    assert filtered == {
        "learning_summary": "kept",
        "understanding_change": 0,
        "critical_understanding": False,
    }
    overlaid = overlay_progress_fields(
        {
            "learning_summary": "previous summary",
            "working_conclusion": "previous conclusion",
        },
        {"learning_summary": "", "working_conclusion": "new conclusion"},
    )
    assert overlaid["learning_summary"] == "previous summary"
    assert overlaid["working_conclusion"] == "new conclusion"


def test_confirm_advance_preserves_prior_progress_when_slim_fields_empty(
    tmp_path,
) -> None:
    """A. Slim incoming blanks must not destroy previously populated progress."""
    store = StudentStore(tmp_path / "slim-keep.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_progress(store, thread_id)
    transition_id = _create_pending(store, thread_id, _slim_assessment())

    resolved = _service(store).resolve(thread_id, transition_id, accepted=True)

    assert resolved.status is TransitionStatus.CONFIRMED
    progress = _progress(store, thread_id)
    assert progress["thinking_stage"] == "concept_generation"
    assert progress["current_stage"] == "concept_generation"
    assert progress["learning_summary"] == _PRIOR["learning_summary"]
    assert progress["working_conclusion"] == _PRIOR["working_conclusion"]
    assert progress["understanding_change"] == _PRIOR["understanding_change"]
    assert progress["critical_understanding"] == _PRIOR["critical_understanding"]


def test_confirm_advance_replaces_progress_when_incoming_is_meaningful(
    tmp_path,
) -> None:
    """B/C. A non-empty incoming value replaces each of the four fields."""
    store = StudentStore(tmp_path / "slim-replace.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_progress(store, thread_id)
    transition_id = _create_pending(
        store,
        thread_id,
        _slim_assessment(
            learning_summary=_REPLACEMENT["learning_summary"],
            working_conclusion=_REPLACEMENT["working_conclusion"],
            understanding_change=_REPLACEMENT["understanding_change"],
            critical_understanding_level=_REPLACEMENT["critical_understanding"],
        ),
    )

    _service(store).resolve(thread_id, transition_id, accepted=True)

    progress = _progress(store, thread_id)
    assert progress["thinking_stage"] == "concept_generation"
    assert progress["learning_summary"] == _REPLACEMENT["learning_summary"]
    assert progress["working_conclusion"] == _REPLACEMENT["working_conclusion"]
    assert progress["understanding_change"] == _REPLACEMENT["understanding_change"]
    assert progress["critical_understanding"] == _REPLACEMENT["critical_understanding"]


def test_stay_path_does_not_corrupt_progress(tmp_path) -> None:
    """D. Rejecting ADVANCE leaves stage and progress unchanged."""
    store = StudentStore(tmp_path / "stay-keep.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_progress(store, thread_id)
    transition_id = _create_pending(store, thread_id, _slim_assessment())

    resolved = _service(store).resolve(thread_id, transition_id, accepted=False)

    assert resolved.status is TransitionStatus.REJECTED
    progress = _progress(store, thread_id)
    assert progress["thinking_stage"] == "problem_identification"
    assert progress["current_stage"] == "problem_identification"
    assert progress["learning_summary"] == _PRIOR["learning_summary"]
    assert progress["working_conclusion"] == _PRIOR["working_conclusion"]
    assert progress["understanding_change"] == _PRIOR["understanding_change"]
    assert progress["critical_understanding"] == _PRIOR["critical_understanding"]


def test_deep_review_persist_does_not_blank_prior_progress(tmp_path) -> None:
    """E. Empty Deep Review progress fields are omitted; snapshot still writes."""
    store = StudentStore(tmp_path / "deep-keep.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_progress(store, thread_id)
    service = _coach_service(store)
    turn = CoachTurn(
        response_text="Formative review of the student's reasoning.",
        assessment=EducationalAssessment(
            current_stage="problem_identification",
            contribution_summary="The student compared two constraints.",
            learning_summary="",
            working_conclusion="  ",
            understanding_change="",
            critical_understanding_level="",
            recommendation=StageDecision.STAY,
            review_strengths=["Named a constraint"],
            review_improvements=["Name who is affected"],
        ),
    )
    request = CoachRequest(
        thread_id=thread_id,
        student_message="Please review my reasoning so far.",
        current_stage="problem_identification",
        response_detail="short",
        conversation_revision=0,
    )

    summary = service._summary_metadata_for_persist(
        turn, prepared_request=request, owned_review=True
    )

    assert "learning_summary" not in summary
    assert "working_conclusion" not in summary
    assert "understanding_change" not in summary
    assert "critical_understanding" not in summary
    snapshot = summary[DEEP_REVIEW_SNAPSHOT_KEY]
    assert snapshot["summary"] == ""
    assert snapshot["working_conclusion"] == ""
    assert snapshot["reviewed_stage_id"] == "problem_identification"
    assert snapshot["strengths"] == ["Named a constraint"]

    store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=0,
        user_content="Please review my reasoning so far.",
        user_metadata={},
        assistant_content=turn.response_text,
        assistant_metadata={"assessment": turn.assessment.persisted_mapping()},
        summary_metadata=summary,
        review_counter_qualifying=False,
        review_counter_deep_succeeded=True,
    )
    progress = _progress(store, thread_id)
    assert progress["learning_summary"] == _PRIOR["learning_summary"]
    assert progress["working_conclusion"] == _PRIOR["working_conclusion"]
    assert progress["understanding_change"] == _PRIOR["understanding_change"]
    assert progress["critical_understanding"] == _PRIOR["critical_understanding"]


def test_historical_rich_assessment_still_writes_progress_on_confirm(
    tmp_path,
) -> None:
    """F. A full historical assessment still parses and still writes values."""
    store = StudentStore(tmp_path / "rich-write.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_progress(store, thread_id)
    assessment = _rich_assessment()
    assert assessment.facione_scores == FacioneDimensionScores(
        analysis=3,
        interpretation=3,
        inference=3,
        evaluation=3,
        explanation=3,
        self_regulation=3,
    )
    transition_id = _create_pending(store, thread_id, assessment)

    _service(store).resolve(thread_id, transition_id, accepted=True)

    progress = _progress(store, thread_id)
    assert progress["thinking_stage"] == "concept_generation"
    assert progress["learning_summary"] == "Rich summary from review."
    assert progress["working_conclusion"] == "Rich conclusion."
    assert progress["understanding_change"] == "Rich change."
    assert progress["critical_understanding"] == "Strong"


def test_fast_chat_persist_omits_empty_progress_fields(tmp_path) -> None:
    """Non-review persist uses the shared helper rather than writing blanks."""
    store = StudentStore(tmp_path / "persist-slim.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _coach_service(store)
    turn = CoachTurn(
        response_text="What assumption is carrying this preference?",
        assessment=_slim_assessment(recommendation=StageDecision.STAY),
    )
    request = CoachRequest(
        thread_id=thread_id,
        student_message="I compared two constraints.",
        current_stage="problem_identification",
        response_detail="short",
    )
    summary = service._summary_metadata_for_persist(
        turn, prepared_request=request, owned_review=False
    )
    assert "learning_summary" not in summary
    assert "working_conclusion" not in summary
    assert "understanding_change" not in summary
    assert "critical_understanding" not in summary
