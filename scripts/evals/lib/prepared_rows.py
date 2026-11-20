"""Run the gate once per gate message and record Laya eligibility.

Shared by ``evaluate_combined_gate`` and ``benchmark_course_intent``. Offline: the gate
adapter and the production eligibility helpers are imported lazily; no model runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from scripts.evals.lib.gate import gate_decision


@dataclass(frozen=True)
class PreparedRow:
    """One gate message with the gate's decision and Laya eligibility."""

    id: str
    category: str
    expected: str
    message: str
    history: tuple[Mapping[str, Any], ...]
    gate_retrieve: bool
    second_chance: bool
    eligible: bool
    first_turn: bool


def prepare_rows(messages: Sequence[Mapping[str, Any]]) -> list[PreparedRow]:
    """Run the gate once per message and record Laya eligibility.

    Eligibility uses the same call as the course-intent eval scripts
    (``local_course_intent_candidate`` with the gate's intent and scope).
    """
    from backend.coaching.evidence_scope import local_course_intent_candidate
    from backend.course_intent import is_first_student_turn

    prepared = []
    for row in messages:
        decision = gate_decision(row)
        eligible = local_course_intent_candidate(
            row["message"],
            intent=decision.intent,
            evidence_scoped=bool(
                decision.scope_cleared or row["attachments"] or row["selected_sources"]
            ),
            searched=decision.retrieve,
        )
        prepared.append(
            PreparedRow(
                id=str(row["id"]),
                category=str(row["category"]),
                expected=str(row["expected_decision"]),
                message=str(row["message"]),
                history=tuple(row["history"]),
                gate_retrieve=bool(decision.retrieve),
                second_chance=bool(decision.second_chance),
                eligible=bool(eligible),
                first_turn=bool(is_first_student_turn(row["history"])),
            )
        )
    return prepared
