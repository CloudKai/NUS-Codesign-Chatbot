from __future__ import annotations

"""Application settings loaded from the project ``.env`` file.

Fallback defaults match ``.env.example``: mock provider, confirmation-mode
stage progression, SQLite + local files, and project-root-relative data paths
so a missing ``.env`` stays cost-safe. Production selects Aurora DSQL and S3
via ``DATABASE_PROVIDER`` / ``FILE_STORAGE_PROVIDER``.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
try:
    load_dotenv(PROJECT_ROOT / ".env")
except OSError:
    # Private .env may be unreadable in some sandboxed test environments.
    pass


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
    # Storage providers: local defaults keep SQLite + filesystem for development.
    database_provider: str = field(
        default_factory=lambda: os.getenv("DATABASE_PROVIDER", "sqlite").strip().lower()
    )
    file_storage_provider: str = field(
        default_factory=lambda: os.getenv(
            "FILE_STORAGE_PROVIDER", "local"
        ).strip().lower()
    )
    aws_region: str = field(
        default_factory=lambda: os.getenv("AWS_REGION", "us-west-2").strip()
    )
    dsql_endpoint: str = field(
        default_factory=lambda: os.getenv("DSQL_ENDPOINT", "").strip()
    )
    dsql_database: str = field(
        default_factory=lambda: os.getenv("DSQL_DATABASE", "postgres").strip()
        or "postgres"
    )
    dsql_user: str = field(
        default_factory=lambda: os.getenv("DSQL_USER", "co_design_app").strip()
        or "co_design_app"
    )
    user_uploads_bucket: str = field(
        default_factory=lambda: os.getenv("USER_UPLOADS_BUCKET", "").strip()
    )
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
    # Cognito owns the browser session via HttpOnly refresh + ID-token cookies.
    # Cookie Max-Age for refresh defaults to 30d; Cognito app-client refresh
    # token validity is authoritative (~30d when configured that way).
    cognito_refresh_cookie_name: str = os.getenv(
        "COGNITO_REFRESH_COOKIE_NAME", "co_design_refresh"
    ).strip() or "co_design_refresh"
    cognito_id_token_cookie_name: str = os.getenv(
        "COGNITO_ID_TOKEN_COOKIE_NAME", "co_design_id"
    ).strip() or "co_design_id"
    cognito_refresh_cookie_max_age: int = int(
        os.getenv("COGNITO_REFRESH_COOKIE_MAX_AGE", "2592000")
    )
    cognito_id_token_cookie_max_age: int = int(
        os.getenv("COGNITO_ID_TOKEN_COOKIE_MAX_AGE", "3600")
    )
    cognito_jwks_cache_ttl_seconds: int = int(
        os.getenv("COGNITO_JWKS_CACHE_TTL_SECONDS", str(6 * 60 * 60))
    )
    # Local demo copies lecture PDFs into notebook storage. Production DSQL+S3
    # must keep this false until the separate course-material/Bedrock owner
    # lands — otherwise student-upload S3 would receive duplicate course PDFs.
    course_material_sync_enabled: bool = _boolean(
        "COURSE_MATERIAL_SYNC_ENABLED", True
    )
    # false for local HTTP on 127.0.0.1; production Compose sets true for HTTPS.
    auth_cookie_secure: bool = _boolean("AUTH_COOKIE_SECURE", False)
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

    @property
    def uses_local_database(self) -> bool:
        """Return True when structured state is stored in SQLite."""
        return self.database_provider == "sqlite"

    @property
    def uses_local_files(self) -> bool:
        """Return True when uploads are stored on the local filesystem."""
        return self.file_storage_provider == "local"

    def ensure_directories(self) -> None:
        """Create local data directories when the local providers are active.

        Production DSQL/S3 deployments must not require ``/app/data``. Lecture
        notes remain optional host/content input and are created only for local
        file mode.
        """
        directories: list[Path] = []
        if self.uses_local_database or self.uses_local_files:
            directories.append(self.data_dir)
        if self.uses_local_files:
            directories.extend((self.files_dir, self.workspaces_dir))
        if self.uses_local_files or self.lecture_notes_dir.exists():
            directories.append(self.lecture_notes_dir)
        # Always ensure lecture_notes for local lecture sync when path is default.
        if self.file_storage_provider != "s3":
            directories.append(self.lecture_notes_dir)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
