"""Contract checks for the local same-origin browser proxy."""

from pathlib import Path


def test_local_proxy_routes_only_explicit_auth_and_health_paths():
    """Caddy exposes exact browser routes while keeping other API paths closed."""
    config = Path("Caddyfile.local").read_text(encoding="utf-8")
    for route in (
        "/api/v1/auth/guest/start",
        "/api/v1/auth/guest/probe",
        "/api/v1/auth/guest/renew",
        "/api/v1/auth/guest/claim/preview",
        "/api/v1/auth/guest/claim/confirm",
        "/api/v1/auth/guest/claim/cancel",
        "/api/v1/auth/login",
        "/api/v1/auth/callback",
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/health",
    ):
        assert f"handle {route} {{" in config
    assert 'handle /api/* {\n\t\trespond "Not Found" 404' in config
    assert "handle /api/* {\n\t\treverse_proxy" not in config


def test_launcher_routes_the_root_through_caddy_with_or_without_guests():
    """Both guest configurations use the same React-first browser endpoint."""
    script = Path("scripts/start.sh").read_text(encoding="utf-8")
    config = Path("Caddyfile.local").read_text(encoding="utf-8")
    assert "command -v caddy" in script
    assert 'caddy run --config "$ROOT/Caddyfile.local" --adapter caddyfile' in script
    assert 'LOCAL_BROWSER_URL="http://127.0.0.1:8080"' in script
    assert "--server.baseUrlPath streamlit" in script
    assert "GUEST_ACCESS_ENABLED" not in script
    assert "handle / {\n\t\treverse_proxy 127.0.0.1:8000" in config
    assert "handle /api/v1/auth/streamlit-access" not in config
    assert "uri /api/v1/auth/streamlit-access" in config
    assert "header_up -Upgrade" in config
    assert "header_up -Connection" in config
