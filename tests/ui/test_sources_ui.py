"""UI helpers and rerun-scope contracts for the Sources panel."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import ui.sources as sources_module
from ui.sources import _select_all_checkbox_state, _sort_course_sources_by_name


def test_select_all_checkbox_has_unchecked_indeterminate_and_checked_states() -> None:
    assert _select_all_checkbox_state(0, 3) == (False, False)
    assert _select_all_checkbox_state(1, 3) == (False, True)
    assert _select_all_checkbox_state(2, 3) == (False, True)
    assert _select_all_checkbox_state(3, 3) == (True, False)
    assert _select_all_checkbox_state(1, 0) == (False, False)


def test_course_sources_sorted_numerically() -> None:
    sources = [
        {"title": "Week 10 Storytelling.pdf"},
        {"title": "Week 2 Design.pdf"},
        {"title": "Week 1 Introduction.pdf"},
    ]
    ordered = _sort_course_sources_by_name(sources)
    assert [item["title"] for item in ordered] == [
        "Week 1 Introduction.pdf",
        "Week 2 Design.pdf",
        "Week 10 Storytelling.pdf",
    ]


def test_source_delete_stays_fragment_local_and_defers_sync_remount() -> None:
    """Deleting a source cannot immediately escalate its fragment interaction."""
    source = Path(inspect.getfile(sources_module)).read_text(encoding="utf-8")
    delete_block = source.split(
        '                            "Delete permanently",',
        1,
    )[1].split("    def render_pending_upload_card", 1)[0]

    assert "store.delete_source(" in delete_block
    assert "_defer_sources_local_action(" in delete_block
    assert "_SOURCE_LOCAL_ACTION_DEFER_KEY" in source
    assert "rerun_fragment()" in delete_block
    assert delete_block.index("_defer_sources_local_action(") < delete_block.index(
        "rerun_fragment()"
    )
    assert "rerun_app()" not in delete_block


def test_source_polling_completion_honors_local_action_defer(monkeypatch) -> None:
    """A deferred delete keeps the timed fragment from remounting the app."""

    class _SessionState(dict[str, object]):
        """Attribute-compatible stand-in for Streamlit session state."""

        def __getattr__(self, key: str) -> object:
            return self[key]

        def __setattr__(self, key: str, value: object) -> None:
            self[key] = value

    class _DoneFuture:
        """Minimal completed future for the polling handoff contract."""

        def done(self) -> bool:
            return True

    class _Store:
        """Minimal store seam used by the Sources polling fragment."""

        def request_course_material_sync(self, _thread_id: str) -> _DoneFuture:
            return _DoneFuture()

    state = _SessionState({"thread_id": "thread-a"})
    monkeypatch.setattr(
        sources_module,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(sources_module, "_render_sources_panel_body", lambda: None)
    monkeypatch.setattr(sources_module, "coach_turn_is_streaming", lambda: False)
    monkeypatch.setattr(sources_module, "pending_source_uploads", lambda _thread_id: [])
    monkeypatch.setattr(sources_module, "store", _Store())
    reruns: list[str] = []
    monkeypatch.setattr(sources_module, "rerun_app", lambda: reruns.append("app"))

    sources_module._defer_sources_local_action("thread-a")
    polling = sources_module._render_sources_panel_polling.__wrapped__
    polling()

    assert reruns == []
    assert "_sources_defer_local_action_for_thread" not in state

    # The next completed poll follows the original course-sync handoff.
    polling()
    assert reruns == ["app"]


def test_source_stable_fragment_clears_leftover_local_action_defer(monkeypatch) -> None:
    """Stable mode removes a token that did not reach the polling branch."""

    class _SessionState(dict[str, object]):
        """Attribute-compatible stand-in for Streamlit session state."""

        def __getattr__(self, key: str) -> object:
            return self[key]

        def __setattr__(self, key: str, value: object) -> None:
            self[key] = value

    class _DoneFuture:
        """Minimal completed future for the stable fragment contract."""

        def done(self) -> bool:
            return True

    class _Store:
        """Minimal store seam used by the Sources stable fragment."""

        def request_course_material_sync(self, _thread_id: str) -> _DoneFuture:
            return _DoneFuture()

    state = _SessionState(
        {
            "thread_id": "thread-a",
            "_sources_defer_local_action_for_thread": "thread-a",
        }
    )
    monkeypatch.setattr(
        sources_module,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(sources_module, "_render_sources_panel_body", lambda: None)
    monkeypatch.setattr(sources_module, "coach_turn_is_streaming", lambda: False)
    monkeypatch.setattr(sources_module, "pending_source_uploads", lambda _thread_id: [])
    monkeypatch.setattr(sources_module, "store", _Store())
    monkeypatch.setattr(sources_module, "rerun_app", lambda: None)

    stable = sources_module._render_sources_panel_stable.__wrapped__
    stable()

    assert "_sources_defer_local_action_for_thread" not in state
