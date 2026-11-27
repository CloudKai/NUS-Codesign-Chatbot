"""Bounded structured canvas suggestions: validated untrusted proposals.

Suggestions are proposals only. They never execute database operations here —
acceptance is the student's explicit ordinary canvas save.
"""

from backend.canvas_suggestions import MAX_CANVAS_SUGGESTIONS, bounded_canvas_suggestions


def _node_suggestion(**overrides) -> dict:
    value = {
        "id": "sg-mock-node-1",
        "kind": "new_node",
        "node_kind": "concept",
        "title": "Safer intersection concept",
        "description": "Grade-separated pedestrian crossing",
        "rationale": "The selected problem node lacks a candidate concept.",
    }
    value.update(overrides)
    return value


def test_valid_suggestion_is_kept_and_server_stamps_base_revision() -> None:
    """A well-formed proposal survives and carries the server-resolved revision."""
    suggestions = bounded_canvas_suggestions(
        [_node_suggestion()], origin_revision=7, origin_canvas_id="c-9"
    )
    assert len(suggestions) == 1
    kept = suggestions[0]
    assert kept.id == "sg-mock-node-1"
    assert kept.kind == "new_node"
    assert kept.base_canvas_revision == 7
    assert kept.base_canvas_id == "c-9"


def test_hostile_or_malformed_entries_are_dropped_not_fatal() -> None:
    """Unknown kinds, forged ids, oversized text and bad relations never crash the turn."""
    hostile = [
        _node_suggestion(id="../../etc/passwd"),
        _node_suggestion(id="sg-ok-1", kind="delete_stage"),
        _node_suggestion(id="sg-ok-2", node_kind="admin_tool"),
        _node_suggestion(id="sg-ok-3", rationale=""),
        _node_suggestion(id="sg-ok-4", title="x" * 400),
        _node_suggestion(id="sg-ok-5", kind="new_edge"),
        _node_suggestion(id="sg-ok-6", kind="new_edge", relation="executes_sql"),
        _node_suggestion(id="sg-ok-7", kind="new_edge", relation="supports",
                         source_node_id="n0", target_node_id="n1"),
        "not even a dict",
        None,
    ]
    suggestions = bounded_canvas_suggestions(hostile, origin_revision=3)
    assert [item.id for item in suggestions] == ["sg-ok-7"]
    edge = suggestions[0]
    assert edge.kind == "new_edge"
    assert edge.relation == "supports"
    assert edge.base_canvas_revision == 3


def test_suggestions_are_bounded_and_deduplicated() -> None:
    """At most five proposals survive and duplicate ids collapse to one."""
    items = [_node_suggestion(id=f"sg-dup-{index % 3}") for index in range(20)]
    suggestions = bounded_canvas_suggestions(items)
    assert len(suggestions) == 3
    assert len({item.id for item in suggestions}) == len(suggestions)
    distinct = [_node_suggestion(id=f"sg-cap-{index}") for index in range(9)]
    assert len(bounded_canvas_suggestions(distinct)) == MAX_CANVAS_SUGGESTIONS
    assert bounded_canvas_suggestions([]) == []
    assert bounded_canvas_suggestions(None) == []


def test_canvas_coaching_turn_carries_one_deterministic_suggestion(tmp_path) -> None:
    """Coaching about a selected canvas node proposes one stamped node suggestion."""
    from backend.domain import CanvasContextOrigin, CoachRequest, StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.repositories import SQLitePhaseTransitionRepository
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "sg.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY),
        SQLitePhaseTransitionRepository(store),
    )
    request = CoachRequest(
        thread_id=thread_id,
        student_message="What is weak about this node?",
        current_stage="problem_identification",
        response_detail="short",
        canvas_context="Node 'Unsafe crossing' (problem): left turns at peak hours",
        canvas_context_origin=CanvasContextOrigin(canvas_id="c-1", revision=4),
    )

    turn = workflow.run(request)

    assert len(turn.canvas_suggestions) == 1
    suggestion = turn.canvas_suggestions[0]
    assert suggestion.kind == "new_node"
    assert suggestion.title.startswith("Idea:")
    assert suggestion.base_canvas_revision == 4
    # The stable identity is deterministic for the same proposed content.
    replay = workflow.run(request)
    assert replay.canvas_suggestions[0].id == suggestion.id


def test_turn_without_canvas_context_has_no_suggestions(tmp_path) -> None:
    """Ordinary coaching and lecture Q&A never invent canvas proposals."""
    from backend.domain import CanvasContextOrigin, CoachRequest, StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.repositories import SQLitePhaseTransitionRepository
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "plain.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY),
        SQLitePhaseTransitionRepository(store),
    )
    coaching = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="My problem is unsafe pedestrian crossings.",
        current_stage="problem_identification",
        response_detail="short",
    ))
    lecture = workflow.run(CoachRequest(
        thread_id=thread_id,
        student_message="What is a stakeholder map?",
        current_stage="problem_identification",
        response_detail="short",
        interaction_intent="lecture_help",
        canvas_context="Node 'Unsafe crossing' (problem): left turns",
        canvas_context_origin=CanvasContextOrigin(canvas_id="c-1", revision=4),
    ))
    assert coaching.canvas_suggestions == []
    assert lecture.canvas_suggestions == []


def test_live_model_proposals_require_server_resolved_origin_and_stay_bounded() -> None:
    """Model canvas proposals survive only with a server-resolved snapshot origin."""
    from types import SimpleNamespace

    from backend.agentcore_provider import _model_canvas_suggestions
    from backend.domain import CanvasContextOrigin, CoachRequest

    def request(origin: CanvasContextOrigin | None) -> CoachRequest:
        return CoachRequest(
            thread_id="t",
            student_message="What is weak about this node?",
            current_stage="problem_identification",
            response_detail="short",
            canvas_context="Node 'Unsafe crossing' (problem): left turns",
            canvas_context_origin=origin,
        )

    output = SimpleNamespace(canvas_suggestions=[{
        "id": "sg-live-1",
        "kind": "new_node",
        "node_kind": "concept",
        "title": "Protected crossing phase",
        "rationale": "The selected problem has no candidate concept yet.",
    }, {
        "id": "sg-live-2",
        "kind": "new_edge",
        "relation": "supports",
        "source_node_id": "n0",
        "target_node_id": "n1",
        "rationale": "Relates the concept back to the stakeholder.",
    }])

    # No resolved origin: nothing a model said survives.
    assert _model_canvas_suggestions(request(None), output) == []
    # With the origin: bounded, validated, revision-stamped proposals.
    stamped = _model_canvas_suggestions(
        request(CanvasContextOrigin(canvas_id="c-1", revision=9)), output
    )
    assert [item.id for item in stamped] == ["sg-live-1", "sg-live-2"]
    assert all(item.base_canvas_revision == 9 for item in stamped)
    # A model claiming its own base revision cannot override the server.
    hostile = SimpleNamespace(canvas_suggestions=[{
        "id": "sg-live-3",
        "kind": "new_node",
        "node_kind": "concept",
        "title": "Forged revision",
        "rationale": "Claims an origin it never saw.",
        "base_canvas_revision": 1,
    }])
    validated = _model_canvas_suggestions(
        request(CanvasContextOrigin(canvas_id="c-1", revision=12)), hostile
    )
    assert validated[0].base_canvas_revision == 12
