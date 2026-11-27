"""Offline comparison of the existing model/runtime paths — no AWS, no live model.

Drives the three existing provider paths through their real adapter contracts
with injected fakes only:

* ``mock`` — the deterministic local provider behind ``MODEL_PROVIDER=mock``.
* ``agentcore`` — the canonical production adapter
  (``backend.agentcore_provider.AgentCoreCoachProvider``) with an injected
  fake ``bedrock-agentcore`` client returning a valid Fast Chat wire payload.
* ``bedrock_direct`` — the direct Bedrock Converse adapter
  (``backend.bedrock_provider.BedrockCoachProvider``) with an injected fake
  ``bedrock-runtime`` client returning a valid legacy ``ProviderCoachOutput``
  tool-use envelope.

The same representative synthetic turns go through every arm. The harness
records latency (adapter+harness timings; any fake sleep is a documented
input), token accounting read from the production ``co_design.usage``
``generation_usage`` events, structured-output first-attempt success, error
accounting through the production ``provider_error_category``, and the
honestly inequivalent parts of each path. It never publishes a runtime
default: ``agentcore_runtime`` stays canonical and the fair live comparison
requirements are recorded as an unexecuted plan. The paid-live tool for that
comparison already exists built and never run
(``scripts/evals/benchmark_agentcore_vs_converse.py``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.domain import (  # noqa: E402
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    ProviderCoachOutput,
    StageDecision,
)
from backend.mock_provider import DeterministicCoachProvider  # noqa: E402
from backend.providers import provider_error_category  # noqa: E402
from scripts.evals.lib.metrics import evenly_spaced_indices  # noqa: E402
from scripts.evals.lib.output import write_json_output  # noqa: E402
from scripts.evals.lib.paths import MESSAGES_PATH  # noqa: E402

ARMS = ("mock", "agentcore", "bedrock_direct")
_USAGE_LOGGER = "co_design.usage"


class _FakeClientError(Exception):
    """Stand-in for botocore ClientError that never imports AWS SDKs."""

    def __init__(self, code: str) -> None:
        super().__init__("offline fake aws error")
        self.response = {"Error": {"Code": code, "Message": "offline fake"}}


class _Body:
    """Minimal bytes stand-in for a fake non-streaming response body."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


_FAST_CHAT_TOOL_INPUT: dict[str, Any] = {
    "mode": "coaching",
    "response_text": "What trade-off in your concept still needs evidence?",
    "citations": [],
    "recommendation": "stay",
    "hmw_scaffold_ready": False,
    "needs_source_retrieval": False,
    "needs_sources": False,
    "out_of_scope": False,
}


def _legacy_output_envelope() -> dict[str, Any]:
    """Return one valid legacy ``ProviderCoachOutput`` envelope."""
    return ProviderCoachOutput(
        response_text="What trade-off still needs evidence?",
        assessment=EducationalAssessment(
            current_stage="problem_identification",
            contribution_summary="The student compared two design constraints.",
            stage_assessment="The contribution is usable but can be developed further.",
            critical_understanding_level="Developing",
            confidence=0.7,
            recommendation=StageDecision.STAY,
            recommendation_rationale="One important element remains to be examined.",
            guidance_questions=["What should you examine next?"],
            learning_summary="The student is developing the design reasoning.",
            citations=[],
            facione_scores=FacioneDimensionScores(analysis=2, evaluation=2),
        ),
        research_coding=None,
    ).model_dump(mode="json")


class _UsageCapture(logging.Handler):
    """Collect ``generation_usage`` events from the production usage logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if isinstance(payload, Mapping) and payload.get("event") == "generation_usage":
            self.events.append(dict(payload))


class _FakeAgentcoreClient:
    """Injected ``bedrock-agentcore`` client returning one fixed fast-chat body."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        malformed: bool = False,
        delay_seconds: float = 0.0,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error
        self._malformed = malformed
        self._delay_seconds = float(delay_seconds)
        self._usage = usage or {
            "model_input_tokens": 7_000,
            "model_output_tokens": 300,
            "cache_read_input_tokens": 0,
            "cache_write_input_tokens": 0,
        }

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        if self._error is not None:
            raise self._error
        from agentcore_runtime.models import parse_fast_chat_turn_output
        from agentcore_runtime.structured_coach import structured_wire_payload

        wire = structured_wire_payload(parse_fast_chat_turn_output(_FAST_CHAT_TOOL_INPUT))
        wire.update(
            self._usage
            | {
                "runtime_model_id": "offline-fake-model",
                "model_first_reply_text_ms": 210,
                "prompt_cache_enabled": False,
            }
        )
        raw = json.dumps({"result": "not json"} if self._malformed else wire).encode(
            "utf-8"
        )
        return {"contentType": "application/json", "response": _Body(raw)}


