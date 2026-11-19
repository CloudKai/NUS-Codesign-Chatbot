"""Retrieval eval script: metric maths, data-file validity, live-path refusal.

No network and no AWS: the live path is only checked for refusal, and the
call counter is exercised with a fake client.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Load the eval script without requiring a scripts package."""
    path = _ROOT / "scripts" / "evals" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("co_design_evaluate_retrieval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


_EVAL = _load()
Hit = _EVAL.RankedHit


def _score(hits, *, material="m1", pages=(5,), alt=(), page_aware=True, k=4):
    return _EVAL.score_question(
        "rq001",
        hits,
        expected_material=material,
        expected_pages=list(pages),
        alt_expected=list(alt),
        k=k,
        page_aware=page_aware,
    )


# ---- metric maths ---------------------------------------------------------


def test_hit_inside_top_four_counts_and_fifth_does_not() -> None:
    other = [Hit("x", 1, 9.0 - i, 0, i) for i in range(4)]
    inside = _score([*other[:3], Hit("m1", 5, 1.0, 1, 5)])
    outside = _score([*other, Hit("m1", 5, 0.5, 1, 5)])
    assert inside.material_hit and inside.first_material_rank == 4
    assert not outside.material_hit and outside.first_material_rank is None


def test_multi_page_tag_needs_only_one_page() -> None:
    outcome = _score([Hit("m1", 7, 2.0)], pages=(5, 7, 9))
    assert outcome.page_hit is True


def test_right_material_wrong_page_is_material_hit_but_page_miss() -> None:
    outcome = _score([Hit("m1", 6, 2.0)], pages=(5, 7))
    assert outcome.material_hit is True
    assert outcome.page_hit is False


def test_alt_expected_counts_with_its_own_pages() -> None:
    alt = [{"material": "m2", "pages": [3], "evidence": "x"}]
    assert _score([Hit("m2", 3, 1.0)], alt=alt).page_hit is True
    wrong_page = _score([Hit("m2", 4, 1.0)], alt=alt)
    assert wrong_page.material_hit is True and wrong_page.page_hit is False
    # Page 5 is accepted for m1 only, not for m2.
    assert _score([Hit("m2", 5, 1.0)], alt=alt).page_hit is False


def test_empty_result_is_a_page_miss_when_page_aware_and_excluded_when_not() -> None:
    aware = _score([], page_aware=True)
    unaware = _score([], page_aware=False)
    assert aware.page_hit is False and unaware.page_hit is None
    assert _EVAL.page_recall_at_k([aware])["denominator"] == 1
    assert _EVAL.page_recall_at_k([unaware])["denominator"] == 0
    assert _EVAL.page_recall_at_k([unaware])["rate"] is None


def test_ranking_sorts_by_score_then_source_order_then_page() -> None:
    hits = [
        Hit("b", 2, 1.0, 2, 2),
        Hit("a", 9, 1.0, 1, 9),
        Hit("a", 3, 1.0, 1, 3),
        Hit("c", 1, 2.0, 3, 1),
    ]
    ranked = _EVAL.rank_hits(hits)
    assert [(h.material_id, h.page) for h in ranked] == [("c", 1), ("a", 3), ("a", 9), ("b", 2)]


def test_tie_at_cutoff_is_flagged_only_when_rank_four_and_five_tie() -> None:
    tied = [Hit("x", i, 3.0 if i >= 3 else 9.0, 0, i) for i in range(1, 6)]
    assert _score(tied, material="zzz").tie_at_cutoff is True
    clear = [Hit("x", i, 10.0 - i, 0, i) for i in range(1, 6)]
    assert _score(clear, material="zzz").tie_at_cutoff is False
    assert _score(clear[:4], material="zzz").tie_at_cutoff is False


def test_recall_at_k_uses_all_questions_as_denominator() -> None:
    hit = _score([Hit("m1", 5, 1.0)])
    miss = _score([Hit("x", 1, 1.0)])
    empty = _score([])
    record = _EVAL.recall_at_k([hit, miss, empty, hit])
    assert (record["numerator"], record["denominator"]) == (2, 4)
    assert record["rate"] == 0.5
    assert _EVAL.recall_at_k([])["rate"] is None


def test_wrong_skip_rate_denominator_is_only_should_retrieve_rows() -> None:
    decisions = [
        ("retrieve", True),
        ("retrieve", False),
        ("retrieve", False),
        ("skip", False),
        ("skip", True),
    ]
    record = _EVAL.wrong_skip_rate(decisions)
    assert (record["numerator"], record["denominator"]) == (2, 3)
    assert record["rate"] == pytest.approx(0.6667, abs=1e-4)
    false_record = _EVAL.false_retrieve_rate(decisions)
    assert (false_record["numerator"], false_record["denominator"]) == (1, 2)
    assert _EVAL.wrong_skip_rate([("skip", True)])["rate"] is None


def test_empty_result_rate_counts_zero_result_attempts() -> None:
    record = _EVAL.empty_result_rate([0, 3, 4, 0, 1])
    assert (record["numerator"], record["denominator"]) == (2, 5)
    assert record["rate"] == 0.4
    assert _EVAL.empty_result_rate([])["rate"] is None


def test_evenly_spaced_indices_are_deterministic_and_bounded() -> None:
    assert _EVAL.evenly_spaced_indices(94, 0) == []
    assert _EVAL.evenly_spaced_indices(5, 10) == [0, 1, 2, 3, 4]
    picked = _EVAL.evenly_spaced_indices(94, 10)
    assert len(picked) == 10 and picked == sorted(set(picked))
    assert picked[0] == 0 and picked[-1] < 94


# ---- data-file validity ---------------------------------------------------


def test_data_files_load_and_meet_the_counts() -> None:
    materials = _EVAL.load_materials()
    questions = _EVAL.load_questions(materials=materials)
    messages = _EVAL.load_messages(materials=materials, question_ids=[q["id"] for q in questions])
    assert 60 <= len(questions) <= 100
    assert len(messages) >= 200
    assert len({q["id"] for q in questions}) == len(questions)
    assert len({m["id"] for m in messages}) == len(messages)
    assert all(m["synthetic"] is True for m in messages)
    assert "synthetic" in _EVAL.MESSAGES_PATH.name
    assert {m["expected_decision"] for m in messages} == {"retrieve", "skip"}
    assert {m["expected_scope"] for m in messages} <= _EVAL.SCOPES
    assert {m["category"] for m in messages} <= _EVAL.MESSAGE_CATEGORIES
    assert {m["certainty"] for m in messages} <= _EVAL.CERTAINTIES


def test_validation_rejects_bad_rows() -> None:
    materials = _EVAL.load_materials()
    questions = _EVAL.load_questions(materials=materials)
    ids = [q["id"] for q in questions]
    messages = _EVAL.load_messages(materials=materials, question_ids=ids)
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_questions(questions[:10], materials)  # below 60
    broken_page = [dict(q) for q in questions]
    broken_page[0]["expected_pages"] = [9999]
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_questions(broken_page, materials)
    duplicate = [dict(q) for q in questions]
    duplicate[1]["id"] = duplicate[0]["id"]
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_questions(duplicate, materials)
    not_synthetic = [dict(m) for m in messages]
    not_synthetic[0]["synthetic"] = False
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_messages(not_synthetic, materials, ids)
    bad_label = [dict(m) for m in messages]
    bad_label[0]["expected_decision"] = "maybe"
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_messages(bad_label, materials, ids)
    with pytest.raises(_EVAL.DatasetError):
        _EVAL.validate_messages(messages[:50], materials, ids)  # below 200


def test_jsonl_files_are_one_object_per_line() -> None:
    for path in (_EVAL.QUESTIONS_PATH, _EVAL.MESSAGES_PATH):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines and all(isinstance(json.loads(line), dict) for line in lines)


# ---- live path refusal ----------------------------------------------------

_LIVE_ENV = {"KNOWLEDGE_BASE_ID": "kb-test", "COURSE_MATERIALS_BUCKET": "bucket-test"}


@pytest.fixture
def no_aws(monkeypatch):
    """Fail the test if anything tries to build an AWS client or touch the data files."""
    import boto3

    def _boom(*_args, **_kwargs):
        raise AssertionError("an AWS client must not be created")

    monkeypatch.setattr(boto3, "client", _boom)
    monkeypatch.setattr(boto3.session.Session, "client", _boom)
    monkeypatch.setattr(_EVAL, "_build_live_client", _boom)
    monkeypatch.setattr(_EVAL, "run_live", _boom)


@pytest.mark.parametrize(
    "argv",
    [
        ["--live-kb"],
        ["--live-kb", "--max-live-calls", "0"],
        ["--live-kb", "--max-live-calls", "-3"],
        ["--live-kb", "--max-live-calls", str(_EVAL.HARD_LIVE_CALL_CAP + 1)],
        ["--max-live-calls", "5"],
    ],
)
def test_live_path_refuses_without_flag_and_valid_call_limit(argv, no_aws, monkeypatch, capsys) -> None:
    for name, value in _LIVE_ENV.items():
        monkeypatch.setenv(name, value)
    assert _EVAL.main(argv) == 2
    assert "refused" in capsys.readouterr().err


def test_live_path_refuses_when_knowledge_base_is_not_configured(no_aws, monkeypatch, capsys) -> None:
    monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
    monkeypatch.setenv("COURSE_MATERIALS_BUCKET", "bucket-test")
    assert _EVAL.main(["--live-kb", "--max-live-calls", "5"]) == 2
    assert "KNOWLEDGE_BASE_ID" in capsys.readouterr().err


def test_check_live_request_accepts_flag_with_limit_and_config() -> None:
    assert _EVAL.check_live_request(True, 7, _LIVE_ENV) == 7
    with pytest.raises(_EVAL.LiveRunRefused):
        _EVAL.check_live_request(False, None, _LIVE_ENV)


def test_call_counter_stops_at_the_limit_without_a_network() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.seen = 0

        def retrieve(self, **_kwargs):
            self.seen += 1
            return {"retrievalResults": []}

    fake = FakeClient()
    counter = _EVAL.CountingClient(fake, 2)
    counter.retrieve(query="a")
    counter.retrieve(query="b")
    with pytest.raises(_EVAL.LiveCallLimitExceeded):
        counter.retrieve(query="c")
    assert fake.seen == 2 and counter.calls == 2


# ---- needs_sources stub models (offline) ---------------------------------


def _row(message: str, expected: str) -> dict:
    return {
        "id": "x",
        "message": message,
        "stage": "problem_identification",
        "selected_sources": [],
        "attachments": [],
        "history": [],
        "expected_decision": expected,
        "certainty": "clear",
        "category": "course_content",
    }


def test_needs_sources_stub_bounds_on_a_small_set() -> None:
    rows = [
        _row("what questions do we ask in the JTBD interview", "retrieve"),
        _row("I think option B is stronger.", "skip"),
        _row("what should I do next", "skip"),
    ]
    scored = [(row, _EVAL.gate_decision(row)) for row in rows]
    assert [d.second_chance for _, d in scored] == [True, True, False]
    stubs = _EVAL._needs_sources_stubs(scored, None)["stubs"]
    # A perfect model rescues the wrong skip and adds no false retrieve.
    assert stubs["oracle"]["wrong_skip_rate"]["numerator"] == 0
    assert stubs["oracle"]["false_retrieve_rate"]["numerator"] == 0
    # A model that flags every eligible message cannot be worse on wrong skips
    # and adds false retrieves only for eligible skip messages.
    assert stubs["flag_all"]["wrong_skip_rate"]["numerator"] == 0
    assert stubs["flag_all"]["false_retrieve_rate"]["numerator"] == 1
    assert stubs["flag_all"]["second_model_calls"] == 2
    # The question-shaped mock rule flags only the first message.
    assert stubs["mock_rule"]["second_model_calls"] == 1


def test_needs_sources_stubs_do_not_change_the_first_pass_numbers() -> None:
    rows = [_row("what questions do we ask in the JTBD interview", "retrieve")]
    gate = _EVAL.evaluate_gate(rows, None)
    assert gate["wrong_skip_rate"]["numerator"] == 1
    assert gate["needs_sources_stubs"]["wrong_skips_before"] == 1


# ---- live model mode (stub Bedrock client only) -----------------------------

_HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
_MODEL_KWARGS = {"provider": "bedrock", "model_id": _HAIKU, "region": "us-west-2"}


def _tool_reply(*, mode="qa", needs_sources=False, out_of_scope=False) -> dict:
    body = {
        "mode": mode,
        "response_text": "Short reply.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "needs_sources": needs_sources,
        "out_of_scope": out_of_scope,
    }
    if mode == "coaching":
        body["recommendation"] = "stay"
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "t", "name": "FastChatTurnOutput", "input": body}}],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 100, "outputTokens": 20},
    }


