# Implementation status

## Current phase

**Auth hardening: OAuth state binder, no Streamlit auth cache, production redirect**

Follow-up to FastAPI-owned application sessions on branch ``Kai``. Fixes three
remaining authentication issues without changing the opaque session design.

### Behavior implemented

1. **Browser-bound OAuth state** — ``/auth/login`` sets short-lived HttpOnly
   ``co_design_oauth_state`` (Path=``/api/v1/auth``, Max-Age=600, SameSite=Lax,
   Secure from ``APP_SESSION_COOKIE_SECURE``). ``/auth/callback`` requires the
   query ``state`` to match that cookie via ``hmac.compare_digest`` before
   consuming the DB PKCE verifier. Cookie cleared on success and handled
   failure; failed validation never creates an app session.
2. **No Streamlit auth cache** — ``authenticated_user()`` calls
   ``/api/v1/auth/me`` on every rerun; raw session token is not stored in
   ``st.session_state``.
3. **Production Cognito redirect** — precedence is explicit
   ``COGNITO_REDIRECT_URI`` → secrets.toml ``redirect_uri`` → derived
   ``CO_DESIGN_PUBLIC_API_URL`` + ``/api/v1/auth/callback``. Compose sets
   production callback explicitly; settings no longer hard-code a local default
   that overrides secrets.

### Files changed

- Updated: ``backend/auth_routes.py``, ``backend/app_sessions.py``,
  ``backend/auth_oidc.py``, ``backend/cognito_config.py``, ``backend/settings.py``,
  ``ui/auth_gate.py``, ``compose.yaml``, ``.env.example``,
  ``.streamlit/secrets.toml.example``, ``tests/test_app_sessions.py``,
  ``tests/test_auth_gate.py``, ``tests/test_deployment_config.py``, this status
  file.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **168 passed** (mock provider; no Cognito
  network; no paid model calls).
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py`` → exit 0.
- ``docker compose config -q`` → exit 0.
- Private ``.env`` / ``.streamlit/secrets.toml`` not modified. No provider code
  changed. No SQLite student data reset.

### Migration / compatibility / rollback

- No schema change. Existing ``app_sessions`` / ``oauth_login_states`` unchanged.
- Production Compose now requires Cognito Allowed callback
  ``https://cde2300chatbot.duckdns.org/api/v1/auth/callback``.
- Local remains ``http://127.0.0.1:8000/api/v1/auth/callback``.

### Risks / blockers

- FastAPI coaching/CRUD remain unauthenticated on the Compose network; Caddy
  still blocks them publicly.
- Cognito hosted SSO is still not cleared on app logout.
- ``/auth/me`` on every Streamlit rerun adds a loopback round-trip (intentional).

### Next exact action

- Redeploy Compose with updated ``COGNITO_REDIRECT_URI``, confirm Cognito console
  allows the production callback, then smoke: login → reload → logout → reject
  old cookie; confirm OAuth state cookie is present only during login/callback.

## Previous completed work

**FastAPI-owned application sessions replace Streamlit OIDC cookies**

Cognito proves identity at sign-in; FastAPI issues a 30-day opaque
``co_design_session`` (hash in SQLite); Streamlit authenticates via ``/auth/me``.

**Public Caddy API exposure reduced / single-EC2 Docker deployment**