class _FakeBedrockClient:
    """Injected ``bedrock-runtime`` client returning one fixed tool-use body."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        malformed: bool = False,
        delay_seconds: float = 0.0,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error
        self._malformed = malformed
        self._delay_seconds = float(delay_seconds)
        self._usage = usage or {"inputTokens": 7_000, "outputTokens": 300}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        if self._error is not None:
            raise self._error
        if self._malformed:
            return {
                "stopReason": "end_turn",
                "output": {"message": {"role": "assistant", "content": [{"text": "no tool call"}]}},
                "usage": dict(self._usage),
            }
        envelope = _legacy_output_envelope()
        return {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "offline-fake",
                                "name": "coach_turn",
                                "input": envelope,
                            }
                        }
                    ],
                }
            },
            "usage": dict(self._usage),
            "ResponseMetadata": {"RetryAttempts": 0},
        }


def configured_paths() -> dict[str, Any]:
    """Document the configured models and runtime for this process environment."""
    from backend.settings import settings

    return {
        "model_provider_default": settings.model_provider,
        "models": {
            "coaching": {
                "provider": settings.coaching_model_provider,
                "model_id": settings.coaching_model_id,
            },
            "qa": {
                "provider": settings.qa_model_provider,
                "model_id": settings.qa_model_id,
            },
            "router": {
                "provider": settings.router_model_provider,
                "model_id": settings.router_model_id,
            },
            "review_deep": {
                "provider": settings.review_deep_model_provider,
                "model_id": settings.review_deep_model_id,
            },
        },
        "source": "backend.settings (this process environment)",
        "agentcore_runtime_arn_configured": bool(
            str(settings.agentcore_runtime_arn or "").strip()
        ),
        "agentcore_runtime_pinned_model_ids": _runtime_pinned_model_ids(),
        "note": (
            "Model IDs above are this environment's settings; the AgentCore "
            "runtime pins Fast Chat and Deep Review models in code "
            "(agentcore_runtime.model), recorded here as the runtime contract. "
            "No secret or ARN value is recorded."
        ),
    }


def _runtime_pinned_model_ids() -> dict[str, str]:
    from agentcore_runtime.model import HAIKU_4_5_MODEL_ID, SONNET_4_6_MODEL_ID

    return {"fast_chat": HAIKU_4_5_MODEL_ID, "deep_review": SONNET_4_6_MODEL_ID}


def _representative_requests(sample: int) -> list[CoachRequest]:
    rows = [json.loads(line) for line in MESSAGES_PATH.read_text().splitlines() if line]
    requests: list[CoachRequest] = []
    for index in evenly_spaced_indices(len(rows), sample):
        row = rows[index]
        requests.append(
            CoachRequest(
                thread_id=f"bench-paths-{row['id']}",
                student_message=row["message"],
                current_stage=row["stage"],
                response_detail="short",
            )
        )
    return requests


def _percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return round(ordered[(percent * len(ordered) - 1) // 100], 3)


def _run_arm(
    arm: str,
    requests: Sequence[CoachRequest],
    *,
    delay_seconds: float,
) -> dict[str, Any]:
    """Run the representative turns through one arm and record the outcomes."""
    capture = _UsageCapture()
    logger = logging.getLogger(_USAGE_LOGGER)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(capture)
    try:
        latencies: list[float] = []
        successes = 0
        failures: list[str] = []
        for request in requests:
            provider = _provider_for(arm, delay_seconds=delay_seconds)
            started = time.perf_counter()
            try:
                provider.assess(request)
                successes += 1
            except Exception as error:  # noqa: BLE001 - harness records the class
                failures.append(type(error).__name__)
            latencies.append((time.perf_counter() - started) * 1_000.0)
        usage_events = [
            event for event in capture.events if event.get("provider") == _arm_provider(arm)
        ]
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
    input_events = [
        int(event["input_tokens"])
        for event in usage_events
        if isinstance(event.get("input_tokens"), int)
    ]
    output_events = [
        int(event["output_tokens"])
        for event in usage_events
        if isinstance(event.get("output_tokens"), int)
    ]
    return {
        "arm": arm,
        "turns_attempted": len(requests),
        "structured_first_attempt_success": successes,
        "failures_by_exception_class": sorted(set(failures)),
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "latency_note": (
            "SIMULATED-INPUT: fake clients sleep "
            f"{round(delay_seconds * 1_000, 1)} ms before responding; these are "
            "adapter+harness timings, never model latency"
        ),
        "usage": {
            "source": "co_design.usage generation_usage events",
            "events": len(usage_events),
            "input_tokens_total": sum(input_events) if input_events else None,
            "output_tokens_total": sum(output_events) if output_events else None,
        },
    }


def _arm_provider(arm: str) -> str:
    return {"mock": "mock", "agentcore": "agentcore", "bedrock_direct": "bedrock"}[arm]


def _provider_for(arm: str, *, delay_seconds: float = 0.0) -> Any:
    """Build one arm's provider with an injected fake where applicable."""
    if arm == "mock":
        return DeterministicCoachProvider()
    if arm == "agentcore":
        from backend.agentcore_provider import AgentCoreCoachProvider

        return AgentCoreCoachProvider(
            "arn:aws:bedrock-agentcore:us-west-2:000000000000:runtime/OfflineFake",
            region="us-west-2",
            qualifier="DEFAULT",
            timeout_seconds=110.0,
            max_retries=0,
            client=_FakeAgentcoreClient(delay_seconds=delay_seconds),
        )
    if arm == "bedrock_direct":
        from backend.bedrock_provider import BedrockCoachProvider

        return BedrockCoachProvider(
            "offline.fake.model",
            region="us-west-2",
            timeout_seconds=110.0,
            max_retries=0,
            client=_FakeBedrockClient(delay_seconds=delay_seconds),
        )
    raise ValueError(f"unknown arm: {arm}")


