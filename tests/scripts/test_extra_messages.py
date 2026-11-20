"""``--extra-messages``: loader, refusal by default, live KB gate and comparison wiring.

Fake files only. No network, no AWS, no weights: the live path runs against the stub
``bedrock-agent-runtime`` client of ``test_evaluate_retrieval_live_kb_gate``, and the
comparison runs offline on the stored data plus a synthetic KB-score fixture.
"""

# ruff: noqa: F811  (pytest fixtures imported from sibling test modules are used as parameters)

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.evals import compare_routing_arms as command
from scripts.evals.lib import prereg
from scripts.evals.lib.extra_messages import (
    ALLOW_FLAG,
    MAX_ROWS,
    ExtraMessagesError,
    load_extra_messages,
)
from scripts.evals.lib.kb_scores import KbFileError, load_kb_scores
from tests.scripts.test_compare_routing_arms import (  # noqa: F401  (fixtures resolve by name)
    messages,
    prepared,
    synthetic_kb,
    write_kb,
)
from tests.scripts.test_compare_routing_arms import scopes as gate_scopes  # noqa: F401
from tests.scripts.test_evaluate_retrieval_live_kb_gate import (  # noqa: F401  (autouse fixture)
    _EVAL,
    _fresh_executor,
    _install,
    _StubClient,
)
from tests.scripts.test_evaluate_retrieval_live_kb_gate import kb_env as live_kb_env  # noqa: F401
from tests.scripts.test_evaluate_retrieval_live_kb_gate import no_aws as live_no_aws  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]

# Text that must never appear in any output. Each row carries its own marker.
M_GREETING = "Hello, thanks a lot!"
M_COURSE = "QZX7741 Explain the PESTEL framework from the week 3 lecture."
M_PERSONAL = "QZX7742 I think our own interviews show users want less clutter."
H_COURSE = "QZX7743 earlier we talked about the reading list"

ROWS: list[dict[str, Any]] = [
    {"id": "ex001", "message": M_GREETING, "label": "skip", "synthetic": True},
    {
        "id": "ex002",
        "message": M_COURSE,
        "label": "retrieve",
        "synthetic": True,
        "history_summary": H_COURSE,
        "category": "course_content",
    },
    {
        "id": "ex003",
        "message": M_PERSONAL,
        "label": "skip",
        "synthetic": True,
        "selected_source": True,
        "attachment": False,
        "stage": "problem_identification",
    },
]


def write_extras(path: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in (ROWS if rows is None else rows)) + "\n", encoding="utf-8")
    return path


def extra_kb(rows: list[dict[str, Any]] | None = None, *, scores: dict[str, float] | None = None) -> dict[str, Any]:
    """SYNTHETIC TEST DATA: a fake KB-score file for the extra rows."""
    scores = scores or {"ex001": 0.2, "ex002": 0.9, "ex003": 0.4}
    return {
        "mode": "live_kb_gate_extra",
        "synthetic_test_fixture": True,
        "rows": [
            {
                "id": row["id"],
                "category": "x",
                "top_score": scores[row["id"]],
                "result_count": 2,
                "status": "ok",
                "failure_category": None,
                "elapsed_ms": 120.0,
                "raw_hit_count": 5,
                "exception_class": None,
            }
            for row in (ROWS if rows is None else rows)
        ],
        "summary": {"stopped_on_auth_error": False},
        "run": {"git_sha": "0" * 40, "git_dirty": False, "generated_at_utc": "2000-01-01T00:00:00Z"},
    }


ALL_TEXT = [M_GREETING, M_COURSE, M_PERSONAL, H_COURSE, "QZX774"]


# ------------------------------------------------------------------------------ loader


