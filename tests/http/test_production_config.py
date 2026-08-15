"""Deterministic fail-closed checks for APP_ENV=production configuration."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.cognito_config import CognitoAuthConfig
from backend.settings import settings, validate_production_configuration
from backend.student_store import StudentStore


_VALID_COGNITO = CognitoAuthConfig(
    client_id="test-client",
    client_secret="test-secret",
    server_metadata_url=(
        "https://cognito-idp.us-west-2.amazonaws.com/pool/"
        ".well-known/openid-configuration"
    ),
    redirect_uri="https://coach.example.edu/api/v1/auth/callback",
)


def _apply_valid_production_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a complete production-safe settings baseline after the autouse fixture."""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "model_provider", "openai")
    monkeypatch.setattr(settings, "mock_openai", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-not-a-real-key")
    monkeypatch.setattr(settings, "openai_timeout_seconds", 110.0)
    monkeypatch.setattr(settings, "openai_max_retries", 0)
    monkeypatch.setattr(settings, "bedrock_model_id", "")
    monkeypatch.setattr(settings, "bedrock_timeout_seconds", 110.0)
    monkeypatch.setattr(settings, "bedrock_max_retries", 0)
    monkeypatch.setattr(settings, "agentcore_runtime_arn", "")
    monkeypatch.setattr(settings, "agentcore_runtime_id", "")
    monkeypatch.setattr(settings, "agentcore_timeout_seconds", 110.0)
    monkeypatch.setattr(settings, "agentcore_max_retries", 0)
    monkeypatch.setattr(settings, "agentcore_model_provider", "")
    monkeypatch.setattr(settings, "agentcore_model_id", "")
    monkeypatch.setattr(settings, "agentcore_model_region", "")
    monkeypatch.setattr(settings, "guardrail_id", "")
    monkeypatch.setattr(settings, "guardrail_version", "")
    monkeypatch.setattr(settings, "course_materials_bucket", "")
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "use_local_api", True)
    monkeypatch.setattr(settings, "enable_local_code_execution", False)
    monkeypatch.setattr(settings, "course_material_sync_enabled", False)
    monkeypatch.setattr(settings, "database_provider", "dsql")
    monkeypatch.setattr(settings, "file_storage_provider", "s3")
    monkeypatch.setattr(settings, "dsql_endpoint", "cluster.dsql.us-west-2.on.aws")
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    monkeypatch.setattr(settings, "dsql_user", "co_design_app")
    monkeypatch.setattr(settings, "user_uploads_bucket", "co-design-uploads-test")
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    monkeypatch.setattr(
        settings, "public_api_base_url", "https://coach.example.edu"
    )
    monkeypatch.setattr(settings, "ui_base_url", "https://coach.example.edu")
    monkeypatch.setattr(
        "backend.cognito_config.load_cognito_auth_config",
        lambda: _VALID_COGNITO,
    )


def test_development_validate_production_configuration_is_noop(monkeypatch):
    """Autouse fixture keeps APP_ENV=development; validator must not raise."""
    monkeypatch.setattr(settings, "app_env", "development")
    # Intentionally leave mock/sqlite/local defaults from conftest.
    assert settings.model_provider == "mock"
    assert settings.database_provider == "sqlite"
    validate_production_configuration()


def test_valid_production_configuration_passes(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    validate_production_configuration()


def test_valid_bedrock_production_configuration_passes_without_openai_key(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "bedrock")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "bedrock_model_id", "us.anthropic.claude-test")
    validate_production_configuration()


