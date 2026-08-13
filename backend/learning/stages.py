"""Immutable definitions for the six-stage Thinking Path."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThinkingStage:
    """One ordered stage in the student critical-thinking journey."""

    id: str
    label: str
    short_label: str
    description: str
    reflection_prompt: str


THINKING_STAGES: tuple[ThinkingStage, ...] = (
    ThinkingStage(
        "focus",
        "Define the focus",
        "Focus",
        "Clarify the question, problem, or claim you are trying to address.",
        "What exactly are you trying to understand, explain, or argue?",
    ),
    ThinkingStage(
        "evidence",
        "Examine evidence",
        "Evidence",
        "Identify the relevant evidence and judge its quality and limits.",
        "Which evidence matters most, and how reliable is it?",
    ),
    ThinkingStage(
        "assumptions",
        "Surface assumptions",
        "Assumptions",
        "Make the hidden premises and interpretations in your reasoning explicit.",
        "What are you assuming, and which assumption is most uncertain?",
    ),
    ThinkingStage(
        "perspectives",
        "Compare perspectives",
        "Perspectives",
        "Test alternatives, objections, and plausible competing explanations.",
        "What is the strongest alternative explanation or counterargument?",
    ),
    ThinkingStage(
        "synthesis",
        "Synthesize the reasoning",
        "Synthesis",
        "Weigh the evidence and alternatives, then refine the position.",
        "How should your claim change after considering the evidence and alternatives?",
    ),
    ThinkingStage(
        "conclusion",
        "Form a conclusion",
        "Conclusion",
        "State a qualified conclusion, its limits, and the next justified step.",
        "What can you conclude now, with what confidence, and what remains unresolved?",
    ),
)

STAGE_BY_ID = {stage.id: stage for stage in THINKING_STAGES}
DEFAULT_STAGE = THINKING_STAGES[0].id