def test_loader_builds_gate_format_rows_with_defaults(tmp_path: Path) -> None:
    loaded = load_extra_messages(write_extras(tmp_path / "x.jsonl"))
    assert loaded.ids == ["ex001", "ex002", "ex003"]
    assert loaded.real_messages is False and loaded.allow_non_synthetic is False
    first, second, third = loaded.rows
    assert first["stage"] == "problem_identification" and first["category"] == "uncategorised"
    assert first["history"] == [] and first["selected_sources"] == [] and first["attachments"] == []
    assert second["history"] == [{"role": "user", "text": H_COURSE}]
    assert second["category"] == "course_content"
    assert third["selected_sources"] == [{"title": "", "filename": ""}] and third["attachments"] == []
    assert [r["expected_decision"] for r in loaded.rows] == ["skip", "retrieve", "skip"]
    assert loaded.describe() == {
        "rows": 3, "retrieve": 1, "skip": 2, "real_messages": False, "allow_non_synthetic": False,
    }


@pytest.mark.parametrize("marker", [False, "yes", 1, None])
def test_non_synthetic_rows_are_refused_by_default(tmp_path: Path, marker: Any) -> None:
    rows = [dict(ROWS[0]), {**ROWS[1], "synthetic": marker}]
    with pytest.raises(ExtraMessagesError) as raised:
        load_extra_messages(write_extras(tmp_path / "x.jsonl", rows))
    text = str(raised.value)
    assert "ex002" in text and "synthetic" in text and "line 2" in text
    assert "ex001" not in text


def test_a_missing_marker_is_refused_even_with_the_flag(tmp_path: Path) -> None:
    row = {k: v for k, v in ROWS[0].items() if k != "synthetic"}
    for allow in (False, True):
        with pytest.raises(ExtraMessagesError, match="missing field"):
            load_extra_messages(write_extras(tmp_path / "x.jsonl", [row]), allow_non_synthetic=allow)


def test_the_explicit_flag_accepts_real_rows_and_marks_the_result(tmp_path: Path) -> None:
    rows = [dict(ROWS[0]), {**ROWS[1], "synthetic": False}]
    path = write_extras(tmp_path / "x.jsonl", rows)
    loaded = load_extra_messages(path, allow_non_synthetic=True)
    assert loaded.real_messages is True and loaded.allow_non_synthetic is True
    assert loaded.describe()["real_messages"] is True
    # the flag does not turn a non-boolean marker into a valid one
    bad = write_extras(tmp_path / "y.jsonl", [{**ROWS[0], "synthetic": "no"}])
    with pytest.raises(ExtraMessagesError, match="true or false"):
        load_extra_messages(bad, allow_non_synthetic=True)
    # all-synthetic rows with the flag are not marked real
    assert load_extra_messages(write_extras(tmp_path / "z.jsonl"), allow_non_synthetic=True).real_messages is False


def test_the_flag_name_is_the_documented_one() -> None:
    assert ALLOW_FLAG == "--allow-non-synthetic"
    assert any(a.option_strings == [ALLOW_FLAG] for a in command.build_parser()._actions)
    assert any(a.option_strings == [ALLOW_FLAG] for a in _EVAL.build_parser()._actions)


@pytest.mark.parametrize(
    "mutation, expect",
    [
        ({"label": "maybe"}, "field 'label'"),
        ({"id": "gm001"}, "gate message id"),
        ({"id": "bad id!"}, "field 'id'"),
        ({"message": "   "}, "field 'message'"),
        ({"message": 5}, "field 'message'"),
        ({"stage": "no_such_stage"}, "field 'stage'"),
        ({"category": "made_up"}, "field 'category'"),
        ({"selected_source": "yes"}, "field 'selected_source'"),
        ({"attachment": 1}, "field 'attachment'"),
        ({"history_summary": 7}, "field 'history_summary'"),
        ({"message": "x" * 4001}, "longer than"),
    ],
)
def test_schema_errors_name_the_line_and_field_never_the_text(tmp_path: Path, mutation, expect) -> None:
    row = {**ROWS[1], "history_summary": H_COURSE, **mutation}
    with pytest.raises(ExtraMessagesError) as raised:
        load_extra_messages(write_extras(tmp_path / "x.jsonl", [row]))
    text = str(raised.value)
    assert expect in text and "line 1" in text
    for secret in ALL_TEXT[:4] + ["QZX774", "xxxxxxxx"]:
        assert secret not in text


