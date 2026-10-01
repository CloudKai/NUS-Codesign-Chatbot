"""Immutable definitions for the five-phase Thinking Path."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThinkingStage:
    """One ordered phase in the student design-thinking journey."""

    id: str
    label: str
    short_label: str
    description: str
    reflection_prompt: str


THINKING_STAGES: tuple[ThinkingStage, ...] = (
    ThinkingStage(
        "problem_identification",
        "Problem identification",
        "Problem",
        "Frame the design problem, who it affects, and why it matters.",
        "What problem are you addressing, for whom, and in what context?",
    ),
    ThinkingStage(
        "concept_generation",
        "Concept generation",
        "Concepts",
        "Generate and compare plausible concepts that respond to the problem.",
        "What distinct concepts could address the problem, and why might each help?",
    ),
    ThinkingStage(
        "design_specification",
        "Design specification",
        "Specification",
        "Make the selected design's requirements, behavior, and constraints explicit.",
        "What must the design do, under which constraints, and how will success be judged?",
    ),
    ThinkingStage(
        "deep_analysis",
        "Ethics & Critical Thinking",
        "Ethics & CT",
        "Critically test the design against evidence, assumptions, trade-offs, risks, and ethical implications.",
        "What evidence, assumption, trade-off, or ethical implication most challenges the current design?",
    ),
    ThinkingStage(
        "reflection",
        "Reflection",
        "Reflection",
        "Evaluate and revise the design reasoning, limits, and next steps.",
        "How has your design reasoning changed, and what remains uncertain?",
    ),
)

STAGE_BY_ID = {stage.id: stage for stage in THINKING_STAGES}
DEFAULT_STAGE = THINKING_STAGES[0].id
