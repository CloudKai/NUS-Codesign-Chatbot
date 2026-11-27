"""Release-rehearsal driver contracts (ticket 51): disposable, offline, aggregate.

The driver rehearses the coordinated release configuration against its own
temporary directory tree only. It has no flag that can point it at a real
database, host or workspace, and its startup stage uses deterministic mock
adapters exclusively.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.release_rehearsal", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=900,
    )


def test_rehearsal_collects_disposable_configuration_contract_and_startup_evidence() -> None:
    """The default rehearsal passes on repository defaults and a throwaway tree."""
    result = _run("--skip-recovery")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["rehearsal"] == "release-rehearsal"
    assert report["disposable"] is True
    stages = report["stages"]

    configuration = stages["configuration"]
    assert configuration["status"] == "pass"
    assert configuration["checks"]["student_stage_selection"] == "true"
    assert configuration["checks"]["auto_advance_stages"] == "false"
    assert configuration["checks"]["guardrail_version"] == "4"
    assert configuration["checks"]["app_image_immutable"] is True
    assert configuration["checks"]["ready_not_public"] is True
    assert configuration["checks"]["reader_contract_edge_parity"] is True
    assert configuration["checks"]["direct_link_paths_allowlisted"] >= 6

    builds = stages["contracts_and_builds"]
    assert builds["status"] == "pass"
    assert builds["reader_contract_paths"] > 0
    assert builds["frontend_dist_index_sha256"]
    assert builds["generated_contract_sha256"]

    startup = stages["coordinated_startup"]
    assert startup["status"] == "pass"
    assert startup["health_status"] == 200
    assert startup["ready_status"] == 200
    # The fail-closed production gate must refuse the disposable mock tuple:
    # a rehearsal adapter set can never masquerade as a production release.
    assert startup["mock_tuple_rejected_for_production"] is True

    assert report["findings"] == []
    assert report["live_gates"]


def test_rehearsal_reports_a_finding_and_fails_when_ready_becomes_public(tmp_path: Path) -> None:
    """A candidate edge file that exposes /ready fails the rehearsal, named."""
    config_dir = tmp_path / "candidate"
    config_dir.mkdir()
    for name in ("compose.prod.yaml", "Caddyfile", "Caddyfile.local"):
        shutil.copy(ROOT / name, config_dir / name)
    caddyfile = (config_dir / "Caddyfile")
    text = caddyfile.read_text(encoding="utf-8").replace(
        "(bootstrap|session|", "(bootstrap|ready|session|"
    )
    assert text != caddyfile.read_text(encoding="utf-8")
    caddyfile.write_text(text, encoding="utf-8")

    result = _run("--config-dir", str(config_dir), "--skip-recovery")
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["stages"]["configuration"]["status"] == "fail"
    assert any("ready" in finding for finding in report["findings"])
