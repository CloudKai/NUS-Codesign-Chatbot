"""Bounded structured artifact feedback: before/after proposals as untrusted data.

Feedback proposals never write by themselves. Only the student's explicit
acceptance — the ordinary revision-guarded artifact save — changes a document.
"""

from backend.artifact_feedback import MAX_ARTIFACT_FEEDBACK, bounded_artifact_feedback


def _feedback(**overrides) -> dict:
    value = {
        "id": "af-mock-1",
        "kind": "revise_text",
        "proposed_text": "Crossings near the school leave older pedestrians "
                         "rushing the final seconds. Name who is affected and "
                         "what success looks like.",
        "rationale": "The passage states the problem but not the affected people.",
    }
    value.update(overrides)
    return value


def test_valid_feedback_is_kept_and_server_stamps_origin() -> None:
    """A well-formed proposal survives and carries the server-resolved snapshot."""
    feedback = bounded_artifact_feedback(
        [_feedback()],
        origin_artifact_id="art-1", origin_revision=5,
        origin_paragraph=2, origin_original_text="The crossing feels unsafe.",
    )
    assert len(feedback) == 1
    proposal = feedback[0]
    assert proposal.id == "af-mock-1"
    assert proposal.base_artifact_revision == 5
    assert proposal.base_artifact_id == "art-1"
    assert proposal.paragraph == 2
    assert proposal.original_text == "The crossing feels unsafe."


def test_hostile_or_malformed_entries_are_dropped_not_fatal() -> None:
    """Unknown kinds, forged ids, oversized text and empty proposals never crash the turn."""
    hostile = [
        _feedback(id="../../etc/passwd"),
        _feedback(id="af-ok-1", kind="delete_document"),
        _feedback(id="af-ok-2", proposed_text=""),
        _feedback(id="af-ok-3", rationale=""),
        _feedback(id="af-ok-4", proposed_text="x" * 20_000),
        _feedback(id="af-ok-5", kind="revise_text"),
        "not even a dict",
        None,
    ]
    feedback = bounded_artifact_feedback(
        hostile,
        origin_artifact_id="art-1", origin_revision=5,
        origin_paragraph=None, origin_original_text="Full draft text.",
    )
    assert [item.id for item in feedback] == ["af-ok-5"]
    assert feedback[0].paragraph is None  # whole-document selection
    assert feedback[0].original_text == "Full draft text."


def test_at_most_one_proposal_survives_and_none_without_origin() -> None:
    """At most one before/after proposal per turn, and none without a resolved origin."""
    items = [_feedback(id=f"af-cap-{index}") for index in range(4)]
    feedback = bounded_artifact_feedback(
        items, origin_artifact_id="art-1", origin_revision=5,
        origin_paragraph=0, origin_original_text="t",
    )
    assert len(feedback) == MAX_ARTIFACT_FEEDBACK == 1
    assert bounded_artifact_feedback(
        items, origin_artifact_id=None, origin_revision=None,
        origin_paragraph=None, origin_original_text="t",
    ) == []
    assert bounded_artifact_feedback(None) == []
    assert bounded_artifact_feedback([]) == []


def test_artifact_feedback_coaching_turn_carries_one_proposal(tmp_path) -> None:
    """Coaching about saved artifact text proposes one stamped before/after pair."""
    from types import SimpleNamespace

    from backend.domain import ArtifactFeedbackOrigin, CoachRequest, StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.repositories import SQLitePhaseTransitionRepository
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "af.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY),
        SQLitePhaseTransitionRepository(store),
    )
    origin = ArtifactFeedbackOrigin(
        artifact_id="art-1", revision=5, paragraph=0,
        original_text="The crossing feels unsafe.",
    )
    request = CoachRequest(
        thread_id=thread_id,
        student_message="How can this paragraph be stronger?",
        current_stage="problem_identification",
        response_detail="short",
        artifact_context="Selected passage from your draft 'Unsafe crossing notes':\n"
                         "The crossing feels unsafe.",
        artifact_feedback_origin=origin,
    )

    turn = workflow.run(request)

    assert len(turn.artifact_feedback) == 1
    proposal = turn.artifact_feedback[0]
    assert proposal.base_artifact_id == "art-1"
    assert proposal.base_artifact_revision == 5
    assert proposal.paragraph == 0
    assert proposal.original_text == "The crossing feels unsafe."
    assert proposal.proposed_text.strip() != proposal.original_text.strip()

    # Lecture Q&A never proposes document edits, even with resolved context.
    lecture = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="What is a problem statement?",
        current_stage="problem_identification",
        response_detail="short",
        interaction_intent="lecture_help",
        artifact_context="Selected passage from your draft 'Unsafe crossing notes':\n"
                         "The crossing feels unsafe.",
        artifact_feedback_origin=origin,
    ))
    assert lecture.artifact_feedback == []
    # A plain coaching turn without resolved artifact context proposes nothing.
    plain = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="My draft paragraph needs work.",
        current_stage="problem_identification",
        response_detail="short",
    ))
    assert plain.artifact_feedback == []
    assert SimpleNamespace is not None  # keep the import honest about scope


def test_live_model_feedback_requires_server_resolved_origin() -> None:
    """Model artifact proposals survive only with a server-resolved snapshot origin."""
    from types import SimpleNamespace

    from backend.agentcore_provider import _model_artifact_feedback
    from backend.domain import ArtifactFeedbackOrigin, CoachRequest

    def request(origin: ArtifactFeedbackOrigin | None) -> CoachRequest:
        return CoachRequest(
            thread_id="t",
            student_message="How can this paragraph be stronger?",
            current_stage="problem_identification",
            response_detail="short",
            artifact_context="Selected passage from your draft 'Notes':\nThe crossing feels unsafe.",
            artifact_feedback_origin=origin,
        )

    output = SimpleNamespace(artifact_feedback={
        "proposed_text": "The crossing feels unsafe for older pedestrians, who "
                         "rush the final seconds; success means nobody rushes.",
        "rationale": "Names the affected people and the intended outcome.",
    })

    assert _model_artifact_feedback(request(None), output) == []
    stamped = _model_artifact_feedback(
        request(ArtifactFeedbackOrigin(artifact_id="art-1", revision=7, paragraph=1,
                                       original_text="The crossing feels unsafe.")),
        output,
    )
    assert len(stamped) == 1
    assert stamped[0].base_artifact_id == "art-1"
    assert stamped[0].base_artifact_revision == 7
    assert stamped[0].paragraph == 1
    assert stamped[0].original_text == "The crossing feels unsafe."
    # A malformed or absent model proposal yields nothing.
    assert _model_artifact_feedback(
        request(ArtifactFeedbackOrigin(artifact_id="art-1", revision=7, paragraph=1,
                                       original_text="t")),
        SimpleNamespace(artifact_feedback=None),
    ) == []
