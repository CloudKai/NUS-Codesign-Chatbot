"""Mock-only load probe regressions: distinct owners and notebook concurrency."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROBE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "load_probe.py"
_SPEC = importlib.util.spec_from_file_location("co_design_load_probe", _PROBE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PROBE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PROBE
_SPEC.loader.exec_module(_PROBE)

run_distinct_owner_probe = _PROBE.run_distinct_owner_probe
run_same_notebook_probe = _PROBE.run_same_notebook_probe
run_sequential_probe = _PROBE.run_sequential_probe
run_two_notebooks_probe = _PROBE.run_two_notebooks_probe


def test_sequential_probe_uses_distinct_owners_and_accepts():
    report = run_sequential_probe(users=3, requests_per_user=1)
    payload = report.as_dict()
    assert payload["virtual_users"] == 3
    assert payload["accepted"] == 3
    assert payload["rate_limited"] == 0
    assert payload["failed"] == 0
    assert "Load probe claim" not in str(payload)
    assert "probe.example.edu" not in str(payload)


def test_distinct_owner_probe_accepts_concurrent_students():
    report = run_distinct_owner_probe(users=8)
    assert report.virtual_users == 8
    assert report.accepted == 8
    assert report.rate_limited == 0
    assert report.failed == 0


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
