"""Lock FastAPI onto the contained Fast Chat / explicit Deep Review paths.

These tests assert behaviour and import-graph facts so a later refactor cannot
silently re-enable the Haiku router, legacy Q&A/Coaching specialists,
incremental Review, or automatic Sonnet. They do not delete those modules:
the published AgentCore runtime still dispatches leftover ``phase`` values for
any principal with ``bedrock-agentcore:InvokeAgentRuntime``. FastAPI must not
send those phases. Mock-only evidence; no AWS.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcore_runtime.main import _output_model_for, _role_for_payload
from agentcore_runtime.model import MODEL_ROLE_FAST_CHAT, MODEL_ROLE_REVIEW_DEEP
from agentcore_runtime.models import CoachTurnOutput, FastChatTurnOutput
from agentcore_runtime.specialists.routing import invoke_kind
from backend.agentcore_provider import AgentCoreCoachProvider
from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, DeepReviewRequest
from backend.learning_service import LearningProgressService
from backend.providers import configured_coach_provider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _coaching_payload() -> dict[str, Any]:
    """Return one slim Fast Chat coaching object."""
    return {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "needs_source_retrieval": False,
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _service(store: StudentStore, client: FakeAgentCoreRuntime) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def _imported_names(path: Path) -> set[str]:
    """Return every imported module and ``from … import`` name in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            for alias in node.names:
                names.add(alias.name)
                if module:
                    names.add(f"{module}.{alias.name}")
    return names


def _self_attrs_called(path: Path, *, class_name: str, method_name: str) -> set[str]:
    """Return ``self.<attr>`` names referenced inside one method body."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != method_name:
                continue
            names: set[str] = set()
            for child in ast.walk(item):
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                ):
                    names.add(child.attr)
            return names
    return set()


def _install_agentcore(
    monkeypatch: pytest.MonkeyPatch, runtime: FakeAgentCoreRuntime
) -> None:
    """Make ``create_app`` wire the injected fake AgentCore adapter."""

    def _factory() -> AgentCoreCoachProvider:
        return _provider(runtime)

    monkeypatch.setattr(
        "backend.owner_context.configured_coach_provider", _factory
    )


def _spy_legacy_entrypoints(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count calls into retired adapter helpers. The helpers themselves are not run."""
    counts = {
        "router_payload": 0,
        "resolve_specialist": 0,
        "invoke_specialist": 0,
        "explicit_review": 0,
    }

    def _count(name: str) -> Any:
        def _inner(*_args: Any, **_kwargs: Any) -> Any:
            counts[name] += 1
            raise AssertionError(f"legacy path {name} must not run")

        return _inner

    monkeypatch.setattr(
        "backend.agentcore_provider._router_payload", _count("router_payload")
    )
    monkeypatch.setattr(
        AgentCoreCoachProvider, "_resolve_specialist", _count("resolve_specialist")
    )
    monkeypatch.setattr(
        AgentCoreCoachProvider, "_invoke_specialist", _count("invoke_specialist")
    )
    monkeypatch.setattr(
        AgentCoreCoachProvider,
        "_assess_explicit_review",
        _count("explicit_review"),
    )
    return counts


def test_assess_never_calls_router_or_legacy_specialist_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct ``assess()`` on a normal request must stay on one ``fast_chat`` call."""
    runtime = FakeAgentCoreRuntime(payload=_coaching_payload())
    counts = _spy_legacy_entrypoints(monkeypatch)
    result = _provider(runtime).assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message="I compared two constraints for Holland Road.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert counts == {
        "router_payload": 0,
        "resolve_specialist": 0,
        "invoke_specialist": 0,
        "explicit_review": 0,
    }
    assert _phases(runtime) == ["fast_chat"]
    payload = _decoded(runtime.calls[0])
    assert payload["output_contract"] == "fast_chat_turn"
    assert payload.get("review_mode") in {None, ""}
    assert invoke_kind(payload) == "fast_chat"
    assert result.assessment.recommendation is not None


def test_http_coach_turn_never_reaches_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POST /api/v1/coach/turn`` must not invoke the retired Haiku router."""
    runtime = FakeAgentCoreRuntime(payload=_coaching_payload())
    counts = _spy_legacy_entrypoints(monkeypatch)
    _install_agentcore(monkeypatch, runtime)
    store = StudentStore(tmp_path / "contain-router.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I compared two constraints for Holland Road.",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": "contain-router",
        },
    )
    assert response.status_code == 200
    assert counts["router_payload"] == 0
    assert counts["resolve_specialist"] == 0
    assert counts["invoke_specialist"] == 0
    assert counts["explicit_review"] == 0
    assert _phases(runtime) == ["fast_chat"]


