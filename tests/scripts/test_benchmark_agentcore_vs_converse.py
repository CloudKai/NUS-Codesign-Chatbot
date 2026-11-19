"""AgentCore vs Converse benchmark harness: refusal, turn set, call cap, stub runs.

Stub clients only. No network and no AWS: every client is a local stand-in and
``boto3.client`` fails the test if it is reached.
"""

from __future__ import annotations

import io
import json

import pytest

from scripts.evals import benchmark_agentcore_vs_converse as bench

_HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/Test_runtime-AbC123"
_SETTINGS = ("bedrock", _HAIKU, "us-west-2", _ARN, "us-west-2", "DEFAULT")
_FIXED_RUN = {"git_sha": "b" * 40, "git_dirty": False, "generated_at_utc": "2026-11-19T12:00:00Z"}


class Clock:
    """Deterministic clock the stubs advance, so latencies are exact."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tool_input(*, mode: str = "qa") -> dict:
    body = {
        "mode": mode,
        "response_text": "Short reply.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "needs_sources": False,
        "out_of_scope": False,
    }
    if mode == "coaching":
        body["recommendation"] = "stay"
    return body


class StubRuntime:
    """Stand-in for the ``bedrock-agentcore`` client."""

    def __init__(self, clock: Clock, *, error=None, raw: bytes | None = None, usage=True) -> None:
        self.clock = clock
        self.requests: list[dict] = []
        self._error = error
        self._raw = raw
        self._usage = usage

    def invoke_agent_runtime(self, **kwargs):
        self.requests.append(kwargs)
        self.clock.advance(0.5)
        if self._error is not None:
            raise self._error(len(self.requests))
        if self._raw is not None:
            return {"contentType": "application/json", "response": io.BytesIO(self._raw)}
        from agentcore_runtime.models import parse_fast_chat_turn_output
        from agentcore_runtime.structured_coach import structured_wire_payload

        wire = structured_wire_payload(parse_fast_chat_turn_output(_tool_input()))
        if self._usage:
            wire.update(
                model_input_tokens=7000,
                model_output_tokens=300,
                cache_read_input_tokens=0,
                cache_write_input_tokens=0,
                runtime_model_id=_HAIKU,
                model_first_reply_text_ms=210,
                prompt_cache_enabled=False,
            )
        return {"contentType": "application/json", "response": io.BytesIO(json.dumps(wire).encode())}


class StubBedrock:
    """Stand-in for the ``bedrock-runtime`` client (Converse and ConverseStream)."""

    def __init__(self, clock: Clock, *, error=None, text_only=False) -> None:
        self.clock = clock
        self.requests: list[dict] = []
        self.stream_requests: list[dict] = []
        self._error = error
        self._text_only = text_only

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        self.clock.advance(0.3)
        if self._error is not None:
            raise self._error(len(self.requests))
        content = (
            [{"text": "plain words"}]
            if self._text_only
            else [{"toolUse": {"toolUseId": "t", "name": "FastChatTurnOutput", "input": _tool_input()}}]
        )
        return {
            "output": {"message": {"role": "assistant", "content": content}},
            "stopReason": "end_turn" if self._text_only else "tool_use",
            "usage": {"inputTokens": 6900, "outputTokens": 280, "cacheReadInputTokens": 100, "cacheWriteInputTokens": 0},
        }

    def converse_stream(self, **kwargs):
        self.stream_requests.append(kwargs)
        text = json.dumps(_tool_input())
        cut = text.index("Short") + 3
        clock = self.clock

        def events():
            clock.advance(0.1)
            yield {"contentBlockStart": {"start": {"toolUse": {"name": "FastChatTurnOutput"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": text[:cut]}}}}
            clock.advance(0.2)
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": text[cut:]}}}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            yield {"metadata": {"usage": {"inputTokens": 6900, "outputTokens": 280}}}

        return {"stream": events()}


def _client_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": "secret body"}}, "Op")


@pytest.fixture(scope="module")
def turns():
    return bench.load_turns()


@pytest.fixture
def no_boto(monkeypatch):
    """Fail the test if a real AWS client would be built."""
    import boto3

    def _boom(*_args, **_kwargs):
        raise AssertionError("an AWS client must not be created")

    monkeypatch.setattr(boto3, "client", _boom)
    monkeypatch.setattr(boto3.session.Session, "client", _boom)
    monkeypatch.setattr(bench, "build_clients", _boom)


def _run(turns, limit, runtime, bedrock, clock, **kwargs):
    budget = bench.CallBudget(limit)
    return bench.run_benchmark(
        turns,
        limit,
        runtime_client=bench.BudgetedClient(runtime, budget, "agentcore"),
        converse_client=bench.BudgetedClient(bedrock, budget, "converse"),
        budget=budget,
        model_id=_HAIKU,
        region="us-west-2",
        runtime_arn=_ARN,
        qualifier="DEFAULT",
        clock=clock,
        **kwargs,
    )


# ---- fixed turn set ----------------------------------------------------------


def test_turn_set_is_the_pinned_fifty_synthetic_rows(turns) -> None:
    assert len(turns) == 50
    assert len({t["id"] for t in turns}) == 50
    assert all(t["synthetic"] is True for t in turns)
    assert [t["id"] for t in turns] == [t["id"] for t in bench.load_turns()]


def test_turn_set_refuses_when_the_dataset_changes(turns) -> None:
    with pytest.raises(bench.BenchmarkRefused, match="pinned"):
        bench.select_benchmark_turns([dict(t, id=f"x{i}") for i, t in enumerate(turns * 6)][:295])


# ---- call cap ----------------------------------------------------------------


@pytest.mark.parametrize(("limit", "turn_count"), [(2, 1), (7, 3), (50, 25), (99, 49), (100, 50)])
def test_cap_pays_for_half_as_many_turns(turns, limit, turn_count) -> None:
    chosen = bench.turns_for_limit(turns, limit)
    assert len(chosen) == turn_count
    assert len(chosen) * bench.CALLS_PER_TURN <= limit


@pytest.mark.parametrize("value", [None, 0, 1, 101, -3])
def test_call_limit_refuses_missing_or_out_of_range(value) -> None:
    with pytest.raises(bench.BenchmarkRefused):
        bench.check_call_limit(value)


def test_shared_budget_stops_the_run_at_the_limit() -> None:
    budget = bench.CallBudget(2)
    budget.take("agentcore")
    budget.take("converse")
    with pytest.raises(bench.retrieval.LiveCallLimitExceeded):
        budget.take("agentcore")
    assert budget.made == 2


# ---- refusal before any client ---------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--live-benchmark"],
        ["--max-live-calls", "4"],
        ["--live-benchmark", "--max-live-calls", "0"],
        ["--live-benchmark", "--max-live-calls", "1"],
        ["--live-benchmark", "--max-live-calls", "101"],
        ["--dry-run"],
    ],
)
def test_refuses_without_a_valid_cap_and_builds_no_client(argv, no_boto, monkeypatch, capsys) -> None:
    monkeypatch.setattr(bench, "_settings_for_run", lambda: _SETTINGS)
    assert bench.main(argv) == 2
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("settings", "needle"),
    [
        (("openai", _HAIKU, "us-west-2", _ARN, "us-west-2", "DEFAULT"), "COACHING_MODEL_PROVIDER"),
        (("bedrock", "global.anthropic.claude-sonnet-4-6", "us-west-2", _ARN, "us-west-2", "DEFAULT"), "Haiku"),
        (("bedrock", _HAIKU, "us-west-2", "", "us-west-2", "DEFAULT"), "AGENTCORE_RUNTIME_ARN"),
        (("bedrock", _HAIKU, "us-west-2", "arn:aws:s3:::bucket", "us-west-2", "DEFAULT"), "AGENTCORE_RUNTIME_ARN"),
        (("bedrock", _HAIKU, "us-west-2", _ARN, "eu-west-1", "DEFAULT"), "region"),
    ],
)
def test_refuses_unsafe_settings_before_any_client(settings, needle, no_boto, monkeypatch, capsys) -> None:
    monkeypatch.setattr(bench, "_settings_for_run", lambda: settings)
    assert bench.main(["--live-benchmark", "--max-live-calls", "4"]) == 2
    assert needle in capsys.readouterr().err


def test_dry_run_prints_the_plan_and_builds_no_client(no_boto, capsys) -> None:
    assert bench.main(["--dry-run", "--max-live-calls", "10"]) == 0
    out = capsys.readouterr().out
    assert "5 of 50 turns, 10 calls" in out and "no client built" in out


# ---- stub runs ---------------------------------------------------------------


def test_run_sends_each_turn_through_both_paths_and_counts_every_call(turns) -> None:
    clock = Clock()
    runtime, bedrock = StubRuntime(clock), StubBedrock(clock)
    result = _run(turns, 7, runtime, bedrock, clock)
    assert result["calls"] == {
        "limit": 7, "made": 6, "agentcore": 3, "converse": 3, "calls_per_turn": 2,
    }
    assert len(runtime.requests) == len(bedrock.requests) == 3
    assert result["turn_set"]["turns_selected_by_cap"] == 3
    assert [r["order"][0] for r in result["rows"]] == ["agentcore", "converse", "agentcore"]
    assert result["exit_code"] == 0 and result["first_failure"] is None


def test_both_paths_get_the_same_prompt_history_and_tool(turns) -> None:
    clock = Clock()
    runtime, bedrock = StubRuntime(clock), StubBedrock(clock)
    _run(turns, 2, runtime, bedrock, clock)
    from agentcore_runtime.structured_coach import specialist_system_prompt

    sent = json.loads(runtime.requests[0]["payload"])
    assert runtime.requests[0]["agentRuntimeArn"] == _ARN
    assert runtime.requests[0]["runtimeSessionId"].startswith("stateless-")
    request = bedrock.requests[0]
    assert request["system"] == [{"text": specialist_system_prompt(sent)}]
    assert request["toolConfig"]["toolChoice"] == {"any": {}}
    assert request["toolConfig"]["tools"][0]["toolSpec"]["name"] == "FastChatTurnOutput"
    assert request["modelId"] == _HAIKU


def test_latency_tokens_and_cost_are_recorded_per_path(turns) -> None:
    clock = Clock()
    result = _run(turns, 4, StubRuntime(clock), StubBedrock(clock), clock)
    agentcore, converse = result["arms"]["agentcore"], result["arms"]["converse"]
    assert agentcore["total_ms"]["median"] == 500 and converse["total_ms"]["median"] == 300
    # Not streamed: first text equals total, and the basis says so.
    assert converse["first_text_ms"]["median"] == 300
    assert result["rows"][0]["converse"]["first_text_basis"] == "total (not streamed)"
    assert agentcore["tokens"] == {
        "rows_with_usage": 2, "input": 14000, "output": 600, "cache_read": 0, "cache_write": 0,
    }
    assert converse["tokens"]["cache_read"] == 200
    # (7000 * 1.00 + 300 * 5.00) / 1e6 per AgentCore call (hand arithmetic).
    assert agentcore["estimated_cost_usd"]["per_priced_call"] == pytest.approx(0.0085)
    assert agentcore["estimated_cost_usd"]["estimate"] is True
    assert result["pairs"]["pairs_both_ok"] == 2
    assert result["pairs"]["median_total_ms_delta_agentcore_minus_converse"] == 200
    assert result["pairs"]["same_mode_turns"] == 2
    assert result["runtime_model_ids_seen"] == [_HAIKU]


def test_missing_usage_is_unknown_not_zero(turns) -> None:
    clock = Clock()
    result = _run(turns, 2, StubRuntime(clock, usage=False), StubBedrock(clock), clock)
    arm = result["arms"]["agentcore"]
    assert arm["tokens"]["rows_with_usage"] == 0
    assert arm["estimated_cost_usd"]["rows_priced"] == 0
    assert arm["estimated_cost_usd"]["per_priced_call"] is None


def test_stream_mode_reports_a_first_text_time_before_the_total(turns) -> None:
    clock = Clock()
    bedrock = StubBedrock(clock)
    result = _run(turns, 2, StubRuntime(clock), bedrock, clock, converse_stream=True)
    row = result["rows"][0]["converse"]
    assert bedrock.stream_requests and not bedrock.requests
    assert row["first_text_ms"] == 100 and row["total_ms"] == 300
    assert row["first_text_basis"] == "first response_text fragment"
    assert result["paths"]["converse"]["api"] == "bedrock-runtime ConverseStream"
    assert row["tokens"]["input"] == 6900


def test_text_only_converse_reply_is_a_parse_failure_with_usage_kept(turns) -> None:
    clock = Clock()
    result = _run(turns, 4, StubRuntime(clock), StubBedrock(clock, text_only=True), clock)
    converse = result["arms"]["converse"]
    assert converse["parse_failures"] == 2 and converse["call_failures"] == 0 and converse["ok"] == 0
    failed = result["rows"][0]["converse"]
    assert failed["failure_detail"]["kind"] == "no_tool_call" and failed["tokens"]["output"] == 280
    assert result["arms"]["agentcore"]["ok"] == 2
    assert result["calls"]["made"] == 4 and result["exit_code"] == 0
    assert "plain words" not in json.dumps(result)


def test_malformed_agentcore_body_is_a_parse_failure_and_costs_a_call(turns) -> None:
    clock = Clock()
    result = _run(turns, 2, StubRuntime(clock, raw=b"not json"), StubBedrock(clock), clock)
    assert result["arms"]["agentcore"]["parse_failures"] == 1
    assert result["arms"]["agentcore"]["calls"] == 1 and result["calls"]["made"] == 2


def test_non_auth_failure_is_recorded_and_the_run_continues(turns) -> None:
    clock = Clock()
    runtime = StubRuntime(clock, error=lambda n: _client_error("ThrottlingException") if n == 1 else None)
    # The stub raises for call 1 only; later calls must not raise ``None``.
    original = runtime.invoke_agent_runtime

    def _once(**kwargs):
        if len(runtime.requests) >= 1:
            runtime._error = None
        return original(**kwargs)

    runtime.invoke_agent_runtime = _once
    result = _run(turns, 6, runtime, StubBedrock(clock), clock)
    assert result["arms"]["agentcore"]["call_failures"] == 1 and result["arms"]["agentcore"]["ok"] == 2
    assert result["first_failure"]["error"] == "botocore.exceptions.ClientError (code ThrottlingException)"
    assert result["stopped_early_on_auth_or_access_error"] is None and result["exit_code"] == 0


@pytest.mark.parametrize("failing", ["agentcore", "converse"])
def test_stops_after_the_first_auth_error_and_records_only_the_class(turns, failing) -> None:
    clock = Clock()
    deny = lambda n: _client_error("AccessDeniedException")  # noqa: E731
    runtime = StubRuntime(clock, error=deny if failing == "agentcore" else None)
    bedrock = StubBedrock(clock, error=deny if failing == "converse" else None)
    result = _run(turns, 20, runtime, bedrock, clock)
    assert result["calls"]["made"] <= 2
    stopped = result["stopped_early_on_auth_or_access_error"]
    assert stopped["arm"] == failing and stopped["id"] == result["rows"][0]["id"]
    assert stopped["error"] == "botocore.exceptions.ClientError (code AccessDeniedException)"
    assert result["first_failure"] == stopped
    assert len(result["rows"]) == 1
    assert "secret body" not in json.dumps(result)


def test_auth_error_after_successes_exits_three(turns) -> None:
    clock = Clock()
    runtime = StubRuntime(clock)
    original = runtime.invoke_agent_runtime

    def _deny_on_second(**kwargs):
        if len(runtime.requests) >= 1:
            runtime.requests.append(kwargs)
            raise _client_error("ExpiredTokenException")
        return original(**kwargs)

    runtime.invoke_agent_runtime = _deny_on_second
    result = _run(turns, 20, runtime, StubBedrock(clock), clock)
    assert result["exit_code"] == 3
    assert result["stopped_early_on_auth_or_access_error"]["error"].endswith("(code ExpiredTokenException)")


def test_exit_code_is_one_when_every_call_fails(turns) -> None:
    clock = Clock()
    result = _run(turns, 4, StubRuntime(clock, raw=b"x"), StubBedrock(clock, text_only=True), clock)
    assert result["exit_code"] == 1


@pytest.mark.parametrize(("flag", "expected"), [("true", True), ("false", False)])
def test_converse_system_prompt_carries_the_runtime_cache_point_rule(turns, monkeypatch, flag, expected) -> None:
    monkeypatch.setenv("FAST_CHAT_PROMPT_CACHE_ENABLED", flag)
    clock = Clock()
    bedrock = StubBedrock(clock)
    result = _run(turns, 2, StubRuntime(clock), bedrock, clock)
    has_point = any("cachePoint" in block for block in bedrock.requests[0]["system"])
    assert has_point is expected
    assert result["rows"][0]["converse"]["prompt_cache_point"] is expected
    assert result["arms"]["converse"]["prompt_cache_point_rows"] == (1 if expected else 0)


def test_main_runs_with_stub_clients_and_writes_the_run_block(monkeypatch, tmp_path, capsys) -> None:
    clock = Clock()
    runtime, bedrock = StubRuntime(clock), StubBedrock(clock)
    monkeypatch.setattr(bench, "_settings_for_run", lambda: _SETTINGS)
    monkeypatch.setattr(
        bench,
        "build_clients",
        lambda region, runtime_region, budget: (
            bench.BudgetedClient(runtime, budget, "agentcore"),
            bench.BudgetedClient(bedrock, budget, "converse"),
        ),
    )
    monkeypatch.setattr(bench.retrieval, "_git_run_metadata", lambda: dict(_FIXED_RUN))
    out = tmp_path / "bench.json"
    assert bench.main(["--live-benchmark", "--max-live-calls", "6", "--json-output", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["run"] == _FIXED_RUN and data["exit_code"] == 0
    assert data["calls"]["made"] == 6 and data["turn_set"]["ids_sha256"] == bench.TURN_IDS_SHA256
    assert "AgentCore vs direct Bedrock Converse benchmark" in capsys.readouterr().out
