"""Create a persisted notebook for UI checks that exercise existing chat state."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from backend.models import DEFAULT_CHAT_MODEL_ID
from backend.student_store import StudentStore
from backend.student_support import DEFAULT_SUPPORT_MODE
from ui.coach_welcome import seed_coach_welcome


def ensure_saved_notebook() -> None:
    """Seed one old-style saved notebook when the isolated test DB is empty."""
    store = StudentStore()
    if store.list_threads():
        return
    thread_id = store.create_thread(
        name="Untitled notebook",
        model_id=DEFAULT_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
    )
    seed_coach_welcome(store, thread_id)


def saved_app() -> AppTest:
    """Mount Streamlit with an existing notebook for legacy UI workflows."""
    ensure_saved_notebook()
    return AppTest.from_file("streamlit_app.py", default_timeout=30).run()
