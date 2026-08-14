"""Application settings loaded from the project ``.env`` file.

Fallback defaults match ``.env.example``: mock provider, confirmation-mode
stage progression, SQLite + local files, and project-root-relative data paths
so a missing ``.env`` stays cost-safe. Production selects Aurora DSQL and S3
via ``DATABASE_PROVIDER`` / ``FILE_STORAGE_PROVIDER`` and must set
``APP_ENV=production`` so ``validate_production_configuration`` fail-closes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
try:
    load_dotenv(PROJECT_ROOT / ".env")
except OSError:
    # Private .env may be unreadable in some sandboxed test environments.
    pass

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _project_path(name: str, default: str) -> Path:
    """Resolve a configured path relative to the project when it is not absolute."""
    configured = Path(os.getenv(name, default)).expanduser()
    return (configured if configured.is_absolute() else PROJECT_ROOT / configured).resolve()


def _default_app_env() -> str:
    """Development-safe default; unknown values are rejected only in production validation."""
    return (os.getenv("APP_ENV") or "development").strip().lower() or "development"


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = _project_path("APP_DATA_DIR", "data")
    database_path: Path = _project_path("APP_DATABASE_PATH", "data/co_design.sqlite3")
    files_dir: Path = _project_path("APP_FILES_DIR", "data/files")
    workspaces_dir: Path = _project_path("APP_WORKSPACES_DIR", "data/workspaces")
    lecture_notes_dir: Path = _project_path("LECTURE_NOTES_DIR", "lecture_notes")
    # development keeps local/mock defaults; production must be set explicitly.
    app_env: str = field(default_factory=_default_app_env)
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
    dsql_sslrootcert: str = field(
        default_factory=lambda: os.getenv(
            "DSQL_SSLROOTCERT",
            "system",
        ).strip()
        or "system"
    )
    user_uploads_bucket: str = field(
        default_factory=lambda: os.getenv("USER_UPLOADS_BUCKET", "").strip()
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    enable_local_code_execution: bool = _boolean("ENABLE_LOCAL_CODE_EXECUTION", False)
    mock_openai: bool = _boolean("MOCK_OPENAI", True)
    mock_recommend_advance: bool = _boolean("MOCK_RECOMMEND_ADVANCE", False)
    auto_advance_stages: bool = _boolean("AUTO_ADVANCE_STAGES", False)
    # When true, Journey lets students pick any Thinking Path stage. Takes
    # precedence over auto_advance_stages (selection wins if both are true).
    student_stage_selection: bool = _boolean("STUDENT_STAGE_SELECTION", False)
    model_provider: str = os.getenv("MODEL_PROVIDER", "mock").strip().lower()
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "110"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "0"))
    bedrock_model_id: str = os.getenv("BEDROCK_MODEL_ID", "").strip()
    bedrock_timeout_seconds: float = float(os.getenv("BEDROCK_TIMEOUT_SECONDS", "110"))
    bedrock_max_retries: int = int(os.getenv("BEDROCK_MAX_RETRIES", "0"))
    agentcore_runtime_arn: str = os.getenv("AGENTCORE_RUNTIME_ARN", "").strip()
    agentcore_runtime_id: str = os.getenv("AGENTCORE_RUNTIME_ID", "").strip()
    agentcore_qualifier: str = (
        os.getenv("AGENTCORE_QUALIFIER", "DEFAULT").strip() or "DEFAULT"
    )
    agentcore_timeout_seconds: float = float(
        os.getenv("AGENTCORE_TIMEOUT_SECONDS", "110")
    )
    agentcore_max_retries: int = int(os.getenv("AGENTCORE_MAX_RETRIES", "0"))
    knowledge_base_id: str = os.getenv("KNOWLEDGE_BASE_ID", "").strip()
    knowledge_base_region: str = os.getenv("KNOWLEDGE_BASE_REGION", "").strip()
    course_materials_bucket: str = field(
        default_factory=lambda: os.getenv("COURSE_MATERIALS_BUCKET", "").strip()
    )
    course_materials_prefix: str = (
        os.getenv("COURSE_MATERIALS_PREFIX", "course/").strip() or "course/"
    )
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
    # Path=/ presence marker so Streamlit can attempt the refresh bridge after
    # the short-lived ID cookie expires. Value is non-sensitive ("1").
    cognito_session_hint_cookie_name: str = os.getenv(
        "COGNITO_SESSION_HINT_COOKIE_NAME", "co_design_session"
    ).strip() or "co_design_session"
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
    # syncs locked Lecture Notes/Readings from shared ``course/`` keys without
    # copying PDFs into ``users/``.
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
    # Single-EC2 in-process coach limits (see backend/rate_limit.py).
    max_active_coach_requests_per_user: int = int(
        os.getenv("MAX_ACTIVE_COACH_REQUESTS_PER_USER", "1")
    )
    coach_requests_per_minute: int = int(os.getenv("COACH_REQUESTS_PER_MINUTE", "8"))
    max_concurrent_model_calls: int = int(
        os.getenv("MAX_CONCURRENT_MODEL_CALLS", "20")
    )
    # Public Cognito login-start throttle (OAuth-state DSQL writes).
    auth_login_requests_per_minute_per_ip: int = int(
        os.getenv("AUTH_LOGIN_REQUESTS_PER_MINUTE_PER_IP", "10")
    )
    auth_login_requests_per_minute_global: int = int(
        os.getenv("AUTH_LOGIN_REQUESTS_PER_MINUTE_GLOBAL", "60")
    )
    python_timeout_seconds: int = int(os.getenv("PYTHON_TIMEOUT_SECONDS", "30"))
    default_model: str = os.getenv("DEFAULT_CHAT_MODEL", "gpt-5.6-luna")
    default_reasoning_effort: str = os.getenv("DEFAULT_REASONING_EFFORT", "low")
    image_model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")

    @property
    def is_production(self) -> bool:
        """Return True when ``APP_ENV=production`` (explicit production gate)."""
        return self.app_env == "production"

    @property
    def effective_auto_advance_stages(self) -> bool:
        """Return whether coach ADVANCE should auto-apply.

        Student stage selection takes precedence: when
        ``STUDENT_STAGE_SELECTION=true``, auto-advance is treated as off even
        if ``AUTO_ADVANCE_STAGES=true``.
        """
        return bool(self.auto_advance_stages) and not bool(self.student_stage_selection)

    @property
    def uses_local_database(self) -> bool:
        """Return True when structured state is stored in SQLite."""
        return self.database_provider == "sqlite"

    @property
    def uses_local_files(self) -> bool:
        """Return True when uploads are stored on the local filesystem."""
        return self.file_storage_provider == "local"

    @property
    def normalized_course_materials_prefix(self) -> str:
        """Return the shared course-object prefix with a trailing slash."""
        cleaned = self.course_materials_prefix.strip().replace("\\", "/").strip("/")
        return f"{cleaned}/" if cleaned else ""

    @property
    def resolved_course_materials_bucket(self) -> str:
        """Return the course-materials bucket, falling back to student uploads."""
        return self.course_materials_bucket.strip() or self.user_uploads_bucket.strip()

    @property
    def uses_shared_course_materials(self) -> bool:
        """Return whether locked course sources should reference shared object keys.

        Production S3 always uses the shared prefix. Memory-backed tests opt in
        by setting ``COURSE_MATERIALS_BUCKET`` so ordinary memory upload tests
        keep the local lecture-notes copy path.
        """
        if not self.normalized_course_materials_prefix:
            return False
        if self.file_storage_provider == "s3":
            return True
        return self.file_storage_provider == "memory" and bool(
            self.course_materials_bucket.strip()
        )

    @property
    def resolved_agentcore_runtime_arn(self) -> str:
        """Return the AgentCore runtime ARN from ARN or id-shaped ARN values."""
        arn = self.agentcore_runtime_arn.strip()
        if arn:
            return arn
        runtime_id = self.agentcore_runtime_id.strip()
        if runtime_id.startswith("arn:"):
            return runtime_id
        return ""

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


def _require_public_https_origin(label: str, value: str) -> None:
    """Reject non-HTTPS or loopback browser-facing origins (category-only errors)."""
    parsed = urlparse((value or "").strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{label} must use HTTPS in production")
    host = (parsed.hostname or "").strip().lower()
    if not host or host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        raise ValueError(f"{label} must not use a loopback host in production")


def validate_production_configuration() -> None:
    """Fail closed when ``APP_ENV=production`` and runtime config is unsafe.

    No-op for ``development``. Reuses ``validate_storage_configuration`` and
    ``validate_cognito_readiness`` without network or AWS calls. Error text is
    category-only so readiness/startup responses stay secret-safe.
    """
    env = (settings.app_env or "").strip().lower() or "development"
    if env == "development":
        return
    if env != "production":
        raise ValueError("APP_ENV must be development or production")

    if settings.model_provider == "mock":
        raise ValueError("MODEL_PROVIDER=mock is not allowed in production")
    if settings.mock_openai:
        raise ValueError("MOCK_OPENAI masking is not allowed in production")
    if settings.model_provider == "openai":
        if not settings.openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is not configured")
        if not 1 <= settings.openai_timeout_seconds <= 120:
            raise ValueError("OPENAI_TIMEOUT_SECONDS must be between 1 and 120")
        if not 0 <= settings.openai_max_retries <= 2:
            raise ValueError("OPENAI_MAX_RETRIES must be between 0 and 2")
    elif settings.model_provider == "bedrock":
        if not settings.bedrock_model_id.strip():
            raise ValueError("BEDROCK_MODEL_ID is not configured")
        if not 1 <= settings.bedrock_timeout_seconds <= 120:
            raise ValueError("BEDROCK_TIMEOUT_SECONDS must be between 1 and 120")
        if not 0 <= settings.bedrock_max_retries <= 2:
            raise ValueError("BEDROCK_MAX_RETRIES must be between 0 and 2")
    elif settings.model_provider == "agentcore":
        if not settings.resolved_agentcore_runtime_arn:
            raise ValueError("AGENTCORE_RUNTIME_ARN is not configured")
        if not 1 <= settings.agentcore_timeout_seconds <= 120:
            raise ValueError("AGENTCORE_TIMEOUT_SECONDS must be between 1 and 120")
        if not 0 <= settings.agentcore_max_retries <= 2:
            raise ValueError("AGENTCORE_MAX_RETRIES must be between 0 and 2")
    else:
        raise ValueError(
            f"Unsupported MODEL_PROVIDER for production: {settings.model_provider}"
        )

    if not settings.use_local_api:
        raise ValueError("USE_LOCAL_API must be enabled in production")
    if settings.enable_local_code_execution:
        raise ValueError("ENABLE_LOCAL_CODE_EXECUTION is not allowed in production")
    if settings.course_material_sync_enabled:
        prefix = settings.normalized_course_materials_prefix
        if settings.file_storage_provider != "s3":
            raise ValueError(
                "COURSE_MATERIAL_SYNC_ENABLED requires FILE_STORAGE_PROVIDER=s3"
            )
        if not prefix:
            raise ValueError("COURSE_MATERIALS_PREFIX is not configured")
        if prefix == "users/" or prefix.startswith("users/"):
            raise ValueError(
                "COURSE_MATERIALS_PREFIX must not use the users/ namespace"
            )
        if not settings.course_materials_bucket.strip():
            raise ValueError("COURSE_MATERIALS_BUCKET is not configured")

    if settings.database_provider == "sqlite":
        raise ValueError("DATABASE_PROVIDER=sqlite is not allowed in production")
    if settings.database_provider != "dsql":
        raise ValueError(
            f"Unsupported DATABASE_PROVIDER for production: {settings.database_provider}"
        )
    if settings.file_storage_provider in {"local", "memory"}:
        raise ValueError(
            "FILE_STORAGE_PROVIDER=local is not allowed in production"
            if settings.file_storage_provider == "local"
            else "FILE_STORAGE_PROVIDER=memory is not allowed in production"
        )
    if settings.file_storage_provider != "s3":
        raise ValueError(
            "Unsupported FILE_STORAGE_PROVIDER for production: "
            f"{settings.file_storage_provider}"
        )

    if not settings.auth_cookie_secure:
        raise ValueError("AUTH_COOKIE_SECURE must be enabled in production")

    _require_public_https_origin(
        "CO_DESIGN_PUBLIC_API_URL", settings.public_api_base_url
    )
    _require_public_https_origin("CO_DESIGN_UI_URL", settings.ui_base_url)

    # Lazy imports avoid cycles with factory/cognito_config which import settings.
    from backend.persistence.factory import validate_storage_configuration
    from backend.cognito_config import validate_cognito_readiness

    validate_storage_configuration()
    validate_cognito_readiness(require_https=True)


settings = Settings()
settings.ensure_directories()
if settings.auto_advance_stages and settings.student_stage_selection:
    import logging

    logging.getLogger(__name__).warning(
        "STUDENT_STAGE_SELECTION=true takes precedence over AUTO_ADVANCE_STAGES; "
        "coach ADVANCE will not auto-apply"
    )
