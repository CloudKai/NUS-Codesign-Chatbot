"""Shared pytest configuration for Co-design Chatbot automated tests.

Module-level environment defaults keep collection cost-safe before backend
imports. An autouse fixture then isolates each test onto its own temporary
data/database/files tree and clears Streamlit resource caches.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Bootstrap paths before backend.settings is imported during collection.
_BOOTSTRAP_ROOT = Path(tempfile.mkdtemp(prefix="co-design-tests-bootstrap-"))
os.environ["MOCK_OPENAI"] = "true"
os.environ["MODEL_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""
# Default AppTest path uses in-process coaching; API-mode UI tests opt in.
os.environ["USE_LOCAL_API"] = "false"
os.environ["AUTO_ADVANCE_STAGES"] = "false"
os.environ["DEFAULT_CHAT_MODEL"] = "gpt-5.6-luna"
os.environ["OPENAI_CHAT_MODEL"] = "gpt-5.6-luna"
os.environ["DEFAULT_REASONING_EFFORT"] = "low"
os.environ["APP_DATA_DIR"] = str(_BOOTSTRAP_ROOT)
os.environ["APP_DATABASE_PATH"] = str(_BOOTSTRAP_ROOT / "co_design.sqlite3")
os.environ["APP_FILES_DIR"] = str(_BOOTSTRAP_ROOT / "files")
os.environ["APP_WORKSPACES_DIR"] = str(_BOOTSTRAP_ROOT / "workspaces")
os.environ["LECTURE_NOTES_DIR"] = str(_BOOTSTRAP_ROOT / "lecture_notes")


def _clear_streamlit_runtime_caches() -> None:
    """Drop cached Streamlit store/workspace/coach/client so each test gets a fresh path."""
    try:
        from ui import runtime
    except Exception:
        return
    for name in ("resources", "course_material_sync", "local_api_client"):
        cached = getattr(runtime, name, None)
        clear = getattr(cached, "clear", None)
        if callable(clear):
            clear()


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give every test its own data directories and assert mock-mode cost guards."""
    root = tmp_path / "runtime"
    root.mkdir()
    database = root / "co_design.sqlite3"
    files_dir = root / "files"
    workspaces_dir = root / "workspaces"
    lecture_notes_dir = root / "lecture_notes"
    for directory in (files_dir, workspaces_dir, lecture_notes_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MOCK_OPENAI", "true")
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("USE_LOCAL_API", "false")
    monkeypatch.setenv("AUTO_ADVANCE_STAGES", "false")
    monkeypatch.setenv("APP_DATA_DIR", str(root))
    monkeypatch.setenv("APP_DATABASE_PATH", str(database))
    monkeypatch.setenv("APP_FILES_DIR", str(files_dir))
    monkeypatch.setenv("APP_WORKSPACES_DIR", str(workspaces_dir))
    monkeypatch.setenv("LECTURE_NOTES_DIR", str(lecture_notes_dir))

    from backend import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "data_dir", root.resolve())
    monkeypatch.setattr(settings_module.settings, "database_path", database.resolve())
    monkeypatch.setattr(settings_module.settings, "files_dir", files_dir.resolve())
    monkeypatch.setattr(
        settings_module.settings, "workspaces_dir", workspaces_dir.resolve()
    )
    monkeypatch.setattr(
        settings_module.settings, "lecture_notes_dir", lecture_notes_dir.resolve()
    )
    monkeypatch.setattr(settings_module.settings, "openai_api_key", "")
    monkeypatch.setattr(settings_module.settings, "mock_openai", True)
    monkeypatch.setattr(settings_module.settings, "model_provider", "mock")
    monkeypatch.setattr(settings_module.settings, "use_local_api", False)
    monkeypatch.setattr(settings_module.settings, "auto_advance_stages", False)

    assert settings_module.settings.model_provider == "mock"
    assert settings_module.settings.mock_openai is True
    assert settings_module.settings.openai_api_key == ""
    assert os.environ.get("OPENAI_API_KEY") == ""

    # Default UI tests run as an authenticated Cognito student so existing
    # AppTest suites keep exercising the full application. Auth-gate tests
    # override ``is_logged_in`` / ``authenticated_user`` explicitly.
    import streamlit as st

    from ui import auth_gate as auth_gate_module

    _default_user = {
        "id": "test-user-id",
        "cognito_sub": "test-cognito-sub",
        "email": "test.student@example.edu",
        "display_name": "Test",
        "role": "student",
    }

    monkeypatch.setattr(auth_gate_module, "is_logged_in", lambda: True)
    monkeypatch.setattr(auth_gate_module, "authenticated_user", lambda: dict(_default_user))
    monkeypatch.setattr(
        auth_gate_module,
        "current_user_claims",
        lambda: {
            "sub": "test-cognito-sub",
            "email": "test.student@example.edu",
            "given_name": "Test",
            "name": "Test Student",
        },
    )

    # App data is scoped to cognito:{sub}; keep direct StudentStore() helpers
    # in tests on the same owner as the authenticated UI.
    from backend.student_store import StudentStore

    _student_store_init = StudentStore.__init__

    def _patched_student_store_init(
        self,
        path=None,
        identifier="cognito:test-cognito-sub",
    ):
        _student_store_init(self, path=path, identifier=identifier)

    monkeypatch.setattr(StudentStore, "__init__", _patched_student_store_init)

    _clear_streamlit_runtime_caches()
    yield root
    _clear_streamlit_runtime_caches()
