"""Check the all-rows Laya run: host notes, per-row output, and the hand-off to compare_routing_arms.

Only stand-in classifiers are used. A file made by a stand-in is marked ``real_model:
false`` and the loader refuses it; the tests that load a file build it with a fake
"real" classifier class, so no Laya package, weights or host is involved.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from scripts.evals import benchmark_course_intent as bench
from scripts.evals import compare_routing_arms as compare
from scripts.evals.lib.fixtures import load_materials, load_messages, load_questions
from scripts.evals.lib.laya_sources import LayaFileError, load_full_run
from scripts.evals.lib.paths import MATERIALS_PATH, MESSAGES_PATH, QUESTIONS_PATH
from scripts.evals.lib.prepared_rows import prepare_rows

HOST_ARGS = [
    "--host-instance-type", "test-host-type",
    "--host-vcpu", "8",
    "--host-ram-gb", "32",
    "--host-arch", "arm64",
]
OLD_KEYS = {
    "gate_messages", "eligible_rows", "course_titles", "environment", "classifier_kind",
    "real_model", "load_ms", "warmup_calls", "first_call_ms", "warmup_call_ms", "memory", "passes", "run",
}


@pytest.fixture(autouse=True)
def _keep_process_state(monkeypatch) -> None:
    from scripts.evals import evaluate_retrieval

    monkeypatch.setattr(evaluate_retrieval, "_block_network", lambda: None)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


@pytest.fixture(scope="module")
def messages() -> list[dict[str, Any]]:
    materials = load_materials(MATERIALS_PATH)
    questions = load_questions(QUESTIONS_PATH, materials)
    return load_messages(MESSAGES_PATH, materials, [q["id"] for q in questions])


@pytest.fixture(scope="module")
def prepared(messages):
    return {row.id: row for row in prepare_rows(messages)}


class FakeRealClassifier:
    """A stand-in the harness treats as a real model (no weights, no package)."""

    busy_messages: set[str] = set()

    def score(self, message: str, history: Any, titles: Any) -> float | None:
        return None if message in self.busy_messages else 0.9


def _run_fake_real(monkeypatch, tmp_path: Path, extra: list[str] | None = None, *, busy_messages=()) -> Path:
    classifier = FakeRealClassifier()
    classifier.busy_messages = set(busy_messages)
    monkeypatch.setitem(sys.modules, "laya", types.ModuleType("laya"))
    monkeypatch.setattr(bench, "build_classifier", lambda args: (classifier, "laya"))
    output = tmp_path / "all-rows.json"
    code = bench.main(
        ["--checkpoint", str(tmp_path), "--passes", "2", "--warmup", "1", *HOST_ARGS,
         "--json-output", str(output), *(extra or [])]
    )
    assert code == 0
    return output


def test_stub_run_needs_no_host_notes_and_covers_every_gate_row(tmp_path, capsys, messages, prepared) -> None:
    output = tmp_path / "stub.json"
    assert bench.main(["--stub-ms", "0", "--passes", "2", "--warmup", "1", "--json-output", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    capsys.readouterr()
    assert OLD_KEYS <= set(data) and data["real_model"] is False
    assert data["host_note"] is None
    assert [row["id"] for row in data["rows"]] == [str(m["id"]) for m in messages]
    assert len(data["rows"]) == 295
    for row in data["rows"]:
        assert set(row) == {"id", "first_turn", "status", "score", "ms"}
        assert row["first_turn"] is prepared[row["id"]].first_turn
        if prepared[row["id"]].eligible:
            assert row["status"] == "scored" and row["score"] == 0.5 and row["ms"] >= 0
        else:
            assert row == {"id": row["id"], "first_turn": row["first_turn"], "status": "not_eligible", "score": None, "ms": None}
    assert sum(r["status"] == "scored" for r in data["rows"]) == data["eligible_rows"]


def test_host_notes_are_recorded_as_given_and_cross_checked_without_stopping(tmp_path, capsys) -> None:
    output = tmp_path / "stub.json"
    args = ["--stub-ms", "0", "--passes", "1", "--warmup", "0", "--json-output", str(output)]
    assert bench.main([*args, *HOST_ARGS]) == 0
    note = json.loads(output.read_text(encoding="utf-8"))["host_note"]
    capsys.readouterr()
    assert (note["instance_type"], note["vcpu"], note["ram_gb"], note["arch"]) == ("test-host-type", 8, 32.0, "arm64")
    assert note["observed"]["machine"] and "operator" in note["source"]
    assert note["arch_matches_observed"] in {True, False, None}
    # A wrong note is recorded, never fatal and never corrected.
    wrong = "x86_64" if note["arch_matches_observed"] else "arm64"
    assert bench.main([*args, "--host-arch", wrong]) == 0
    partial = json.loads(output.read_text(encoding="utf-8"))["host_note"]
    capsys.readouterr()
    assert partial["arch"] == wrong and partial["instance_type"] is None and partial["vcpu_matches_observed"] is None


@pytest.mark.parametrize("flag", ["--host-instance-type", "--host-vcpu", "--host-ram-gb", "--host-arch"])
def test_checkpoint_run_refuses_a_missing_host_note_before_loading_anything(monkeypatch, tmp_path, flag) -> None:
    def explode(args: Any) -> Any:
        raise AssertionError("the classifier must not load before the host notes are checked")

    monkeypatch.setitem(sys.modules, "laya", types.ModuleType("laya"))
    monkeypatch.setattr(bench, "build_classifier", explode)
    kept: list[str] = []
    skip = False
    for token in HOST_ARGS:
        if token == flag:
            skip = True
        elif skip:
            skip = False
        else:
            kept.append(token)
    with pytest.raises(SystemExit) as exit_info:
        bench.main(["--checkpoint", str(tmp_path), *kept])
    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--host-instance-type", "<TYPE>"],
        ["--host-instance-type", "  "],
        ["--host-vcpu", "0"],
        ["--host-vcpu", "<N>"],
        ["--host-ram-gb", "-1"],
        ["--host-ram-gb", "<GB>"],
        ["--host-arch", "<arm64|x86_64>"],
        ["--host-arch", "riscv"],
    ],
)
def test_placeholders_and_bad_values_are_refused_even_with_the_stub(extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        bench.main(["--stub-ms", "0", *extra])
    assert exit_info.value.code == 2


def test_output_carries_no_message_text(tmp_path, capsys, messages) -> None:
    output = tmp_path / "stub.json"
    bench.main(["--stub-ms", "0", "--passes", "1", "--warmup", "0", "--json-output", str(output)])
    blob = output.read_text(encoding="utf-8") + capsys.readouterr().out
    long_messages = [str(row["message"]) for row in messages if len(str(row["message"])) >= 25]
    assert len(long_messages) > 100
    for text in long_messages:
        assert text not in blob


def test_stub_file_is_refused_by_the_loader(tmp_path, prepared) -> None:
    output = tmp_path / "stub.json"
    bench.main(["--stub-ms", "0", "--passes", "1", "--warmup", "0", *HOST_ARGS, "--json-output", str(output)])
    with pytest.raises(LayaFileError, match="stub"):
        load_full_run(output, "stub", prepared, cutoff=0.8)


def test_fake_real_run_loads_in_compare_routing_arms(monkeypatch, tmp_path, capsys, prepared) -> None:
    path = _run_fake_real(monkeypatch, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["real_model"] is True and data["classifier_kind"] == "laya"
    assert data["host_note"]["instance_type"] == "test-host-type"
    source = load_full_run(path, "full", prepared, cutoff=0.8)
    eligible = [i for i, r in prepared.items() if r.eligible]
    assert source.host_noted and source.consistency["consistent"]
    assert set(source.decisions) == set(prepared)
    assert all(source.decisions[i] for i in eligible)
    assert not any(v for i, v in source.decisions.items() if i not in eligible)
    assert all(source.ms[i] is not None for i in eligible)
    assert source.memory["peak_rss_mib"] and source.host_note["arch"] == "arm64"
    # The cutoffs are applied unchanged: 0.9 clears 0.8 but not a stricter one.
    assert not any(load_full_run(path, "full", prepared, cutoff=0.95).decisions.values())
    capsys.readouterr()
    result = tmp_path / "compare.json"
    assert compare.main(["--laya-full", str(path), "--json-output", str(result)]) == 0
    entry = json.loads(result.read_text(encoding="utf-8"))["sources"]["laya_full_multilingual"]
    assert entry["coverage"]["complete"] is True and entry["host_noted"] is True
    capsys.readouterr()
    assert compare.main(["--laya-full", str(path), "--laya-full-kind", "learn", "--json-output", str(result)]) == 0


def test_busy_calls_are_recorded_and_not_promoted(monkeypatch, tmp_path, prepared, messages) -> None:
    eligible = [m for m in messages if prepared[str(m["id"])].eligible]
    busy = eligible[0]
    path = _run_fake_real(monkeypatch, tmp_path, busy_messages={busy["message"]})
    data = json.loads(path.read_text(encoding="utf-8"))
    row = next(r for r in data["rows"] if r["id"] == str(busy["id"]))
    assert row["status"] == "busy" and row["score"] is None
    source = load_full_run(path, "full", prepared, cutoff=0.8)
    assert source.decisions[str(busy["id"])] is False
    assert source.consistency["consistent"]