def test_errors_report_ids_and_never_repeat_values(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(ROWS[0]),
                json.dumps({**ROWS[1], "QZX7750 secret key": "QZX7751 value"}),
                "{QZX7752 not json",
                "",
                json.dumps(ROWS[0]),
                json.dumps(["QZX7753"]),
                json.dumps({"id": "QZX7754 not a token", "message": "QZX7755", "label": "x", "synthetic": 1}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ExtraMessagesError) as raised:
        load_extra_messages(path)
    text = str(raised.value)
    assert "line 2 (id ex002): unexpected field(s): <invalid name>" in text
    assert "line 3: not valid JSON" in text and "line 4: blank line" in text
    assert "line 5 (id ex001): duplicate id" in text
    assert "line 6: row is not a JSON object" in text
    assert "QZX775" not in text


def test_file_level_errors(tmp_path: Path) -> None:
    with pytest.raises(ExtraMessagesError, match="cannot read"):
        load_extra_messages(tmp_path / "absent.jsonl")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ExtraMessagesError, match="empty"):
        load_extra_messages(empty)
    many = [{**ROWS[0], "id": f"e{i:03d}"} for i in range(MAX_ROWS + 1)]
    with pytest.raises(ExtraMessagesError, match=f"more than {MAX_ROWS}"):
        load_extra_messages(write_extras(tmp_path / "many.jsonl", many))
    assert len(load_extra_messages(write_extras(tmp_path / "ok.jsonl", many[:MAX_ROWS])).rows) == MAX_ROWS


# ------------------------------------------------------------------- live KB gate wiring


def _live(tmp_path: Path, *args: str) -> tuple[int, dict[str, Any] | None]:
    out = tmp_path / "gate.json"
    code = _EVAL.main(["--live-kb-gate", "--json-output", str(out), *args])
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


def test_the_live_gate_sends_only_the_extra_rows_and_writes_a_separate_record(
    live_kb_env, monkeypatch, tmp_path: Path, capsys, caplog
) -> None:
    stub = _StubClient()
    _install(monkeypatch, stub)
    caplog.set_level(logging.DEBUG)
    path = write_extras(tmp_path / "x.jsonl")
    code, data = _live(tmp_path, "--max-live-calls", "295", "--extra-messages", str(path))
    assert code == 0 and data is not None
    assert len(stub.requests) == 3
    assert data["mode"] == "live_kb_gate_extra" and data["set"] == "extra_messages"
    assert data["messages_in_set"] == 3 and data["live_calls_made"] == 3 and data["live_call_limit"] == 295
    assert [r["id"] for r in data["rows"]] == ["ex001", "ex002", "ex003"]
    assert data["extra_messages"] == {
        "rows": 3, "retrieve": 1, "skip": 2, "real_messages": False, "allow_non_synthetic": False,
    }
    assert {"git_sha", "git_dirty", "generated_at_utc"} <= set(data["run"])
    captured = capsys.readouterr()
    haystack = (tmp_path / "gate.json").read_text(encoding="utf-8") + captured.out + captured.err + caplog.text
    for secret in ALL_TEXT:
        assert secret not in haystack
    for row in data["rows"]:
        assert "message" not in row and "history" not in row


def test_the_call_cap_applies_to_the_extra_rows(live_kb_env, monkeypatch, tmp_path: Path) -> None:
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, data = _live(tmp_path, "--max-live-calls", "2", "--extra-messages", str(write_extras(tmp_path / "x.jsonl")))
    assert code == 0 and data is not None and len(stub.requests) == 2 and data["live_calls_made"] == 2
    assert [r["id"] for r in data["rows"]] == ["ex001", "ex002"]