def test_http_coach_turn_never_reaches_review_or_sonnet_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal HTTP turn must not select the Review specialist or Sonnet role."""
    runtime = FakeAgentCoreRuntime(payload=_coaching_payload())
    counts = _spy_legacy_entrypoints(monkeypatch)
    _install_agentcore(monkeypatch, runtime)
    store = StudentStore(tmp_path / "contain-sonnet.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I compared two constraints for Holland Road.",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": "contain-sonnet",
        },
    )
    assert response.status_code == 200
    assert counts["explicit_review"] == 0
    assert counts["invoke_specialist"] == 0
    assert _phases(runtime) == ["fast_chat"]
    payload = _decoded(runtime.calls[0])
    assert invoke_kind(payload) == "fast_chat"
    assert _role_for_payload(payload) == MODEL_ROLE_FAST_CHAT
    assert _role_for_payload(payload) != MODEL_ROLE_REVIEW_DEEP
    assert str(payload.get("review_mode") or "") != "incremental"
    body = response.json()
    assert body["assessment"].get("review_depth") != "deep"


def test_browser_cannot_escalate_to_review_through_public_request_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public model still accepts ``specialist=review``; FastAPI must strip it.

    Catch: a future change that honors client ``specialist`` on ``/coach/turn``
    would invoke ``_assess_explicit_review`` (Sonnet) instead of Fast Chat.
    """
    accepted = CoachRequest(
        thread_id="thread-demo",
        student_message="I compared two constraints for Holland Road.",
        current_stage="problem_identification",
        response_detail="short",
        specialist="review",
    )
    assert accepted.specialist == "review"
    with pytest.raises(ValidationError):
        DeepReviewRequest.model_validate({"specialist": "review"})

    runtime = FakeAgentCoreRuntime(payload=_coaching_payload())
    counts = _spy_legacy_entrypoints(monkeypatch)
    _install_agentcore(monkeypatch, runtime)
    store = StudentStore(tmp_path / "contain-hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I compared two constraints for Holland Road.",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": "contain-hint",
            "specialist": "review",
        },
    )
    assert response.status_code == 200
    assert counts["explicit_review"] == 0
    assert counts["resolve_specialist"] == 0
    assert counts["invoke_specialist"] == 0
    assert _phases(runtime) == ["fast_chat"]
    assert "review" not in _phases(runtime)
    body = response.json()
    assert body["assessment"].get("review_depth") != "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None


