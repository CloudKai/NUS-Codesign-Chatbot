"""``evaluate_retrieval --live-kb-gate``: refusals, call cap, fail-fast, record schema.

No network and no AWS. ``boto3.client`` is patched to fail, and the command's
client builder is replaced by a stub ``bedrock-agent-runtime`` client, so the
real production adapter (``BedrockKnowledgeBaseRetriever``) runs against canned
Retrieve responses.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from backend import bedrock_retrieve
from backend.settings import settings
from scripts.evals.lib import kb_gate
from scripts.evals.lib.fixtures import load_materials, load_messages, load_questions
from tests.scripts.test_evaluate_retrieval import _EVAL

_BUCKET = "bucket-test"
_KB_ID = "KB-TEST-ID"
_MATERIALS = load_materials()
_MESSAGES = load_messages(
    materials=_MATERIALS,
    question_ids=[q["id"] for q in load_questions(materials=_MATERIALS)],
)
_KEY = _MATERIALS[0]["object_key"]


def _hit(score: float, *, bucket: str = _BUCKET, key: str = _KEY, text: str = "excerpt") -> dict[str, Any]:
    return {
        "content": {"text": text},
        "score": score,
        "location": {"type": "S3", "s3Location": {"uri": f"s3://{bucket}/{key}"}},
    }


class _AwsError(Exception):
    """Stand-in for botocore ``ClientError`` (carries ``response`` like the real one)."""

    def __init__(self, code: str, message: str = "denied") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


def _filtered_key(kwargs: dict[str, Any]) -> str:
    """Return the object key of the first material the request filters on."""
    search = next(iter(kwargs["retrievalConfiguration"].values()))
    condition = search["filter"].get("in") or search["filter"]["equals"]
    value = condition["value"]
    material_id = value[0] if isinstance(value, list) else value
    return next(entry["object_key"] for entry in _MATERIALS if entry["material_id"] == material_id)


class _StubClient:
    """``bedrock-agent-runtime`` stand-in. ``plan(call_number, kwargs)`` returns a response or raises."""

    def __init__(self, plan: Any = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._plan = plan or (lambda number, kwargs: {
            "retrievalResults": [_hit(0.5 + number / 1000, key=_filtered_key(kwargs))]
        })

    def retrieve(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self._plan(len(self.requests), kwargs)


@pytest.fixture(autouse=True)
def _fresh_executor():
    bedrock_retrieve.reset_shared_retrieve_executor()
    yield
    bedrock_retrieve.reset_shared_retrieve_executor()


@pytest.fixture
def kb_env(monkeypatch):
    """Configure the Knowledge Base the way a live run would (env for the check, settings for the adapter)."""
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", _KB_ID)
    monkeypatch.setenv("COURSE_MATERIALS_BUCKET", _BUCKET)
    monkeypatch.setattr(settings, "knowledge_base_id", _KB_ID)
    monkeypatch.setattr(settings, "course_materials_bucket", _BUCKET)
    monkeypatch.setattr(settings, "knowledge_base_type", "managed")
    monkeypatch.setattr(settings, "knowledge_base_metadata_filter_mode", "required")
    monkeypatch.setattr(settings, "knowledge_base_region", "us-west-2")


@pytest.fixture
def no_aws(monkeypatch):
    """Fail the test if any AWS client is built."""
    import boto3

    built: list[str] = []

    def _boom(*_args, **_kwargs):
        built.append("client")
        raise AssertionError("an AWS client must not be created")

    monkeypatch.setattr(boto3, "client", _boom)
    monkeypatch.setattr(boto3.session.Session, "client", _boom)
    monkeypatch.setattr(_EVAL, "_build_live_client", _boom)
    monkeypatch.setattr(_EVAL, "_build_live_gate_client", _boom)
    return built


def _install(monkeypatch, stub: _StubClient) -> list[tuple[str, int, float]]:
    """Make the command build the stub (wrapped by the real call counter) as its client."""
    builds: list[tuple[str, int, float]] = []

    def _build(region: str, limit: int, timeout_seconds: float):
        builds.append((region, limit, timeout_seconds))
        return _EVAL.CountingClient(stub, limit)

    monkeypatch.setattr(_EVAL, "_build_live_gate_client", _build)
    return builds


def _run(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any] | None]:
    out = tmp_path / "gate.json"
    code = _EVAL.main(["--live-kb-gate", "--json-output", str(out), *extra])
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


# ---- refusals ---------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--live-kb-gate"],
        ["--live-kb-gate", "--max-live-calls", "0"],
        ["--live-kb-gate", "--max-live-calls", "-1"],
        ["--live-kb-gate", "--max-live-calls", "296"],
        ["--live-kb-gate", "--max-live-calls", "5", "--live-kb"],
        ["--live-kb-gate", "--max-live-calls", "5", "--live-model"],
        ["--live-kb-gate", "--max-live-calls", "5", "--ids", "gm001"],
        ["--live-kb-gate", "--max-live-calls", "5", "--categories", "greeting_thanks_chitchat"],
        ["--live-kb-gate", "--max-live-calls", "5", "--expected-decision", "retrieve"],
        ["--live-kb-gate", "--max-live-calls", "5", "--skip-sample", "2"],
        ["--live-kb-gate", "--max-live-calls", "5", "--compare-source-check"],
    ],
)
def test_refuses_with_exit_2_and_builds_no_client(argv, kb_env, no_aws, capsys) -> None:
    assert _EVAL.main(argv) == 2
    assert "refused" in capsys.readouterr().err
    assert no_aws == []


@pytest.mark.parametrize("missing", ["KNOWLEDGE_BASE_ID", "COURSE_MATERIALS_BUCKET"])
def test_refuses_when_the_knowledge_base_is_not_configured(missing, kb_env, no_aws, monkeypatch, capsys) -> None:
    monkeypatch.delenv(missing)
    assert _EVAL.main(["--live-kb-gate", "--max-live-calls", "5"]) == 2
    assert missing in capsys.readouterr().err
    assert no_aws == []


def test_the_cap_is_295() -> None:
    assert _EVAL.LIVE_KB_GATE_CAP == 295 == len(_MESSAGES)
    env = {"KNOWLEDGE_BASE_ID": "kb", "COURSE_MATERIALS_BUCKET": "b"}
    assert _EVAL.check_live_gate_request(295, env) == 295
    for bad in (None, 0, 296):
        with pytest.raises(_EVAL.LiveRunRefused):
            _EVAL.check_live_gate_request(bad, env)


def test_existing_flags_still_refuse_without_the_gate_flag(kb_env, no_aws, capsys) -> None:
    assert _EVAL.main(["--max-live-calls", "5"]) == 2
    assert _EVAL.main(["--live-kb", "--max-live-calls", "101"]) == 2
    assert no_aws == []


# ---- cap and record schema --------------------------------------------------


def test_full_run_makes_295_calls_and_writes_the_record(kb_env, monkeypatch, tmp_path, capsys) -> None:
    stub = _StubClient()
    builds = _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "295")
    assert code == 0 and data is not None
    assert len(stub.requests) == 295
    assert builds == [("us-west-2", 295, 10.0)]
    assert data["mode"] == "live_kb_gate"
    assert data["live_calls_made"] == 295 and data["live_call_limit"] == 295
    assert data["messages_in_set"] == 295 and data["set"] == "retrieval_gate_messages.synthetic.jsonl"
    assert data["first_auth_error"] is None
    assert data["kb_settings"] == {
        "candidates": 12,
        "max_results": 4,
        "filter_mode": "required",
        "knowledge_base_type": "managed",
        "timeout_seconds": 10.0,
        "region": "us-west-2",
    }
    assert re.fullmatch(r"[0-9a-f]{40}", data["run"]["git_sha"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["run"]["generated_at_utc"])
    assert isinstance(data["run"]["git_dirty"], bool)
    rows = data["rows"]
    assert [row["id"] for row in rows] == [row["id"] for row in _MESSAGES]
    assert set(rows[0]) == {
        "id", "category", "top_score", "result_count", "status",
        "failure_category", "elapsed_ms", "raw_hit_count", "exception_class",
    }  # fmt: skip
    first = rows[0]
    assert first["top_score"] == 0.501 and first["result_count"] == 1 and first["raw_hit_count"] == 1
    assert first["status"] == "ok" and first["failure_category"] is None and first["exception_class"] is None
    assert isinstance(first["elapsed_ms"], float) and first["category"] == _MESSAGES[0]["category"]
    summary = data["summary"]
    assert summary["rows_recorded"] == 295 == summary["rows_requested"]
    assert summary["status_counts"] == {"ok": 295} and summary["stopped_on_auth_error"] is False
    assert summary["elapsed_ms_answered"]["n"] == 295
    out = capsys.readouterr().out
    assert "live calls made: 295 of limit 295" in out


def test_a_lower_cap_sends_an_evenly_spaced_subset(kb_env, monkeypatch, tmp_path) -> None:
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "10")
    assert code == 0 and data is not None
    assert len(stub.requests) == 10 and data["live_calls_made"] == 10 and data["live_call_limit"] == 10
    expected = [_MESSAGES[i * 295 // 10]["id"] for i in range(10)]
    assert [row["id"] for row in data["rows"]] == expected


def test_the_recording_client_enforces_its_own_cap() -> None:
    stub = _StubClient(lambda _number, _kwargs: {"retrievalResults": []})
    client = kb_gate.RecordingRetrieveClient(stub, 2)
    client.retrieve(x=1)
    client.retrieve(x=2)
    with pytest.raises(kb_gate.LiveCallLimitExceeded):
        client.retrieve(x=3)
    assert client.calls == 2 and len(stub.requests) == 2


# ---- production adapter path ------------------------------------------------


def test_validated_top_score_ignores_dropped_hits_and_results_are_trimmed(kb_env, monkeypatch, tmp_path) -> None:
    def plan(_number, _kwargs):
        return {
            "retrievalResults": [
                _hit(0.99, bucket="foreign-bucket"),
                _hit(0.98, key="course/lectureNotes/not-in-the-course.pdf"),
                _hit(0.97, text=""),
                *[_hit(0.50 + i / 100, text=f"distinct excerpt {i}") for i in range(9)],
            ]
        }

    _install(monkeypatch, _StubClient(plan))
    code, data = _run(tmp_path, "--max-live-calls", "1")
    assert code == 0 and data is not None
    row = data["rows"][0]
    assert row["raw_hit_count"] == 12
    assert row["result_count"] == 4  # nine validated hits trimmed to FAST_CHAT_RETRIEVAL_MAX_CHUNKS
    assert row["top_score"] == 0.58  # the dropped 0.99 / 0.98 / 0.97 hits never count
    assert row["status"] == "ok"


def test_request_uses_the_production_candidate_count_and_course_material_filter(kb_env, monkeypatch, tmp_path) -> None:
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, _ = _run(tmp_path, "--max-live-calls", "3")
    assert code == 0 and len(stub.requests) == 3
    for request in stub.requests:
        assert request["knowledgeBaseId"] == _KB_ID
        search = request["retrievalConfiguration"]["managedSearchConfiguration"]
        assert search["numberOfResults"] == 12
        condition = search["filter"].get("in") or search["filter"]["equals"]
        assert condition["key"] == "course_material_id"
        values = condition["value"]
        values = values if isinstance(values, list) else [values]
        assert set(values) <= {entry["material_id"] for entry in _MATERIALS} and values


def test_vector_type_uses_the_vector_search_configuration(kb_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "knowledge_base_type", "vector")
    stub = _StubClient()
    _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "1")
    assert code == 0 and data is not None
    assert "vectorSearchConfiguration" in stub.requests[0]["retrievalConfiguration"]
    assert data["kb_settings"]["knowledge_base_type"] == "vector"


# ---- failures ---------------------------------------------------------------


def test_stops_on_the_first_access_error_and_prints_the_class(kb_env, monkeypatch, tmp_path, capsys) -> None:
    def plan(number, _kwargs):
        if number == 3:
            raise _AwsError("AccessDeniedException", "SECRET-QUERY-TEXT")
        return {"retrievalResults": [_hit(0.7)]}

    stub = _StubClient(plan)
    _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "20")
    assert code == 3 and data is not None
    assert len(stub.requests) == 3 and data["live_calls_made"] == 3
    assert [row["status"] for row in data["rows"]] == ["ok", "ok", "unavailable"]
    last = data["rows"][-1]
    assert last["exception_class"] == "_AwsError" and last["top_score"] is None and last["result_count"] == 0
    assert last["failure_category"] and last["raw_hit_count"] is None
    assert data["first_auth_error"]["id"] == last["id"]
    assert "_AwsError" in data["first_auth_error"]["exception"]
    assert data["summary"]["stopped_on_auth_error"] is True
    captured = capsys.readouterr()
    assert "_AwsError" in captured.err and "AccessDeniedException" in captured.err
    assert "SECRET-QUERY-TEXT" not in captured.out + captured.err + json.dumps(data)


def test_missing_credentials_also_stop_the_run(kb_env, monkeypatch, tmp_path, capsys) -> None:
    class NoCredentialsError(Exception):
        pass

    def plan(_number, _kwargs):
        raise NoCredentialsError("Unable to locate credentials")

    stub = _StubClient(plan)
    _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "20")
    assert code == 3 and data is not None and len(stub.requests) == 1
    # The adapter reports this as client_error; the wrapper still sees the real class.
    assert data["rows"][0]["failure_category"] == "client_error"
    assert data["rows"][0]["exception_class"] == "NoCredentialsError"
    assert "NoCredentialsError" in capsys.readouterr().err


def test_other_failures_and_empty_results_are_recorded_and_the_run_continues(kb_env, monkeypatch, tmp_path) -> None:
    def plan(number, _kwargs):
        if number == 2:
            raise _AwsError("ThrottlingException")
        if number == 3:
            return {"retrievalResults": []}
        return {"retrievalResults": [_hit(0.6)]}

    stub = _StubClient(plan)
    _install(monkeypatch, stub)
    code, data = _run(tmp_path, "--max-live-calls", "4")
    assert code == 0 and data is not None and len(stub.requests) == 4
    assert [row["status"] for row in data["rows"]] == ["ok", "unavailable", "empty", "ok"]
    failed, empty = data["rows"][1], data["rows"][2]
    assert failed["top_score"] is None and failed["result_count"] == 0 and failed["raw_hit_count"] is None
    assert failed["exception_class"] == "_AwsError" and failed["failure_category"]
    assert empty["top_score"] is None and empty["result_count"] == 0 and empty["raw_hit_count"] == 0
    assert empty["failure_category"] is None
    summary = data["summary"]
    assert summary["status_counts"] == {"empty": 1, "ok": 2, "unavailable": 1}
    assert summary["rows_with_validated_hit"] == 2 and summary["elapsed_ms_answered"]["n"] == 3
    assert summary["elapsed_ms_all_attempts"]["n"] == 4


def test_exit_code_is_1_when_no_call_is_answered(kb_env, monkeypatch, tmp_path, capsys) -> None:
    def plan(_number, _kwargs):
        raise _AwsError("ThrottlingException")

    _install(monkeypatch, _StubClient(plan))
    code, data = _run(tmp_path, "--max-live-calls", "3")
    assert code == 1 and data is not None and data["live_calls_made"] == 3
    assert "no call was answered" in capsys.readouterr().err


# ---- privacy ----------------------------------------------------------------


def test_no_message_or_history_text_reaches_the_file_stdout_stderr_or_logs(
    kb_env, monkeypatch, tmp_path, capsys, caplog
) -> None:
    def plan(number, _kwargs):
        if number == 50:
            raise _AwsError("ThrottlingException")
        return {"retrievalResults": [_hit(0.6)]}

    _install(monkeypatch, _StubClient(plan))
    caplog.set_level(logging.DEBUG)
    code, data = _run(tmp_path, "--max-live-calls", "295")
    assert code == 0 and data is not None
    captured = capsys.readouterr()
    haystack = (tmp_path / "gate.json").read_text(encoding="utf-8") + captured.out + captured.err + caplog.text
    texts = [str(row["message"]) for row in _MESSAGES] + [
        str(turn["text"]) for row in _MESSAGES for turn in row["history"]
    ]
    long_texts = [text for text in texts if len(text) >= 25]
    assert len(long_texts) > 100
    leaked = [text for text in long_texts if text in haystack]
    assert leaked == []
    for row in data["rows"]:
        assert "message" not in row and "history" not in row


def test_no_knowledge_base_id_or_bucket_in_the_record(kb_env, monkeypatch, tmp_path) -> None:
    _install(monkeypatch, _StubClient())
    code, _ = _run(tmp_path, "--max-live-calls", "2")
    assert code == 0
    text = (tmp_path / "gate.json").read_text(encoding="utf-8")
    assert _KB_ID not in text and _BUCKET not in text


# ---- no side effects --------------------------------------------------------


def test_importing_the_command_and_lib_builds_no_client(no_aws) -> None:
    import importlib

    importlib.reload(kb_gate)
    assert no_aws == []
