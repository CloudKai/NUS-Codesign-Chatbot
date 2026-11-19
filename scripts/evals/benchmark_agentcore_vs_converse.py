"""Benchmark the AgentCore runtime path against a direct Bedrock Converse call.

BUILT, NOT RUN. This script is a paid live tool. It refuses to do anything
without ``--max-live-calls`` (and ``--live-benchmark``), and it refuses before
any AWS client is built. Pytest never reaches the live path; tests use stub
clients only. Run it only with the user's approval and a call cap.

What is compared (the same fixed turns through both paths, one call each):

* ``agentcore``: ``bedrock-agentcore`` ``InvokeAgentRuntime`` on the configured
  runtime ARN and qualifier, with the payload ``AgentCoreCoachProvider`` sends
  for a Fast Chat turn. The runtime builds the system prompt, runs the Strands
  agent with the forced ``FastChatTurnOutput`` tool, applies its guardrail and
  returns one JSON object. The reply is checked with the provider's own
  ``_payload_from_runtime_response`` and ``_validated_fast_chat``.
* ``converse``: ``bedrock-runtime`` ``Converse`` (or ``ConverseStream`` with
  ``--converse-stream``) on ``COACHING_MODEL_ID`` with the same payload turned
  into Converse arguments by ``LiveFastChatBridge`` (same system prompt, same
  history, same ``FastChatTurnOutput`` tool schema, forced tool choice) and the
  same ``_validated_fast_chat`` check. The system prompt carries the runtime's
  prefix cache point exactly when ``FAST_CHAT_PROMPT_CACHE_ENABLED`` is true in
  this process (``agentcore_runtime.structured_coach.agent_system_prompt``).

Differences that stay (recorded in ``docs/RETRIEVAL_EVAL.md``): the Converse arm
has no Bedrock guardrail, no Strands event loop and no recovery turn; both arms
make one call per turn with no SDK retry.

The 50 turns: ``select_benchmark_turns`` takes every ``i * 295 // 50``-th row
of ``retrieval_gate_messages.synthetic.jsonl`` (``evenly_spaced_indices``) and
checks the id list against a pinned SHA-256, so the set cannot change silently.
All rows are synthetic. No retrieved excerpts are attached to either path and
``source_need_check`` is off, as in production with
``FAST_CHAT_NEEDS_SOURCES_ENABLED`` off.

Call cap: ``--max-live-calls N`` counts every call to either path. A turn costs
2 calls, so ``min(50, N // 2)`` turns are sent, evenly spaced over the 50, and
the shared counter never allows more than N calls in total (1 <= N <= 100).

Safety: stops after the first auth or access error in either path, records the
first failure's exception class (never message text), the exit code and run
metadata (git SHA, UTC timestamp). Exit codes: 0 ran, 1 every call failed,
2 refused before any client was built, 3 stopped early on an auth or access
error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.evals import evaluate_retrieval as retrieval  # noqa: E402

TURN_COUNT = 50
# SHA-256 of the 50 selected ids joined by newlines, in file order.
TURN_IDS_SHA256 = "a79b9d5a5c9f0b26e42eef9de70187c902964cb0166436d58252376ce5a0ff37"
CALLS_PER_TURN = 2
HARD_CALL_CAP = TURN_COUNT * CALLS_PER_TURN
ARMS = ("agentcore", "converse")

# ESTIMATE ONLY. Claude Haiku 4.5 on the ``global.`` inference profile, USD per
# million tokens. Input and output come from third-party pages (the AWS pricing
# page did not render for the Phase 4 item 5 research); cache read is 0.1x and
# cache write 1.25x the input rate. Confirm on https://aws.amazon.com/bedrock/pricing/
# before relying on a figure. Model tokens only: AgentCore Runtime compute,
# guardrail and any runtime-side recovery call are not priced here.
PRICE_USD_PER_MTOK = {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25}
PARSE_FAILURE_CATEGORIES = frozenset({"structured_output_failure", "malformed"})
RUN_DEFINITION = (
    "Each selected turn is sent once to AgentCore InvokeAgentRuntime and once to "
    "Bedrock Converse with the same Fast Chat payload (order alternates by turn: "
    "even turns AgentCore first). total_ms runs from just before the call to the "
    "complete response body, before local validation. first_text_ms equals "
    "total_ms for both paths unless --converse-stream is used: neither a "
    "non-streaming Converse call nor the AgentCore runtime (one JSON object) "
    "returns partial text. With --converse-stream the Converse arm reports the "
    "time of the first response_text fragment. Tokens are the usage each path "
    "reports. A parse failure is a reply without a valid FastChatTurnOutput "
    "tool call or one that the Fast Chat contract rejects; any other failed "
    "call is a call failure. Cost is an estimate from PRICE_USD_PER_MTOK."
)


class BenchmarkRefused(retrieval.LiveRunRefused):
    """Raised when the benchmark is asked to run without approval or safe input."""


# ---------------------------------------------------------------------------
# Turn set and call cap (pure, no AWS)
# ---------------------------------------------------------------------------


def select_benchmark_turns(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the fixed 50 turns from the gate messages, in file order.

    Raises:
        BenchmarkRefused: When the dataset no longer yields the pinned id list.
    """
    indices = retrieval.evenly_spaced_indices(len(messages), TURN_COUNT)
    turns = [messages[i] for i in indices]
    digest = hashlib.sha256("\n".join(str(t["id"]) for t in turns).encode("utf-8")).hexdigest()
    if len(turns) != TURN_COUNT or digest != TURN_IDS_SHA256:
        raise BenchmarkRefused(
            "the gate messages no longer yield the pinned 50-turn set "
            f"(got {len(turns)} turns, sha256 {digest[:12]}); update TURN_IDS_SHA256 "
            "deliberately and record why"
        )
    return turns


