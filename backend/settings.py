from __future__ import annotations

"""Application settings loaded from the project ``.env`` file.

Fallback defaults match ``.env.example``: mock provider, confirmation-mode
stage progression, and project-root-relative data paths so a missing ``.env``
stays cost-safe.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _project_path(name: str, default: str) -> Path:
    """Resolve a configured path relative to the project when it is not absolute."""
    configured = Path(os.getenv(name, default)).expanduser()
    return (configured if configured.is_absolute() else PROJECT_ROOT / configured).resolve()


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = _project_path("APP_DATA_DIR", "data")
    database_path: Path = _project_path("APP_DATABASE_PATH", "data/co_design.sqlite3")
    files_dir: Path = _project_path("APP_FILES_DIR", "data/files")
    workspaces_dir: Path = _project_path("APP_WORKSPACES_DIR", "data/workspaces")
    lecture_notes_dir: Path = _project_path("LECTURE_NOTES_DIR", "lecture_notes")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    enable_local_code_execution: bool = _boolean("ENABLE_LOCAL_CODE_EXECUTION", False)
    mock_openai: bool = _boolean("MOCK_OPENAI", True)
    mock_recommend_advance: bool = _boolean("MOCK_RECOMMEND_ADVANCE", False)
    auto_advance_stages: bool = _boolean("AUTO_ADVANCE_STAGES", False)
    model_provider: str = os.getenv("MODEL_PROVIDER", "mock").strip().lower()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "gpt-oss:20b")
    ollama_embedding_model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
    api_base_url: str = os.getenv("CO_DESIGN_API_URL", "http://127.0.0.1:8000")
    public_api_base_url: str = os.getenv(
        "CO_DESIGN_PUBLIC_API_URL",
        os.getenv("CO_DESIGN_API_URL", "http://127.0.0.1:8000"),
    )
    ui_base_url: str = os.getenv("CO_DESIGN_UI_URL", "http://127.0.0.1:8501")
    use_local_api: bool = _boolean("USE_LOCAL_API", True)
    # Opaque FastAPI application session (not Cognito token lifetime).
    app_session_ttl_seconds: int = int(os.getenv("APP_SESSION_TTL_SECONDS", "2592000"))
    app_session_cookie_name: str = os.getenv(
        "APP_SESSION_COOKIE_NAME", "co_design_session"
    ).strip() or "co_design_session"
    app_session_cookie_secure: bool = _boolean("APP_SESSION_COOKIE_SECURE", False)
    # Empty when unset so Cognito config can fall through to secrets.toml or
    # derive from CO_DESIGN_PUBLIC_API_URL (never hard-code a local override).
    cognito_redirect_uri: str = os.getenv("COGNITO_REDIRECT_URI", "").strip()
    oauth_state_cookie_name: str = os.getenv(
        "OAUTH_STATE_COOKIE_NAME", "co_design_oauth_state"
    ).strip() or "co_design_oauth_state"
    max_tool_iterations: int = int(os.getenv("MAX_TOOL_ITERATIONS", "3"))
    max_files: int = int(os.getenv("MAX_FILES_PER_MESSAGE", "5"))
    max_lecture_notes: int = int(os.getenv("MAX_LECTURE_NOTES", "20"))
    max_course_material_size_mb: int = int(
        os.getenv("MAX_COURSE_MATERIAL_SIZE_MB", "50")
    )
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
    python_timeout_seconds: int = int(os.getenv("PYTHON_TIMEOUT_SECONDS", "30"))
    default_model: str = os.getenv("DEFAULT_CHAT_MODEL", "gpt-5.6-luna")
    default_reasoning_effort: str = os.getenv("DEFAULT_REASONING_EFFORT", "low")
    image_model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.files_dir,
            self.workspaces_dir,
            self.lecture_notes_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
