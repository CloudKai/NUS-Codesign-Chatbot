"""Deterministic contracts for provisional research coding beside coaching."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain import (
    ClearCode,
    CoachRequest,
    EducationalAssessment,
    FacioneBehavior,
    HolisticCandidate,
    ProviderAssessmentResult,
    ProviderCoachOutput,
    ProvisionalResearchCoding,
    ResearchCodingStatus,
    ResearchEvidence,
    StageDecision,
)
from backend.application import CoachApplicationService, _research_observation_from_coding
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.student_journey import THINKING_STAGES
from backend.student_journey import learning_review
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _assessment(stage: str) -> EducationalAssessment:
    return EducationalAssessment(
        current_stage=stage,
        contribution_summary="The student made one design-reasoning contribution.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=StageDecision.STAY,
        recommendation_rationale="One important element remains to be examined.",
        guidance_questions=["What should you examine next?"],
        learning_summary="The student is developing the design reasoning.",
    )


def _coding(*, holistic: bool = False) -> ProvisionalResearchCoding:
    return ProvisionalResearchCoding(
        coding_status=ResearchCodingStatus.CODED,
        dominant_clear=ClearCode.LOGICAL,
        facione_behaviors=[FacioneBehavior.ANALYSIS, FacioneBehavior.EVALUATION],
        ethics_concepts=[],
        evidence=[
            ResearchEvidence(
                quote="I compared the two constraints before revising the design.",
                rationale="The student explicitly relates constraints to a revision.",
                confidence=0.8,
            )
        ],
        holistic_candidate=(
            HolisticCandidate(
                score=3,
                rationale="The conversation shows clear, adequate reflective reasoning.",
                evidence_quotes=["I revised the design after testing my assumption."],
            )
            if holistic
            else None
        ),
    )


def test_research_coding_enforces_clear_status_and_facione_limit():
    with pytest.raises(ValidationError, match="requires one dominant CLEAR"):
        ProvisionalResearchCoding(coding_status="coded")
    with pytest.raises(ValidationError, match="cannot assign CLEAR"):
        ProvisionalResearchCoding(
            coding_status="partial",
            dominant_clear="explicit",
        )
    with pytest.raises(ValidationError):
        ProvisionalResearchCoding(
            coding_status="coded",
            dominant_clear="logical",
            facione_behaviors=["analysis", "evaluation", "explanation"],
        )


def test_invalid_optional_research_does_not_destroy_valid_coaching():
    output = ProviderCoachOutput.model_validate(
        {
            "response_text": "What constraint matters most?",
            "assessment": _assessment("design_specification").model_dump(mode="json"),
            "research_coding": {
                "coding_status": "coded",
                "dominant_clear": None,
                "facione_behaviors": ["not-a-facione-code"],
            },
        }
    )

    assert output.response_text == "What constraint matters most?"
    assert output.assessment.current_stage == "design_specification"
    assert output.research_coding is None


def test_holistic_candidate_is_forced_absent_outside_reflection():
    early = ProviderCoachOutput(
        response_text="Specify the design.",
        assessment=_assessment("design_specification"),
        research_coding=_coding(holistic=True),
    )
    reflection = ProviderCoachOutput(
        response_text="Reflect on the change.",
        assessment=_assessment("reflection"),
        research_coding=_coding(holistic=True),
    )

    assert early.research_coding is not None
    assert early.research_coding.holistic_candidate is None
    assert reflection.research_coding is not None
    assert reflection.research_coding.holistic_candidate is not None


def test_one_workflow_call_keeps_research_internal_and_coach_turn_stable(tmp_path):
    class CountingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            self.calls += 1
            return ProviderAssessmentResult(
                response_text="What evidence challenges this design?",
                assessment=_assessment(request.current_stage),
                research_coding=_coding(),
            )

    store = StudentStore(tmp_path / "research-workflow.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    workflow = CoachWorkflow(provider, SQLitePhaseTransitionRepository(store))
    turn = workflow.run(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared the evidence and revised the constraint.",
            current_stage="deep_analysis",
            response_detail="short",
        )
    )

    assert provider.calls == 1
    assert "research_coding" not in turn.model_dump()
    coding = workflow.provisional_research_coding(thread_id)
    assert coding is not None
    assert coding.dominant_clear is ClearCode.LOGICAL


def test_mock_returns_valid_phase_coding_and_reflection_only_holistic_candidate():
    provider = DeterministicCoachProvider(StageDecision.STAY)
    for stage in THINKING_STAGES:
        result = provider.assess(
            CoachRequest(
                thread_id=f"mock-{stage.id}",
                student_message="I made this design decision and explained why.",
                current_stage=stage.id,
                response_detail="short",
            )
        )
        coding = result.research_coding
        assert coding is not None
        assert coding.coding_status is ResearchCodingStatus.CODED
        assert coding.dominant_clear is not None
        assert len(coding.facione_behaviors) <= 2
        assert bool(coding.holistic_candidate) is (stage.id == "reflection")


def test_application_converts_research_quotes_to_offsets_and_persists_atomically(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "research-persistence.sqlite3")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY), transitions
    )
    service = CoachApplicationService(
        store,
        notebooks,
        workflow,
        LearningProgressService(store, notebooks, transitions),
    )
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={"response_detail": "short"})
    message = "I compared privacy and fairness before choosing the design."
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="long",  # Persisted Quick preference is authoritative.
        )
    )

    assert "research_coding" not in turn.model_dump()
    observations = store.list_research_observations(notebook_id=thread_id)
    assert len(observations) == 1
    observation = observations[0]
    assert observation["phase_id"] == "problem_identification"
    assert observation["coaching_profile"] == "quick"
    assert observation["provider"] == "mock"
    assert observation["evidence"] == [
        {
            "start_offset": 0,
            "end_offset": len(message),
            "rationale": (
                "The quoted contribution is the direct evidence used for this "
                "provisional coding."
            ),
            "confidence": 0.7,
        }
    ]
    serialized = str(observation)
    assert message not in serialized
    assistant = next(
        item for item in store.get_messages(thread_id) if item["role"] == "assistant"
    )
    assert message not in str(assistant["metadata"].get("research_coding"))


def test_unmatched_quote_drops_optional_research_without_affecting_coaching():
    request = CoachRequest(
        thread_id="thread",
        student_message="The persisted contribution.",
        current_stage="deep_analysis",
        response_detail="short",
        model_id="mock",
    )
    coding = _coding().model_copy(
        update={
            "evidence": [
                ResearchEvidence(
                    quote="Text not present in the contribution.",
                    rationale="This cannot be located safely.",
                    confidence=0.5,
                )
            ]
        }
    )

    assert (
        _research_observation_from_coding(coding, request, provider="mock") is None
    )


def test_auto_advance_keeps_offset_research_metadata_for_student_review(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "research-auto.sqlite3")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(
            DeterministicCoachProvider(StageDecision.ADVANCE), transitions
        ),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=True,
    )
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(
        "backend.settings.settings.student_stage_selection", False
    )

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert turn.auto_advanced_to == "concept_generation"
    messages = store.get_messages(thread_id)
    assistant = next(item for item in messages if item["role"] == "assistant")
    research = assistant["metadata"].get("research_coding")
    assert research is not None
    assert research["phase_id"] == "problem_identification"
    assert all("quote" not in item for item in research["evidence"])
    assert "evidence_quotes" not in (research.get("holistic_candidate") or {})
    review = learning_review(messages, store.get_thread(thread_id)["metadata"])
    assert review["facione_behavior_counts"]["analysis"] == 1
    assert len(store.list_research_observations(notebook_id=thread_id)) == 1
