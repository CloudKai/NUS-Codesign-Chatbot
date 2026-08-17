"""Cache-key and shared-client safety for Streamlit runtime resources."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from backend.auth_profiles import store_identifier_for_sub
from ui.services.runtime import (
    _NonPersistentCookies,
    bind_owner_identifier,
    local_api_client,
    owner_identifier,
    resources,
)


def test_cognito_store_identifier_cannot_collide_with_demo_owner() -> None:
    """Unauthenticated ``local-student`` must not share a Cognito cache key."""
    assert store_identifier_for_sub("local-student") == "cognito:local-student"
    assert store_identifier_for_sub("test-cognito-sub") != "local-student"
    first, _, _, _ = resources("local-student")
    second, _, _, _ = resources("cognito:test-cognito-sub")
    assert first is not second
    assert getattr(first, "identifier", None) != getattr(second, "identifier", None)


def test_owner_identifier_repairs_cognito_session_without_demo_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bound Cognito sub must not resolve to the unauthenticated demo owner."""
    import ui.services.runtime as runtime_mod

    fake_state: dict[str, object] = {"_auth_bound_sub": "sub-from-session"}
    monkeypatch.setattr(runtime_mod, "st", SimpleNamespace(session_state=fake_state))
    identifier = owner_identifier()
    assert identifier == "cognito:sub-from-session"
    assert identifier != "local-student"
    bind_owner_identifier("cognito:other-sub")
    assert owner_identifier() == "cognito:other-sub"


def test_shared_local_api_client_does_not_persist_set_cookie() -> None:
    """Process-wide httpx client must not keep another student's Set-Cookie."""
    local_api_client.clear()
    client = local_api_client()
    http = client._http
    assert isinstance(http, httpx.Client)
    assert isinstance(http._cookies, _NonPersistentCookies)
    request = httpx.Request("GET", "http://127.0.0.1:8000/api/v1/health")
    response = httpx.Response(
        200,
        headers=[("set-cookie", "co_design_id=stolen-session; Path=/")],
        request=request,
    )
    http.cookies.extract_cookies(response)
    assert "co_design_id" not in http.cookies
    assert list(http.cookies.jar) == []


def test_cookie_provider_still_forwards_id_cookie_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth still attaches the current browser ID cookie on each request."""
    local_api_client.clear()
    client = local_api_client()
    monkeypatch.setattr(
        client,
        "_cookie_provider",
        lambda: {"co_design_id": "current-student-token"},
    )
    forwarded = client._auth_cookies()
    assert forwarded == {"co_design_id": "current-student-token"}
    # The shared jar stays empty; per-request cookies are not stored there.
    assert list(client._http.cookies.jar) == []


def test_course_material_sync_jobs_are_keyed_by_thread_not_shared_result() -> None:
    """Sync serialization is a performance limit; jobs do not share by student.

    ``CourseMaterialSyncCoordinator`` uses ``max_workers=1`` process-wide, so
    students queue. In-process keys include store identifier + thread id.
    API-mode keys include thread id. That is not a data-visibility bug: joining
    a job requires the same notebook id, and the future only carries counts.
    """
    from backend.source_library import CourseMaterialSyncCoordinator

    coordinator = CourseMaterialSyncCoordinator()
    store = SimpleNamespace(path="/tmp/a.sqlite3", identifier="cognito:student-a")
    assert coordinator._key(store, "thread-1") != coordinator._key(
        SimpleNamespace(path="/tmp/a.sqlite3", identifier="cognito:student-b"),
        "thread-1",
    )
    assert coordinator._key(store, "thread-1") != coordinator._key(store, "thread-2")