def turns_for_limit(turns: Sequence[Mapping[str, Any]], limit: int) -> list[Mapping[str, Any]]:
    """Return the turns a cap of ``limit`` calls pays for: ``limit // 2``, evenly spaced."""
    return [turns[i] for i in retrieval.evenly_spaced_indices(len(turns), limit // CALLS_PER_TURN)]


def check_benchmark_request(
    live_benchmark: bool,
    max_live_calls: int | None,
    *,
    provider: str,
    model_id: str,
    region: str,
    runtime_arn: str,
    runtime_region: str,
) -> int:
    """Validate the opt-in, the cap and the settings; return the approved limit.

    Makes no network call and builds no client.

    Raises:
        BenchmarkRefused: When the flag or the cap is missing or out of range, the
            fast-chat settings are not Haiku on Bedrock, or the runtime ARN is
            missing, malformed or in a different region from the runtime client.
    """
    if not live_benchmark:
        raise BenchmarkRefused("live benchmark mode was not requested (--live-benchmark)")
    limit = check_call_limit(max_live_calls)
    try:
        retrieval.check_live_model_request(
            True, False, limit, provider=provider, model_id=model_id, region=region
        )
    except retrieval.LiveRunRefused as error:
        raise BenchmarkRefused(str(error)) from error
    parts = str(runtime_arn or "").strip().split(":")
    if len(parts) != 6 or parts[:3] != ["arn", "aws", "bedrock-agentcore"] or not parts[5].startswith("runtime/"):
        raise BenchmarkRefused(
            "AGENTCORE_RUNTIME_ARN must be arn:aws:bedrock-agentcore:<region>:<account>:runtime/<id>"
        )
    if str(runtime_region or "").strip() != parts[3]:
        raise BenchmarkRefused("AWS_REGION does not match the region in AGENTCORE_RUNTIME_ARN")
    return limit


def check_call_limit(max_live_calls: int | None) -> int:
    """Return the cap, or refuse when it is missing or outside 1 to 100."""
    if max_live_calls is None:
        raise BenchmarkRefused(
            f"--max-live-calls N (1 to {HARD_CALL_CAP}) is required; no call limit was given"
        )
    if not 1 <= max_live_calls <= HARD_CALL_CAP:
        raise BenchmarkRefused(f"--max-live-calls must be between 1 and {HARD_CALL_CAP}")
    if max_live_calls < CALLS_PER_TURN:
        raise BenchmarkRefused(
            "every turn goes through both paths (2 calls); --max-live-calls must be at least 2"
        )
    return max_live_calls


class CallBudget:
    """One call counter shared by both paths."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.made = 0
        self.by_path = {name: 0 for name in ARMS}

    def take(self, path: str) -> None:
        if self.made >= self.limit:
            raise retrieval.LiveCallLimitExceeded(f"call limit {self.limit} reached")
        self.made += 1
        self.by_path[path] += 1


class BudgetedClient:
    """Wrap one boto3 client; every billable call draws from the shared budget."""

    def __init__(self, client: Any, budget: CallBudget, path: str) -> None:
        self._client = client
        self._budget = budget
        self._path = path

    def invoke_agent_runtime(self, **kwargs: Any) -> Any:
        self._budget.take(self._path)
        return self._client.invoke_agent_runtime(**kwargs)

    def converse(self, **kwargs: Any) -> Any:
        self._budget.take(self._path)
        return self._client.converse(**kwargs)

    def converse_stream(self, **kwargs: Any) -> Any:
        self._budget.take(self._path)
        return self._client.converse_stream(**kwargs)


def build_clients(
    region: str, runtime_region: str, budget: CallBudget
) -> tuple[BudgetedClient, BudgetedClient]:
    """Create the two real boto3 clients. Only called after every check passed."""
    import boto3
    from botocore.config import Config

    from backend.settings import settings

    def config(timeout: float) -> Any:
        # One attempt per call: a retry would be an uncounted billable call.
        return Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            read_timeout=timeout,
            connect_timeout=10,
        )

    runtime = boto3.client(
        "bedrock-agentcore",
        region_name=runtime_region,
        config=config(float(settings.agentcore_timeout_seconds)),
    )
    converse = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=config(retrieval.LIVE_MODEL_TIMEOUT_SECONDS),
    )
    return (
        BudgetedClient(runtime, budget, "agentcore"),
        BudgetedClient(converse, budget, "converse"),
    )


# ---------------------------------------------------------------------------
# One call per path
# ---------------------------------------------------------------------------


def _ms(seconds: float) -> int:
    return max(0, int(round(seconds * 1000)))


def _count(value: Any) -> int | None:
    """Return a non-negative int token count, else ``None`` (never invented)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def _tokens(input_: Any, output: Any, cache_read: Any, cache_write: Any) -> dict[str, Any]:
    values = {
        "input": _count(input_),
        "output": _count(output),
        "cache_read": _count(cache_read),
        "cache_write": _count(cache_write),
    }
    values["reported"] = values["input"] is not None and values["output"] is not None
    return values


def estimate_cost_usd(tokens: Mapping[str, Any]) -> float | None:
    """Estimated model-token cost of one call, or ``None`` when usage was not reported."""
    if not tokens.get("reported"):
        return None
    total = sum(
        int(tokens.get(key) or 0) * price for key, price in PRICE_USD_PER_MTOK.items()
    )
    return round(total / 1_000_000, 6)


def failure_kind(error: BaseException) -> str:
    """``parse_failure`` for an unusable structured reply, else ``call_failure``."""
    from agentcore_runtime.models import FastChatContractError
    from backend.providers import ProviderUnavailableError

    if isinstance(error, (retrieval.LiveStructuredOutputError, FastChatContractError)):
        return "parse_failure"
    if isinstance(error, ProviderUnavailableError) and error.category in PARSE_FAILURE_CATEGORIES:
        return "parse_failure"
    return "call_failure"


def is_stop_error(error: BaseException) -> bool:
    """Credential or permission failure: every later call would fail the same way."""
    if retrieval.is_auth_or_access_error(error):
        return True
    return str(getattr(error, "category", "")) == "access_denied"


def _failed(error: BaseException, started: float, clock: Callable[[], float]) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_kind": failure_kind(error),
        "error": retrieval.exception_label(error),
        "failure_detail": retrieval.live_failure_detail(error),
        "total_ms": _ms(clock() - started),
    }


def run_agentcore_call(
    client: Any,
    runtime_arn: str,
    qualifier: str,
    request: Any,
    payload: Mapping[str, Any],
    clock: Callable[[], float],
) -> tuple[dict[str, Any], BaseException | None]:
    """One ``InvokeAgentRuntime`` call, timed, parsed and validated like production."""
    from backend.agentcore_provider import (
        _payload_from_runtime_response,
        _stateless_session_id,
        _validated_fast_chat,
    )

    started = clock()
    parsed: dict[str, Any] | None = None
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            qualifier=qualifier,
            runtimeSessionId=_stateless_session_id(),
            payload=json.dumps(payload).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        returned = clock()
        if not isinstance(response, Mapping):
            raise retrieval.LiveStructuredOutputError("runtime response is not a mapping", {"kind": "no_tool_call"})
        parsed = _payload_from_runtime_response(response)
        total = clock()
        result = _validated_fast_chat(parsed, request)
    except retrieval.LiveCallLimitExceeded:
        raise
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed
        row = _failed(error, started, clock)
        row["tokens"] = _agentcore_tokens(parsed)
        return row, error
    runtime_first = _count((parsed or {}).get("model_first_reply_text_ms"))
    return (
        {
            "status": "ok",
            "total_ms": _ms(total - started),
            "first_text_ms": _ms(total - started),
            "first_text_basis": "total (the runtime returns one JSON object)",
            "invoke_returned_ms": _ms(returned - started),
            "tokens": _agentcore_tokens(parsed),
            "mode": str(result.specialist),
            "runtime_model_id": _safe_text((parsed or {}).get("runtime_model_id")),
            "runtime_first_reply_text_ms": runtime_first,
            "runtime_cycle_count": _count((parsed or {}).get("event_loop_cycle_count")),
            "runtime_prompt_cache_point": bool((parsed or {}).get("prompt_cache_enabled")),
        },
        None,
    )


def _safe_text(value: Any) -> str | None:
    return str(value)[:120] if isinstance(value, str) and value else None


def _agentcore_tokens(parsed: Mapping[str, Any] | None) -> dict[str, Any]:
    data = parsed or {}
    return _tokens(
        data.get("model_input_tokens"),
        data.get("model_output_tokens"),
        data.get("cache_read_input_tokens"),
        data.get("cache_write_input_tokens"),
    )


class _TimedConverse:
    """Client facade for ``LiveFastChatBridge``: times the call, optionally streams.

    ``converse`` returns a normal Converse response dict either way, so the
    bridge's parser and failure details are reused unchanged.
    """

    def __init__(self, client: Any, *, stream: bool, clock: Callable[[], float]) -> None:
        self._client = client
        self._stream = stream
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.started = 0.0
        self.returned: float | None = None
        self.first_text: float | None = None
        self.usage: Mapping[str, Any] | None = None

    def converse(self, **kwargs: Any) -> Any:
        self.reset()
        self.started = self._clock()
        if not self._stream:
            response = self._client.converse(**kwargs)
            self.returned = self._clock()
            usage = response.get("usage") if isinstance(response, Mapping) else None
            self.usage = usage if isinstance(usage, Mapping) else None
            return response
        response = self._read_stream(self._client.converse_stream(**kwargs))
        self.returned = self._clock()
        return response

    def _read_stream(self, stream_response: Any) -> dict[str, Any]:
        """Assemble ConverseStream events into a Converse-shaped response."""
        from backend.coaching.reply_text import ReplyTextExtractor

        extractor = ReplyTextExtractor()
        name = ""
        parts: list[str] = []
        stop_reason: Any = None
        for event in (stream_response or {}).get("stream") or ():
            if not isinstance(event, Mapping):
                continue
            start = (event.get("contentBlockStart") or {}).get("start")
            tool_start = start.get("toolUse") if isinstance(start, Mapping) else None
            if isinstance(tool_start, Mapping):
                name = str(tool_start.get("name") or name)
            delta = (event.get("contentBlockDelta") or {}).get("delta")
            tool_delta = delta.get("toolUse") if isinstance(delta, Mapping) else None
            if isinstance(tool_delta, Mapping) and "input" in tool_delta:
                fragment = str(tool_delta.get("input") or "")
                parts.append(fragment)
                if self.first_text is None and extractor.feed(fragment):
                    self.first_text = self._clock()
            stop = event.get("messageStop")
            if isinstance(stop, Mapping):
                stop_reason = stop.get("stopReason")
            usage = (event.get("metadata") or {}).get("usage")
            if isinstance(usage, Mapping):
                self.usage = usage
        content: list[dict[str, Any]] = []
        if parts:
            try:
                tool_input = json.loads("".join(parts))
            except ValueError:
                tool_input = None
            content.append({"toolUse": {"name": name, "input": tool_input}})
        return {
            "output": {"message": {"role": "assistant", "content": content}},
            "stopReason": stop_reason,
            "usage": dict(self.usage or {}),
        }


def make_converse_bridge(client: Any, model_id: str, *, stream: bool, clock: Callable[[], float]) -> Any:
    """Return ``(bridge, timed)``: the Converse arm over one budgeted client."""
    from agentcore_runtime.structured_coach import agent_system_prompt

    timed = _TimedConverse(client, stream=stream, clock=clock)

    class _Bridge(retrieval.LiveFastChatBridge):
        def request_kwargs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
            kwargs = super().request_kwargs(payload)
            # Same cache-point rule as the runtime (env FAST_CHAT_PROMPT_CACHE_ENABLED).
            system = agent_system_prompt(payload)
            kwargs["system"] = [{"text": system}] if isinstance(system, str) else list(system)
            return kwargs

    return _Bridge(timed, model_id), timed


def run_converse_call(
    bridge: Any,
    timed: _TimedConverse,
    request: Any,
    payload: Mapping[str, Any],
    clock: Callable[[], float],
) -> tuple[dict[str, Any], BaseException | None]:
    """One Converse call, timed, parsed and validated like production."""
    from backend.agentcore_provider import _validated_fast_chat
    started = clock()
    cache_point = any(
        isinstance(block, Mapping) and "cachePoint" in block
        for block in bridge.request_kwargs(payload)["system"]
    )
    timed.reset()
    try:
        wire = bridge.invoke(payload)
        total = timed.returned if timed.returned is not None else clock()
        result = _validated_fast_chat(wire, request)
    except retrieval.LiveCallLimitExceeded:
        raise
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed
        row = _failed(error, started, clock)
        row["tokens"] = _converse_tokens(timed.usage)
        row["stop_reason"] = bridge.last_stop_reason
        row["prompt_cache_point"] = cache_point
        return row, error
    first = timed.first_text if timed.first_text is not None else total
    return (
        {
            "status": "ok",
            "total_ms": _ms(total - timed.started),
            "first_text_ms": _ms(first - timed.started),
            "first_text_basis": (
                "first response_text fragment" if timed.first_text is not None else "total (not streamed)"
            ),
            "tokens": _converse_tokens(timed.usage),
            "mode": str(result.specialist),
            "stop_reason": bridge.last_stop_reason,
            "prompt_cache_point": cache_point,
        },
        None,
    )


def _converse_tokens(usage: Mapping[str, Any] | None) -> dict[str, Any]:
    data = usage or {}
    return _tokens(
        data.get("inputTokens"),
        data.get("outputTokens"),
        data.get("cacheReadInputTokens"),
        data.get("cacheWriteInputTokens"),
    )


# ---------------------------------------------------------------------------
# Run and summarize
# ---------------------------------------------------------------------------


def _percentile(sorted_values: Sequence[int], q: float) -> int:
    """Nearest-rank percentile of a non-empty sorted list."""
    rank = max(1, int(-(-q * len(sorted_values) // 1)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _latency_block(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": round(statistics.fmean(ordered), 1),
        "median": int(statistics.median(ordered)),
        "p90": _percentile(ordered, 0.90),
        "max": ordered[-1],
    }


def summarize_arm(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Latency, tokens, failures and estimated cost for one path's calls."""
    ok = [r for r in rows if r["status"] == "ok"]
    reported = [r for r in rows if r["tokens"]["reported"]]
    totals = {
        key: sum(int(r["tokens"].get(key) or 0) for r in reported)
        for key in ("input", "output", "cache_read", "cache_write")
    }
    costs = [c for c in (estimate_cost_usd(r["tokens"]) for r in rows) if c is not None]
    return {
        "calls": len(rows),
        "ok": len(ok),
        "parse_failures": sum(1 for r in rows if r.get("failure_kind") == "parse_failure"),
        "call_failures": sum(1 for r in rows if r.get("failure_kind") == "call_failure"),
        "first_text_ms": _latency_block([r["first_text_ms"] for r in ok]),
        "total_ms": _latency_block([r["total_ms"] for r in ok]),
        "tokens": {"rows_with_usage": len(reported), **totals},
        "estimated_cost_usd": {
            "estimate": True,
            "rows_priced": len(costs),
            "total": round(sum(costs), 6),
            "per_priced_call": round(sum(costs) / len(costs), 6) if costs else None,
            "scope": "model tokens only; excludes AgentCore Runtime compute and guardrail",
        },
        "prompt_cache_point_rows": sum(
            1 for r in rows if r.get("prompt_cache_point") or r.get("runtime_prompt_cache_point")
        ),
    }


def summarize_pairs(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare the paths on turns where both calls succeeded."""
    both = [r for r in rows if all(r.get(a, {}).get("status") == "ok" for a in ARMS)]
    deltas = [r["agentcore"]["total_ms"] - r["converse"]["total_ms"] for r in both]
    return {
        "pairs_both_ok": len(both),
        "median_total_ms_delta_agentcore_minus_converse": int(statistics.median(deltas)) if deltas else None,
        "agentcore_slower_turns": sum(1 for d in deltas if d > 0),
        "same_mode_turns": sum(1 for r in both if r["agentcore"]["mode"] == r["converse"]["mode"]),
    }


def run_benchmark(
    turns: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    runtime_client: Any,
    converse_client: Any,
    budget: CallBudget,
    model_id: str,
    region: str,
    runtime_arn: str,
    qualifier: str,
    converse_stream: bool = False,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Send ``limit // 2`` of the fixed turns through both paths.

    Stops after the first auth or access error in either path and never retries.
    The clients must draw from ``budget`` (``BudgetedClient``).
    """
    provider = retrieval._live_eval_provider()
    bridge, timed = make_converse_bridge(converse_client, model_id, stream=converse_stream, clock=clock)
    chosen = turns_for_limit(turns, limit)
    rows: list[dict[str, Any]] = []
    first_failure: dict[str, Any] | None = None
    stopped_on: dict[str, Any] | None = None
    stop = False
    for position, row in enumerate(chosen):
        entry: dict[str, Any] = {
            "id": row["id"],
            "category": row["category"],
            "order": list(ARMS if position % 2 == 0 else reversed(ARMS)),
        }
        rows.append(entry)
        try:
            request, payload = _build_turn(provider, row)
        except Exception as error:  # noqa: BLE001 - recorded, no call was made
            entry["build_error"] = retrieval.exception_label(error)
            first_failure = first_failure or {"id": row["id"], "arm": "build", "error": entry["build_error"]}
            continue
        for arm in entry["order"]:
            try:
                if arm == "agentcore":
                    outcome, error = run_agentcore_call(
                        runtime_client, runtime_arn, qualifier, request, payload, clock
                    )
                else:
                    outcome, error = run_converse_call(bridge, timed, request, payload, clock)
            except retrieval.LiveCallLimitExceeded:
                stop = True
                break
            entry[arm] = outcome
            if error is None:
                continue
            failure = {"id": row["id"], "arm": arm, "error": outcome["error"]}
            first_failure = first_failure or failure
            if is_stop_error(error):
                stopped_on = failure
                stop = True
                break
        if stop:
            break
    per_arm = {arm: [r[arm] for r in rows if arm in r] for arm in ARMS}
    attempted = [r for r in rows if "build_error" not in r]
    result: dict[str, Any] = {
        "mode": "benchmark_agentcore_vs_converse",
        "definition": RUN_DEFINITION,
        "turn_set": {
            "source": "scripts/evals/datasets/retrieval_gate_messages.synthetic.jsonl",
            "synthetic": True,
            "rule": "evenly_spaced_indices(len(rows), 50) in file order, then turns_for_limit",
            "ids_sha256": TURN_IDS_SHA256,
            "turns_in_set": len(turns),
            "turns_selected_by_cap": len(chosen),
            "turns_attempted": len(attempted),
        },
        "paths": {
            "agentcore": {
                "api": "bedrock-agentcore InvokeAgentRuntime",
                "runtime_arn": runtime_arn,
                "qualifier": qualifier,
            },
            "converse": {
                "api": "bedrock-runtime ConverseStream" if converse_stream else "bedrock-runtime Converse",
                "model_id": model_id,
                "region": region,
            },
        },
        "calls": {
            "limit": limit,
            "made": budget.made,
            "agentcore": budget.by_path["agentcore"],
            "converse": budget.by_path["converse"],
            "calls_per_turn": CALLS_PER_TURN,
        },
        "prices_usd_per_mtok": {**PRICE_USD_PER_MTOK, "estimate": True},
        "first_failure": first_failure,
        "stopped_early_on_auth_or_access_error": stopped_on,
        "arms": {arm: summarize_arm(per_arm[arm]) for arm in ARMS},
        "pairs": summarize_pairs(rows),
        "runtime_model_ids_seen": sorted(
            {r["agentcore"]["runtime_model_id"] for r in rows if r.get("agentcore", {}).get("runtime_model_id")}
        ),
        "rows": rows,
    }
    result["exit_code"] = exit_code(result)
    return result


def _build_turn(provider: Any, row: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Build the request and the runtime payload for one turn (no network)."""
    from backend.agentcore_provider import _FAST_CHAT_CONTRACT, _FAST_CHAT_PHASE
    from backend.context_planner import CONTEXT_POLICY_FAST_CHAT

    decision = retrieval.gate_decision(row)
    request = retrieval.build_live_request(row, decision, source_check=False)
    payload, _plan = provider._invoke_payload(
        request,
        _FAST_CHAT_PHASE,
        context_policy=CONTEXT_POLICY_FAST_CHAT,
        phase=_FAST_CHAT_PHASE,
        output_contract=_FAST_CHAT_CONTRACT,
    )
    return request, payload


def exit_code(result: Mapping[str, Any]) -> int:
    """0 = ran; 1 = every call failed; 3 = stopped early on an auth/access error."""
    if sum(int(result["arms"][a]["ok"]) for a in ARMS) == 0:
        return 1
    if result.get("stopped_early_on_auth_or_access_error"):
        return 3
    return 0


# ---------------------------------------------------------------------------
# Report and CLI
# ---------------------------------------------------------------------------


def format_report(result: Mapping[str, Any]) -> str:
    """Render the result as plain text."""
    calls = result["calls"]
    lines = [
        "AgentCore vs direct Bedrock Converse benchmark",
        f"calls: {calls['made']} of limit {calls['limit']} "
        f"(agentcore {calls['agentcore']}, converse {calls['converse']}); "
        f"turns attempted {result['turn_set']['turns_attempted']} of {result['turn_set']['turns_selected_by_cap']}",
    ]
    for arm in ARMS:
        a = result["arms"][arm]
        cost = a["estimated_cost_usd"]
        lines.append(
            f"{arm}: ok {a['ok']}/{a['calls']}, parse failures {a['parse_failures']}, "
            f"call failures {a['call_failures']}; first text median {a['first_text_ms'].get('median')} ms, "
            f"total median {a['total_ms'].get('median')} ms (p90 {a['total_ms'].get('p90')}); "
            f"tokens in {a['tokens']['input']} out {a['tokens']['output']} "
            f"cache read {a['tokens']['cache_read']} write {a['tokens']['cache_write']} "
            f"({a['tokens']['rows_with_usage']} rows reported); "
            f"estimated cost ${cost['total']:.4f} (estimate)"
        )
    pairs = result["pairs"]
    lines.append(
        f"pairs both ok: {pairs['pairs_both_ok']}; median total delta (agentcore - converse): "
        f"{pairs['median_total_ms_delta_agentcore_minus_converse']} ms; "
        f"agentcore slower on {pairs['agentcore_slower_turns']}; same mode on {pairs['same_mode_turns']}"
    )
    lines.append(f"exit code: {result['exit_code']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark AgentCore InvokeAgentRuntime against direct Bedrock Converse "
        "on the same 50 fixed turns. Live and paid: needs --live-benchmark and --max-live-calls.",
    )
    parser.add_argument("--live-benchmark", action="store_true", help="Opt in to paid live calls.")
    parser.add_argument(
        "--max-live-calls",
        type=int,
        default=None,
        help=f"Required. Total calls to both paths (1 to {HARD_CALL_CAP}); a turn costs 2.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; build no client, make no call.")
    parser.add_argument(
        "--converse-stream",
        action="store_true",
        help="Use ConverseStream so first_text_ms is measured (needs bedrock:InvokeModelWithResponseStream).",
    )
    parser.add_argument("--json-output", type=Path, default=None, help="Write the result (with a run block).")
    return parser


def _settings_for_run() -> tuple[str, str, str, str, str, str]:
    from backend.settings import settings

    provider, model_id, region = retrieval.live_model_settings()
    return (
        provider,
        model_id,
        region,
        str(settings.resolved_agentcore_runtime_arn or ""),
        str(settings.aws_region or ""),
        str(settings.agentcore_qualifier or "DEFAULT"),
    )


def load_turns() -> list[Mapping[str, Any]]:
    """Load the validated gate messages and select the pinned 50 turns."""
    materials = retrieval.load_materials()
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(retrieval.MESSAGES_PATH, materials, [q["id"] for q in questions])
    return select_benchmark_turns(messages)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.dry_run:
            limit = check_call_limit(args.max_live_calls)
            turns = load_turns()
            chosen = turns_for_limit(turns, limit)
            print(
                f"dry run: {len(chosen)} of {len(turns)} turns, {len(chosen) * CALLS_PER_TURN} calls "
                f"(limit {limit}); no client built, no call made\n" + " ".join(str(t["id"]) for t in chosen)
            )
            return 0
        provider, model_id, region, arn, runtime_region, qualifier = _settings_for_run()
        limit = check_benchmark_request(
            args.live_benchmark,
            args.max_live_calls,
            provider=provider,
            model_id=model_id,
            region=region,
            runtime_arn=arn,
            runtime_region=runtime_region,
        )
        turns = load_turns()
    except retrieval.LiveRunRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    budget = CallBudget(limit)
    runtime_client, converse_client = build_clients(region, runtime_region, budget)
    result = run_benchmark(
        turns,
        limit,
        runtime_client=runtime_client,
        converse_client=converse_client,
        budget=budget,
        model_id=model_id,
        region=region,
        runtime_arn=arn,
        qualifier=qualifier,
        converse_stream=args.converse_stream,
    )
    print(format_report(result))
    if result["first_failure"]:
        print(f"first failure class: {result['first_failure']['error']} ({result['first_failure']['arm']})", file=sys.stderr)
    if args.json_output:
        retrieval._write_json_output(args.json_output, result)
    code = int(result["exit_code"])
    if code == 1:
        print("every call failed", file=sys.stderr)
    elif code == 3:
        print("stopped early on an auth or access error", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
