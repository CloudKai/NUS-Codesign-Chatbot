"""Authored stage deliverable criteria, projected read-only next to saved work.

The lines restate the existing CDE2300-aligned deliverable expectations that
already drive ``project_resume`` actions and the lecture tools — they add no
schedule, assessment rule or completion authority. Stage completion and
advancement remain owned by ``LearningProgressService`` confirmation.
"""

from __future__ import annotations

from backend.learning.stages import STAGE_BY_ID

_STAGE_CRITERIA: dict[str, tuple[str, ...]] = {
    "problem_identification": (
        "Names the affected people and their context.",
        "Describes the outcome they need without fixing one solution.",
        "Points to evidence from interviews or fieldwork.",
    ),
    "concept_generation": (
        "Describes at least two distinct concepts.",
        "Says how each concept addresses the need.",
        "Compares the concepts instead of choosing one too early.",
    ),
    "design_specification": (
        "Chooses one requirement and explains its rationale.",
        "Describes how success would be tested.",
        "States the constraints the design must respect.",
    ),
    "deep_analysis": (
        "Identifies one possible harm and who could be affected.",
        "Names the assumption or trade-off being examined.",
        "Suggests a mitigation or the evidence to check.",
    ),
    "reflection": (
        "Explains one change in your thinking.",
        "Gives the evidence that changed it.",
        "Names what remains uncertain.",
    ),
}


def stage_criteria(stage_id: str) -> tuple[str, ...]:
    """Return the authored criteria for one stage's deliverable.

    Args:
        stage_id: Canonical Thinking Path stage id.

    Returns:
        Short deterministic criteria lines; empty for unknown stage ids so a
        saved-but-unrecognized stage can never invent requirements.
    """
    if stage_id not in STAGE_BY_ID:
        return ()
    return _STAGE_CRITERIA[stage_id]
