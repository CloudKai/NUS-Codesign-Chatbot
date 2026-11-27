"""Bounded canvas-to-artifact draft proposals: reviewable synthesis as untrusted data.

A draft proposal never creates or overwrites an artifact by itself. Only the
student's explicit confirmation — the ordinary authorized artifact create —
writes anything, and it never overwrites an existing artifact.
"""

from backend.canvas_draft import bounded_canvas_draft


def _origin() -> dict:
    return {"canvas_id": "c-1", "revision": 6, "node_ids": ["n0", "n1"]}


def test_valid_draft_is_kept_and_server_stamps_origin() -> None:
    """A well-formed synthesis survives and carries the server-resolved snapshot."""
    draft = bounded_canvas_draft({
        "title": "Crossing concept brief",
        "draft_text": "Older pedestrians need a crossing that never rushes them.\n\n"
                      "The concept separates signal phases.",
        "rationale": "Synthesized from the two nodes you selected.",
    }, **_origin())
    assert draft is not None
    assert draft.title == "Crossing concept brief"
    assert draft.base_canvas_id == "c-1"
    assert draft.base_canvas_revision == 6
    assert draft.node_ids == ["n0", "n1"]
    assert draft.provenance == "coach"


def test_hostile_or_malformed_drafts_are_dropped_not_fatal() -> None:
    """Oversized, empty or non-dict proposals never crash the turn."""
    assert bounded_canvas_draft("not a dict", **_origin()) is None
    assert bounded_canvas_draft(None, **_origin()) is None
    assert bounded_canvas_draft({"title": "", "draft_text": "x"}, **_origin()) is None
    assert bounded_canvas_draft({"title": "t", "draft_text": ""}, **_origin()) is None
    assert bounded_canvas_draft({"title": "t", "draft_text": "y" * 20_000}, **_origin()) is None
    assert bounded_canvas_draft({"title": "x" * 400, "draft_text": "body"}, **_origin()) is None
    assert bounded_canvas_draft({"title": "t", "draft_text": "body",
                                 "node_ids": ["forged", "list"]}, **_origin()) is not None, \
        "model-supplied node lists are ignored, not trusted"


def test_no_draft_without_a_resolved_canvas_origin() -> None:
    """Without a resolved snapshot nothing survives, whatever the model said."""
    assert bounded_canvas_draft({"title": "t", "draft_text": "body"}) is None
    assert bounded_canvas_draft(
        {"title": "t", "draft_text": "body"}, canvas_id="c-1", revision=6, node_ids=[]
    ) is None


def test_draft_synthesis_turn_carries_one_reviewable_draft(tmp_path) -> None:
    """An explicit draft request over selected nodes returns one stamped proposal."""
    from backend.domain import CanvasContextOrigin, CoachRequest, StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.repositories import SQLitePhaseTransitionRepository
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "cd.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY),
        SQLitePhaseTransitionRepository(store),
    )
    origin = CanvasContextOrigin(canvas_id="c-1", revision=6, node_ids=["n0", "n1"])
    request = CoachRequest(
        thread_id=thread_id,
        student_message="Draft a problem brief from these nodes.",
        current_stage="problem_identification",
        response_detail="short",
        canvas_context="Node 'Unsafe crossing' (problem): left turns at peak hours\n"
                       "Node 'Students' (stakeholder): cross twice daily",
        canvas_context_origin=origin,
        canvas_selection_purpose="draft",
    )

    turn = workflow.run(request)

    assert turn.canvas_draft is not None
    draft = turn.canvas_draft
    assert draft.base_canvas_id == "c-1"
    assert draft.base_canvas_revision == 6
    assert draft.node_ids == ["n0", "n1"]
    assert draft.provenance == "coach"
    assert draft.draft_text.strip()

    # A plain discussion of the same nodes synthesizes nothing.
    discuss = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="What is weak about this node?",
        current_stage="problem_identification",
        response_detail="short",
        canvas_context="Node 'Unsafe crossing' (problem): left turns at peak hours",
        canvas_context_origin=origin,
    ))
    assert discuss.canvas_draft is None
    # A draft request without resolved context synthesizes nothing.
    unresolved = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="Draft a problem brief from these nodes.",
        current_stage="problem_identification",
        response_detail="short",
        canvas_selection_purpose="draft",
    ))
    assert unresolved.canvas_draft is None