def _fault_outcome(arm: str, fake_factory: Callable[[], Any]) -> dict[str, Any]:
    """Run one request against a faulted fake and record the safe accounting."""
    provider = _provider_for(arm)
    if arm == "agentcore":
        provider._client = fake_factory()
    else:
        provider._client = fake_factory()
    request = _representative_requests(1)[0]
    try:
        provider.assess(request)
        return {"outcome": "succeeded", "category": "-", "fake_calls": -1}
    except Exception as error:  # noqa: BLE001 - recorded through production mapping
        fake = provider._client
        return {
            "outcome": "provider_unavailable",
            "category": provider_error_category(error),
            "fake_calls": len(getattr(fake, "calls", [])),
        }


def measure_error_accounting() -> dict[str, Any]:
    """Record throttling, access and malformed-reply accounting per path.

    SDK retries are botocore-owned, so injected fakes are called exactly once
    per attempt; offline runs cannot exercise the SDK retry loop and that
    limit is recorded rather than silently accepted.
    """
    faults: dict[str, Any] = {}
    for arm in ("agentcore", "bedrock_direct"):
        faults[arm] = {
            "ThrottlingException": _fault_outcome(arm, lambda: _fake_with(arm, error=_FakeClientError("ThrottlingException"))),
            "AccessDeniedException": _fault_outcome(arm, lambda: _fake_with(arm, error=_FakeClientError("AccessDeniedException"))),
            "malformed_reply": _fault_outcome(arm, lambda: _fake_with(arm, malformed=True)),
            "sdk_retries_offline": (
                "not exercisable with injected fakes: both adapters delegate "
                "retries to botocore (max_retries configures the SDK client); "
                "live-only evidence, see live_comparison_plan"
            ),
        }
    faults["mock"] = {
        "note": "the deterministic provider has no injected-failure seam; local failures are code bugs, not provider errors"
    }
    return faults


def _fake_with(arm: str, *, error: BaseException | None = None, malformed: bool = False) -> Any:
    if arm == "agentcore":
        return _FakeAgentcoreClient(error=error, malformed=malformed)
    return _FakeBedrockClient(error=error, malformed=malformed)


ADAPTER_CONTRACTS: dict[str, dict[str, str]] = {
    "mock": {
        "adapter": "backend.mock_provider.DeterministicCoachProvider (MODEL_PROVIDER=mock path)",
        "output_contract": "deterministic reply, no model call",
    },
    "agentcore": {
        "adapter": "backend.agentcore_provider.AgentCoreCoachProvider",
        "output_contract": "FastChatTurnOutput",
    },
    "bedrock_direct": {
        "adapter": "backend.bedrock_provider.BedrockCoachProvider",
        "output_contract": "ProviderCoachOutput (legacy coaching contract)",
    },
}


