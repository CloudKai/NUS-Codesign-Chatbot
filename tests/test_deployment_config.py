"""Static safety checks for the single-EC2 Docker deployment files."""

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
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = _service_block(compose, "app")

    assert "source: ./data" in app
    assert "target: /app/data" in app
    assert "source: ./.streamlit/secrets.toml" in app
    assert "target: /app/.streamlit/secrets.toml" in app
    assert "read_only: true" in app
    assert app.count("create_host_path: false") == 2


def test_caddy_exposes_only_auth_browser_routes_and_health_to_fastapi():
    """Public Caddy must not forward arbitrary /api/* into FastAPI."""
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert "cde2300chatbot.duckdns.org" in caddyfile
    assert "handle /api/v1/auth/login" in caddyfile
    assert "handle /api/v1/auth/callback" in caddyfile
    assert "handle /api/v1/auth/logout" in caddyfile
    assert "handle /api/v1/health" in caddyfile
    assert "handle /api/*" in caddyfile
    assert 'respond "Not Found" 404' in caddyfile
    assert "reverse_proxy app:8501" in caddyfile
    assert "handle_path" not in caddyfile
    assert "handle /api/v1/auth/me" not in caddyfile

    login_index = caddyfile.index("handle /api/v1/auth/login")
    callback_index = caddyfile.index("handle /api/v1/auth/callback")
    logout_index = caddyfile.index("handle /api/v1/auth/logout")
    health_index = caddyfile.index("handle /api/v1/health")
    block_index = caddyfile.index("handle /api/*")
    streamlit_index = caddyfile.index("handle {\n\t\treverse_proxy app:8501")
    assert login_index < block_index
    assert callback_index < block_index
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
        "*.log",
    ):
        assert required in ignore
    assert ".streamlit/secrets.toml.example" not in ignore
    assert "lecture_notes/" not in ignore


def test_dockerfile_uses_python_312_and_production_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "python -m pip install -r requirements.txt" in dockerfile
    assert 'ENTRYPOINT ["sh", "scripts/start_prod.sh"]' in dockerfile


def test_production_script_binds_both_services_to_container_network():
    script = (ROOT / "scripts" / "start_prod.sh").read_text(encoding="utf-8")

    assert "backend.api:app" in script
    assert "--host 0.0.0.0" in script
    assert "--server.address 0.0.0.0" in script
    assert "--server.headless true" in script
    assert "USE_LOCAL_API" in script
    assert "kill -0" in script
    assert "Application data directory must exist and be writable" in script
    assert "Streamlit secrets must be a readable file" in script