def test_submit_strips_browser_review_hint_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Application ``submit()`` must ignore a client ``specialist=review`` stamp."""
    runtime = FakeAgentCoreRuntime(payload=_coaching_payload())
    counts = _spy_legacy_entrypoints(monkeypatch)
    store = StudentStore(tmp_path / "contain-submit.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _service(store, runtime).submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared two constraints for Holland Road.",
            current_stage="problem_identification",
            response_detail="short",
            specialist="review",
            idempotency_key="contain-submit",
        )
    )
    assert counts["explicit_review"] == 0
    assert counts["resolve_specialist"] == 0
    assert counts["invoke_specialist"] == 0
    assert _phases(runtime) == ["fast_chat"]


def test_assess_method_does_not_wire_retired_helpers() -> None:
    """``assess()`` may only branch to Fast Chat or explicit Deep Review."""
    path = _PROJECT_ROOT / "backend" / "agentcore_provider.py"
    assess_attrs = _self_attrs_called(
        path, class_name="AgentCoreCoachProvider", method_name="assess"
    )
    assert "_assess_fast_chat" in assess_attrs
    assert "_assess_explicit_review" in assess_attrs
    assert "_resolve_specialist" not in assess_attrs
    assert "_invoke_specialist" not in assess_attrs
    fast_attrs = _self_attrs_called(
        path, class_name="AgentCoreCoachProvider", method_name="_assess_fast_chat"
    )
    assert "_resolve_specialist" not in fast_attrs
    assert "_invoke_specialist" not in fast_attrs
    assert "_call_runtime" in fast_attrs


def test_execution_does_not_import_automatic_deep_review_helpers() -> None:
    """Catch: re-importing ``resolve_deep_review_trigger`` into the live path."""
    names = _imported_names(_PROJECT_ROOT / "backend" / "coaching" / "execution.py")
    assert "explicit_deep_review_available" in names
    assert "resolve_deep_review_trigger" not in names
    assert "should_run_deep_review" not in names
    workflow_names = _imported_names(_PROJECT_ROOT / "backend" / "workflow.py")
    assert "resolve_deep_review_trigger" not in workflow_names
    assert "should_run_deep_review" not in workflow_names
    http_names = _imported_names(_PROJECT_ROOT / "backend" / "http" / "app.py")
    assert "resolve_deep_review_trigger" not in http_names
    assert "should_run_deep_review" not in http_names


def test_ui_and_http_do_not_import_student_chat_engine() -> None:
    """Streamlit and FastAPI must not revive the legacy chat engine."""
    offenders: list[str] = []
    for package in ("ui", "backend/http"):
        for path in (_PROJECT_ROOT / package).rglob("*.py"):
            names = _imported_names(path)
            if "StudentChatEngine" in names or "chat_service" in names:
                offenders.append(str(path.relative_to(_PROJECT_ROOT)))
    assert offenders == []


def test_production_provider_factory_does_not_select_eval_harness() -> None:
    """``MODEL_PROVIDER=agentcore`` must stay on InvokeAgentRuntime, not Luna eval."""
    names = _imported_names(_PROJECT_ROOT / "backend" / "providers.py")
    assert "AgentCoreHarnessCoachProvider" not in names
    assert "agentcore_harness_provider" not in names
    assert "backend.agentcore_harness_provider" not in names
    source = (_PROJECT_ROOT / "backend" / "providers.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "configured_coach_provider":
            called: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    called.add(child.id)
            assert "AgentCoreHarnessCoachProvider" not in called
            assert "AgentCoreCoachProvider" in called
            break
    else:
        raise AssertionError("configured_coach_provider is missing")
    provider = configured_coach_provider()
    assert provider.provider_id == "mock"


def test_automatic_stage_update_is_not_on_the_live_coaching_path() -> None:
    """Hidden HTML stage markers must not be imported by execution or HTTP."""
    for relative in (
        "backend/coaching/execution.py",
        "backend/http/app.py",
        "backend/workflow.py",
        "backend/learning_service.py",
        "backend/agentcore_provider.py",
    ):
        names = _imported_names(_PROJECT_ROOT / relative)
        assert "automatic_stage_update" not in names
        assert "contribution_supports_stage" not in names


def test_fast_chat_output_model_is_not_nested_coach_turn() -> None:
    """Normal chat structured output is ``FastChatTurnOutput``, not ``CoachTurnOutput``."""
    assert _output_model_for("fast_chat", "fast_chat_turn") is FastChatTurnOutput
    assert _output_model_for("fast_chat", "fast_chat_turn") is not CoachTurnOutput
    assert _output_model_for("coaching", "coach_turn") is CoachTurnOutput


def test_stage_judge_module_is_not_imported_by_runtime_entrypoint() -> None:
    """Leftover judge payloads are mapped in routing.py; ``stage_judge.py`` is unused."""
    names = _imported_names(_PROJECT_ROOT / "agentcore_runtime" / "main.py")
    assert "stage_judge" not in names
    assert "agentcore_runtime.stage_judge" not in names
    routing_names = _imported_names(
        _PROJECT_ROOT / "agentcore_runtime" / "specialists" / "routing.py"
    )
    assert "stage_judge" not in routing_names