def test_valid_agentcore_production_configuration_passes_without_openai_key(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(
        settings,
        "agentcore_runtime_arn",
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
    )
    monkeypatch.setattr(settings, "agentcore_model_provider", "bedrock")
    monkeypatch.setattr(
        settings, "agentcore_model_id", "global.anthropic.claude-sonnet-4-6"
    )
    monkeypatch.setattr(settings, "agentcore_model_region", "us-west-2")
    monkeypatch.setattr(settings, "guardrail_id", "test-guardrail")
    monkeypatch.setattr(settings, "guardrail_version", "1")
    validate_production_configuration()


def test_valid_agentcore_mantle_luna_configuration_passes(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(
        settings,
        "agentcore_runtime_arn",
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
    )
    monkeypatch.setattr(settings, "agentcore_model_provider", "bedrock_mantle_responses")
    monkeypatch.setattr(settings, "agentcore_model_id", "openai.gpt-5.6-luna")
    monkeypatch.setattr(settings, "agentcore_model_region", "us-west-2")
    monkeypatch.setattr(settings, "guardrail_id", "test-guardrail")
    monkeypatch.setattr(settings, "guardrail_version", "1")
    validate_production_configuration()


def test_production_rejects_mantle_with_claude_model_id(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(
        settings,
        "agentcore_runtime_arn",
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
    )
    monkeypatch.setattr(settings, "agentcore_model_provider", "bedrock_mantle_responses")
    monkeypatch.setattr(
        settings, "agentcore_model_id", "global.anthropic.claude-sonnet-4-6"
    )
    monkeypatch.setattr(settings, "agentcore_model_region", "us-west-2")
    monkeypatch.setattr(settings, "guardrail_id", "test-guardrail")
    monkeypatch.setattr(settings, "guardrail_version", "1")
    with pytest.raises(ValueError, match="openai"):
        validate_production_configuration()


def test_valid_production_configuration_allows_shared_course_sync(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "course_materials_bucket", "course-content-test")
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "knowledge_base_id", "JUQNP8AZAZ")
    validate_production_configuration()


def test_production_shared_course_sync_requires_knowledge_base_id(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "course_materials_bucket", "course-content-test")
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "knowledge_base_id", "")
    with pytest.raises(ValueError, match="KNOWLEDGE_BASE_ID"):
        validate_production_configuration()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("agentcore_runtime_arn", "", r"AGENTCORE_RUNTIME_ARN"),
        ("agentcore_timeout_seconds", 0, r"AGENTCORE_TIMEOUT_SECONDS"),
        ("agentcore_timeout_seconds", 121, r"AGENTCORE_TIMEOUT_SECONDS"),
        ("agentcore_max_retries", 3, r"AGENTCORE_MAX_RETRIES"),
        ("agentcore_model_provider", "", r"AGENTCORE_MODEL_PROVIDER"),
        ("agentcore_model_provider", "claude", r"AGENTCORE_MODEL_PROVIDER"),
        ("agentcore_model_id", "", r"AGENTCORE_MODEL_ID"),
        ("agentcore_model_region", "", r"AGENTCORE_MODEL_REGION"),
        ("guardrail_id", "", r"GUARDRAIL_ID"),
        ("guardrail_version", "", r"GUARDRAIL_ID and GUARDRAIL_VERSION"),
        ("agentcore_model_id", "openai.gpt-5.6-luna", r"Luna cannot use BedrockModel"),
    ],
)
def test_production_rejects_incomplete_agentcore_configuration(
    monkeypatch, field: str, value: object, match: str
):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(
        settings,
        "agentcore_runtime_arn",
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
    )
    monkeypatch.setattr(settings, "agentcore_model_provider", "bedrock")
    monkeypatch.setattr(
        settings, "agentcore_model_id", "global.anthropic.claude-sonnet-4-6"
    )
    monkeypatch.setattr(settings, "agentcore_model_region", "us-west-2")
    monkeypatch.setattr(settings, "guardrail_id", "test-guardrail")
    monkeypatch.setattr(settings, "guardrail_version", "1")
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ValueError, match=match):
        validate_production_configuration()


