"""Security readiness regressions for the student reader API (mock provider only).

Covers second-owner access, guest and registered boundaries, upload limits,
download headers, same-origin guards, admission bypass attempts, prompt
delimiters and secret-free logs and error bodies.
"""

from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.persistence.guest_sessions import guest_secret_digest
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user

ORIGIN = {"Origin": "https://testserver"}
BASE = "https://testserver"
NOTES = "Analogy transfers a relationship from a familiar setting to a new design problem."
PRIVATE = "PRIVATE_SOURCE_MARKER_zebra_9137"


class World:
    """One app with a registered owner A, a second owner B and guests."""

    def __init__(self, root: StudentStore, monkeypatch: MonkeyPatch, **options: Any) -> None:
        monkeypatch.setattr(settings, "public_api_base_url", BASE)
        monkeypatch.setattr(settings, "ui_base_url", BASE)
        monkeypatch.setattr(settings, "guest_access_enabled", True)
        self.root = root
        self.clients: list[TestClient] = []
        self.oidc = FakeOIDC(root)
        self.app = create_app(root, oidc_client=self.oidc, **options)
        for sub in ("alice", "bob"):
            _seed_user(root, sub, "student")

    def browser(self) -> TestClient:
        """Return a started client so the upload queue lifespan is running."""
        client = TestClient(self.app, base_url=BASE)
        client.__enter__()
        self.clients.append(client)
        return client

    def close(self) -> None:
        """Drain every started client."""
        for client in self.clients:
            client.__exit__(None, None, None)

    def registered(self, sub: str) -> TestClient:
        """Return a browser signed in as a seeded registered student."""
        client = self.browser()
        client.cookies.set(settings.cognito_id_token_cookie_name, self.oidc.add(sub))
        return client

    def guest(self) -> TestClient:
        """Return a browser that started a guest workspace."""
        client = self.browser()
        assert client.post("/api/v1/auth/guest/start", headers=ORIGIN).status_code == 200
        return client


def _turn(client: TestClient, path: str, message: str, key: str, *, kind: str = "lecture") -> dict[str, Any]:
    """Run one streamed turn and return the saved turn."""
    response = client.post(f"{path}/{kind}/stream", json={"student_message": message, "idempotency_key": key}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    return next(event["turn"] for event in events if event["event"] == "done")


def _wait_source(client: TestClient, path: str, title: str) -> dict[str, Any]:
    """Poll the source list until the background upload is visible."""
    for _ in range(400):
        found = next((row for row in client.get(path + "/sources").json()["sources"] if row["title"] == title), None)
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError("Upload did not become visible")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: MonkeyPatch) -> Any:
    """Return a fresh two-owner application."""
    value = World(StudentStore(tmp_path / "security.sqlite3"), monkeypatch)
    yield value
    value.close()


@pytest.fixture
def alice_data(world: World) -> dict[str, Any]:
    """Create owner A's chat with a private source, a cited answer and a saved turn."""
    alice = world.registered("alice")
    chat = alice.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    path = f"/api/v1/reader/threads/{chat}"
    body = f"{NOTES} {PRIVATE}".encode()
    assert alice.post(path + "/uploads", files={"files": ("alice-notes.txt", body, "text/plain")}, headers=ORIGIN).status_code == 202
    source = _wait_source(alice, path, "alice-notes.txt")
    turn = _turn(alice, path, "What is analogy?", "alice-1")
    message = alice.get(path + "/messages/page").json()["messages"][-1]
    assert message["citations"], turn
    return {"client": alice, "thread": chat, "path": path, "source": source["id"], "message": message["id"]}


