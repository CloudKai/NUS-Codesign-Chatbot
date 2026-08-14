"""Regression gates for package boundaries and compatibility façades.

These tests protect observable contracts while large modules are extracted.
They intentionally avoid arbitrary file-size or folder-shape assertions: the
architecture is judged by dependencies and public behavior, not cosmetics.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType
from typing import Iterable

from backend.api import create_app
from backend.persistence.dsql_student_store import _OCC_WRITE_METHODS
from backend.student_store import StudentStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _python_modules(package: str) -> dict[str, Path]:
    """Return importable module names and source paths below *package*."""
    root = PROJECT_ROOT / package
    modules: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PROJECT_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    return modules


def _top_level_imports(path: Path) -> Iterable[tuple[str, int]]:
    """Yield absolute import targets and relative levels at module scope."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Import):
            yield from ((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def _resolve_import(module: str, target: str, level: int) -> str:
    """Resolve one AST import target relative to *module*."""
    if level == 0:
        return target
    package_parts = module.split(".")[:-1]
    keep = max(0, len(package_parts) - level + 1)
    base = package_parts[:keep]
    if target:
        base.extend(target.split("."))
    return ".".join(base)


def _internal_import_graph(package: str) -> dict[str, set[str]]:
    """Build the module-scope dependency graph for one production package."""
    modules = _python_modules(package)
    graph = {module: set() for module in modules}
    for module, path in modules.items():
        for target, level in _top_level_imports(path):
            resolved = _resolve_import(module, target, level)
            candidates = resolved.split(".")
            while candidates:
                candidate = ".".join(candidates)
                if candidate in modules:
                    graph[module].add(candidate)
                    break
                candidates.pop()
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return strongly connected components containing a real import cycle."""
    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for dependency in graph[node]:
            if dependency not in indexes:
                visit(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[dependency])
        if lowlinks[node] != indexes[node]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or node in graph[node]:
            components.append(sorted(component))

    for node in graph:
        if node not in indexes:
            visit(node)
    return sorted(components)


def test_backend_never_imports_ui() -> None:
    """The application/backend boundary must not depend on presentation."""
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "backend").rglob("*.py"):
        for target, _level in _top_level_imports(path):
            if target == "ui" or target.startswith("ui."):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == []


def test_ui_has_no_direct_infrastructure_or_model_sdk_imports() -> None:
    """Streamlit presentation may call services but not infrastructure SDKs."""
    banned = ("boto3", "langchain", "langgraph", "openai", "psycopg", "sqlite3")
    offenders: list[tuple[str, str]] = []
    for path in (PROJECT_ROOT / "ui").rglob("*.py"):
        for target, _level in _top_level_imports(path):
            if target in banned or target.startswith(
                tuple(f"{name}." for name in banned)
            ):
                offenders.append((str(path.relative_to(PROJECT_ROOT)), target))
    assert offenders == []


def test_production_packages_have_no_module_scope_import_cycles() -> None:
    """Production imports must remain acyclic at module initialization time."""
    assert _cycles(_internal_import_graph("backend")) == []
    assert _cycles(_internal_import_graph("ui")) == []


def test_compatibility_facade_exports_and_signatures_are_stable() -> None:
    """Existing import paths remain valid while implementations move."""
    expected: dict[str, dict[str, str | None]] = {
        "backend.api": {
            "create_app": "(store: 'StudentStore | None' = None, *, auto_advance_stages: 'bool | None' = None, workspace: 'WorkspaceService | None' = None, oidc_client: 'CognitoOIDCClient | None' = None) -> 'FastAPI'",
        },
        "backend.student_journey": {
            "normalize_journey": "(value: 'Any') -> 'dict[str, Any]'",
            "complete_and_advance": "(journey: 'dict[str, Any]', *, note: 'str | None' = None) -> 'dict[str, Any]'",
            "learning_review": "(messages: 'Iterable[dict[str, Any]]', journey: 'dict[str, Any]', *, detail: 'str | None' = None) -> 'dict[str, Any]'",
        },
        "backend.source_library": {
            "add_file_sources": "(store: 'StudentStore', thread_id: 'str', uploads: 'Iterable[tuple[str, bytes, str | None]]', *, origin: 'str' = 'source_panel', extra_metadata: 'dict[str, Any] | None' = None, max_file_size_mb: 'int | None' = None, preserve_display_names: 'bool' = False, compress: 'bool' = True) -> 'list[dict[str, Any]]'",
            "selected_source_context": "(sources: 'Iterable[dict[str, Any]]', *, limit: 'int' = 160000) -> 'tuple[str, list[dict[str, Any]]]'",
            "image_inputs_for_source_ids": "(store: 'StudentStore', thread_id: 'str', source_ids: 'Iterable[str]') -> 'list[dict[str, str]]'",
        },
        "ui.auth_gate": {
            # The autouse UI fixture replaces these callables to keep AppTest
            # authenticated; export presence is the stable contract here.
            "authenticated_user": None,
            "is_logged_in": None,
            "render_login_gate": "() -> 'None'",
        },
        "ui.runtime": {
            "local_api_client": "() -> 'LocalApiClient'",
            "rerun_app": "() -> 'None'",
            "rerun_fragment": "() -> 'None'",
        },
        "ui.chat": {
            "render_chat_panel": "(model_id: 'str', reasoning_effort: 'str | None') -> 'None'",
        },
        "ui.sources": {"render_sources_panel": "() -> 'None'"},
        "ui.studio": {"render_studio_panel": "() -> 'None'"},
    }
    for module_name, exports in expected.items():
        module: ModuleType = __import__(module_name, fromlist=["*"])
        for name, signature in exports.items():
            value = getattr(module, name)
            assert callable(value)
            if signature is not None:
                assert str(inspect.signature(value)) == signature


def test_student_store_public_and_dsql_occ_contracts_are_stable() -> None:
    """Persistence extraction cannot silently drop methods or OCC coverage."""
    expected_public = {
        "add_message",
        "add_source",
        "append_research_adjudication",
        "append_research_review",
        "apply_phase_transition_decision",
        "claim_coach_request",
        "complete_coach_request",
        "consume_oauth_login_state",
        "create_phase_transition",
        "create_thread",
        "delete_source",
        "delete_thread",
        "fail_coach_request",
        "find_source_by_path",
        "get_messages",
        "get_messages_at_revision",
        "get_pending_phase_transition",
        "get_research_observation",
        "get_source",
        "get_system_metadata",
        "get_thread",
        "get_user_by_cognito_sub",
        "get_user_by_id",
        "get_user_preferences",
        "list_research_adjudications",
        "list_research_observations",
        "list_research_reviews",
        "list_sources",
        "list_threads",
        "lookup_completed_coach_request",
        "lookup_completed_or_recorded_coach_request",
        "persist_coach_turn",
        "ping",
        "record_research_access_event",
        "rename_source",
        "research_workflow_contract_ready",
        "resolve_phase_transition",
        "revise_conversation_from_user_message",
        "revise_user_message",
        "save_oauth_login_state",
        "select_learning_stage",
        "set_all_sources_selected",
        "set_source_selected",
        "set_system_metadata",
        "try_resume_revision_result",
        "update_message",
        "update_thread",
        "update_user_preferences",
        "upsert_cognito_user",
    }
    actual_public = {
        name
        for name, value in inspect.getmembers(StudentStore, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert actual_public == expected_public
    assert set(_OCC_WRITE_METHODS) == {
        "add_message",
        "add_source",
        "append_research_adjudication",
        "append_research_review",
        "apply_phase_transition_decision",
        "claim_coach_request",
        "complete_coach_request",
        "consume_oauth_login_state",
        "create_phase_transition",
        "create_thread",
        "fail_coach_request",
        "persist_coach_turn",
        "record_research_access_event",
        "rename_source",
        "resolve_phase_transition",
        "revise_conversation_from_user_message",
        "revise_user_message",
        "save_oauth_login_state",
        "select_learning_stage",
        "set_all_sources_selected",
        "set_source_selected",
        "set_system_metadata",
        "update_message",
        "update_thread",
        "update_user_preferences",
        "upsert_cognito_user",
    }


def test_complete_fastapi_route_inventory_is_stable(tmp_path: Path) -> None:
    """Every application route retains its method, path, and operation name."""
    app = create_app(StudentStore(tmp_path / "route-contract.sqlite3"))
    actual = {
        (method, route.path, route.name)
        for route in app.routes
        for method in sorted(getattr(route, "methods", set()) or [])
        if route.path.startswith("/api/")
    }
    expected = {
        (method, path, name)
        for method, path, name in (
            ("GET", "/api/v1/auth/login", "auth_login"),
            ("GET", "/api/v1/auth/callback", "auth_callback"),
            ("GET", "/api/v1/auth/refresh", "auth_refresh"),
            ("GET", "/api/v1/auth/me", "auth_me"),
            ("GET", "/api/v1/auth/logout", "auth_logout"),
            ("POST", "/api/v1/auth/logout", "auth_logout"),
            ("GET", "/api/v1/auth/logout/callback", "auth_logout_callback"),
            ("GET", "/api/v1/health", "health"),
            ("GET", "/api/v1/ready", "ready"),
            ("GET", "/api/v1/preferences", "get_preferences"),
            ("PATCH", "/api/v1/preferences", "patch_preferences"),
            ("GET", "/api/v1/threads", "list_threads"),
            ("POST", "/api/v1/threads", "create_thread"),
            ("GET", "/api/v1/threads/{thread_id}", "get_thread"),
            ("PATCH", "/api/v1/threads/{thread_id}", "update_thread"),
            ("DELETE", "/api/v1/threads/{thread_id}", "delete_thread"),
            ("GET", "/api/v1/threads/{thread_id}/messages", "list_messages"),
            ("POST", "/api/v1/threads/{thread_id}/messages", "create_message"),
            (
                "GET",
                "/api/v1/threads/{thread_id}/transcript.txt",
                "download_transcript",
            ),
            (
                "POST",
                "/api/v1/threads/{thread_id}/messages/{message_id}/revise",
                "revise_user_message",
            ),
            ("GET", "/api/v1/threads/{thread_id}/sources", "list_sources"),
            ("POST", "/api/v1/threads/{thread_id}/sources", "upload_sources"),
            ("GET", "/api/v1/threads/{thread_id}/sources/{source_id}", "get_source"),
            (
                "PATCH",
                "/api/v1/threads/{thread_id}/sources/{source_id}",
                "update_source",
            ),
            (
                "DELETE",
                "/api/v1/threads/{thread_id}/sources/{source_id}",
                "delete_source",
            ),
            (
                "POST",
                "/api/v1/threads/{thread_id}/sources/select-all",
                "select_all_sources",
            ),
            (
                "GET",
                "/api/v1/threads/{thread_id}/sources/{source_id}/content",
                "source_content",
            ),
            (
                "POST",
                "/api/v1/threads/{thread_id}/sources/backfill-legacy",
                "backfill_legacy",
            ),
            (
                "POST",
                "/api/v1/threads/{thread_id}/sources/sync-course-materials",
                "sync_course_materials",
            ),
            ("GET", "/api/v1/threads/{thread_id}/learning-state", "learning_state"),
            (
                "POST",
                "/api/v1/threads/{thread_id}/learning-state/select-stage",
                "select_learning_stage",
            ),
            (
                "GET",
                "/api/v1/threads/{thread_id}/phase-transitions/pending",
                "pending_transition",
            ),
            (
                "POST",
                "/api/v1/threads/{thread_id}/phase-transitions/{transition_id}/resolve",
                "resolve_transition",
            ),
            ("GET", "/api/v1/threads/{thread_id}/graph", "graph_inspection"),
            ("POST", "/api/v1/coach/turn", "coach_turn"),
            ("POST", "/api/v1/coach/turn/stream", "coach_turn_stream"),
            ("GET", "/api/v1/professor/overview", "professor_overview"),
            ("GET", "/api/v1/professor/students", "professor_students"),
            (
                "GET",
                "/api/v1/professor/students/{student_id}",
                "professor_student_detail",
            ),
            (
                "GET",
                "/api/v1/professor/students/{student_id}/conversations/{notebook_id}",
                "professor_conversation_transcript",
            ),
            (
                "GET",
                "/api/v1/professor/critical-thinking",
                "professor_critical_thinking",
            ),
            ("GET", "/api/v1/professor/engagement", "professor_engagement"),
            (
                "GET",
                "/api/v1/professor/research/summary",
                "professor_research_summary",
            ),
            ("GET", "/api/v1/professor/research/queue", "professor_research_queue"),
            (
                "GET",
                "/api/v1/professor/research/notebooks/{notebook_id}",
                "professor_research_notebook",
            ),
            (
                "POST",
                "/api/v1/professor/research/reviews",
                "professor_research_review",
            ),
            (
                "POST",
                "/api/v1/professor/research/adjudications",
                "professor_research_adjudication",
            ),
            (
                "GET",
                "/api/v1/professor/research/export.csv",
                "professor_research_export",
            ),
        )
    }
    assert actual == expected


def test_fastapi_does_not_publish_openapi_docs(tmp_path: Path) -> None:
    """Swagger/ReDoc/OpenAPI must not advertise internal routes."""
    from fastapi.testclient import TestClient

    app = create_app(StudentStore(tmp_path / "docs-contract.sqlite3"))
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    client = TestClient(app)
    for path in ("/docs", "/docs/", "/redoc", "/redoc/", "/openapi.json"):
        assert client.get(path).status_code == 404
