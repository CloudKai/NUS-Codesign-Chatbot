"""Static safety checks for local and production Docker deployment files."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _service_block(compose: str, service: str) -> str:
    """Return one top-level Compose service block."""
    lines = compose.splitlines()
    start = lines.index(f"  {service}:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def test_app_ports_are_internal_and_only_caddy_publishes_origin_http():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")
    caddy = _service_block(compose, "caddy")

    assert "expose:" in app
    assert '"8000"' in app
    assert '"8501"' in app
    assert "ports:" not in app
    assert '"80:80"' in caddy
    assert '"443:443"' not in caddy
    assert "8000:8000" not in compose
    assert "8501:8501" not in compose


def test_compose_persists_data_and_mounts_private_secrets_read_only():
    """Local compose keeps the data mount for SQLite/dev; prod does not."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")

    assert "source: ./data" in app
    assert "target: /app/data" in app
    assert "source: ./.streamlit/secrets.toml" in app
    assert "target: /app/.streamlit/secrets.toml" in app
    assert "read_only: true" in app
    assert app.count("create_host_path: false") == 3
    assert 'DATABASE_PROVIDER: "sqlite"' in app
    assert 'FILE_STORAGE_PROVIDER: "local"' in app
    assert 'COURSE_MATERIAL_SYNC_ENABLED: "true"' in app
    assert 'AGENTCORE_MODEL_PROVIDER: "bedrock"' in app
    assert 'AGENTCORE_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'ROUTER_MODEL_PROVIDER: "bedrock"' in app
    assert 'ROUTER_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'QA_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'COACHING_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_INCREMENTAL_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_DEEP_MODEL_ID: "global.anthropic.claude-sonnet-4-6"' in app
    assert 'ROUTER_MIN_CONFIDENCE: "0.60"' in app
    assert 'DEEP_REVIEW_INTERVAL_TURNS: "3"' in app
    assert 'FAST_CHAT_RECENT_VERBATIM_MESSAGES: "6"' in app
    assert 'FAST_CHAT_RECENT_HISTORY_MAX_TOKENS: "3000"' in app
    assert 'FAST_CHAT_HISTORY_MESSAGE_MAX_TOKENS: "1500"' in app
    assert 'FAST_CHAT_SOFT_INPUT_TOKENS: "12000"' in app
    assert 'FAST_CHAT_MAX_INPUT_TOKENS: "16000"' in app
    assert 'FAST_CHAT_PROMPT_CACHE_ENABLED: "false"' in app
    assert 'AGENTCORE_QUALIFIER: "DEFAULT"' in app
    assert 'GUARDRAIL_VERSION: "3"' in app
    assert "source: ./lecture_notes" in app
    assert "target: /app/lecture_notes" in app


