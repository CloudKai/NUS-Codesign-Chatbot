"""Head-to-head routing comparison on the 295 gate messages, offline.

Compares four arms by what the student receives: A the existing gate, B gate + Laya,
C Knowledge Base score routing, D gate + Laya to search and the KB score to inject.
The rules are fixed in ``.agents/tasks/headtohead-prereg/plan.md`` and implemented in
``scripts/evals/lib`` (split, ``T`` selection, pass rule, tie-break, exact McNemar).

Inputs, all read from disk, nothing live:

* ``--kb-gate``: the JSON from ``evaluate_retrieval --live-kb-gate``. Without it the KB
  figures for arms C and D are ``missing`` and A and B use a search-only proxy
  (``bound``). A file that does not cover all 295 ids counts as missing for KB figures.
* the stored Laya decisions in ``--laya-results-dir`` (floor, ceiling, scored-only), and
  ``--laya-full`` for an all-rows run file (see ``lib/laya_sources.py`` for its schema).

All reported figures use the holdout half. ``T`` is chosen on the calibration half and
frozen. Laya cutoffs are read, never fitted. No message text is written anywhere.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.evals.lib import prereg  # noqa: E402
from scripts.evals.lib.arm_metrics import compare  # noqa: E402
from scripts.evals.lib.arm_report import format_report  # noqa: E402
from scripts.evals.lib.extra_arms import extra_section, format_extra_section  # noqa: E402
from scripts.evals.lib.extra_messages import (  # noqa: E402
    ALLOW_FLAG,
    ExtraMessages,
    ExtraMessagesError,
    load_extra_messages,
)
from scripts.evals.lib.fixtures import load_materials, load_messages, load_questions  # noqa: E402
from scripts.evals.lib.kb_scores import EXTRA_MODE, KbFileError, KbScores, load_kb_scores  # noqa: E402
from scripts.evals.lib.laya_sources import (  # noqa: E402
    LayaFileError,
    LayaSource,
    load_full_run,
    load_stored_learn,
    load_stored_multilingual,
)
from scripts.evals.lib.offline import block_network  # noqa: E402
from scripts.evals.lib.output import write_json_output  # noqa: E402
from scripts.evals.lib.paths import MATERIALS_PATH, MESSAGES_PATH, QUESTIONS_PATH  # noqa: E402
from scripts.evals.lib.prepared_rows import prepare_rows  # noqa: E402
from scripts.evals.lib.routing_arms import build_row_scopes  # noqa: E402

PHASE3D_DIR = _PROJECT_ROOT / ".agents" / "tasks" / "phase3d-work"
FULL_KINDS = ("multilingual", "learn")
STORED_SOURCES = (
    ("laya_multilingual_0.8", "multilingual.json", load_stored_multilingual, "primary"),
    ("laya_typed_decisions_0.8", "typed-decisions.json", load_stored_multilingual, "secondary"),
    ("laya_learn_per_turn_holdout", "course-intent-by-turn.json", load_stored_learn, "secondary"),
)
ROLE_NOTES = {
    "primary": "primary: Laya multilingual at the unchanged 0.8 cutoff",
    "secondary": "secondary: the Learn bundle was fitted on 150 rows of this set, and typed decisions are a different run",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--kb-gate", type=Path, default=None, help="JSON from evaluate_retrieval --live-kb-gate (absent: arms C and D are missing)")
    parser.add_argument("--laya-results-dir", type=Path, default=PHASE3D_DIR, help="folder with the stored phase3d Laya JSON files")
    parser.add_argument("--laya-full", type=Path, default=None, help="all-rows Laya run file (benchmark_course_intent with host notes)")
    parser.add_argument("--laya-full-kind", choices=FULL_KINDS, default="multilingual", help="which cutoffs --laya-full uses: multilingual 0.8, or Learn per-turn")
    parser.add_argument("--plan", type=Path, default=prereg.PLAN_PATH, help="the pre-registration file; its sha256 and commit go into the output")
    parser.add_argument("--extra-messages", type=Path, default=None, help="JSONL of anonymised, human-labelled messages; reported in a separate section, never in M1, M2, the split or T")
    parser.add_argument("--extra-kb-gate", type=Path, default=None, help="JSON from evaluate_retrieval --live-kb-gate --extra-messages (needs --extra-messages); without it the extra rows' evidence is missing")
    parser.add_argument(ALLOW_FLAG, action="store_true", help="accept extra rows marked synthetic: false (real messages); the default refuses them")
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    return parser


def _refuse(message: str) -> int:
    print(f"refused: {message}", file=sys.stderr)
    return 2


def load_sources(
    args: argparse.Namespace, prepared: dict[str, Any]
) -> tuple[list[LayaSource], list[dict[str, str]], dict[str, str]]:
    """Stored sources (missing files are listed, not fatal) and the optional full run."""
    sources: list[LayaSource] = []
    unavailable: list[dict[str, str]] = []
    roles: dict[str, str] = {}
    for name, filename, loader, role in STORED_SOURCES:
        path = args.laya_results_dir / filename
        if path.is_file():
            sources.append(loader(path, name, prepared))
            roles[name] = ROLE_NOTES[role]
        else:
            unavailable.append({"name": name, "reason": f"{path} not found"})
    if args.laya_full is not None:
        cutoffs = prereg.LAYA_CUTOFFS
        if args.laya_full_kind == "learn":
            source = load_full_run(
                args.laya_full, "laya_full_learn", prepared,
                cutoff=cutoffs["learn_continuing"], first_turn_cutoff=cutoffs["learn_first_turn"],
            )
        else:
            source = load_full_run(args.laya_full, "laya_full_multilingual", prepared, cutoff=cutoffs["multilingual"])
        sources.append(source)
        roles[source.name] = "all-rows run: floor, ceiling and scored-only coincide"
    return sources, unavailable, roles


def main(argv: Sequence[str] | None = None) -> int:
    """Write the comparison JSON and a short Markdown report. Exit 0 or 2 (refused)."""
    args = build_parser().parse_args(argv)
    block_network()
    if args.extra_messages is None and (args.extra_kb_gate is not None or args.allow_non_synthetic):
        return _refuse(f"--extra-kb-gate and {ALLOW_FLAG} need --extra-messages")
    extras: ExtraMessages | None = None
    extra_kb: KbScores | None = None
    if args.extra_messages is not None:
        try:
            extras = load_extra_messages(args.extra_messages, allow_non_synthetic=args.allow_non_synthetic)
            if args.extra_kb_gate is not None:
                extra_kb = load_kb_scores(args.extra_kb_gate, set(extras.ids), mode=EXTRA_MODE)
        except (ExtraMessagesError, KbFileError) as error:
            return _refuse(f"extra messages: {error}")
    try:
        plan = prereg.plan_record(args.plan)
    except (OSError, ValueError) as error:
        return _refuse(f"plan {args.plan}: {type(error).__name__}")
    if not plan["constants_match_code"]:
        return _refuse("the plan's prereg-constants block differs from scripts/evals/lib/prereg.py")
    materials = load_materials(MATERIALS_PATH)
    questions = load_questions(QUESTIONS_PATH, materials)
    messages = load_messages(MESSAGES_PATH, materials, [row["id"] for row in questions])
    prepared_rows = prepare_rows(messages)
    prepared = {row.id: row for row in prepared_rows}
    if len(prepared) != prereg.GATE_MESSAGE_COUNT:
        return _refuse(f"expected {prereg.GATE_MESSAGE_COUNT} gate messages, found {len(prepared)}")
    kb: KbScores | None = None
    try:
        if args.kb_gate is not None:
            kb = load_kb_scores(args.kb_gate, set(prepared))
        sources, unavailable, roles = load_sources(args, prepared)
    except (KbFileError, LayaFileError) as error:
        return _refuse(str(error))
    scopes = build_row_scopes(messages, prepared)
    result = compare(scopes, prepared, sources, kb)
    result = {
        "definition": __doc__,
        "prereg": {"plan": plan, "split_rule": prereg.PREREG_CONSTANTS["split"]},
        "arms": {
            "A": "existing gate",
            "B": "gate + Laya promotion at the unchanged cutoffs",
            "C": "skip on greeting/acknowledgement, stage navigation or personal reasoning; else search the KB; inject if top validated score >= T",
            "D": "gate + Laya decide whether to search; inject if top validated score >= T",
        },
        "status_labels": "measured, bound, missing; synthetic_test_data marks a fixture, never a result",
        "source_roles": roles,
        "sources_unavailable": unavailable,
        **result,
    }
    report = format_report(result)
    if extras is not None:
        result["extra_messages"] = extra_section(
            extras, extra_kb, result["calibration"],
            main_kb_synthetic=bool(result["kb_file"].get("synthetic_test_fixture")),
        )
        report += format_extra_section(result["extra_messages"])
    if args.json_output is not None:
        write_json_output(args.json_output, result)
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
