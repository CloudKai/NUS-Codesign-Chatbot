from __future__ import annotations

from dataclasses import dataclass

from .student_journey import current_stage, normalize_journey


@dataclass(frozen=True)
class SupportMode:
    id: str
    label: str
    description: str
    guidance: str
    starters: tuple[str, ...]


SUPPORT_MODES: tuple[SupportMode, ...] = (
    SupportMode(
        "critical-thinking",
        "Critical Thinking Coach",
        "Question assumptions, compare interpretations, and strengthen reasoning.",
        (
            "Use a Socratic coaching approach. Help the student identify the central claim, "
            "surface assumptions, distinguish observations from interpretations, test "
            "alternative explanations, and decide what evidence would change the conclusion. "
            "Do not merely hand over an answer when a short sequence of questions can help the "
            "student reason it out."
        ),
        (
            "Help me test the reasoning in my argument.",
            "What assumptions am I making about this topic?",
            "Compare three plausible explanations for this result.",
        ),
    ),
    SupportMode(
        "assignment-planner",
        "Assignment Planner",
        "Turn a brief or rubric into an achievable plan.",
        (
            "Convert the assignment into deliverables, criteria, dependencies, milestones, "
            "and a realistic work plan. Point out ambiguous requirements and questions the "
            "student should clarify with the instructor. Keep authorship with the student."
        ),
        (
            "Break this assignment into milestones.",
            "Help me interpret this rubric.",
            "Make a study and writing plan for my deadline.",
        ),
    ),
    SupportMode(
        "evidence-review",
        "Evidence Reviewer",
        "Assess source quality, relevance, and gaps.",
        (
            "Evaluate whether each source actually supports the claim. Separate source "
            "credibility, relevance, recency, methodology, limitations, and possible bias. "
            "Never invent citations. Clearly label claims that still need verification."
        ),
        (
            "Evaluate whether my evidence supports my conclusion.",
            "Find the evidence gaps in this outline.",
            "Give me a source-evaluation checklist for this topic.",
        ),
    ),
    SupportMode(
        "argument-builder",
        "Argument Builder",
        "Develop a defensible thesis, reasons, objections, and responses.",
        (
            "Help the student construct an argument map: thesis, reasons, evidence, warrants, "
            "counterarguments, and qualified responses. Prefer precise, defensible claims over "
            "overstated ones. Show where reasoning is missing or circular."
        ),
        (
            "Turn these notes into an argument map.",
            "Help me write a defensible thesis.",
            "What is the strongest counterargument to my position?",
        ),
    ),
    SupportMode(
        "writing-feedback",
        "Writing Feedback",
        "Improve clarity, structure, and academic voice without replacing authorship.",
        (
            "Give diagnostic feedback before rewriting. Explain the highest-impact revisions "
            "for logic, structure, clarity, evidence, and citation practice. If providing an "
            "example revision, keep it short and explain why it is better so the student can "
            "apply the technique independently."
        ),
        (
            "Give me feedback on this draft.",
            "Check whether each paragraph advances my thesis.",
            "Help me make this explanation clearer and more concise.",
        ),
    ),
    SupportMode(
        "general-tutor",
        "General Tutor",
        "Explain concepts and support practice across subjects.",
        (
            "Teach at the student's current level. Use worked examples, checks for "
            "understanding, and gradual hints. Encourage the student to attempt the next step "
            "before revealing a complete solution when appropriate."
        ),
        (
            "Explain this concept with an example.",
            "Quiz me on this topic.",
            "Help me understand where my solution went wrong.",
        ),
    ),
)

SUPPORT_MODE_BY_ID = {mode.id: mode for mode in SUPPORT_MODES}
DEFAULT_SUPPORT_MODE = "critical-thinking"


ACADEMIC_INTEGRITY_GUIDANCE = """
You support learning and student authorship. You may explain, coach, critique, outline,
brainstorm, and demonstrate methods. Do not falsely claim that generated work is the
student's own. When a request appears to ask for submission-ready assessed work, help
with reasoning, structure, examples, or feedback and remind the student to follow their
course policy. Never fabricate sources, quotations, data, experiments, or citations.
Clearly distinguish facts, inferences, assumptions, and uncertainties. Encourage the
student to verify important claims against course materials and primary sources.
""".strip()


def get_support_mode(mode_id: str | None) -> SupportMode:
    return SUPPORT_MODE_BY_ID.get(mode_id or "", SUPPORT_MODE_BY_ID[DEFAULT_SUPPORT_MODE])


def build_student_instructions(
    mode_id: str | None,
    *,
    assignment_title: str = "",
    assignment_brief: str = "",
    rubric: str = "",
    course_context: str = "",
    thinking_stage_id: str = "focus",
    response_detail: str = "short",
    response_language: str = "English",
) -> str:
    mode = get_support_mode(mode_id)
    stage = current_stage({"current_stage": thinking_stage_id})
    detail = normalize_journey({"response_detail": response_detail})["response_detail"]
    language = str(response_language or "English").strip() or "English"
    context_parts = [
        f"Assignment title: {assignment_title.strip()}" if assignment_title.strip() else "",
        f"Course or subject: {course_context.strip()}" if course_context.strip() else "",
        f"Assignment brief:\n{assignment_brief.strip()}" if assignment_brief.strip() else "",
        f"Rubric or success criteria:\n{rubric.strip()}" if rubric.strip() else "",
    ]
    context = "\n\n".join(part for part in context_parts if part)
    return "\n\n".join(
        [
            "You are Co-design, a careful learning assistant for university students.",
            ACADEMIC_INTEGRITY_GUIDANCE,
            f"Current support mode: {mode.label}\n{mode.guidance}",
            (
                f"Current thinking stage: {stage.label}\n"
                f"{stage.description}\n"
                f"Use this reflection question to guide the turn: {stage.reflection_prompt}"
            ),
            (
                "Response detail: Short. Be concise and focused: use no more than 3 short "
                "sections or bullets, then end with one stage-appropriate reflection question."
                if detail == "short"
                else
                "Response detail: Long. Give a thorough explanation that connects the claim, "
                "evidence, assumptions, alternatives, and implications. End with a clear "
                "stage-appropriate reflection question."
            ),
            (
                f"Response language: {language}. Respond in {language}. Keep source titles, "
                "proper nouns, quotations, and citation labels in their original language "
                "when translating them would reduce accuracy."
            ),
            (
                "Respond in a useful, encouraging way. Make reasoning visible: identify the "
                "question, relevant evidence, assumptions, alternatives, and a justified next "
                "step. Do not output hidden control markers or claim that you can change the "
                "student's learning stage. Ask a focused clarifying question when more work "
                "is needed at the current stage."
            ),
            f"Student-provided assignment context:\n{context}" if context else "",
        ]
    ).strip()


def critical_thinking_scaffold() -> tuple[str, ...]:
    return (
        "What exactly is the claim or problem?",
        "What evidence is available, and how reliable is it?",
        "Which assumptions connect the evidence to the conclusion?",
        "What alternative explanation or counterargument is strongest?",
        "What information would change the conclusion?",
        "What is the most justified next step?",
    )