def test_production_compose_is_stateless_and_uses_prebuilt_image():
    compose = (ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")
    caddy = _service_block(compose, "caddy")

    assert "image: ${APP_IMAGE}" in app
    assert "build:" not in app
    assert "source: ./data" not in app
    assert "target: /app/data" not in app
    assert 'APP_ENV: "production"' in app
    assert 'AUTO_ADVANCE_STAGES: "true"' in app
    assert 'STUDENT_STAGE_SELECTION: "false"' in app
    assert "Month-2+" in compose
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "STUDENT_STAGE_SELECTION=false" in env_example
    assert 'DATABASE_PROVIDER: "dsql"' in app
    assert 'FILE_STORAGE_PROVIDER: "s3"' in app
    assert 'DSQL_USER: "co_design_app"' in app
    assert 'AWS_REGION: "us-west-2"' in app
    assert 'COURSE_MATERIAL_SYNC_ENABLED: "true"' in app
    assert 'COURSE_MATERIALS_PREFIX: "course/"' in app
    assert 'KNOWLEDGE_BASE_TYPE: "MANAGED"' in app
    assert "LECTURE_NOTES_DIR" not in app
    assert "DSQL_USER: \"admin\"" not in app
    assert "ports:" not in app
    assert '"8000"' in app
    assert '"8501"' in app
    assert '"80:80"' in caddy
    assert '"443:443"' not in caddy
    assert "8000:8000" not in compose
    assert "8501:8501" not in compose
    assert (
        'COGNITO_REDIRECT_URI: "${PUBLIC_ORIGIN:?PUBLIC_ORIGIN is required}/api/v1/auth/callback"'
        in app
    )
    assert (
        'CO_DESIGN_PUBLIC_API_URL: "${PUBLIC_ORIGIN:?PUBLIC_ORIGIN is required}"'
        in app
    )
    assert 'CO_DESIGN_UI_URL: "${PUBLIC_ORIGIN:?PUBLIC_ORIGIN is required}"' in app
    assert 'MODEL_PROVIDER: "agentcore"' in app
    assert 'MOCK_OPENAI: "false"' in app
    assert 'AGENTCORE_QUALIFIER: "DEFAULT"' in app
    assert 'AGENTCORE_MODEL_PROVIDER: "bedrock"' in app
    assert 'AGENTCORE_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'ROUTER_MODEL_PROVIDER: "bedrock"' in app
    assert 'ROUTER_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'QA_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'COACHING_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_INCREMENTAL_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_DEEP_MODEL_ID: "global.anthropic.claude-sonnet-4-6"' in app
    assert 'ROUTER_MIN_CONFIDENCE: "0.60"' in app
    assert 'DEEP_REVIEW_INTERVAL_TURNS: "3"' in app
    assert 'FAST_CHAT_RECENT_VERBATIM_MESSAGES: "6"' in app
    assert 'FAST_CHAT_RECENT_HISTORY_MAX_TOKENS: "3000"' in app
    assert 'FAST_CHAT_HISTORY_MESSAGE_MAX_TOKENS: "1500"' in app
    assert 'FAST_CHAT_SOFT_INPUT_TOKENS: "12000"' in app
    assert 'FAST_CHAT_MAX_INPUT_TOKENS: "16000"' in app
    assert 'FAST_CHAT_PROMPT_CACHE_ENABLED: "false"' in app
    assert 'GUARDRAIL_VERSION: "3"' in app
    assert 'MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK: "1"' in app
    assert 'MAX_ACTIVE_COACH_REQUESTS_PER_USER: "2"' in app
    assert 'COACH_REQUESTS_PER_MINUTE: "8"' in app
    assert 'MAX_CONCURRENT_MODEL_CALLS: "120"' in app
    assert 'SYNC_THREADPOOL_TOKENS: "120"' in app
    assert "source: ./.streamlit/secrets.toml" in app
    for block in (app, caddy):
        assert "no-new-privileges:true" in block
        assert "driver: json-file" in block
        assert 'max-size: "10m"' in block
        assert 'max-file: "3"' in block
    # Do not force a read-only root filesystem on app/caddy without verifying
    # Streamlit/Caddy writable paths; only the secrets bind mount is read_only.


def test_production_compose_keeps_host_env_knowledge_base_contract():
    """Host `.env` must supply KB/course/runtime IDs; Compose must not drop them.

    Production Compose uses ``env_file: .env`` rather than interpolating those
    values. CI copies `.env.example`, which comments the live IDs, so required
    interpolations would break mock CI.
    """
    compose = (ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "env_file:" in app
    assert "- .env" in app
    assert "${PUBLIC_ORIGIN:?PUBLIC_ORIGIN is required}" in app
    assert 'AWS_REGION: "us-west-2"' in app
    assert 'COURSE_MATERIALS_PREFIX: "course/"' in app
    assert 'KNOWLEDGE_BASE_TYPE: "MANAGED"' in app
    assert 'COURSE_MATERIAL_SYNC_ENABLED: "true"' in app
    assert 'MODEL_PROVIDER: "agentcore"' in app
    assert 'MOCK_OPENAI: "false"' in app
    assert 'AGENTCORE_QUALIFIER: "DEFAULT"' in app
    assert 'AGENTCORE_MODEL_PROVIDER: "bedrock"' in app
    assert 'AGENTCORE_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'ROUTER_MODEL_PROVIDER: "bedrock"' in app
    assert 'ROUTER_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'QA_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'COACHING_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_INCREMENTAL_MODEL_ID: "global.anthropic.claude-haiku-4-5-20251001-v1:0"' in app
    assert 'REVIEW_DEEP_MODEL_ID: "global.anthropic.claude-sonnet-4-6"' in app
    assert 'ROUTER_MIN_CONFIDENCE: "0.60"' in app
    assert 'DEEP_REVIEW_INTERVAL_TURNS: "3"' in app
    assert 'FAST_CHAT_RECENT_VERBATIM_MESSAGES: "6"' in app
    assert 'FAST_CHAT_RECENT_HISTORY_MAX_TOKENS: "3000"' in app
    assert 'FAST_CHAT_HISTORY_MESSAGE_MAX_TOKENS: "1500"' in app
    assert 'FAST_CHAT_SOFT_INPUT_TOKENS: "12000"' in app
    assert 'FAST_CHAT_MAX_INPUT_TOKENS: "16000"' in app
    assert 'FAST_CHAT_PROMPT_CACHE_ENABLED: "false"' in app
    assert 'GUARDRAIL_VERSION: "3"' in app
    assert "${KNOWLEDGE_BASE_ID" not in compose
    assert "${COURSE_MATERIALS_BUCKET" not in compose
    assert "${AGENTCORE_RUNTIME_ARN" not in compose
    assert "${GUARDRAIL_ID" not in compose
    assert "${GUARDRAIL_VERSION" not in compose
    for needle in (
        "KNOWLEDGE_BASE_ID: set in host .env",
        "COURSE_MATERIALS_BUCKET: set in host .env",
        "AGENTCORE_RUNTIME_ARN: set in host .env",
        "GUARDRAIL_ID: set in host .env",
    ):
        assert needle in compose
    for needle in (
        "KNOWLEDGE_BASE_ID=",
        "KNOWLEDGE_BASE_TYPE=",
        "COURSE_MATERIALS_BUCKET=",
        "AGENTCORE_RUNTIME_ARN=",
        "AGENTCORE_QUALIFIER=",
        "GUARDRAIL_ID=",
        "GUARDRAIL_VERSION=",
        "PUBLIC_ORIGIN=",
        "MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK=",
        "MAX_ACTIVE_COACH_REQUESTS_PER_USER=",
        "COACH_REQUESTS_PER_MINUTE=",
        "MAX_CONCURRENT_MODEL_CALLS=",
        "SYNC_THREADPOOL_TOKENS=",
    ):
        assert needle in env_example


def test_caddy_exposes_only_auth_browser_routes_and_health_to_fastapi():
    """Public Caddy must not forward arbitrary /api/* into FastAPI."""
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert caddyfile.startswith(":80 {")
    assert "CloudFront terminates viewer TLS" in caddyfile
    assert "handle /api/v1/auth/login" in caddyfile
    assert "handle /api/v1/auth/callback" in caddyfile
    assert "handle /api/v1/auth/me" in caddyfile
    assert "handle /api/v1/auth/refresh" in caddyfile
    assert "handle /api/v1/auth/logout" in caddyfile
    assert "handle /api/v1/health" in caddyfile
    assert "handle /api/*" in caddyfile
    assert 'respond "Not Found" 404' in caddyfile
    assert "reverse_proxy app:8501" in caddyfile
    assert "handle_path" not in caddyfile
    assert "Strict-Transport-Security" in caddyfile
    assert "X-Content-Type-Options" in caddyfile
    assert "nosniff" in caddyfile
    assert "Referrer-Policy" in caddyfile
    assert "Permissions-Policy" in caddyfile
    assert "Content-Security-Policy" not in caddyfile
    assert ":443" not in caddyfile

    login_index = caddyfile.index("handle /api/v1/auth/login")
    callback_index = caddyfile.index("handle /api/v1/auth/callback")
    me_index = caddyfile.index("handle /api/v1/auth/me")
    refresh_index = caddyfile.index("handle /api/v1/auth/refresh")
    logout_index = caddyfile.index("handle /api/v1/auth/logout")
    health_index = caddyfile.index("handle /api/v1/health")
    block_index = caddyfile.index("handle /api/*")
    streamlit_index = caddyfile.index("handle {\n\t\treverse_proxy app:8501")
    assert login_index < block_index
    assert callback_index < block_index
    assert me_index < block_index
    assert refresh_index < block_index
    assert logout_index < block_index
    assert health_index < block_index < streamlit_index

    api_block = caddyfile[block_index:streamlit_index]
    assert "reverse_proxy app:8000" not in api_block
    assert 'respond "Not Found" 404' in api_block


def test_compose_keeps_internal_fastapi_url_for_container_local_calls():
    """In-container FastAPI remains on loopback; only browser origins are public."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")

    assert 'CO_DESIGN_API_URL: "http://127.0.0.1:8000"' in app
    assert 'CO_DESIGN_PUBLIC_API_URL: "https://d1sxfuoybzedj5.cloudfront.net"' in app
    assert 'CO_DESIGN_UI_URL: "https://d1sxfuoybzedj5.cloudfront.net"' in app
    assert "ports:" not in app


def test_compose_sets_production_cognito_redirect_uri():
    """Production must not silently use the local 127.0.0.1 Cognito callback."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")

    assert (
        'COGNITO_REDIRECT_URI: "https://d1sxfuoybzedj5.cloudfront.net/api/v1/auth/callback"'
        in app
    )
    assert 'COGNITO_REDIRECT_URI: "http://127.0.0.1' not in app
    assert "127.0.0.1:8000/api/v1/auth/callback" not in app
    assert 'AUTH_COOKIE_SECURE: "true"' in app


def test_docker_context_excludes_secrets_state_and_development_artifacts():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for required in (
        ".env",
        ".env.*",
        "!.env.example",
        ".streamlit/secrets.toml",
        ".venv/",
        "venv/",
        "__pycache__/",
        ".pytest_cache/",
        ".git",
        "data/",
        "*.sqlite3",
        "*.log",
    ):
        assert required in ignore
    assert ".streamlit/secrets.toml.example" not in ignore
    assert "lecture_notes/" in ignore


def test_dockerfile_is_architecture_neutral():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "--platform=linux/arm64" not in dockerfile
    assert "--platform=linux/amd64" not in dockerfile
    assert "ca-certificates" in dockerfile
    assert "python -m pip install -r requirements.txt" in dockerfile
    assert 'ENTRYPOINT ["sh", "scripts/start_prod.sh"]' in dockerfile


def test_production_script_validates_provider_config_without_requiring_data_for_dsql():
    script = (ROOT / "scripts" / "start_prod.sh").read_text(encoding="utf-8")

    assert "backend.api:app" in script
    assert "--host 0.0.0.0" in script
    assert "--server.address 0.0.0.0" in script
    assert "--server.headless true" in script
    assert "USE_LOCAL_API" in script
    assert "kill -0" in script
    assert "DATABASE_PROVIDER=dsql requires DSQL_ENDPOINT" in script
    assert "FILE_STORAGE_PROVIDER=s3 requires USER_UPLOADS_BUCKET" in script
    assert "DSQL_USER=admin is not allowed" in script
    assert "Streamlit secrets must be a readable file" in script
    assert 'DATABASE_PROVIDER" = "sqlite"' in script
    assert 'FILE_STORAGE_PROVIDER" = "local"' in script
    assert "Application data directory must exist and be writable" in script
    assert "--workers" not in script
    assert "python -m uvicorn backend.api:app" in script


def test_caddy_documents_loopback_fastapi_and_does_not_time_out_coach_turns():
    """Caddy fronts Streamlit; coaching HTTP stays on container loopback."""
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    compose_prod = (ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "Caddy does not proxy" in caddyfile
    assert "/api/v1/coach" in caddyfile
    assert "unlimited read timeout" in caddyfile
    assert "transport http" not in caddyfile
    assert "read_timeout" not in caddyfile
    assert "start_prod.sh has no --workers" in compose_prod
    assert "durable mutex" in compose_prod
    assert "There is no separate COACH_IDEMPOTENCY_LEASE_SECONDS knob" in env_example
    assert "DERIVED from this value" in env_example


def test_cloudfront_is_the_only_documented_production_edge():
    retired_provider = "duck" + "dns"
    paths = [
        ROOT / "README.md",
        ROOT / "Caddyfile",
        ROOT / "compose.yaml",
        ROOT / "compose.prod.yaml",
        ROOT / "scripts" / "AGENTS.md",
        ROOT / "docs" / "AGENTS.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ]
    for path in paths:
        assert retired_provider not in path.read_text(encoding="utf-8").lower()
    assert not (ROOT / "scripts" / "host" / "duck.sh").exists()
    assert not (ROOT / "scripts" / "host" / "duck.env.example").exists()


def test_ci_validates_compose_and_caddy_configuration():
    workflow = (ROOT / ".github" / "workflows" / "mock-ci.yml").read_text(
        encoding="utf-8"
    )
    assert "PUBLIC_ORIGIN: https://d1sxfuoybzedj5.cloudfront.net" in workflow
    assert "APP_IMAGE: co-design:test" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker compose -f compose.prod.yaml config --quiet" in workflow
    assert "--entrypoint caddy" in workflow
    assert "validate --config /etc/caddy/Caddyfile" in workflow


def test_dockerfile_records_immutable_git_revision():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG GIT_SHA=unknown" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "APP_GIT_SHA" in dockerfile


def test_student_stage_selection_boolean_and_effective_auto_advance(monkeypatch):
    from backend.settings import Settings, _boolean

    assert _boolean("STUDENT_STAGE_SELECTION", False) is False
    monkeypatch.setenv("STUDENT_STAGE_SELECTION", "true")
    assert _boolean("STUDENT_STAGE_SELECTION", False) is True
    monkeypatch.setenv("STUDENT_STAGE_SELECTION", "0")
    assert _boolean("STUDENT_STAGE_SELECTION", False) is False

    from backend.settings import settings

    monkeypatch.setattr(settings, "auto_advance_stages", True)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    assert settings.effective_auto_advance_stages is True
    monkeypatch.setattr(settings, "student_stage_selection", True)
    assert settings.effective_auto_advance_stages is False
    # Settings dataclass fields are import-time; ensure the property still
    # reflects mutual exclusion on a freshly constructed instance shape.
    assert hasattr(Settings, "effective_auto_advance_stages")
