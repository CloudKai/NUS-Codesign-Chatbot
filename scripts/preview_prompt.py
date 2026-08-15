#!/usr/bin/env python3
"""Render a demo-composed coach prompt for local inspection (no providers/DB).

Usage::

    python scripts/preview_prompt.py --stage deep_analysis

Uses fake/demo context only. Does not load student data, tokens, API keys, or
call a model provider.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.prompts import PromptComposer, PromptContext, load_stage_prompt  # noqa: E402
from backend.student_journey import DEFAULT_STAGE, STAGE_BY_ID  # noqa: E402


def _demo_context(stage_id: str) -> PromptContext:
    """Build unlabeled demo context for prompt preview only."""
    return PromptContext(
        current_stage=stage_id,
        student_project_context=(
            "Design project exploring safer pedestrian crossings for older adults "
            "near schools."
        ),
        retrieved_course_context=(
            "--- [S1] Demo lecture excerpt ---\n"
            "Older pedestrians may require longer crossing intervals."
        ),
        conversation_summary=(
            "The student is clarifying a workable research question about crossing "
            "design for older pedestrians."
        ),
        recent_messages=[
            {
                "role": "user",
                "content": "I want to evaluate a crossing design near schools.",
            },
            {
                "role": "assistant",
                "content": "What outcome for older pedestrians matters most?",
            },
        ],
        student_message=(
            "I will compare signal timing so older pedestrians have enough time "
            "to cross safely."
        ),
        response_detail="short",
        allow_model_knowledge=False,
    )


def main(argv: list[str] | None = None) -> int:
    """Print labeled prompt sections for one Thinking Path stage."""
    parser = argparse.ArgumentParser(
        description="Preview a composed coaching prompt with demo context only."
    )
    parser.add_argument(
        "--stage",
        default=DEFAULT_STAGE,
        choices=sorted(STAGE_BY_ID),
        help="Authoritative Thinking Path stage ID",
    )
    parser.add_argument(
        "--empty-sources",
        action="store_true",
        help="Preview with no retrieved source context",
    )
    args = parser.parse_args(argv)

    # Touch the stage file early so typos fail before composition.
    load_stage_prompt(args.stage)
    context = _demo_context(args.stage)
    if args.empty_sources:
        context = context.model_copy(update={"retrieved_course_context": ""})
    prepared = PromptComposer().compose(context)

    stage_label = STAGE_BY_ID[args.stage].short_label.upper()
    print("================ SHARED ================")
    print(prepared.shared_instructions.strip())
    print()
    print(f"================ STAGE: {stage_label} ================")
    print(prepared.stage_instructions.strip())
    print()
    print("================ STUDENT PROJECT CONTEXT ================")
    print(context.student_project_context.strip())
    print()
    print("================ RETRIEVED SOURCE CONTEXT ================")
    retrieved = (context.retrieved_course_context or "").strip() or (
        "No retrieved source context was provided for this turn."
    )
    print(retrieved)
    print()
    print("================ RECENT MESSAGES ================")
    for message in context.recent_messages:
        role = str(message.get("role", "unknown")).title()
        print(f"{role}: {message.get('content', '')}")
    print()
    print("================ STUDENT MESSAGE ================")
    print(context.student_message.strip())
    print()
    print(f"(composed length: {len(prepared.composed_text)} characters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