def _student_message(kwargs: dict) -> str:
    text = kwargs["messages"][-1]["content"][0]["text"]
    return text.split("<student_message>\n", 1)[1].split("\n</student_message>", 1)[0]


class _StubBedrock:
    """Stand-in for the ``bedrock-runtime`` client. Never touches a network."""

    def __init__(self, decide=None, error=None) -> None:
        self.requests: list[dict] = []
        self._decide = decide or (lambda message: _tool_reply())
        self._error = error

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error(len(self.requests))
        return self._decide(_student_message(kwargs))


def _client_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": "secret body"}}, "Converse")


def _rows(*items):
    return [dict(_row(message, expected), id=f"t{i}") for i, (message, expected) in enumerate(items, 1)]


def _run(rows, stub, limit=None):
    counter = _EVAL.CountingConverseClient(stub, limit or len(rows))
    return _EVAL.run_live_model(rows, limit or len(rows), client=counter, model_id=_HAIKU, region="us-west-2")


@pytest.fixture
def no_boto(monkeypatch):
    """Fail the test if the live model path builds a real AWS client."""
    import boto3

    def _boom(*_args, **_kwargs):
        raise AssertionError("an AWS client must not be created")

    monkeypatch.setattr(boto3, "client", _boom)
    monkeypatch.setattr(boto3.session.Session, "client", _boom)
    monkeypatch.setattr(_EVAL, "_build_bedrock_runtime_client", _boom)
    monkeypatch.setattr(_EVAL, "run_live_model", _boom)


