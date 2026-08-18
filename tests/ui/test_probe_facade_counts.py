"""Instrumented workspace read counts for Streamlit page runs.

Before Phase 11 (measured 2026-08-17 on Integrate-Bedrock, in-process AppTest,
counting ``WorkspaceFacade`` method invocations):

- initial page load: 29 facade calls
  (get_messages 5, get_user_preferences 7, list_sources 3, backfill 2,
  get_thread 2, pending_transition 2, request_course_material_sync 3,
  update_user_preferences 4, list_threads 1)
- Send (includes the previous unconditional post-reply rerun): 39 facade calls
- waiting / answer-complete: not a separate Streamlit script run under AppTest
  (the mock stream finishes inside the Send run)
- explicit rerun: 21 facade calls
- citation rendering: not N+1 (no get_source per citation)

After (inner ``WorkspaceService`` / learning / sync reads, measured
2026-08-17, in-process AppTest):

- initial page load: 16
  (get_preferences 4, get_thread 3, get_messages 2, update_preferences 2,
  list_sources 1, backfill 1, get_pending 1, request 1, list_threads 1)
- Send / waiting / answer-complete: 9 in the same script run under AppTest
  (full-script Send still rebuilds Chat then Journey then Sources; the extra
  read is Journey refreshing after persist because Chat now runs first.
  Browser Send uses the composer fragment and skips Journey/Sources before
  FastAPI. Stay-turns still do not force a post-reply remount.)
- explicit rerun: 7
  (get_preferences 1, get_thread 1, get_messages 1, list_sources 1,
  backfill 1, get_pending 1, request 1)
- citation rendering: still not N+1 (get_source 0)
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from backend.learning_service import LearningProgressService
from backend.source_library import CourseMaterialSyncCoordinator
from backend.workspace_service import WorkspaceService
from ui.runtime import store as runtime_store


INNER_METHODS = (
    (WorkspaceService, "get_preferences"),
    (WorkspaceService, "update_preferences"),
    (WorkspaceService, "list_threads"),
    (WorkspaceService, "get_thread"),
    (WorkspaceService, "get_messages"),
    (WorkspaceService, "list_sources"),
    (WorkspaceService, "get_source"),
    (WorkspaceService, "backfill_legacy_sources"),
    (LearningProgressService, "get_pending"),
    (CourseMaterialSyncCoordinator, "request"),
)

BEFORE_FACADE = {
    "initial_page_load": 29,
    "send_including_forced_rerun": 39,
    "explicit_rerun": 21,
}


def install_inner_read_counter() -> tuple[Counter[str], Callable[[], None]]:
    """Count underlying workspace reads, not memoized facade wrappers."""
    counts: Counter[str] = Counter()
    patches: list[Any] = []

    def _wrap(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            counts[name] += 1
            return original(*args, **kwargs)

        return wrapped

    for owner, name in INNER_METHODS:
        original = getattr(owner, name)
        patches.append(patch.object(owner, name, _wrap(name, original)))
    original_get_source = runtime_store.get_source
    patches.append(
        patch.object(
            runtime_store,
            "get_source",
            _wrap("get_source", original_get_source),
        )
    )
    for item in patches:
        item.start()

    def stop() -> None:
        for item in patches:
            item.stop()

    return counts, stop


def snapshot(counts: Counter[str]) -> dict[str, int]:
    """Return a JSON-friendly copy of non-zero method counts."""
    return {key: int(counts[key]) for key in sorted(counts) if counts[key]}


def test_run_scoped_memo_cuts_duplicate_workspace_reads() -> None:
    """One script run should not repeat the same notebook/preference reads."""
    counts, stop = install_inner_read_counter()
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30)
        app.run()
        after_load = snapshot(counts)
        load_total = sum(after_load.values())
        counts.clear()

        app.chat_input[0].set_value("What is a design problem I could explore?").run()
        after_send = snapshot(counts)
        send_total = sum(after_send.values())
        counts.clear()

        app.run()
        after_rerun = snapshot(counts)
        rerun_total = sum(after_rerun.values())

        assert after_load.get("get_messages", 0) <= 2
        assert after_load.get("list_sources", 0) <= 1
        assert after_load.get("backfill_legacy_sources", 0) <= 1
        assert after_load.get("get_preferences", 0) <= 4
        assert after_load.get("get_pending", 0) <= 1
        assert after_load.get("request", 0) <= 1
        assert after_load.get("get_source", 0) == 0
        assert load_total == 16
        assert send_total == 9
        assert after_send.get("get_source", 0) == 0
        assert rerun_total == 7
        assert after_rerun.get("get_messages", 0) <= 2
        assert after_rerun.get("list_sources", 0) <= 1
        assert after_rerun.get("backfill_legacy_sources", 0) <= 1
        assert after_rerun.get("get_preferences", 0) <= 4
        assert after_send.get("list_sources", 0) <= 1
        assert after_send.get("backfill_legacy_sources", 0) <= 1
    finally:
        stop()


def test_citation_render_does_not_fetch_sources_per_button() -> None:
    """Citation chips reuse the panel source-id set; they are not an N+1 loop."""
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    counts, stop = install_inner_read_counter()
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
        local_store = StudentStore()
        add_text_source(
            local_store,
            app.session_state["thread_id"],
            "Lecture evidence",
            "The study included eighty students and compared two teaching methods.",
        )
        app.run()
        counts.clear()
        app.chat_input[0].set_value("What evidence does my source provide?").run()
        after_send = snapshot(counts)
        assert after_send.get("get_source", 0) == 0
    finally:
        stop()
