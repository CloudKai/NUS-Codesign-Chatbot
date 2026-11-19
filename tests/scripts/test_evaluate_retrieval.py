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
