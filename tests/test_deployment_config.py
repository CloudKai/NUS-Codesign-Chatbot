"""Static safety checks for local and production Docker deployment files."""

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


def test_app_ports_are_internal_and_only_caddy_publishes_http_ports():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")
    caddy = _service_block(compose, "caddy")

    assert "expose:" in app
    assert '"8000"' in app
    assert '"8501"' in app
    assert "ports:" not in app
    assert '"80:80"' in caddy
    assert '"443:443"' in caddy
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
    assert 'DATABASE_PROVIDER: "dsql"' in app
    assert 'FILE_STORAGE_PROVIDER: "s3"' in app
    assert 'DSQL_USER: "co_design_app"' in app
    assert 'AWS_REGION: "us-west-2"' in app
    assert 'COURSE_MATERIAL_SYNC_ENABLED: "false"' in app
    assert "LECTURE_NOTES_DIR" not in app
    assert "DSQL_USER: \"admin\"" not in app
    assert "ports:" not in app
    assert '"8000"' in app
    assert '"8501"' in app
    assert '"80:80"' in caddy
    assert '"443:443"' in caddy
    assert "8000:8000" not in compose
    assert "8501:8501" not in compose
    assert (
        'COGNITO_REDIRECT_URI: "https://cde2300chatbot.duckdns.org/api/v1/auth/callback"'
        in app
    )
    assert 'CO_DESIGN_PUBLIC_API_URL: "https://cde2300chatbot.duckdns.org"' in app
    assert 'CO_DESIGN_UI_URL: "https://cde2300chatbot.duckdns.org"' in app
    assert "source: ./.streamlit/secrets.toml" in app


def test_caddy_exposes_only_auth_browser_routes_and_health_to_fastapi():
    """Public Caddy must not forward arbitrary /api/* into FastAPI."""
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert "cde2300chatbot.duckdns.org" in caddyfile
    assert "handle /api/v1/auth/login" in caddyfile
    assert "handle /api/v1/auth/callback" in caddyfile
    assert "handle /api/v1/auth/me" in caddyfile
    assert "handle /api/v1/auth/logout" in caddyfile
    assert "handle /api/v1/health" in caddyfile
    assert "handle /api/*" in caddyfile
    assert 'respond "Not Found" 404' in caddyfile
    assert "reverse_proxy app:8501" in caddyfile
    assert "handle_path" not in caddyfile

    login_index = caddyfile.index("handle /api/v1/auth/login")
    callback_index = caddyfile.index("handle /api/v1/auth/callback")
    me_index = caddyfile.index("handle /api/v1/auth/me")
    logout_index = caddyfile.index("handle /api/v1/auth/logout")
    health_index = caddyfile.index("handle /api/v1/health")
    block_index = caddyfile.index("handle /api/*")
    streamlit_index = caddyfile.index("handle {\n\t\treverse_proxy app:8501")
    assert login_index < block_index
    assert callback_index < block_index
    assert me_index < block_index
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
    assert 'CO_DESIGN_PUBLIC_API_URL: "https://cde2300chatbot.duckdns.org"' in app
    assert 'CO_DESIGN_UI_URL: "https://cde2300chatbot.duckdns.org"' in app
    assert "ports:" not in app


def test_compose_sets_production_cognito_redirect_uri():
    """Production must not silently use the local 127.0.0.1 Cognito callback."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")

    assert (
        'COGNITO_REDIRECT_URI: "https://cde2300chatbot.duckdns.org/api/v1/auth/callback"'
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
        "**/duck.env",
    ):
        assert required in ignore
    assert ".streamlit/secrets.toml.example" not in ignore
    assert "lecture_notes/" in ignore


def test_dockerfile_is_architecture_neutral():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "--platform=linux/arm64" not in dockerfile
    assert "--platform=linux/amd64" not in dockerfile
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


def test_duckdns_stays_on_host_not_in_application_modules():
    duck = (ROOT / "scripts" / "host" / "duck.sh").read_text(encoding="utf-8")
    assert "duckdns.org/update" in duck
    assert "DUCKDNS_TOKEN" in duck
    assert 'echo "$DUCKDNS_TOKEN"' not in duck
    for path in (ROOT / "backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "duckdns.org/update" not in text
        assert "DUCKDNS_TOKEN" not in text
