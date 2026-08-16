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


def _unit_interval(name: str, default: float) -> float:
    """Parse a ``[0.0, 1.0]`` env float, ignoring invalid values."""
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    if value != value:
        return default
    return min(1.0, max(0.0, value))


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Parse an integer env value and clamp it to ``[minimum, maximum]``."""
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum or value > maximum:
        return default
    return value


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
    # Runtime process env (also required on the published AgentCore runtime).
    # Empty in local mock/dev; production AgentCore fail-closes when unset.
    agentcore_model_provider: str = os.getenv("AGENTCORE_MODEL_PROVIDER", "").strip().lower()
    agentcore_model_id: str = os.getenv("AGENTCORE_MODEL_ID", "").strip()
    agentcore_model_region: str = os.getenv("AGENTCORE_MODEL_REGION", "").strip()
    router_model_provider: str = os.getenv("ROUTER_MODEL_PROVIDER", "").strip().lower()
    router_model_id: str = os.getenv("ROUTER_MODEL_ID", "").strip()
    qa_model_provider: str = os.getenv("QA_MODEL_PROVIDER", "").strip().lower()
    qa_model_id: str = os.getenv("QA_MODEL_ID", "").strip()
    coaching_model_provider: str = os.getenv("COACHING_MODEL_PROVIDER", "").strip().lower()
    coaching_model_id: str = os.getenv("COACHING_MODEL_ID", "").strip()
    review_model_provider: str = os.getenv("REVIEW_MODEL_PROVIDER", "").strip().lower()
    review_model_id: str = os.getenv("REVIEW_MODEL_ID", "").strip()
    review_incremental_model_provider: str = os.getenv(
        "REVIEW_INCREMENTAL_MODEL_PROVIDER", ""
    ).strip().lower()
    review_incremental_model_id: str = os.getenv(
        "REVIEW_INCREMENTAL_MODEL_ID", ""
    ).strip()
    review_deep_model_provider: str = os.getenv(
        "REVIEW_DEEP_MODEL_PROVIDER", ""
    ).strip().lower()
    review_deep_model_id: str = os.getenv("REVIEW_DEEP_MODEL_ID", "").strip()
    router_min_confidence: float = _unit_interval("ROUTER_MIN_CONFIDENCE", 0.60)
    deep_review_interval_turns: int = _bounded_int(
        "DEEP_REVIEW_INTERVAL_TURNS", 3, 1, 20
    )
    guardrail_id: str = os.getenv("GUARDRAIL_ID", "").strip()
    guardrail_version: str = os.getenv("GUARDRAIL_VERSION", "").strip()
    knowledge_base_id: str = os.getenv("KNOWLEDGE_BASE_ID", "").strip()
    knowledge_base_region: str = os.getenv("KNOWLEDGE_BASE_REGION", "").strip()
    knowledge_base_type: str = os.getenv("KNOWLEDGE_BASE_TYPE", "").strip()
    knowledge_base_strict_metadata_filter: bool = _boolean(
        "KNOWLEDGE_BASE_STRICT_METADATA_FILTER", False
    )
    model_context_limit_tokens: int = int(
        os.getenv("MODEL_CONTEXT_LIMIT_TOKENS", "272000")
    )
    model_max_input_tokens: int = int(os.getenv("MODEL_MAX_INPUT_TOKENS", "210000"))
    model_output_reserve_tokens: int = int(
        os.getenv("MODEL_OUTPUT_RESERVE_TOKENS", "32000")
    )
    model_context_safety_margin_tokens: int = int(
        os.getenv("MODEL_CONTEXT_SAFETY_MARGIN_TOKENS", "30000")
    )
    history_recent_verbatim_messages: int = int(
        os.getenv("HISTORY_RECENT_VERBATIM_MESSAGES", "12")
    )
    agentcore_eval_harness_arn: str = os.getenv(
        "AGENTCORE_EVAL_HARNESS_ARN", ""
    ).strip()
    live_eval_model_id: str = os.getenv(
        "LIVE_EVAL_MODEL_ID", "openai.gpt-5.6-luna"
    ).strip() or "openai.gpt-5.6-luna"
    live_eval_api_format: str = os.getenv(
        "LIVE_EVAL_API_FORMAT", "responses"
    ).strip() or "responses"
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
    def normalized_knowledge_base_type(self) -> str:
        """Return ``vector`` or ``managed`` for the Retrieve search configuration.

        Empty local/dev values default to classic vector Retrieve. Production
        shared course sync must set ``KNOWLEDGE_BASE_TYPE`` explicitly because
        a MANAGED Knowledge Base rejects ``vectorSearchConfiguration``.
        """
        raw = self.knowledge_base_type.strip().casefold()
        if raw in {"", "vector"}:
            return "vector"
        if raw == "managed":
            return "managed"
        return raw

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


def _validate_provider_model_pair(
    provider: str,
    model_id: str,
    *,
    provider_env: str,
    model_env: str,
) -> None:
    """Reject unsafe provider/model pairs without substituting a model."""
    cleaned_provider = (provider or "").strip().lower()
    cleaned_model = (model_id or "").strip()
    if cleaned_provider not in {"bedrock", "bedrock_mantle_responses"}:
        raise ValueError(f"{provider_env} is not configured")
    if not cleaned_model:
        raise ValueError(f"{model_env} is not configured")
    if cleaned_provider == "bedrock" and cleaned_model.lower().startswith("openai."):
        raise ValueError("Luna cannot use BedrockModel")
    if cleaned_provider == "bedrock_mantle_responses" and not cleaned_model.lower().startswith(
        "openai."
    ):
        raise ValueError("Mantle Responses requires an openai.* model id")


def _validate_agentcore_role_models() -> None:
    """Require explicit per-role production models. No silent Haiku↔Sonnet swap."""
    roles = (
        ("router", settings.router_model_provider, settings.router_model_id),
        ("qa", settings.qa_model_provider, settings.qa_model_id),
        ("coaching", settings.coaching_model_provider, settings.coaching_model_id),
        (
            "review_incremental",
            settings.review_incremental_model_provider,
            settings.review_incremental_model_id,
        ),
        (
            "review_deep",
            settings.review_deep_model_provider,
            settings.review_deep_model_id,
        ),
    )
    env_names = {
        "router": ("ROUTER_MODEL_PROVIDER", "ROUTER_MODEL_ID"),
        "qa": ("QA_MODEL_PROVIDER", "QA_MODEL_ID"),
        "coaching": ("COACHING_MODEL_PROVIDER", "COACHING_MODEL_ID"),
        "review_incremental": (
            "REVIEW_INCREMENTAL_MODEL_PROVIDER",
            "REVIEW_INCREMENTAL_MODEL_ID",
        ),
        "review_deep": ("REVIEW_DEEP_MODEL_PROVIDER", "REVIEW_DEEP_MODEL_ID"),
    }
    for role, provider, model_id in roles:
        provider_env, model_env = env_names[role]
        _validate_provider_model_pair(
            provider, model_id, provider_env=provider_env, model_env=model_env
        )
    if not 0.0 <= float(settings.router_min_confidence) <= 1.0:
        raise ValueError("ROUTER_MIN_CONFIDENCE must be between 0 and 1")
    if not 1 <= int(settings.deep_review_interval_turns) <= 20:
        raise ValueError("DEEP_REVIEW_INTERVAL_TURNS must be between 1 and 20")


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
        if not settings.agentcore_model_region.strip():
            raise ValueError("AGENTCORE_MODEL_REGION is not configured")
        if not settings.guardrail_id.strip() or not settings.guardrail_version.strip():
            raise ValueError("GUARDRAIL_ID and GUARDRAIL_VERSION are required")
        _validate_provider_model_pair(
            settings.agentcore_model_provider,
            settings.agentcore_model_id,
            provider_env="AGENTCORE_MODEL_PROVIDER",
            model_env="AGENTCORE_MODEL_ID",
        )
        _validate_agentcore_role_models()
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
        if not settings.knowledge_base_id.strip():
            raise ValueError("KNOWLEDGE_BASE_ID is not configured")
        kb_type = settings.normalized_knowledge_base_type
        if not settings.knowledge_base_type.strip() or kb_type not in {
            "vector",
            "managed",
        }:
            raise ValueError("KNOWLEDGE_BASE_TYPE must be VECTOR or MANAGED")

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