def test_the_live_gate_refuses_non_synthetic_rows_unless_allowed(live_kb_env, monkeypatch, tmp_path: Path, capsys) -> None:
    rows = [dict(ROWS[0]), {**ROWS[1], "synthetic": False}]
    path = write_extras(tmp_path / "x.jsonl", rows)
    built: list[int] = []
    monkeypatch.setattr(_EVAL, "_build_live_gate_client", lambda *a, **k: built.append(1))
    code, data = _live(tmp_path, "--max-live-calls", "5", "--extra-messages", str(path))
    err = capsys.readouterr().err
    assert code == 2 and data is None and built == []
    assert "refused" in err and "ex002" in err and "synthetic" in err
    for secret in ALL_TEXT:
        assert secret not in err
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, data = _live(tmp_path, "--max-live-calls", "5", "--extra-messages", str(path), ALLOW_FLAG)
    assert code == 0 and data is not None and len(stub.requests) == 2
    assert data["extra_messages"]["real_messages"] is True and data["extra_messages"]["allow_non_synthetic"] is True


def test_the_new_flags_refuse_without_the_live_gate_and_build_no_client(live_kb_env, live_no_aws, tmp_path: Path, capsys) -> None:
    path = str(write_extras(tmp_path / "x.jsonl"))
    for argv in (
        ["--extra-messages", path],
        ["--extra-messages", path, "--max-live-calls", "5"],
        [ALLOW_FLAG],
        ["--live-kb-gate", "--max-live-calls", "5", ALLOW_FLAG],
        ["--live-kb-gate", "--max-live-calls", "5", "--extra-messages", str(tmp_path / "absent.jsonl")],
        ["--live-kb-gate", "--max-live-calls", "296", "--extra-messages", path],
    ):
        assert _EVAL.main(argv) == 2
        assert "refused" in capsys.readouterr().err
    assert live_no_aws == []


def test_the_live_gate_without_the_flag_is_unchanged(live_kb_env, monkeypatch, tmp_path: Path) -> None:
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, data = _live(tmp_path, "--max-live-calls", "3")
    assert code == 0 and data is not None
    assert data["mode"] == "live_kb_gate" and "extra_messages" not in data
    assert data["set"] != "extra_messages" and data["messages_in_set"] == 295


# ---------------------------------------------------------------- comparison wiring


def _compare(args: list[str], capsys) -> tuple[int, str, str]:
    code = command.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def _main_kb(tmp_path: Path, scopes_) -> str:
    return str(write_kb(tmp_path / "kb.json", synthetic_kb(scopes_)))


def test_the_extra_section_is_separate_and_changes_nothing_in_the_main_result(
    tmp_path: Path, capsys, gate_scopes
) -> None:
    kb = _main_kb(tmp_path, gate_scopes)
    plain, extra = tmp_path / "plain.json", tmp_path / "extra.json"
    assert _compare(["--kb-gate", kb, "--json-output", str(plain)], capsys)[0] == 0
    extras_file = write_extras(tmp_path / "x.jsonl")
    # extreme extra scores must not move T or any main figure
    extra_kb_path = write_kb(tmp_path / "ekb.json", extra_kb(scores={"ex001": 0.99, "ex002": 0.99, "ex003": 0.99}))
    code, out, err = _compare(
        ["--kb-gate", kb, "--extra-messages", str(extras_file), "--extra-kb-gate", str(extra_kb_path),
         "--json-output", str(extra)], capsys,
    )
    assert code == 0 and err == ""
    base = json.loads(plain.read_text(encoding="utf-8"))
    with_extra = json.loads(extra.read_text(encoding="utf-8"))
    assert "extra_messages" not in base
    section = with_extra.pop("extra_messages")
    for volatile in ("run",):
        base.pop(volatile), with_extra.pop(volatile)
    assert base == with_extra
    assert with_extra["rows"] == 295 and "T_C" in with_extra["calibration"]
    assert sum(v["rows"] for v in with_extra["split"].values()) == 295
    assert "pairs" not in section and "pass_rule" not in section
    assert [r["id"] for r in section["rows"]] == ["ex001", "ex002", "ex003"]
    assert section["arms_not_evaluated"].keys() == {"B", "D"}
    assert "## Extra messages (separate from M1 and M2)" in out