def path_characteristics() -> dict[str, Any]:
    """Record the honestly inequivalent parts of each path."""
    return {
        "mock": {
            "adapter": ADAPTER_CONTRACTS["mock"]["adapter"],
            "output_contract": ADAPTER_CONTRACTS["mock"]["output_contract"],
            "bedrock_guardrail": "not applicable",
            "strands_event_loop": False,
            "recovery_turn": False,
            "deterministic": True,
        },
        "agentcore": {
            "adapter": ADAPTER_CONTRACTS["agentcore"]["adapter"],
            "output_contract": ADAPTER_CONTRACTS["agentcore"]["output_contract"],
            "bedrock_guardrail": "runtime-side, not exercised offline",
            "strands_event_loop": True,
            "recovery_turn": "runtime-side, not exercised offline",
            "deterministic": False,
        },
        "bedrock_direct": {
            "adapter": ADAPTER_CONTRACTS["bedrock_direct"]["adapter"],
            "output_contract": ADAPTER_CONTRACTS["bedrock_direct"]["output_contract"],
            "bedrock_guardrail": "none",
            "strands_event_loop": False,
            "recovery_turn": False,
            "deterministic": False,
            "note": (
                "the direct adapter implements the legacy coaching contract, "
                "not the Fast Chat one-call contract, and has no Bedrock "
                "guardrail; recorded as a real difference, not ignored"
            ),
        },
    }


def build_report(sample: int = 10, delay_ms: float = 0.0) -> dict[str, Any]:
    """Build the full offline comparison report."""
    requests = _representative_requests(sample)
    delay_seconds = delay_ms / 1_000.0
    return {
        "measurement_kind": "offline-simulation",
        "ticket": 41,
        "scope": (
            "Offline comparison of the three existing provider paths with "
            "injected fakes over the same representative turns. No AWS client, "
            "no live model, no runtime default change."
        ),
        "configured_paths": configured_paths(),
        "arms": [
            _run_arm(arm, requests, delay_seconds=delay_seconds) for arm in ARMS
        ],
        "error_accounting": measure_error_accounting(),
        "path_characteristics": path_characteristics(),
        "live_comparison_plan": {
            "executed_here": False,
            "existing_live_tool": (
                "scripts/evals/benchmark_agentcore_vs_converse.py — built, "
                "paid-live-gated, never run; refuses without --live-benchmark "
                "and --max-live-calls"
            ),
            "call_cap": (
                "explicit --max-live-calls N (e.g. 100) with a per-call shared "
                "counter; never uncapped"
            ),
            "same_turns_both_arms": (
                "the same fixed representative turns (pinned id set) through "
                "both paths, order alternating by turn"
            ),
            "guardrail_equivalence": (
                "both arms must carry equivalent guardrails and citation "
                "validation; the direct Converse arm needs an explicit guardrail "
                "story before any comparison can be called fair"
            ),
            "other_equivalence_requirements": [
                "same composed instructions and session/history handling",
                "safe streaming and first-safe-visible-text boundaries",
                "bounded retries with recorded retry counts",
                "persistence and idempotency identical on both paths",
            ],
            "pricing_dated": (
                "cost per successful turn from reported usage and dated "
                "confirmed pricing; no estimate is treated as a measured cost"
            ),
            "approval_gate": (
                "live execution requires separate explicit approval with "
                "request/token or cost caps and concurrency limits"
            ),
        },
        "recommendation": {
            "runtime_default_change": False,
            "summary": (
                "agentcore_runtime stays canonical: the offline comparison "
                "exercises the adapter contracts and their honest differences "
                "but cannot rank live model quality, latency or cost; "
                "MODEL_PROVIDER stays as configured (mock locally) and no arm "
                "is promoted or removed on this evidence. A fair live "
                "comparison needs the recorded call caps, guardrail "
                "equivalence and dated pricing first."
            ),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=int, default=10, help="representative turns per arm")
    parser.add_argument(
        "--simulated-model-latency-ms",
        type=float,
        default=0.0,
        help="deterministic fake sleep applied to every arm (an input, not a measurement)",
    )
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--i-approve-live-aws",
        action="store_true",
        help="Refused. This script never calls AWS.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.i_approve_live_aws:
        print("this entry point never calls AWS", file=sys.stderr)
        return 2
    from scripts.evals.lib.offline import block_network

    block_network()
    report = build_report(sample=max(1, args.sample), delay_ms=max(0.0, args.simulated_model_latency_ms))
    if args.json_output is not None:
        write_json_output(args.json_output, report)
    arms = report["arms"]
    summary = ", ".join(
        f"{row['arm']}: {row['structured_first_attempt_success']}/{row['turns_attempted']} ok"
        for row in arms
    )
    print(f"offline runtime-path comparison ({summary}); agentcore_runtime stays canonical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
