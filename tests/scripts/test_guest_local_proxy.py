"""Contract checks for the optional local same-origin guest proxy."""

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


def test_launcher_keeps_existing_mode_and_disables_guests_without_caddy():
    """Guest mode optionally starts Caddy; missing Caddy preserves standard startup."""
    script = Path("scripts/start.sh").read_text(encoding="utf-8")
    assert "command -v caddy" in script
    assert 'export GUEST_ACCESS_ENABLED="false"' in script
    assert 'LOCAL_BROWSER_URL="http://127.0.0.1:8501"' in script
    assert 'caddy run --config "$ROOT/Caddyfile.local" --adapter caddyfile' in script
    assert 'LOCAL_BROWSER_URL="http://127.0.0.1:8080"' in script
    proxy_branch = script.index('export CO_DESIGN_UI_URL="${CO_DESIGN_UI_URL:-http://127.0.0.1:8080}"')
    regular_branch = script.index('export CO_DESIGN_UI_URL="${CO_DESIGN_UI_URL:-http://127.0.0.1:8501}"')
    assert proxy_branch < regular_branch
    assert script.index('if command -v caddy') < proxy_branch