def test_the_extra_section_applies_the_frozen_t_c_and_never_chooses_one(tmp_path: Path, capsys, gate_scopes) -> None:
    kb = _main_kb(tmp_path, gate_scopes)
    out_json = tmp_path / "o.json"
    extras_file = write_extras(tmp_path / "x.jsonl")
    ekb = write_kb(tmp_path / "ekb.json", extra_kb())
    assert _compare(["--kb-gate", kb, "--extra-messages", str(extras_file), "--extra-kb-gate", str(ekb),
                     "--json-output", str(out_json)], capsys)[0] == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    section = data["extra_messages"]
    t_info = data["calibration"]["T_C"]["threshold"]
    assert section["t_c_frozen"] == t_info
    threshold = float("inf") if t_info["infinite"] else t_info["value"]
    by_id = {r["id"]: r for r in section["rows"]}
    # arm A injects whenever its KB search found a hit; arm C compares the top score with T_C
    for row_id, score in {"ex001": 0.2, "ex002": 0.9, "ex003": 0.4}.items():
        c = by_id[row_id]["C"]
        if c["kb_search"] and not c["local_search"]:
            assert c["evidence"] is (score >= threshold)
        a = by_id[row_id]["A"]
        assert a["evidence"] is bool(a["kb_search"] or a["local_search"])
    assert by_id["ex001"]["C"]["skip_rule"] == "greeting" and by_id["ex001"]["C"]["kb_search"] is False
    assert by_id["ex002"]["C"]["kb_search"] is True
    # statuses: a synthetic KB fixture is never a result
    assert section["summary"]["C"]["status"] == "synthetic_test_data"
    assert section["summary"]["A"]["status"] == "synthetic_test_data"
    # descriptive counts, not the M1/M2 blocks
    assert "retrieve_rows_without_evidence" in section["summary"]["A"]
    assert "m1_no_evidence_on_retrieve_rows" not in json.dumps(section)
    # the same T_C as a run without extras
    assert data["calibration"]["T_C"]["calibration_rows"] == len(
        [r for r in gate_scopes if prereg.split_of(r.id) == prereg.CALIBRATION]
    )


def test_without_an_extra_kb_file_evidence_is_missing(tmp_path: Path, capsys, gate_scopes) -> None:
    out_json = tmp_path / "o.json"
    code, out, _ = _compare(["--extra-messages", str(write_extras(tmp_path / "x.jsonl")),
                             "--json-output", str(out_json)], capsys)
    assert code == 0
    section = json.loads(out_json.read_text(encoding="utf-8"))["extra_messages"]
    assert section["kb_file"] == {"present": False}
    assert section["t_c_frozen"] is None
    assert section["summary"]["A"] == {"status": "missing"} and section["summary"]["C"] == {"status": "missing"}
    for row in section["rows"]:
        assert row["A"]["evidence"] is None and row["C"]["evidence"] is None and row["A"]["status"] == "missing"
    assert "Evidence columns are `missing`" in out


def test_a_partial_extra_kb_file_leaves_evidence_missing(tmp_path: Path, capsys, gate_scopes) -> None:
    partial = extra_kb(ROWS[:2])
    out_json = tmp_path / "o.json"
    code, _, _ = _compare(["--kb-gate", _main_kb(tmp_path, gate_scopes),
                           "--extra-messages", str(write_extras(tmp_path / "x.jsonl")),
                           "--extra-kb-gate", str(write_kb(tmp_path / "ekb.json", partial)),
                           "--json-output", str(out_json)], capsys)
    assert code == 0
    section = json.loads(out_json.read_text(encoding="utf-8"))["extra_messages"]
    assert section["kb_file"]["used"] is False and section["summary"]["A"] == {"status": "missing"}