@pytest.fixture
def haiku_settings(monkeypatch):
    monkeypatch.setattr(_EVAL, "live_model_settings", lambda: ("bedrock", _HAIKU, "us-west-2"))


@pytest.mark.parametrize(
    "argv",
    [
        ["--live-model"],
        ["--live-model", "--max-live-calls", "0"],
        ["--live-model", "--max-live-calls", str(_EVAL.LIVE_MODEL_HARD_CALL_CAP + 1)],
        ["--live-model", "--live-kb", "--max-live-calls", "5"],
    ],
)
def test_live_model_refuses_without_a_valid_call_limit(argv, no_boto, haiku_settings, capsys) -> None:
    assert _EVAL.main(argv) == 2
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("provider", "model_id", "region", "needle"),
    [
        ("openai", _HAIKU, "us-west-2", "COACHING_MODEL_PROVIDER"),
        ("bedrock", "global.anthropic.claude-sonnet-4-6", "us-west-2", "Haiku"),
        ("bedrock", "", "us-west-2", "Haiku"),
        ("bedrock", _HAIKU, "", "AGENTCORE_MODEL_REGION"),
    ],
)
def test_live_model_refuses_when_settings_are_not_the_haiku_role(
    provider, model_id, region, needle, no_boto, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(_EVAL, "live_model_settings", lambda: (provider, model_id, region))
    assert _EVAL.main(["--live-model", "--max-live-calls", "5"]) == 2
    assert needle in capsys.readouterr().err


def test_max_live_calls_alone_is_still_refused(no_boto, capsys) -> None:
    assert _EVAL.main(["--max-live-calls", "5"]) == 2
    assert "--live-model" in capsys.readouterr().err


def test_check_live_model_request_accepts_a_limit() -> None:
    assert _EVAL.check_live_model_request(True, False, 295, **_MODEL_KWARGS) == 295


def test_main_live_model_runs_with_a_stub_client_and_exits_zero(
    haiku_settings, monkeypatch, tmp_path, capsys
) -> None:
    stub = _StubBedrock()
    monkeypatch.setattr(
        _EVAL, "_build_bedrock_runtime_client", lambda region, limit: _EVAL.CountingConverseClient(stub, limit)
    )
    out = tmp_path / "live.json"
    assert _EVAL.main(["--live-model", "--max-live-calls", "6", "--json-output", str(out)]) == 0
    assert len(stub.requests) == 6
    data = json.loads(out.read_text())
    assert data["mode"] == "live_model" and data["calls"]["made"] == 6
    assert "live_model" in capsys.readouterr().out


def test_first_call_reuses_the_production_prompt_and_tool_contract() -> None:
    from agentcore_runtime.specialists.fast_chat import fast_chat_static_prefix

    stub = _StubBedrock()
    row = _row("what questions do we ask in the JTBD interview", "retrieve")
    _run([dict(row, id="t1", history=[
        {"role": "user", "text": "what is dot voting?"},
        {"role": "assistant", "text": "Each person places a few dots."},
    ])], stub)
    call = stub.requests[0]
    system = call["system"][0]["text"]
    # Runtime fast-chat prompt, output contract and the SOURCE CHECK rule.
    assert "FAST CHAT OUTPUT CONTRACT" in system and "SOURCE CHECK" in system
    assert system.startswith(fast_chat_static_prefix("problem_identification"))
    assert call["modelId"] == _HAIKU
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    assert _student_message(call) == "what questions do we ask in the JTBD interview"
    tool = call["toolConfig"]["tools"][0]["toolSpec"]
    assert tool["name"] == "FastChatTurnOutput" and call["toolConfig"]["toolChoice"] == {"any": {}}
    schema = tool["inputSchema"]["json"]
    assert "$defs" not in schema and "$ref" not in json.dumps(schema)
    assert "needs_sources" in schema["properties"]
    assert call["inferenceConfig"]["maxTokens"] == _EVAL.LIVE_MODEL_MAX_OUTPUT_TOKENS


def test_source_check_rule_is_on_for_every_row_and_no_excerpts_are_attached() -> None:
    rows = _rows(("hello there", "skip"), ("what is a creative matrix", "retrieve"))
    stub = _StubBedrock()
    _run(rows, stub)
    for call in stub.requests:
        assert "SOURCE CHECK" in call["system"][0]["text"]
        assert "No retrieved source context was provided" in call["messages"][-1]["content"][0]["text"]


def test_eligible_flagged_row_is_rescued_and_an_extra_call_is_counted() -> None:
    rows = _rows(
        ("what questions do we ask in the JTBD interview", "retrieve"),
        ("I think option B is stronger.", "skip"),
    )
    stub = _StubBedrock(lambda message: _tool_reply(needs_sources="JTBD" in message))
    result = _run(rows, stub)
    overall = result["overall"]
    assert overall["wrong_skip_gate_only"]["numerator"] == 1
    assert overall["wrong_skip_with_model"]["numerator"] == 0
    assert overall["false_retrieve_with_model"]["numerator"] == 0
    assert overall["extra_model_calls"] == 1
    assert overall["flag_rate_eligible"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert result["calls"]["made"] == 2 and result["tokens"] == {"input": 200, "output": 40}
    assert result["false_flags"] == [] and result["missed_flags"] == []


def test_skip_labelled_message_flagged_true_is_a_false_retrieve_and_listed() -> None:
    rows = _rows(("I think option B is stronger.", "skip"))
    assert _EVAL.gate_decision(rows[0]).second_chance
    result = _run(rows, _StubBedrock(lambda message: _tool_reply(needs_sources=True)))
    assert result["overall"]["false_retrieve_gate_only"]["numerator"] == 0
    assert result["overall"]["false_retrieve_with_model"]["numerator"] == 1
    assert result["overall"]["extra_model_calls"] == 1
    assert [f["id"] for f in result["false_flags"]] == ["t1"]


def test_flag_on_a_coaching_turn_is_not_honoured() -> None:
    rows = _rows(("what questions do we ask in the JTBD interview", "retrieve"))
    result = _run(rows, _StubBedrock(lambda m: _tool_reply(mode="coaching", needs_sources=True)))
    overall = result["overall"]
    assert overall["raw_flags_not_honoured"] == 1
    assert overall["extra_model_calls"] == 0
    assert overall["wrong_skip_with_model"]["numerator"] == 1
    assert result["flag_ignored"][0]["mode"] == "coaching"


def test_non_eligible_rows_never_change_the_metrics() -> None:
    # Retrieved by the gate already: the flag must not matter.
    rows = _rows(("what is a creative matrix", "retrieve"))
    decision = _EVAL.gate_decision(rows[0])
    assert decision.retrieve and not decision.second_chance
    result = _run(rows, _StubBedrock(lambda m: _tool_reply(needs_sources=True)))
    assert result["overall"]["eligible_messages"] == 0
    assert result["overall"]["extra_model_calls"] == 0
    assert result["overall"]["flag_rate_raw_all_rows"]["numerator"] == 1


def test_category_split_sums_to_the_overall_numbers() -> None:
    rows = _rows(
        ("what questions do we ask in the JTBD interview", "retrieve"),
        ("I think option B is stronger.", "skip"),
        ("thanks", "skip"),
    )
    rows[1]["category"] = "project_reasoning"
    rows[2]["category"] = "greeting_thanks_chitchat"
    result = _run(rows, _StubBedrock(lambda m: _tool_reply(needs_sources="JTBD" in m)))
    assert set(result["by_category"]) == {"course_content", "project_reasoning", "greeting_thanks_chitchat"}
    assert sum(b["extra_model_calls"] for b in result["by_category"].values()) == result["overall"]["extra_model_calls"]
    assert sum(b["messages_sent"] for b in result["by_category"].values()) == 3


def test_run_stops_after_the_first_auth_error_and_names_its_class(capsys) -> None:
    rows = _rows(*[("what is a creative matrix", "retrieve")] * 5)
    stub = _StubBedrock(error=lambda n: _client_error("AccessDeniedException"))
    result = _run(rows, stub)
    assert len(stub.requests) == 1
    assert result["stopped_early_on_auth_or_access_error"]["error"] == (
        "botocore.exceptions.ClientError (code AccessDeniedException)"
    )
    assert result["first_failure"]["id"] == "t1"
    assert _EVAL.live_model_exit_code(result) == 1  # no call succeeded
    assert "secret body" not in json.dumps(result)


def test_auth_error_after_successes_exits_with_the_stopped_early_code() -> None:
    rows = _rows(*[("what is a creative matrix", "retrieve")] * 4)

    def error(n):
        return _client_error("ExpiredTokenException")

    class Flaky(_StubBedrock):
        def converse(self, **kwargs):
            if len(self.requests) >= 2:
                self.requests.append(kwargs)
                raise error(0)
            return super().converse(**kwargs)

    stub = Flaky()
    result = _run(rows, stub)
    assert len(stub.requests) == 3 and result["calls"]["succeeded"] == 2
    assert _EVAL.live_model_exit_code(result) == 3


def test_every_call_failing_without_an_auth_error_tries_each_row_and_exits_nonzero() -> None:
    rows = _rows(*[("what is a creative matrix", "retrieve")] * 4)
    stub = _StubBedrock(error=lambda n: _client_error("ThrottlingException"))
    result = _run(rows, stub)
    assert len(stub.requests) == 4
    assert result["calls"]["failed"] == 4 and result["stopped_early_on_auth_or_access_error"] is None
    assert result["first_failure"]["error"].endswith("(code ThrottlingException)")
    assert _EVAL.live_model_exit_code(result) == 1


def test_reply_without_a_tool_call_is_a_failure_not_a_flag() -> None:
    rows = _rows(("what is a creative matrix", "retrieve"))
    empty = {"output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}}, "stopReason": "end_turn"}
    result = _run(rows, _StubBedrock(lambda m: empty))
    assert result["calls"]["failed"] == 1
    assert "LiveStructuredOutputError" in result["first_failure"]["error"]


def test_call_limit_sends_an_even_subset_and_never_exceeds_the_limit() -> None:
    rows = [dict(_row("what is a creative matrix", "retrieve"), id=f"t{i}") for i in range(10)]
    stub = _StubBedrock()
    result = _run(rows, stub, limit=4)
    assert len(stub.requests) == 4 and result["calls"]["messages_attempted"] == 4
    assert [o["id"] for o in result["rows"]] == ["t0", "t2", "t5", "t7"]
    class Bare:
        def converse(self, **_kwargs):
            return {}

    counter = _EVAL.CountingConverseClient(Bare(), 1)
    counter.converse(modelId="x")
    with pytest.raises(_EVAL.LiveCallLimitExceeded):
        counter.converse(modelId="x")


def test_agentcore_is_never_invoked_by_the_live_model_path() -> None:
    # The provider is built with a runtime client that raises when used; a
    # completed run proves the AgentCore invoke path was not touched.
    assert _run(_rows(("hello", "skip")), _StubBedrock())["calls"]["succeeded"] == 1


def test_offline_gate_numbers_are_unchanged_by_the_new_gate_fields() -> None:
    messages = _EVAL.load_messages()
    gate = _EVAL.evaluate_gate(messages, None)
    assert gate["wrong_skip_rate"]["numerator"] == 76
    assert gate["false_retrieve_rate"]["numerator"] == 7
    assert gate["needs_sources_stubs"]["eligible_messages"] == 189


def test_gate_decision_carries_the_scope_fields_the_live_request_needs() -> None:
    cleared = _EVAL.gate_decision(_row("what stage am I in", "skip"))
    assert cleared.scope_cleared and cleared.expected_mode == "qa" and not cleared.second_chance
    request = _EVAL.build_live_request(_row("what stage am I in", "skip"), cleared)
    assert request.source_ids == [] and request.source_need_check is True
    attach = dict(_row("can you review this persona", "retrieve"), attachments=[{"title": "P", "filename": "P.pdf"}])
    request = _EVAL.build_live_request(attach, _EVAL.gate_decision(attach))
    assert request.attachment_source_ids == ["eval-attachment-1"] and request.attachment_titles == ["P"]


def test_live_composition_matches_the_offline_mock_rule_stub_on_the_real_gate_set() -> None:
    """A stub model using the mock provider's rule must reproduce ``mock_rule``.

    This ties the live composition (gate decision plus honoured flag) to the
    offline ``needs_sources_stubs`` maths on all 295 messages.
    """
    from backend.mock_provider import mock_flags_needs_sources

    messages = _EVAL.load_messages()
    stub = _StubBedrock(lambda message: _tool_reply(needs_sources=mock_flags_needs_sources(message)))
    result = _run(messages, stub)
    offline = _EVAL.evaluate_gate(messages, None)["needs_sources_stubs"]["stubs"]["mock_rule"]
    overall = result["overall"]
    assert result["calls"]["succeeded"] == len(messages) == 295
    assert overall["wrong_skip_with_model"] == offline["wrong_skip_rate"]
    assert overall["false_retrieve_with_model"] == offline["false_retrieve_rate"]
    assert overall["extra_model_calls"] == offline["second_model_calls"]


# ---- live Knowledge Base page recall (fake client only) ---------------------

_PAGE_KEY = "x-amz-bedrock-kb-document-page-number"


def _run_live_with_fake_kb(monkeypatch, pages_by_question):
    """Run ``run_live`` against a fake client; ``pages_by_question`` maps text to a page or None.

    Each question gets one hit on its expected material. The hit carries the
    page metadata attribute only when the mapped page is not ``None``.
    """
    from backend.settings import settings

    materials = _EVAL.load_materials()
    by_id = {entry["material_id"]: entry for entry in materials}
    first, second, third = (entry["material_id"] for entry in materials[:3])
    questions = [
        {"id": "t1", "question": "alpha topic", "expected_material": first,
         "expected_pages": [3], "alt_expected": []},
        {"id": "t2", "question": "beta topic", "expected_material": second,
         "expected_pages": [4], "alt_expected": []},
        {"id": "t3", "question": "gamma topic", "expected_material": third,
         "expected_pages": [5], "alt_expected": []},
    ]
    expected_by_text = {q["question"]: q["expected_material"] for q in questions}

    class FakeKb:
        def retrieve(self, **kwargs):
            text = kwargs["retrievalQuery"]["text"]
            material = expected_by_text[text]
            hit = {
                "content": {"text": f"excerpt for {text}"},
                "location": {
                    "type": "S3",
                    "s3Location": {"uri": f"s3://bucket-test/{by_id[material]['object_key']}"},
                },
                "score": 0.8,
            }
            page = pages_by_question[text]
            if page is not None:
                hit["metadata"] = {_PAGE_KEY: page}
            return {"retrievalResults": [hit]}

    monkeypatch.setattr(settings, "knowledge_base_id", "kb-test")
    monkeypatch.setattr(settings, "course_materials_bucket", "bucket-test")
    monkeypatch.setattr(settings, "knowledge_base_page_citations_enabled", False)
    monkeypatch.setattr(
        _EVAL, "_build_live_client", lambda _region, limit: _EVAL.CountingClient(FakeKb(), limit)
    )
    result = _EVAL.run_live(materials, questions, _EVAL.load_messages(materials=materials), 3)
    return result["retrieval"]


def test_live_page_recall_scores_only_questions_whose_results_carry_a_page(monkeypatch) -> None:
    # t1: right page. t2: wrong page. t3: no page metadata (left out, not a miss).
    # The production page switch is off here; the eval must still read pages.
    retrieval = _run_live_with_fake_kb(
        monkeypatch, {"alpha topic": 3, "beta topic": 9, "gamma topic": None}
    )
    assert retrieval["recall_at_4_material"]["numerator"] == 3
    assert retrieval["recall_at_4_page"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert retrieval["page_coverage"] == {
        "results": 3,
        "results_with_page": 2,
        "questions_with_page": 2,
        "questions_evaluated": 3,
    }


def test_live_page_recall_stays_not_available_when_no_result_carries_a_page(monkeypatch) -> None:
    retrieval = _run_live_with_fake_kb(
        monkeypatch, {"alpha topic": None, "beta topic": None, "gamma topic": None}
    )
    assert retrieval["recall_at_4_page"]["denominator"] == 0
    assert retrieval["recall_at_4_page"]["rate"] is None
    assert retrieval["page_coverage"]["results_with_page"] == 0
    assert retrieval["page_coverage"]["questions_with_page"] == 0
    assert "n/a" in _EVAL.format_rate(retrieval["recall_at_4_page"])


# ---- follow-up cases (phase 3b item C) --------------------------------------


def _case(decision: str, *, passes: bool, standalone_ok: bool | None) -> dict:
    return {
        "expected_decision": decision,
        "end_to_end_pass": passes,
        "standalone_ok": standalone_ok,
    }


def test_followup_file_loads_and_is_kept_apart_from_the_gate_messages() -> None:
    materials = _EVAL.load_materials()
    ids = [q["id"] for q in _EVAL.load_questions(materials=materials)]
    rows = _EVAL.load_followups(materials=materials, question_ids=ids)
    gate_ids = {m["id"] for m in _EVAL.load_messages(materials=materials, question_ids=ids)}
    assert 10 <= len(rows) <= 15
    assert not gate_ids & {r["id"] for r in rows}
    assert all(r["synthetic"] is True and r["follow_up"] is True and r["history"] for r in rows)
    assert {r["expected_decision"] for r in rows} == {"retrieve", "skip"}
    assert "synthetic" in _EVAL.FOLLOWUPS_PATH.name


def test_followup_loader_rejects_rows_without_history_or_link(tmp_path) -> None:
    materials = _EVAL.load_materials()
    ids = [q["id"] for q in _EVAL.load_questions(materials=materials)]
    rows = _EVAL.load_followups(materials=materials, question_ids=ids)
    retrieve = next(r for r in rows if r["expected_decision"] == "retrieve")
    for change in ({"history": []}, {"question_id": None}, {"id": "gm001"}):
        path = tmp_path / "bad.jsonl"
        path.write_text(json.dumps({**retrieve, **change}) + "\n", encoding="utf-8")
        with pytest.raises(_EVAL.DatasetError):
            _EVAL.load_followups(path, materials, ids)


def test_followup_verdict_applies_the_recorded_threshold() -> None:
    def cases(failures: int, attributable: int) -> list[dict]:
        out = [_case("retrieve", passes=False, standalone_ok=i < attributable) for i in range(failures)]
        out += [_case("retrieve", passes=True, standalone_ok=True) for _ in range(9 - failures)]
        out += [_case("skip", passes=False, standalone_ok=None) for _ in range(3)]
        return out

    assert _EVAL.followup_verdict(cases(5, 5))["clearly_fail"] is True
    assert _EVAL.followup_verdict(cases(4, 4))["clearly_fail"] is False
    assert _EVAL.followup_verdict(cases(8, 4))["clearly_fail"] is False
    verdict = _EVAL.followup_verdict(cases(8, 3))
    assert (verdict["retrieve_cases"], verdict["end_to_end_failures"]) == (9, 8)
    assert verdict["attributable_failures"] == 3 and verdict["clearly_fail"] is False


def test_captured_query_comes_from_the_adapter_and_makes_no_network_call() -> None:
    from backend.retrieval import RetrievalSource

    source = RetrievalSource(
        source_id="s1",
        label="S1",
        title="Week 1",
        text="",
        object_key="course/lectureNotes/week1.pdf",
    )
    history = [
        {"role": "user", "text": "what is the rule of threes?"},
        {"role": "assistant", "text": "Audiences remember groups of three. [S1]"},
    ]
    anaphoric = _EVAL.captured_kb_query("which lecture is that from?", history, source)
    assert "what is the rule of threes?" in anaphoric
    plain = _EVAL.captured_kb_query("what are the axes?", history, source)
    assert plain == "what are the axes?"


def test_followup_block_is_separate_and_leaves_the_gate_numbers_alone() -> None:
    materials = _EVAL.load_materials()
    questions = _EVAL.load_questions(materials=materials)
    ids = [q["id"] for q in questions]
    followups = _EVAL.load_followups(materials=materials, question_ids=ids)
    search = _EVAL.OfflineCourseSearch(materials)
    block = _EVAL.evaluate_followups(followups, questions, search)
    assert block["cases"] == len(followups)
    assert len(block["per_case"]) == len(followups)
    assert block["verdict"] == _EVAL.followup_verdict(block["per_case"])
    skip_cases = [c for c in block["per_case"] if c["expected_decision"] == "skip"]
    assert all(c["standalone_ok"] is None for c in skip_cases)
    # The 295-message numbers do not move.
    gate = _EVAL.evaluate_gate(_EVAL.load_messages(), None)
    assert gate["messages"] == 295
    assert gate["wrong_skip_rate"]["numerator"] == 76
