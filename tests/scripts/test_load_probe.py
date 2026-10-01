"""Mock-only load probe regressions: distinct owners, slow fake provider, KB pool."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from backend.mock_provider import DeterministicCoachProvider

_PROBE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "load_probe.py"
_SPEC = importlib.util.spec_from_file_location("co_design_load_probe", _PROBE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PROBE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PROBE
_SPEC.loader.exec_module(_PROBE)

run_distinct_owner_probe = _PROBE.run_distinct_owner_probe
run_failed_turn_no_partial_probe = _PROBE.run_failed_turn_no_partial_probe
run_kb_fail_closed_probe = _PROBE.run_kb_fail_closed_probe
run_kb_pool_probe = _PROBE.run_kb_pool_probe
run_kb_timeout_slot_probe = _PROBE.run_kb_timeout_slot_probe
run_ownership_isolation_probe = _PROBE.run_ownership_isolation_probe
run_same_notebook_probe = _PROBE.run_same_notebook_probe
run_sequential_probe = _PROBE.run_sequential_probe
run_slow_idempotency_probe = _PROBE.run_slow_idempotency_probe
run_two_notebooks_probe = _PROBE.run_two_notebooks_probe

_REQUIRED_KEYS = (
    "scenario",
    "users",
    "fake_provider_delay_ms",
    "fake_kb_delay_ms",
    "kb_workers",
    "requests",
    "accepted",
    "rate_limited",
    "capacity_exhausted",
    "failed",
    "p50_ms",
    "p95_ms",
    "mean_ms",
    "requests_per_sec",
    "peak_threads",
    "peak_kb_admitted",
    "peak_kb_worker_threads",
    "rss_peak_kb",
    "process_max_rss_kb",
)


def _assert_privacy(payload: dict) -> None:
    """Reports must not contain student text, emails, or notebook identifiers."""
    dumped = json.dumps(payload, default=str)
    assert "Load probe claim" not in dumped
    assert "probe.example.edu" not in dumped
    assert "Older adults" not in dumped


def test_sequential_probe_uses_distinct_owners_and_accepts():
    report = run_sequential_probe(users=3, requests_per_user=1)
    payload = report.as_dict()
    assert payload["virtual_users"] == 3
    assert payload["users"] == 3
    assert payload["accepted"] == 3
    assert payload["rate_limited"] == 0
    assert payload["failed"] == 0
    assert payload["peak_threads"] is not None and payload["peak_threads"] >= 1
    _assert_privacy(payload)
    for key in _REQUIRED_KEYS:
        assert key in payload


def test_distinct_owner_probe_accepts_concurrent_students():
    report = run_distinct_owner_probe(users=8)
    assert report.virtual_users == 8
    assert report.accepted == 8
    assert report.rate_limited == 0
    assert report.failed == 0
    assert report.structurally_invalid == 0
    assert report.fake_provider_delay_ms == 0


def test_two_notebooks_probe_accepts_both_turns():
    report = run_two_notebooks_probe()
    assert report.virtual_users == 1
    assert report.accepted == 2
    assert report.rate_limited == 0
    assert report.failed == 0


def test_same_notebook_probe_rejects_overlapping_turn():
    report = run_same_notebook_probe()
    assert report.virtual_users == 1
    assert report.accepted == 1
    assert report.rate_limited == 1
    assert report.failed == 0


def test_slow_distinct_owners_tiny_delay_restores_provider():
    original = DeterministicCoachProvider.assess
    report = run_distinct_owner_probe(users=4, provider_delay_ms=40)
    assert DeterministicCoachProvider.assess is original
    assert report.scenario == "slow-distinct-owners"
    assert report.accepted == 4
    assert report.rate_limited == 0
    assert report.failed == 0
    assert report.fake_provider_delay_ms == 40
    assert report.ownership_violations == 0
    assert report.structurally_invalid == 0
    assert report.provider_calls == 4
    assert report.mean_ms >= 30
    assert report.peak_threads is not None and report.peak_threads >= 4
    _assert_privacy(report.as_dict())


def test_ownership_isolation_under_concurrency():
    report = run_ownership_isolation_probe(users=6)
    assert report.accepted == 6
    assert report.failed == 0
    assert report.ownership_violations == 0


def test_slow_idempotency_makes_one_provider_call():
    report = run_slow_idempotency_probe(provider_delay_ms=20)
    assert report.accepted == 2
    assert report.failed == 0
    assert report.provider_calls == 1


def test_failed_turn_does_not_persist_assistant():
    report = run_failed_turn_no_partial_probe()
    assert report.accepted == 0
    assert report.failed == 1
    assert report.assistant_turns_after_failure == 0


def test_kb_pool_admits_workers_and_fail_closes():
    report = run_kb_pool_probe(workers=2, concurrency=8, delay_ms=40, timeout_seconds=2.0)
    payload = report.as_dict()
    assert payload["scenario"] == "kb-pool"
    assert payload["kb_workers"] == 2
    assert payload["users"] == 8
    assert payload["fake_kb_delay_ms"] == 40
    assert payload["accepted"] == 2
    assert payload["capacity_exhausted"] == 6
    assert payload["failed"] == 0
    assert payload["unexpected_queueing"] == 0
    assert payload["pool_recovered"] == 1
    assert payload["peak_kb_admitted"] is not None
    assert payload["peak_kb_admitted"] <= 2
    assert payload["peak_kb_worker_threads"] is not None
    assert payload["peak_kb_worker_threads"] <= 2
    _assert_privacy(payload)


def test_kb_timeout_holds_admission_slot_then_recovers():
    report = run_kb_timeout_slot_probe(workers=2, concurrency=8, delay_ms=250)
    assert report.accepted == 0
    assert report.capacity_exhausted == 6
    assert report.failed == 2
    assert report.unexpected_queueing == 0
    assert report.pool_recovered == 1
    assert report.peak_kb_admitted == 2


def test_kb_fail_closed_drops_foreign_bucket():
    report = run_kb_fail_closed_probe()
    assert report.accepted == 0
    assert report.failed == 0
    assert report.capacity_exhausted == 0
    _assert_privacy(report.as_dict())


def test_force_mock_capacity_snapshots_app_env_and_disables_sync(monkeypatch):
    """Already-imported production-shaped settings must still be forced local."""
    from backend.settings import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    snapshot = _PROBE._snapshot_capacity_settings()
    assert snapshot["app_env"] == "production"
    assert snapshot["course_material_sync_enabled"] is True
    try:
        _PROBE._force_mock_capacity()
        assert settings.app_env == "development"
        assert settings.course_material_sync_enabled is False
        assert settings.model_provider == "mock"
        assert settings.knowledge_base_id == ""
    finally:
        _PROBE._restore_capacity_settings(snapshot)


def test_rss_fields_are_process_lifetime_high_water():
    report = run_sequential_probe(users=2, requests_per_user=1)
    payload = report.as_dict()
    assert "rss_peak_kb" in payload
    assert "process_max_rss_kb" in payload
    assert payload["rss_peak_kb"] == payload["process_max_rss_kb"]
