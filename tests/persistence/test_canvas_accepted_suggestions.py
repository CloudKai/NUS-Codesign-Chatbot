"""Canvas snapshots persist bounded accepted suggestion ids without changing legacy graphs."""

from pathlib import Path

import pytest

from backend.student_store import StudentStore


def _store(tmp_path: Path) -> StudentStore:
    root = StudentStore(tmp_path / "canvas-suggestions.sqlite3")
    with root._connect() as connection:
        connection.execute(
            "INSERT INTO users (id, identifier, role, preferences_text, created_at) "
            "VALUES ('user-alice', 'cognito:alice', 'student', '{}', "
            "'2026-01-01T00:00:00Z')"
        )
        connection.commit()
    return StudentStore(root.path, identifier="cognito:alice")


def _graph(*accepted: object) -> dict[str, object]:
    graph: dict[str, object] = {"nodes": [
        {"id": "n0", "kind": "concept", "title": "Crossing", "description": "",
         "x": 0.0, "y": 0.0},
        {"id": "n1", "kind": "stakeholder", "title": "Students", "description": "",
         "x": 100.0, "y": 0.0},
    ], "edges": []}
    if accepted:
        graph["accepted_suggestion_ids"] = list(accepted)
    return graph


def test_accepted_suggestion_ids_round_trip_through_create_update_and_versions(
    tmp_path: Path,
) -> None:
    """A save records accepted ids once each; every checkpoint preview keeps them."""
    store = _store(tmp_path)
    thread = store.create_thread(
        name="Maps", model_id="mock", support_mode="critical-thinking",
    )

    created = store.create_canvas(
        thread, "Concept map", _graph("sg-a", "sg-b", "sg-a"),
    )
    assert created["graph"]["accepted_suggestion_ids"] == ["sg-a", "sg-b"]
    assert created["revision"] == 1

    saved = store.update_canvas(
        created["id"], _graph("sg-a", "sg-b", "sg-c"), created["revision"],
    )
    assert saved["graph"]["accepted_suggestion_ids"] == ["sg-a", "sg-b", "sg-c"]

    first = store.get_canvas_version(created["id"], 1)
    second = store.get_canvas_version(created["id"], 2)
    assert first is not None and first["graph"]["accepted_suggestion_ids"] == [
        "sg-a", "sg-b",
    ]
    assert second is not None and second["graph"]["accepted_suggestion_ids"] == [
        "sg-a", "sg-b", "sg-c",
    ]


def test_legacy_graph_without_accepted_ids_still_compares_exactly(tmp_path: Path) -> None:
    """Absent ids stay absent so every pre-suggestion snapshot is unchanged."""
    store = _store(tmp_path)
    thread = store.create_thread(
        name="Maps", model_id="mock", support_mode="critical-thinking",
    )
    legacy = _graph()

    created = store.create_canvas(thread, "Legacy map", legacy)
    assert created["graph"] == legacy
    assert "accepted_suggestion_ids" not in created["graph"]

    saved = store.update_canvas(created["id"], legacy, created["revision"])
    assert saved["graph"] == legacy
    assert "accepted_suggestion_ids" not in saved["graph"]


@pytest.mark.parametrize(
    ("accepted", "message"),
    [
        ("sg-a", "must be a list"),
        ([7], "bounded non-empty string"),
        ([""], "bounded non-empty string"),
        (["x" * 65], "bounded non-empty string"),
        ([f"sg-{index}" for index in range(1_001)], "too many accepted suggestion ids"),
    ],
)
def test_malformed_accepted_suggestion_ids_are_rejected(
    tmp_path: Path, accepted: object, message: str,
) -> None:
    """Only a bounded list of bounded non-empty ids may be stored."""
    store = _store(tmp_path)
    thread = store.create_thread(
        name="Maps", model_id="mock", support_mode="critical-thinking",
    )
    graph = _graph()
    graph["accepted_suggestion_ids"] = accepted

    with pytest.raises(ValueError, match=message):
        store.create_canvas(thread, "Broken map", graph)
