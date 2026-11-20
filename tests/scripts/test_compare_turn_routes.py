"""Regression checks for offline routing precedence and passage fact scoring."""

import pytest

from scripts.evals import compare_turn_routes as routes
from scripts.evals import evaluate_passage_support as passages


def predict_both(_: str) -> dict[str, dict[str, float]]:
    """Return a deliberately overconfident mixed-source, factual response."""
    return {
        "scope": {"none": 0.0, "course": 0.0, "both": 1.0, "student_upload": 0.0},
        "mode": {"lecture_help": 1.0, "project_coaching": 0.0},
    }


def test_runtime_context_and_unavailable_scope() -> None:
    row = routes.inputs()["fresh"][0]
    assert row["history"][-1]["text"] in routes.state(row)
    decision = routes.observe(dict(row, follow_up=False), predict_both)
    assert decision["follow_up"]
    assert routes.apply(decision, "scope", 0.5) == (decision["gate"], "unavailable_source")
    opening = routes.observe(dict(row, follow_up=True, history=[]), predict_both)
    assert routes.apply(opening, "scope", 0.5) == (opening["gate"], "opening_without_file")


@pytest.mark.parametrize(
    ("message", "mode", "attach", "scope", "answer"),
    [
        ("move me to concept generation", None, False, "none", "project_coaching"),
        ("what stage am I in", None, False, "none", "lecture_help"),
        (
            "what's missing from the attached persona?",
            None,
            True,
            "student_upload",
            "project_coaching",
        ),
        ("help me plan tomorrow", "lecture_help", False, "both", "lecture_help"),
        ("help me plan tomorrow", "project_coaching", False, "none", "project_coaching"),
    ],
)
def test_explicit_scope_overrides(
    message: str, mode: str | None, attach: bool, scope: str, answer: str
) -> None:
    file = {"title": "Bench notes", "filename": "bench.pdf"}
    row = dict(
        id="contract",
        stage="problem_identification",
        message=message,
        explicit_mode=mode,
        history=[],
        selected_sources=[file],
        attachments=[file] if attach else [],
        expected_scope=scope,
    )
    observed = routes.observe(row, predict_both)
    assert observed["protected"]
    assert routes.apply(observed, "scope", 0)[0] == scope
    assert routes.apply(observed, "mode", 0)[0] == answer


def test_fact_union_requires_every_fact() -> None:
    facts = ["date", "weight"]
    assert passages.coverage([{"facts": []}], facts) == "insufficient"
    assert passages.coverage([{"facts": [0]}, {"facts": [0]}], facts) == "partial"
    assert passages.coverage([{"facts": [0]}, {"facts": [1]}], facts) == "sufficient"
