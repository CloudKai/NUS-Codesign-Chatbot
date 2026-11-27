"""Offline prompt-variant and prompt-cache benchmark: report contracts.

Stub-free and network-free: the harness composes real prompt files and
estimator token counts only. No AWS client is ever built and no live model
is called.
"""

from __future__ import annotations

import json


from scripts.evals import benchmark_prompt_variants as bench


def test_report_measures_existing_and_compacted_variants_per_stage() -> None:
    report = bench.build_report(sample=3)
    topics = {row["topic"] for row in report["variants"]}
    assert topics == set(bench.STAGE_TOPICS)
    for row in report["variants"]:
        assert row["existing_chars"] > 0
        assert row["existing_est_tokens"] > 0
        assert row["compacted_chars"] > 0
        assert row["compacted_est_tokens"] > 0
        assert row["compacted_est_tokens"] <= row["existing_est_tokens"]
        # Compaction must not drop required pedagogy, evidence, schema, stage
        # or security markers from any stage variant.
        assert row["missing_markers"] == []


def test_compaction_only_removes_duplicates_and_whitespace_keeps_content() -> None:
    text = "Rule A.\n\nRule  A.\n\nRule B.\n\nRule A.\n\nRule B.\n\n\n\nRule C."
    compacted = bench.compact_prompt_text(text)
    assert compacted == "Rule A.\nRule B.\nRule C."
    # The compacted prefix of a real stage keeps its content, not a copy.
    prefix = bench.compact_prompt_text(bench.fast_chat_prefix("problem_identification"))
    assert "Socratic" in prefix


def test_representative_turns_are_measured_offline() -> None:
    report = bench.build_report(sample=3)
    turns = report["representative_turns"]
    assert turns["sample_size"] == 3
    assert turns["est_tokens"]["agentcore_system_prompt"]["max"] > 0
    assert turns["source"] == "retrieval_gate_messages.synthetic.jsonl"


def test_workspace_context_costs_scale_with_selected_context() -> None:
    report = bench.build_report(sample=3)
    costs = report["workspace_context_costs"]
    by_name = {row["scenario"]: row["total_est_tokens"] for row in costs}
    assert by_name["no_workspace_context"] == min(by_name.values())
    assert by_name["all_contexts_at_cap"] == max(by_name.values())
    assert by_name["retrieved_excerpts_at_cap"] > by_name["retrieved_excerpts_2k"] > 0
    assert len(costs) >= 3


def test_cache_eligibility_and_off_on_shapes_are_recorded() -> None:
    report = bench.build_report(sample=3)
    cache = report["prompt_cache"]
    assert {row["topic"] for row in cache["candidates"]} == set(bench.STAGE_TOPICS)
    for row in cache["candidates"]:
        assert row["existing_prefix_est_tokens"] > 0
        assert row["eligible"] is (
            row["existing_prefix_est_tokens"] >= bench.HAIKU_MIN_CACHE_TOKENS
        )
        assert "compacted_prefix_est_tokens" in row
    # Only prefixes above the 4,096-token Haiku floor get a cache point; record
    # which measured stages actually qualify today.
    eligible = {row["topic"] for row in cache["candidates"] if row["eligible"]}
    assert eligible == set(bench.cache_eligible_topics())
    # Cache-off stays string-identical; cache-on inserts one cachePoint and the
    # blocks concatenate back to the exact uncached string, per topic.
    shapes = cache["shape_checks"]
    assert shapes["cache_off_matches_uncached_string"] is True
    assert shapes["cache_on_single_cache_point"] is True
    assert shapes["blocks_concatenate_to_uncached_string"] is True


def test_cache_economics_use_documented_estimate_pricing() -> None:
    report = bench.build_report(sample=3)
    economics = report["prompt_cache"]["economics"]
    assert economics["pricing_note"].startswith("ESTIMATE")
    assert economics["cache_ttl_minutes"] == 5
    row = economics["per_turn_usd"]
    assert row["without_cache"] > 0
    assert row["with_cache_turn_1"] > row["without_cache"]  # write premium
    assert row["with_cache_read_hit"] < row["without_cache"]
    assert economics["break_even_turns_within_ttl"] >= 2
    # Economics price only an eligible prefix; the ineligible stages are
    # listed explicitly rather than silently priced.
    assert set(economics["ineligible_topics_priced"]) == set(
        bench.STAGE_TOPICS
    ) - set(bench.cache_eligible_topics())


def test_recommendation_is_recorded_with_numbers_and_live_plan() -> None:
    report = bench.build_report(sample=3)
    recommendation = report["recommendation"]
    assert isinstance(recommendation["adopt_prompt_compaction_now"], bool)
    assert "est_tokens" in json.dumps(recommendation)
    live = report["live_evaluation_plan"]
    assert live["executed_here"] is False
    assert "request_cap" in live and "approval" in live["approval_gate"]


def test_cli_refuses_live_and_writes_json(tmp_path) -> None:
    assert bench.main(["--i-approve-live-aws"]) == 2
    output = tmp_path / "report.json"
    assert bench.main(["--sample", "2", "--json-output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["generated_at_utc"].endswith("Z")
    assert payload["measurement_kind"] == "offline-simulation"


def test_no_aws_client_is_built(monkeypatch) -> None:
    def _fail(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("boto3 client built during offline benchmark")

    monkeypatch.setattr("boto3.client", _fail, raising=False)
    monkeypatch.setattr("boto3.Session", _fail, raising=False)
    bench.build_report(sample=2)


def test_required_markers_exist_in_the_current_prompts() -> None:
    text = "\n".join(bench.prompt_source_texts().values())
    missing = [marker for marker in bench.REQUIRED_MARKERS if marker not in text]
    assert missing == []
