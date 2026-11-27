"""Mixed-workload probe regressions: report invariants and a small live run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROBE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mixed_workload_probe.py"
_SPEC = importlib.util.spec_from_file_location("co_design_mixed_workload_probe", _PROBE_PATH)
assert _SPEC is not None and _PROBE_PATH.is_file()
_PROBE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PROBE
_SPEC.loader.exec_module(_PROBE)

Observation = _PROBE.Observation
percentiles = _PROBE.percentiles
run_probe = _PROBE.run_probe
summarize = _PROBE.summarize


def test_percentiles_use_nearest_rank_with_p90_p95_p99_tails() -> None:
    """The recorded percentiles are the documented nearest-rank definition."""
    values = [float(value) for value in range(1, 101)]
    reported = percentiles(values)
    assert reported == {"p50": 50.0, "p90": 90.0, "p95": 95.0, "p99": 99.0,
                        "max": 100.0}
    assert percentiles([]) == {"p50": None, "p90": None, "p95": None, "p99": None,
                               "max": None}


def test_summarize_separates_errors_conflicts_and_saved_latencies() -> None:
    """Errors, OCC conflicts and saved-only latencies are reported separately."""
    observations = [
        Observation("artifact_autosave", True, 10.0, saved=True),
        Observation("artifact_autosave", False, 20.0, conflict=True,
                    detail="conflict"),
        Observation("artifact_autosave", True, 30.0, saved=True, retried=True),
    ]
    report = summarize(observations)
    assert report["operations"] == 3
    assert report["succeeded"] == 2
    assert report["errors"] == 1
    assert report["error_details"] == {"conflict": 1}
    assert report["occ_conflicts"] == 1
    assert report["occ_retries"] == 1
    assert report["latency_ms_saved"]["max"] == 30.0
    assert report["latency_ms_all_outcomes"]["max"] == 30.0


def test_rate_limit_pins_survive_the_settings_bounds(monkeypatch) -> None:
    """Every limiter pin is inside its setting bound so none silently reverts.

    ``_bounded_int`` returns the documented DEFAULT when the value is out of
    range, so an out-of-bound pin would silently restore the 8 RPM/owner
    default and fabricate ``user_rpm`` rejections under the accumulated
    cross-wave load (observed and diagnosed on the first 80-student run).
    """
    from backend.settings import _bounded_int

    pinned = _PROBE._environment(Path("/tmp/x"), "http://127.0.0.1:0")
    for name, default, minimum, maximum in (
        ("COACH_REQUESTS_PER_MINUTE", 8, 1, 120),
        ("MAX_CONCURRENT_MODEL_CALLS", 20, 1, 500),
        ("SYNC_THREADPOOL_TOKENS", 40, 8, 500),
        ("DEEP_REVIEW_MAX_CONCURRENT", 8, 1, 32),
    ):
        monkeypatch.setenv(name, pinned[name])
        applied = _bounded_int(name, default, minimum, maximum)
        assert applied == int(pinned[name]) and minimum <= applied <= maximum, name


def test_small_mixed_probe_reconciles_without_loss_or_duplicates() -> None:
    """A two-student mixed wave saves, reconciles and reports honestly."""
    report = run_probe(levels=(2,), delay_seconds=0.05, review_deadline_seconds=60.0)
    assert report["evidence"] == "local_mock_characterization_only"
    assert report["levels"][0]["students"] == 2
    assert report["environment"]["mock_provider_delay_seconds"] == 0.05
    assert report["limitations"]
    level = report["levels"][0]
    reconciliation = level["reconciliation"]
    assert reconciliation["verified_sessions"] == 2
    assert reconciliation["confirmed_losses"] == 0
    assert reconciliation["confirmed_duplicates"] == 0
    operations = level["operations"]
    # Every category succeeded except the exactly-one OCC conflict per student.
    for category in ("startup", "navigation", "source_upload", "ordinary_turn",
                     "grounded_turn", "canvas_autosave", "deep_review_submit"):
        assert operations[category]["errors"] == 0, category
    autosave = operations["artifact_autosave"]
    assert autosave["occ_conflicts"] == 2
    assert autosave["occ_retries"] == 2
    assert autosave["succeeded"] == 4  # two saves per student: winner + retry
    for category, summary in operations.items():
        for label in ("p50", "p90", "p95", "p99", "max"):
            assert summary["latency_ms_all_outcomes"][label] is not None, (category, label)
    review = report["deep_review_completion"]
    assert review["submitted"] == 2
    assert review["statuses"].get("completed") == 2
    assert review["still_unfinished_at_deadline"] == 0
