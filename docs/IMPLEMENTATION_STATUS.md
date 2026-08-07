# Implementation status

## Current phase

**FastAPI-owned application sessions replace Streamlit OIDC cookies**

Authentication is now:

```text
Cognito authentication
        ↓
FastAPI /api/v1/auth/callback
        ↓
30-day application session (SQLite locally / PostgreSQL later)
        ↓
opaque HttpOnly co_design_session cookie
        ↓
Streamlit asks FastAPI /api/v1/auth/me
```

Cognito tokens establish identity at sign-in. The application does not persist
Cognito access, ID, or refresh tokens. Ongoing authentication is controlled by
the FastAPI application session. ``st.login`` / ``st.user`` / ``st.logout`` are
no longer the session authority.

### Behavior implemented

- Added ``app_sessions`` and ``oauth_login_states`` SQLite tables (additive
  ``CREATE TABLE IF NOT EXISTS``).
- Session tokens: ``secrets.token_urlsafe(32)``; only SHA-256 hashes stored.
- FastAPI routes: ``/auth/login``, ``/auth/callback``, ``/auth/me``, ``/auth/logout``.
- Streamlit auth gate reads ``st.context.cookies`` and trusts only ``/auth/me``.
- Caddy publicly exposes login/callback/logout/(legacy logout callback)/health;
  blocks other ``/api/*``. ``/auth/me`` stays on container loopback.
- Existing Cognito ``sub`` upsert / ``cognito:{sub}`` owner binding preserved.
- Cookie: HttpOnly, SameSite=Lax, Path=/, Max-Age=APP_SESSION_TTL_SECONDS,
  Secure from ``APP_SESSION_COOKIE_SECURE`` (false local / true Compose).

### Files changed

- Added: ``backend/session_tokens.py``, ``backend/app_sessions.py``,
  ``backend/cognito_config.py``, ``backend/auth_oidc.py``,
  ``backend/auth_routes.py``, ``tests/test_app_sessions.py``.
- Updated: ``backend/api.py``, ``backend/api_client.py``, ``backend/settings.py``,
  ``backend/student_store.py``, ``backend/auth_profiles.py``, ``ui/auth_gate.py``,
  ``streamlit_app.py``, ``tests/conftest.py``, ``tests/test_auth_gate.py``,
  ``tests/test_deployment_config.py``, ``Caddyfile``, ``compose.yaml``,
  ``.env.example``, ``.streamlit/secrets.toml.example``, ``requirements.txt``,
  ``README.md``, this status file.

### Dependency

- ``joserfc>=1.0.0`` — verify Cognito ID tokens against JWKS with a maintained
  JOSE library (Authlib's jose path is deprecated; Authlib already depended on
  joserfc transitively; pinned explicitly for clarity).

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **163 passed** (mock provider; no Cognito
  network; no paid model calls).
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py`` → exit 0.
- ``docker compose config -q`` → exit 0.
- Private ``.env`` / ``.streamlit/secrets.toml`` remain gitignored and were not
  modified by this phase. No model/provider modules changed. No live SQLite
  student DB reset.

### Migration / compatibility / rollback

- Additive schema only; existing notebooks/users/uploads untouched when present.
- Cognito console must allow
  ``http://127.0.0.1:8000/api/v1/auth/callback`` (local) instead of Streamlit
  ``/oauth2callback``.
- Rollback restores Streamlit OIDC gate code; session tables can remain unused.

### Risks / blockers

- FastAPI coaching/CRUD remain unauthenticated on the Compose network; Caddy
  still blocks them publicly.
- Cognito hosted SSO session is not cleared on app logout (by design this phase).
- Live Cognito smoke requires updated callback URL and local secrets.

### Next exact action

- Update Cognito Allowed callback URLs, set private secrets
  ``redirect_uri`` to the FastAPI callback, restart ``sh scripts/start.sh``,
  and manually complete sign-in → reload → logout → reject old cookie.

## Previous completed work

**Public Caddy API exposure reduced to logout + health** (superseded by the
broader auth-route allow-list above).

**Single-EC2 production Docker deployment preparation complete**

Python 3.12 app image, supervised dual-process entrypoint, Compose with
internal ``8000``/``8501``, and Caddy on ``80``/``443``.

**Earlier Cognito / Streamlit OIDC login** (replaced by this phase)

Streamlit-native Cognito authorization-code login and Streamlit's signed
identity cookie are no longer the application session authority.