def test_production_rejects_users_namespace_as_course_prefix(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "course_materials_bucket", "course-content-test")
    monkeypatch.setattr(settings, "course_materials_prefix", "users/")
    with pytest.raises(ValueError, match="users/"):
        validate_production_configuration()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("bedrock_model_id", "", r"BEDROCK_MODEL_ID"),
        ("bedrock_timeout_seconds", 0, r"BEDROCK_TIMEOUT_SECONDS"),
        ("bedrock_timeout_seconds", 121, r"BEDROCK_TIMEOUT_SECONDS"),
        ("bedrock_max_retries", 3, r"BEDROCK_MAX_RETRIES"),
    ],
)
def test_production_rejects_incomplete_bedrock_configuration(
    monkeypatch, field: str, value: object, match: str
):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "bedrock")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "bedrock_model_id", "us.anthropic.claude-test")
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ValueError, match=match):
        validate_production_configuration()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("model_provider", "mock", r"MODEL_PROVIDER=mock"),
        ("mock_openai", True, r"MOCK_OPENAI"),
        ("model_provider", "ollama", r"Unsupported MODEL_PROVIDER"),
        ("model_provider", "unknown", r"Unsupported MODEL_PROVIDER"),
        ("openai_api_key", "", r"OPENAI_API_KEY"),
        ("openai_timeout_seconds", 0, r"OPENAI_TIMEOUT_SECONDS"),
        ("openai_timeout_seconds", 121, r"OPENAI_TIMEOUT_SECONDS"),
        ("openai_max_retries", 3, r"OPENAI_MAX_RETRIES"),
        ("use_local_api", False, r"USE_LOCAL_API"),
        ("enable_local_code_execution", True, r"ENABLE_LOCAL_CODE_EXECUTION"),
        ("course_material_sync_enabled", True, r"COURSE_MATERIALS_BUCKET"),
        ("database_provider", "sqlite", r"sqlite"),
        ("file_storage_provider", "local", r"local"),
        ("dsql_user", "admin", r"admin"),
        ("auth_cookie_secure", False, r"AUTH_COOKIE_SECURE"),
        ("public_api_base_url", "http://127.0.0.1:8000", r"loopback|HTTPS"),
        ("ui_base_url", "http://127.0.0.1:8501", r"loopback|HTTPS"),
        ("public_api_base_url", "https://127.0.0.1", r"loopback"),
        ("ui_base_url", "http://coach.example.edu", r"HTTPS"),
        ("dsql_endpoint", "", r"DSQL_ENDPOINT"),
        ("user_uploads_bucket", "", r"USER_UPLOADS_BUCKET"),
        ("aws_region", "", r"AWS_REGION"),
    ],
)
def test_production_rejects_forbidden_configuration(
    monkeypatch, field: str, value: object, match: str
):
    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ValueError, match=match):
        validate_production_configuration()


def test_production_rejects_http_cognito_callback(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    insecure = replace(
        _VALID_COGNITO,
        redirect_uri="http://coach.example.edu/api/v1/auth/callback",
    )
    monkeypatch.setattr(
        "backend.cognito_config.load_cognito_auth_config",
        lambda: insecure,
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_production_configuration()


def test_production_rejects_incomplete_cognito_configuration(monkeypatch):
    _apply_valid_production_baseline(monkeypatch)
    incomplete = CognitoAuthConfig(
        client_id="",
        client_secret="secret",
        server_metadata_url=_VALID_COGNITO.server_metadata_url,
        redirect_uri=_VALID_COGNITO.redirect_uri,
    )
    monkeypatch.setattr(
        "backend.cognito_config.load_cognito_auth_config",
        lambda: incomplete,
    )
    with pytest.raises(ValueError, match="Cognito authentication configuration"):
        validate_production_configuration()


def test_create_app_fails_closed_for_production_mock_provider(tmp_path, monkeypatch):
    # Import while APP_ENV is still development so module-level create_app()
    # in backend.api does not fail during collection/import.
    from backend.api import create_app

    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "model_provider", "mock")

    with pytest.raises(ValueError, match="MODEL_PROVIDER=mock"):
        create_app(StudentStore(tmp_path / "prod-mock.sqlite3"))


def test_readiness_returns_503_for_production_config_failure(tmp_path, monkeypatch):
    """Development create_app stays up; APP_ENV=production then fails ready."""
    from backend.api import create_app

    store = StudentStore(tmp_path / "prod-ready-config.sqlite3")
    client = TestClient(create_app(store))

    _apply_valid_production_baseline(monkeypatch)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert "AUTH_COOKIE_SECURE" in response.json()["detail"]