def test_real_rows_are_marked_in_json_and_markdown(tmp_path: Path, capsys) -> None:
    rows = [dict(ROWS[0]), {**ROWS[1], "synthetic": False}]
    path = write_extras(tmp_path / "x.jsonl", rows)
    code, _, err = _compare(["--extra-messages", str(path)], capsys)
    assert code == 2 and "refused" in err and "ex002" in err
    out_json = tmp_path / "o.json"
    code, out, _ = _compare(["--extra-messages", str(path), ALLOW_FLAG, "--json-output", str(out_json)], capsys)
    assert code == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["extra_messages"]["real_messages"] is True
    assert "real_messages" in out


def test_comparison_refusals_report_ids_and_flags_not_text(tmp_path: Path, capsys, gate_scopes) -> None:
    path = str(write_extras(tmp_path / "x.jsonl"))
    for argv in (
        ["--extra-kb-gate", str(tmp_path / "e.json")],
        [ALLOW_FLAG],
        ["--extra-messages", str(tmp_path / "absent.jsonl")],
        ["--extra-messages", path, "--extra-kb-gate", str(tmp_path / "absent.json")],
        # a gate-set file is not an extra-rows file, and the reverse
        ["--extra-messages", path, "--extra-kb-gate", _main_kb(tmp_path, gate_scopes)],
        ["--kb-gate", str(write_kb(tmp_path / "e2.json", extra_kb()))],
    ):
        code, out, err = _compare(argv, capsys)
        assert code == 2 and err.startswith("refused:") and out == ""
        for secret in ALL_TEXT:
            assert secret not in err
    bad = extra_kb()
    bad["rows"][0]["id"] = "zz999"
    code, _, err = _compare(["--extra-messages", path, "--extra-kb-gate", str(write_kb(tmp_path / "b.json", bad))], capsys)
    assert code == 2 and "extra-messages file" in err


def test_no_extra_message_text_reaches_the_json_markdown_or_stdout(tmp_path: Path, capsys, gate_scopes, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    out_json, out_md = tmp_path / "o.json", tmp_path / "o.md"
    code, out, err = _compare(
        ["--kb-gate", _main_kb(tmp_path, gate_scopes), "--extra-messages", str(write_extras(tmp_path / "x.jsonl")),
         "--extra-kb-gate", str(write_kb(tmp_path / "ekb.json", extra_kb())),
         "--json-output", str(out_json), "--markdown-output", str(out_md)], capsys,
    )
    assert code == 0
    haystack = out_json.read_text(encoding="utf-8") + out_md.read_text(encoding="utf-8") + out + err + caplog.text
    for secret in ALL_TEXT:
        assert secret not in haystack


def test_the_extra_kb_loader_only_accepts_its_own_mode(tmp_path: Path) -> None:
    ids = {"ex001", "ex002", "ex003"}
    path = write_kb(tmp_path / "e.json", extra_kb())
    assert load_kb_scores(path, ids, mode="live_kb_gate_extra").complete
    with pytest.raises(KbFileError, match="live_kb_gate"):
        load_kb_scores(path, ids)


def test_the_new_modules_load_no_aws_model_or_other_command() -> None:
    code = (
        "import sys\n"
        "import scripts.evals.lib.extra_messages, scripts.evals.lib.extra_arms, scripts.evals.compare_routing_arms\n"
        "heavy = {'laya', 'vegaml', 'setfit', 'torch', 'onnxruntime', 'boto3', 'botocore'}\n"
        "others = [m for m in sys.modules if m.startswith('scripts.evals.') and not m.startswith('scripts.evals.lib')\n"
        "          and m != 'scripts.evals.compare_routing_arms']\n"
        "print(sorted(heavy & set(sys.modules)), others)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[] []"