def _reader_requests(data: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every reader route that takes a notebook, with a plausible well-formed request."""
    path, source, message = data["path"], data["source"], data["message"]
    pdf = {"files": ("x.txt", b"hello", "text/plain")}
    return [
        ("GET", path + "/settings", {}),
        ("GET", path + "/transcript.txt", {}),
        ("GET", path + "/messages/page", {}),
        ("GET", path + "/project", {}),
        ("GET", path + "/coach-turn?idempotency_key=alice-1", {}),
        ("GET", path + "/uploads", {}),
        ("GET", path + "/sources", {}),
        ("GET", path + f"/sources/{source}", {}),
        ("GET", path + f"/sources/{source}/content", {}),
        ("GET", path + f"/messages/{message}/citations/{source}/content", {}),
        ("POST", path + "/settings", {"json": {"name": "hijacked"}}),
        ("POST", path + "/move", {"json": {"parent_notebook_id": None}}),
        ("POST", path + "/remove", {"json": {"confirmed": True}}),
        ("POST", path + "/attachments", {"files": pdf}),
        ("POST", path + "/uploads", {"files": pdf}),
        ("POST", path + "/uploads/nope/retry", {}),
        ("POST", path + "/uploads/nope/discard", {}),
        ("POST", path + f"/sources/{source}/select", {"json": {"selected": False}}),
        ("POST", path + f"/sources/{source}/link", {}),
        ("POST", path + f"/sources/{source}/remove", {}),
        ("POST", path + "/lecture/stream", {"json": {"student_message": "hi there", "idempotency_key": "b-1"}}),
        ("POST", path + "/project/stream", {"json": {"student_message": "hi there", "idempotency_key": "b-2"}}),
        ("POST", path + "/project/select-stage", {"json": {"stage_id": "concept_generation"}}),
        ("POST", path + "/project/resolve/nope", {"json": {"accepted": True}}),
        ("POST", path + f"/messages/{message}/revise", {"json": {"content": "rewrite", "idempotency_key": "b-3"}}),
        ("POST", path + f"/messages/{message}/learning-signal", {"json": {"kind": "useful"}}),
    ]


@pytest.mark.parametrize("second", ["registered", "guest"])
def test_second_owner_cannot_read_or_write_any_reader_route(world: World, alice_data: dict[str, Any], second: str) -> None:
    """Every notebook-scoped reader route returns 404 for another owner and never echoes A's data."""
    intruder = world.registered("bob") if second == "registered" else world.guest()
    for method, url, options in _reader_requests(alice_data):
        response = intruder.request(method, url, headers=ORIGIN if method == "POST" else {}, **options)
        assert response.status_code in {404, 409}, (method, url, response.status_code, response.text[:200])
        assert PRIVATE not in response.text, (method, url)
        assert "alice-notes" not in response.text, (method, url)
    mine = alice_data["client"]
    path = alice_data["path"]
    assert mine.get(path + "/settings").json()["notebook"]["name"] != "hijacked"
    assert mine.get(path + "/messages/page").json()["total_count"] == 2
    assert [row["id"] for row in mine.get(path + "/sources").json()["sources"]] == [alice_data["source"]]
    assert mine.get(path + f"/sources/{alice_data['source']}").json()["source"]["selected"] is True


def test_second_owner_library_and_attachment_ids_are_not_resolvable(world: World, alice_data: dict[str, Any]) -> None:
    """B cannot reach A's source by id through the Library, its own notebook or an attachment id."""
    bob = world.registered("bob")
    source = alice_data["source"]
    own = bob.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    own_path = f"/api/v1/reader/threads/{own}"
    for url in (
        f"/api/v1/reader/threads/library/sources/{source}",
        f"/api/v1/reader/threads/library/sources/{source}/content",
        own_path + f"/sources/{source}",
        own_path + f"/sources/{source}/content",
    ):
        assert bob.get(url).status_code == 404, url
    assert bob.post(own_path + f"/sources/{source}/link", headers=ORIGIN).status_code == 404
    assert bob.post(f"/api/v1/reader/threads/library/sources/{source}/remove", json={"confirmed": True}, headers=ORIGIN).status_code in {404, 409}
    assert source not in {row["id"] for row in bob.get("/api/v1/reader/threads/library/sources").json()["sources"]}
    attachment = alice_data["client"].post(
        alice_data["path"] + "/attachments", files={"files": ("secret.txt", PRIVATE.encode(), "text/plain")}, headers=ORIGIN,
    ).json()[0]["id"]
    reply = bob.post(own_path + "/lecture/stream", json={
        "student_message": "Summarise the attached file.", "idempotency_key": "steal-1", "attachment_source_ids": [attachment],
    }, headers=ORIGIN)
    assert PRIVATE not in reply.text
    assert reply.status_code == 200
    events = [json.loads(line) for line in reply.text.splitlines()]
    assert [event["event"] for event in events] == ["started", "error"]
    assert events[-1]["status"] == 400
    assert alice_data["client"].get(alice_data["path"] + f"/sources/{source}").status_code == 200


LEGACY = [
    ("GET", "/api/v1/threads/{t}", {}),
    ("GET", "/api/v1/threads/{t}/messages", {}),
    ("GET", "/api/v1/threads/{t}/sources", {}),
    ("GET", "/api/v1/threads/{t}/sources/{s}", {}),
    ("GET", "/api/v1/threads/{t}/sources/{s}/content", {}),
    ("GET", "/api/v1/threads/{t}/transcript.txt", {}),
    ("GET", "/api/v1/threads/{t}/deep-analysis.pdf", {}),
    ("GET", "/api/v1/threads/{t}/deep-review", {}),
    ("GET", "/api/v1/threads/{t}/learning-state", {}),
    ("GET", "/api/v1/threads/{t}/phase-transitions/pending", {}),
    ("GET", "/api/v1/threads/{t}/journey-stage-reviews", {}),
    ("GET", "/api/v1/threads/{t}/coach-turn?idempotency_key=alice-1", {}),
    ("GET", "/api/v1/threads/{t}/graph", {}),
    ("PATCH", "/api/v1/threads/{t}", {"json": {"name": "hijacked"}}),
    ("DELETE", "/api/v1/threads/{t}", {}),
    ("DELETE", "/api/v1/threads/{t}/sources/{s}", {}),
    ("PATCH", "/api/v1/threads/{t}/sources/{s}", {"json": {"selected": False}}),
    ("POST", "/api/v1/threads/{t}/deep-review", {"json": {"idempotency_key": "b-deep"}}),
    ("POST", "/api/v1/threads/{t}/messages", {"json": {"role": "assistant", "content": "forged"}}),
    ("POST", "/api/v1/threads/{t}/learning-state/select-stage", {"json": {"stage_id": "concept_generation"}}),
    ("POST", "/api/v1/threads/{t}/sources", {"files": {"files": ("x.txt", b"hello", "text/plain")}}),
    ("POST", "/api/v1/threads/{t}/attachments", {"files": {"files": ("x.txt", b"hello", "text/plain")}}),
    ("POST", "/api/v1/threads/{t}/sources/select-all", {"json": {"selected": False}}),
    ("POST", "/api/v1/coach/turn", {"json": {
        "thread_id": "{t}", "student_message": "hello there", "current_stage": "problem_identification",
        "response_detail": "short", "idempotency_key": "b-legacy-1",
    }}),
]


def _fill(value: Any, data: dict[str, Any]) -> Any:
    """Substitute notebook and source ids into a legacy request template."""
    if isinstance(value, str):
        return value.replace("{t}", data["thread"]).replace("{s}", data["source"])
    if isinstance(value, dict):
        return {key: _fill(item, data) for key, item in value.items()}
    return value


@pytest.mark.parametrize("second", ["registered", "guest"])
def test_second_owner_cannot_use_legacy_routes_including_deep_review(world: World, alice_data: dict[str, Any], second: str) -> None:
    """The owner-scoped store API also hides A's notebook, sources, project state and Deep Review."""
    intruder = world.registered("bob") if second == "registered" else world.guest()
    for method, template, options in LEGACY:
        url = _fill(template, alice_data)
        response = intruder.request(method, url, **{key: _fill(value, alice_data) for key, value in options.items()})
        assert response.status_code in {400, 404}, (method, url, response.status_code, response.text[:200])
        assert PRIVATE not in response.text, (method, url)
    assert alice_data["client"].get(alice_data["path"] + "/messages/page").json()["total_count"] == 2
    assert alice_data["client"].get(alice_data["path"] + "/settings").json()["notebook"]["name"] != "hijacked"


def test_citation_content_requires_the_saved_citation_and_downloads_as_attachment(world: World, alice_data: dict[str, Any]) -> None:
    """Only a saved assistant citation opens evidence, and it cannot execute in a browser."""
    alice, path, source = alice_data["client"], alice_data["path"], alice_data["source"]
    message = alice_data["message"]
    ok = alice.get(path + f"/messages/{message}/citations/{source}/content")
    assert ok.status_code == 200
    assert ok.headers["content-type"].split(";")[0] == "application/octet-stream"
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["content-disposition"].startswith("attachment;")
    user_row = next(row for row in alice.get(path + "/messages/page").json()["messages"] if row["role"] == "user")
    assert alice.get(path + f"/messages/{user_row['id']}/citations/{source}/content").status_code == 404
    other = alice.post(path + "/attachments", files={"files": ("other.txt", b"not cited", "text/plain")}, headers=ORIGIN).json()[0]["id"]
    assert alice.get(path + f"/messages/{message}/citations/{other}/content").status_code == 404
    assert alice.get(path + f"/messages/nope/citations/{source}/content").status_code == 404


@pytest.mark.parametrize("name,mime", [
    ("page.html", "text/html"), ("data.xml", "application/xml"),
    ("code.js", "text/javascript"), ("note.txt", "text/html"),
])
def test_active_content_uploads_never_render_inline(world: World, name: str, mime: str) -> None:
    """HTML, SVG and script uploads come back as nosniff attachments on the reader and legacy routes."""
    client = world.guest()
    chat = client.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    path = f"/api/v1/reader/threads/{chat}"
    payload = b"<script>alert(document.cookie)</script><img src=x onerror=alert(1)>"
    assert client.post(path + "/uploads", files={"files": (name, payload, mime)}, headers=ORIGIN).status_code == 202
    source = _wait_source(client, path, name)["id"]
    for url in (path + f"/sources/{source}/content",
                f"/api/v1/threads/{chat}/sources/{source}/content",
                f"/api/v1/threads/library/sources/{source}/content"):
        response = client.get(url)
        if response.status_code == 404:
            continue
        assert response.status_code == 200, url
        assert response.headers["content-type"].split(";")[0] in {"application/octet-stream", "text/plain"}, (url, response.headers)
        assert response.headers.get("x-content-type-options") == "nosniff", url
        assert response.headers["content-disposition"].lower().startswith("attachment"), (url, response.headers)
    detail = client.get(path + f"/sources/{source}")
    assert detail.headers["content-type"].startswith("application/json")


def test_svg_upload_is_rejected_as_an_image(world: World) -> None:
    """An SVG is not an accepted raster image, so scriptable image markup is never stored."""
    client = world.guest()
    chat = client.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    response = client.post(f"/api/v1/reader/threads/{chat}/uploads", headers=ORIGIN, files={
        "files": ("image.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml"),
    })
    assert response.status_code == 422


def test_filename_in_content_disposition_cannot_inject_headers(world: World) -> None:
    """A hostile upload name cannot split headers or escape the attachment filename."""
    client = world.guest()
    chat = client.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    path = f"/api/v1/reader/threads/{chat}"
    name = 'a"; filename="evil.html\r\nX-Injected: 1.txt'
    assert client.post(path + "/uploads", files={"files": (name, b"hello", "text/plain")}, headers=ORIGIN).status_code == 202
    for _ in range(400):
        rows = client.get(path + "/sources").json()["sources"]
        if rows:
            break
        time.sleep(0.01)
    response = client.get(path + f"/sources/{rows[0]['id']}/content")
    assert response.status_code == 200
    assert "x-injected" not in {key.lower() for key in response.headers}
    assert "\n" not in response.headers["content-disposition"]
    assert '"' not in response.headers["content-disposition"].split("filename*=", 1)[1]


def test_source_titles_and_listings_never_expose_storage_paths(world: World, alice_data: dict[str, Any]) -> None:
    """Reader and legacy source projections carry no object keys or filesystem paths; the reader list also omits extracted text."""
    alice, path, thread = alice_data["client"], alice_data["path"], alice_data["thread"]
    bodies = [
        alice.get(path + "/sources").text,
        alice.get(path + f"/sources/{alice_data['source']}").text.replace(PRIVATE, ""),
        alice.get(f"/api/v1/threads/{thread}/sources").text.replace(PRIVATE, ""),
        alice.get(path + "/messages/page").text,
    ]
    for body in bodies:
        for forbidden in ("object_key", "users/", "/threads/", str(settings.files_dir)):
            assert forbidden not in body, forbidden
    assert PRIVATE not in alice.get(path + "/sources").text


def _reader_routes(app: Any) -> list[APIRoute]:
    """Every public reader route registered on the application."""
    return [
        route for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/reader/")
    ]


def _concrete(path: str) -> str:
    """Fill every path parameter with a placeholder id."""
    import re

    return re.sub(r"\{[^}]+\}", "x", path)


def test_reader_route_inventory_is_large_enough_to_trust_the_origin_sweep(world: World) -> None:
    """The sweep below must see the real inventory, not an empty or shrunken list."""
    routes = _reader_routes(world.app)
    assert len([route for route in routes if "POST" in route.methods]) >= 18
    assert len([route for route in routes if "GET" in route.methods]) >= 10


def test_every_state_changing_reader_route_requires_same_origin(world: World) -> None:
    """A signed-in browser still gets 403 without Origin, with a foreign Origin or cross-site fetch metadata."""
    client = world.registered("alice")
    hostile = [
        {},
        {"Origin": "https://evil.test"},
        {"Origin": "null"},
        {"Origin": "https://testserver.evil.test"},
        {"Origin": "https://evil.test/https://testserver"},
        {"Origin": "http://testserver"},
        {"Origin": "https://testserver:8443"},
        {"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"},
    ]
    for route in _reader_routes(world.app):
        if not route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        for headers in hostile:
            response = client.post(_concrete(route.path), headers=headers)
            assert response.status_code == 403, (route.path, headers, response.status_code, response.text[:120])
    assert client.post("/api/v1/reader/preferences", json={"appearance": "Dark"}, headers=ORIGIN).status_code == 200


def test_every_reader_route_requires_credentials_and_rejects_cross_site_reads(world: World) -> None:
    """Anonymous callers get 401; cross-site and foreign-origin reads get 403 even when signed in."""
    anonymous = TestClient(world.app, base_url=BASE)
    signed_in = world.registered("alice")
    for route in _reader_routes(world.app):
        url = _concrete(route.path)
        for method in sorted(route.methods & {"GET", "POST"}):
            response = anonymous.request(method, url, headers=ORIGIN)
            assert response.status_code == 401, (method, route.path, response.status_code)
            assert signed_in.request(method, url, headers={**ORIGIN, "Sec-Fetch-Site": "cross-site"}).status_code == 403, (method, route.path)
            assert signed_in.request(method, url, headers={"Origin": "https://evil.test"}).status_code == 403, (method, route.path)


def test_legacy_state_changing_routes_reject_foreign_browser_origins(world: World, alice_data: dict[str, Any]) -> None:
    """A cookie-bearing browser POST from another origin or site cannot mutate through the owner-scoped API."""
    alice, thread = alice_data["client"], alice_data["thread"]
    for headers in ({"Origin": "https://evil.test"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
        assert alice.patch(f"/api/v1/threads/{thread}", json={"name": "csrf"}, headers=headers).status_code == 403, headers
        assert alice.delete(f"/api/v1/threads/{thread}", headers=headers).status_code == 403, headers
        assert alice.post("/api/v1/threads", json={"name": "csrf", "model_id": "mock", "support_mode": "critical-thinking"}, headers=headers).status_code == 403, headers
        assert alice.post("/api/v1/coach/turn", json={"thread_id": thread, "student_message": "csrf", "current_stage": "problem_identification",
                                                       "response_detail": "short", "idempotency_key": "csrf-1"}, headers=headers).status_code == 403, headers
    assert alice.get(f"/api/v1/threads/{thread}").json()["name"] != "csrf"
    # Server-side callers (Streamlit) and same-origin browsers carry no or matching Origin.
    assert alice.patch(f"/api/v1/threads/{thread}", json={"name": "ok"}).status_code == 200
    assert alice.patch(f"/api/v1/threads/{thread}", json={"name": "ok2"}, headers=ORIGIN).status_code == 200


def test_guest_and_registered_boundaries(world: World, monkeypatch: MonkeyPatch) -> None:
    """Guests stay in their own workspace, never reach lecturer routes, and cannot start while the flag is off."""
    guest, other_guest, registered = world.guest(), world.guest(), world.registered("alice")
    assert guest.get("/api/v1/reader/session").json()["kind"] == "guest"
    assert registered.get("/api/v1/reader/session").json()["kind"] == "registered"
    assert guest.get("/api/v1/reader/session").json()["owner_id"] != other_guest.get("/api/v1/reader/session").json()["owner_id"]
    for client in (guest, registered):
        for url in ("/api/v1/professor/overview", "/api/v1/professor/students", "/api/v1/professor/learning-funnel", "/api/v1/professor/research/export.csv"):
            assert client.get(url).status_code in {401, 403}, url
    assert guest.get("/api/v1/auth/me").status_code == 401
    mine = guest.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    assert other_guest.get(f"/api/v1/reader/threads/{mine}/messages/page").status_code == 404
    assert registered.get(f"/api/v1/reader/threads/{mine}/messages/page").status_code == 404
    monkeypatch.setattr(settings, "guest_access_enabled", False)
    assert guest.get("/api/v1/reader/session").status_code == 401
    assert TestClient(world.app, base_url=BASE).post("/api/v1/auth/guest/start", headers=ORIGIN).status_code == 404


def test_lecturer_and_admin_roles_cannot_use_the_student_reader(world: World) -> None:
    """Staff accounts are sent to the lecturer workspace instead of reading student reader routes."""
    _seed_user(world.root, "prof", "lecturer")
    client = world.registered("prof")
    assert client.get("/api/v1/reader/session").status_code == 403
    assert client.get("/api/v1/reader/threads").status_code == 403


def test_invalid_or_revoked_guest_secrets_fail_closed(world: World) -> None:
    """Forged, truncated, digest-as-secret and revoked guest cookies never open a workspace."""
    guest = world.guest()
    secret = guest.cookies.get(settings.guest_session_cookie_name)
    assert secret
    for value in ("forged", secret[:-1], secret + "x", guest_secret_digest(secret), "", "' OR 1=1 --"):
        probe = TestClient(world.app, base_url=BASE)
        probe.cookies.set(settings.guest_session_cookie_name, value)
        assert probe.get("/api/v1/reader/session").status_code == 401, value
    bad = TestClient(world.app, base_url=BASE)
    bad.cookies.set(settings.cognito_id_token_cookie_name, "not-a-token")
    bad.cookies.set(settings.guest_session_cookie_name, secret)
    assert bad.get("/api/v1/reader/session").status_code == 401
    assert world.root.revoke_guest_session(secret)
    assert guest.get("/api/v1/reader/session").status_code == 401


def test_guest_claim_needs_a_cognito_account_origin_and_the_matching_operation(world: World) -> None:
    """A guest cookie alone cannot claim itself, and another account cannot finish A's pending claim."""
    guest = world.guest()
    secret = guest.cookies.get(settings.guest_session_cookie_name)
    for url in ("preview", "confirm", "cancel"):
        assert guest.post(f"/api/v1/auth/guest/claim/{url}", json={"confirmed": True, "operation_id": "0" * 32}).status_code == 403
        assert guest.post(f"/api/v1/auth/guest/claim/{url}", json={"confirmed": True, "operation_id": "0" * 32}, headers=ORIGIN).status_code == 401
    chat = guest.post("/api/v1/reader/threads", json={"kind": "chat"}, headers=ORIGIN).json()["notebook"]["id"]
    alice, bob = world.registered("alice"), world.registered("bob")
    for browser in (alice, bob):
        browser.cookies.set(settings.guest_session_cookie_name, secret)
    preview = alice.post("/api/v1/auth/guest/claim/preview", headers=ORIGIN)
    assert preview.status_code == 200, preview.text
    operation = preview.json()["operation_id"]
    assert alice.post("/api/v1/auth/guest/claim/confirm", json={"confirmed": False, "operation_id": operation}, headers=ORIGIN).status_code == 400
    stolen = bob.post("/api/v1/auth/guest/claim/confirm", json={"confirmed": True, "operation_id": operation}, headers=ORIGIN)
    assert stolen.status_code in {401, 409}, stolen.text
    assert bob.get(f"/api/v1/reader/threads/{chat}/messages/page").status_code == 404
    assert alice.post("/api/v1/auth/guest/claim/confirm", json={"confirmed": True, "operation_id": operation}, headers=ORIGIN).status_code == 200
    assert alice.get(f"/api/v1/reader/threads/{chat}/messages/page").status_code == 200
    assert bob.get(f"/api/v1/reader/threads/{chat}/messages/page").status_code == 404
    assert guest.get("/api/v1/reader/session").status_code == 401
