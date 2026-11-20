"""Search decisions of the four routing arms (A, B, C, D) for one gate message.

Every scope decision comes from ``backend.coaching.evidence_scope``
(``decide_first_pass_scope`` through ``scripts.evals.lib.gate`` and ``is_chit_chat``).
This module adds no rule: arm C's skip is the OR of three existing outputs, and arms B
and D differ from A only by the promotion flag the scope function already takes.

* A: the gate's decision.
* B: the gate with a Laya promotion applied (only on eligible rows).
* C: skip when the greeting, stage-navigation or personal-reasoning output fires,
  otherwise search the Knowledge Base. Local searches are A's (not modelled further).
* D: B's search decision. The KB score then decides whether evidence is injected.

The backend is imported lazily, inside ``build_row_scopes``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from scripts.evals.lib.prepared_rows import PreparedRow

ARMS = ("A", "B", "C", "D")
LAYA_ARMS = frozenset({"B", "D"})
INTENT_PERSONAL = "high_confidence_personal"

SKIP_GREETING = "greeting"
SKIP_NAVIGATION = "navigation"
SKIP_PERSONAL = "personal_reasoning"


@dataclass(frozen=True)
class RowScopes:
    """The scope outputs one gate message needs, computed once.

    ``kb_promoted`` and ``local_promoted`` are the decision with the Laya promotion
    applied. They equal the plain decision on a row that is not Laya-eligible.
    """

    id: str
    category: str
    expected: str
    eligible: bool
    first_turn: bool
    chit_chat: bool
    scope_cleared: bool
    personal: bool
    kb_a: bool
    local_a: bool
    kb_promoted: bool
    local_promoted: bool

    @property
    def skip_rule(self) -> str | None:
        """The skip rule that fires, in attribution order (greeting, navigation, personal)."""
        if self.chit_chat:
            return SKIP_GREETING
        if self.scope_cleared:
            return SKIP_NAVIGATION
        if self.personal:
            return SKIP_PERSONAL
        return None

    @property
    def skipped_by_c(self) -> bool:
        """Arm C skips the KB when any of the three rules fires (their OR)."""
        return self.chit_chat or self.scope_cleared or self.personal


def build_row_scopes(
    messages: Sequence[Mapping[str, Any]], prepared: Mapping[str, PreparedRow]
) -> list[RowScopes]:
    """Run the existing scope code once per message, with and without a promotion."""
    from backend.coaching.evidence_scope import decide_first_pass_scope, is_chit_chat
    from scripts.evals.lib.gate import gate_decision, scope_inputs_for_row

    scopes = []
    for row in messages:
        row_id = str(row["id"])
        meta = prepared[row_id]
        gate = gate_decision(row)
        promoted = decide_first_pass_scope(
            scope_inputs_for_row(row), course_intent_promoted=bool(meta.eligible)
        )
        scopes.append(
            RowScopes(
                id=row_id,
                category=str(row["category"]),
                expected=str(row["expected_decision"]),
                eligible=bool(meta.eligible),
                first_turn=bool(meta.first_turn),
                chit_chat=bool(is_chit_chat(str(row["message"]))),
                scope_cleared=bool(gate.scope_cleared),
                personal=gate.intent == INTENT_PERSONAL,
                kb_a=bool(gate.course),
                local_a=bool(gate.student),
                kb_promoted=bool(promoted.include_course_catalog),
                local_promoted=bool(promoted.searches_personal_files),
            )
        )
    return scopes


def search_flags(arm: str, scopes: RowScopes, promoted: bool) -> tuple[bool, bool]:
    """Return ``(kb_search, local_search)`` for one arm on one row.

    ``promoted`` is the Laya decision for the row and is read only by B and D.
    """
    if arm == "A":
        return scopes.kb_a, scopes.local_a
    if arm == "C":
        return (not scopes.skipped_by_c), scopes.local_a
    if arm in LAYA_ARMS:
        if promoted and scopes.eligible:
            return scopes.kb_promoted, scopes.local_promoted
        return scopes.kb_a, scopes.local_a
    raise ValueError(f"unknown arm {arm!r}")


def skip_attribution(scopes: Sequence[RowScopes]) -> dict[str, Any]:
    """Count rows by the skip rule that fires first, and how many rules overlap."""
    counts = {SKIP_GREETING: 0, SKIP_NAVIGATION: 0, SKIP_PERSONAL: 0}
    for row in scopes:
        rule = row.skip_rule
        if rule is not None:
            counts[rule] += 1
    return {
        "rows": len(scopes),
        "skipped_by_c": sum(1 for row in scopes if row.skipped_by_c),
        "first_rule_that_fires": counts,
        "rule_fires_any": {
            SKIP_GREETING: sum(1 for row in scopes if row.chit_chat),
            SKIP_NAVIGATION: sum(1 for row in scopes if row.scope_cleared),
            SKIP_PERSONAL: sum(1 for row in scopes if row.personal),
        },
    }
