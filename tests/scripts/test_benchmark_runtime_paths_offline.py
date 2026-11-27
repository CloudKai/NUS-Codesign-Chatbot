"""Offline runtime-path comparison harness: contracts, no AWS, no live model.

Three existing paths are driven through the real adapter contracts with
injected fakes only: the deterministic mock provider, the canonical AgentCore
adapter and the direct Bedrock Converse adapter. Every fake is local; boto3
never builds a client and no network is touched.
"""

from __future__ import annotations

import json

from scripts.evals import benchmark_runtime_paths_offline as bench


def test_configured_paths_are_documented_without_secrets() -> None:
    report = bench.build_report(sample=2)
    configured = report["configured_paths"]
    assert configured["model_provider_default"] == "mock"
    for role in ("coaching", "qa", "router", "review_deep"):
        entry = configured["models"][role]
        assert "provider" in entry and "model_id" in entry
    assert configured["source"] == "backend.settings (this process environment)"
    assert isinstance(configured["agentcore_runtime_arn_configured"], bool)
    # No ARN value anywhere in the documented configuration.
    assert configured["agentcore_runtime_arn_configured"] in (True, False)
    dumped = json.dumps(configured).lower()
    assert "arn:aws" not in dumped


def test_all_three_arms_complete_representative_turns_offline() -> None:
    report = bench.build_report(sample=2)
    arms = {row["arm"]: row for row in report["arms"]}
    assert set(arms) == set(bench.ARMS)
    for name, row in arms.items():
        assert row["turns_attempted"] == 2
        assert row["structured_first_attempt_success"] == 2
        assert row["latency_ms"]["max"] > 0
        # Simulated latency is a documented input, never a measurement claim.
        assert row["latency_note"].startswith("SIMULATED-INPUT")
        assert report["path_characteristics"][name]["adapter"] == (
            bench.ADAPTER_CONTRACTS[name]["adapter"]
        )


def test_agentcore_and_bedrock_arms_meter_usage_through_production_paths() -> None:
    report = bench.build_report(sample=2)
    arms = {row["arm"]: row for row in report["arms"]}
    agentcore = arms["agentcore"]["usage"]
    bedrock = arms["bedrock_direct"]["usage"]
    assert agentcore["input_tokens_total"] > 0
    assert agentcore["source"] == "co_design.usage generation_usage events"
    assert bedrock["input_tokens_total"] > 0
    # The mock provider legitimately leaves model usage unknown.
    assert arms["mock"]["usage"]["input_tokens_total"] is None


def test_error_accounting_is_safe_and_fakes_are_called_once_per_attempt() -> None:
    report = bench.build_report(sample=2)
    faults = report["error_accounting"]
    for arm in ("agentcore", "bedrock_direct"):
        throttled = faults[arm]["ThrottlingException"]
        assert throttled["category"] == "throttled"
        assert throttled["fake_calls"] == 1  # SDK owns retries; fakes bypass them
        malformed = faults[arm]["malformed_reply"]
        assert malformed["category"] in {"malformed", "structured_output_failure"}
        assert faults[arm]["AccessDeniedException"]["category"] == "access_denied"


def test_path_characteristics_record_inequivalent_parts_honestly() -> None:
    report = bench.build_report(sample=2)
    characteristics = report["path_characteristics"]
    agentcore = characteristics["agentcore"]
    assert agentcore["output_contract"] == "FastChatTurnOutput"
    assert agentcore["bedrock_guardrail"] == "runtime-side, not exercised offline"
    bedrock = characteristics["bedrock_direct"]
    assert bedrock["output_contract"] == "ProviderCoachOutput (legacy coaching contract)"
    assert bedrock["bedrock_guardrail"] == "none"
    assert characteristics["mock"]["deterministic"] is True


def test_recommendation_keeps_agentcore_canonical_and_records_live_requirements() -> None:
    report = bench.build_report(sample=2)
    recommendation = report["recommendation"]
    assert recommendation["runtime_default_change"] is False
    assert "agentcore_runtime stays canonical" in recommendation["summary"]
    live = report["live_comparison_plan"]
    assert live["executed_here"] is False
    for required in (
        "call_cap",
        "guardrail_equivalence",
        "same_turns_both_arms",
        "pricing_dated",
    ):
        assert required in json.dumps(live)


def test_cli_refuses_live_and_writes_json(tmp_path) -> None:
    assert bench.main(["--i-approve-live-aws"]) == 2
    output = tmp_path / "report.json"
    assert bench.main(["--sample", "1", "--json-output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["generated_at_utc"].endswith("Z")
    assert payload["measurement_kind"] == "offline-simulation"


def test_no_aws_client_is_built(monkeypatch) -> None:
    def _fail(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("boto3 client built during offline benchmark")

    monkeypatch.setattr("boto3.client", _fail, raising=False)
    monkeypatch.setattr("boto3.Session", _fail, raising=False)
    bench.build_report(sample=1)
