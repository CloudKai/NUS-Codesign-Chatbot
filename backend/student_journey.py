from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ThinkingStage:
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
RESPONSE_DETAILS = ("short", "long")
_STAGE_DECISION = re.compile(
    r"<!--\s*stage\s*:\s*(advance|stay)\s*-->",
    re.IGNORECASE,
)
_CONTRIBUTION_RESTATEMENT = re.compile(
    r"(?m)^(?:You(?:'|’)re exploring|I understand your current contribution as):.*"
    r"(?:\n\n|$)",
)
_STAGE_SIGNALS: dict[str, tuple[str, ...]] = {
    "focus": (
        "question",
        "problem",
        "claim",
        "focus",
        "understand",
        "evaluate",
        "compare",
        "whether",
    ),
    "evidence": (
        "evidence",
        "source",
        "data",
        "study",
        "result",
        "finding",
        "example",
        "reliable",
        "sample",
    ),
    "assumptions": (
        "assume",
        "assumption",
        "because",
        "depends",
        "implies",
        "premise",
        "believe",
        "uncertain",
    ),
    "perspectives": (
        "alternative",
        "counter",
        "however",
        "another",
        "perspective",
        "objection",
        "although",
        "whereas",
    ),
    "synthesis": (
        "overall",
        "therefore",
        "weigh",
        "balance",
        "combined",
        "considering",
        "stronger",
        "suggests",
    ),
    "conclusion": (
        "conclude",
        "conclusion",
        "confidence",
        "confident",
        "limitation",
        "remains",
        "qualified",
        "next step",
    ),
}
_STAGE_GUIDANCE: dict[str, tuple[str, str, str]] = {
    "focus": (
        "What exactly are you trying to understand, explain, or argue?",
        "Can you state the central question or claim in one clear sentence?",
        "What would a useful answer help you decide or do?",
    ),
    "evidence": (
        "Which evidence matters most, and how reliable is it?",
        "What does the strongest source directly support?",
        "What limitation could weaken that evidence?",
    ),
    "assumptions": (
        "What are you assuming, and which assumption is most uncertain?",
        "Which unstated premise connects your evidence to your claim?",
        "What changes if that premise is false?",
    ),
    "perspectives": (
        "What is the strongest alternative explanation or counterargument?",
        "Who might interpret the same evidence differently, and why?",
        "What would the strongest critic say about your reasoning?",
    ),
    "synthesis": (
        "How should your claim change after considering the evidence and alternatives?",
        "Which considerations deserve the most weight?",
        "Where do the competing perspectives agree or remain unresolved?",
    ),
    "conclusion": (
        "What can you conclude now, with what confidence, and what remains unresolved?",
        "Which limitation should qualify your conclusion?",
        "What is the most justified next step?",
    ),
}


def default_journey() -> dict[str, Any]:
    return {
        "current_stage": DEFAULT_STAGE,
        "completed_stages": [],
        "stage_notes": {},
        "working_conclusion": "",
        "critical_reflection": "",
        "response_detail": "short",
    }


def normalize_journey(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    journey = default_journey()
    current_stage = raw.get("current_stage")
    journey["current_stage"] = current_stage if current_stage in STAGE_BY_ID else DEFAULT_STAGE
    completed = raw.get("completed_stages")
    if isinstance(completed, list):
        journey["completed_stages"] = [
            stage.id for stage in THINKING_STAGES if stage.id in set(completed)
        ]
    if (
        journey["current_stage"] in journey["completed_stages"]
        and journey["current_stage"] != THINKING_STAGES[-1].id
    ):
        current_index = next(
            index
            for index, stage in enumerate(THINKING_STAGES)
            if stage.id == journey["current_stage"]
        )
        journey["current_stage"] = next(
            (
                stage.id
                for stage in THINKING_STAGES[current_index + 1 :]
                if stage.id not in journey["completed_stages"]
            ),
            THINKING_STAGES[-1].id,
        )
    notes = raw.get("stage_notes")
    if isinstance(notes, dict):
        journey["stage_notes"] = {
            stage.id: str(notes.get(stage.id, "")).strip()
            for stage in THINKING_STAGES
            if str(notes.get(stage.id, "")).strip()
        }
    journey["working_conclusion"] = str(raw.get("working_conclusion", "")).strip()
    journey["critical_reflection"] = str(raw.get("critical_reflection", "")).strip()
    detail = str(raw.get("response_detail", "short")).lower()
    journey["response_detail"] = detail if detail in RESPONSE_DETAILS else "short"
    return journey


def current_stage(journey: dict[str, Any]) -> ThinkingStage:
    normalized = normalize_journey(journey)
    return STAGE_BY_ID[normalized["current_stage"]]


def stage_guidance_questions(stage_id: str) -> tuple[str, str, str]:
    return _STAGE_GUIDANCE.get(stage_id, _STAGE_GUIDANCE[DEFAULT_STAGE])


def personalized_stage_questions(
    stage_id: str,
    student_contribution: str,
    *,
    has_course_sources: bool = False,
) -> tuple[str, ...]:
    """Create concise next-step prompts tied to the student's current topic.

    This helper personalizes coaching language only; it never decides whether a
    stage is complete. Provider-generated questions remain preferred when they
    are available, while this deterministic fallback keeps mock and offline
    demonstrations useful.
    """
    normalized = " ".join(student_contribution.lower().split())
    older_adult_topic = any(
        phrase in normalized
        for phrase in (
            "elderly",
            "older adult",
            "older people",
            "older pedestrian",
            "senior",
            "aged",
        )
    )
    evidence_reference = (
        "the selected lecture notes or readings"
        if has_course_sources
        else "the course materials"
    )

    if stage_id == "evidence":
        population_question = (
            "Which group of older adults are you focusing on—for example, people "
            "with limited mobility, slower walking speeds, visual impairments, or "
            "cognitive difficulties?"
            if older_adult_topic
            else "Which specific people, setting, or situation within your topic should "
            "you focus on first?"
        )
        return (
            population_question,
            f"What evidence in {evidence_reference} supports that focus, and what are "
            "the limits of that evidence?",
        )
    if stage_id == "assumptions":
        subject = "older adults" if older_adult_topic else "the people in your chosen context"
        return (
            f"What are you assuming about {subject}, and which assumption is least certain?",
            f"Does {evidence_reference} support that assumption, challenge it, or leave it unresolved?",
        )
    if stage_id == "perspectives":
        subject = "older adults, caregivers, and road users" if older_adult_topic else "the affected groups"
        return (
            f"How might {subject} view the problem differently?",
            f"Which perspective is missing from {evidence_reference}, and why might it matter?",
        )
    if stage_id == "synthesis":
        return (
            "Which pieces of evidence should carry the most weight in your current reasoning?",
            f"How should your idea change after comparing the tensions or limits in {evidence_reference}?",
        )
    if stage_id == "conclusion":
        return (
            "What can you conclude now, and how confident are you in that conclusion?",
            f"Which limitation in {evidence_reference} should qualify your conclusion?",
        )
    return stage_guidance_questions(stage_id)[:2]


def advanced_stage_response(
    response_text: str,
    current_stage_id: str,
    next_stage_id: str,
    questions: Iterable[str],
) -> str:
    """Present an automatic transition as the new stage plus useful questions."""
    current_stage_value = STAGE_BY_ID[current_stage_id]
    next_stage_value = STAGE_BY_ID[next_stage_id]
    response_body = response_text.strip()
    current_heading = f"**{current_stage_value.label}**"
    if response_body.startswith(current_heading):
        response_body = response_body[len(current_heading) :].strip()
    legacy_notice = (
        f"**Thinking Path:** I’ve moved you to {next_stage_value.short_label}."
    )
    response_body = response_body.replace(legacy_notice, "").strip()
    normalized_questions = [question.strip() for question in questions if question.strip()]
    question_list = "\n".join(f"- {question}" for question in normalized_questions)
    return (
        f"**{next_stage_value.label}**\n\n"
        f"{response_body}\n\n"
        f"**Questions to explore**\n\n{question_list}"
    ).strip()


def concise_coach_response(response_text: str) -> str:
    """Hide legacy contribution restatements while preserving canonical history."""
    return _CONTRIBUTION_RESTATEMENT.sub("", response_text, count=1).strip()


def set_current_stage(journey: dict[str, Any], stage_id: str) -> dict[str, Any]:
    normalized = normalize_journey(journey)
    if stage_id not in STAGE_BY_ID:
        raise ValueError(f"Unknown thinking stage: {stage_id}")
    normalized["current_stage"] = stage_id
    return normalized


def complete_and_advance(
    journey: dict[str, Any],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    if note is not None and note.strip():
        normalized["stage_notes"][stage.id] = note.strip()
    if stage.id not in normalized["completed_stages"]:
        normalized["completed_stages"].append(stage.id)
    index = next(index for index, item in enumerate(THINKING_STAGES) if item.id == stage.id)
    if index < len(THINKING_STAGES) - 1:
        normalized["current_stage"] = THINKING_STAGES[index + 1].id
    return normalize_journey(normalized)


def contribution_supports_stage(content: str, stage_id: str) -> bool:
    """Fallback assessment when a model response omits its hidden stage decision."""
    normalized = " ".join(content.lower().split())
    words = re.findall(r"[a-z0-9']+", normalized)
    if stage_id not in STAGE_BY_ID or len(words) < 8:
        return False
    signals = _STAGE_SIGNALS[stage_id]
    signal_count = sum(1 for signal in signals if signal in normalized)
    if signal_count:
        return True
    return len(words) >= 24


def automatic_stage_update(
    journey: dict[str, Any],
    student_contribution: str,
    assistant_response: str,
    *,
    allow_advance: bool = True,
) -> tuple[dict[str, Any], str, str]:
    """Apply the coach's hidden decision and return clean assistant text."""
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    decisions = _STAGE_DECISION.findall(assistant_response)
    clean_response = _STAGE_DECISION.sub("", assistant_response).strip()
    if not allow_advance:
        decision = "stay"
    elif decisions:
        decision = decisions[-1].lower()
    else:
        decision = (
            "advance"
            if contribution_supports_stage(student_contribution, stage.id)
            else "stay"
        )
    if decision == "advance":
        normalized = complete_and_advance(
            normalized,
            note=student_contribution,
        )
        if stage.id in {"synthesis", "conclusion"}:
            normalized["working_conclusion"] = student_contribution.strip()
        if stage.id != "focus":
            normalized["critical_reflection"] = (
                f"The discussion advanced from {stage.label.lower()} after the student "
                "made the reasoning for this stage explicit."
            )
    return normalize_journey(normalized), decision, clean_response


def journey_progress(journey: dict[str, Any]) -> int:
    normalized = normalize_journey(journey)
    return round(len(normalized["completed_stages"]) / len(THINKING_STAGES) * 100)


def understanding_level(journey: dict[str, Any]) -> tuple[str, str]:
    completed = len(normalize_journey(journey)["completed_stages"])
    if completed <= 1:
        return "Emerging", "You are clarifying the problem and beginning to identify relevant reasoning."
    if completed <= 3:
        return "Developing", "You are connecting evidence, assumptions, and alternative perspectives."
    if completed <= 5:
        return "Connected", "You are synthesizing competing considerations into a defensible position."
    return "Integrated", "You have worked through the full reasoning cycle and recorded a conclusion."


def _student_messages(messages: Iterable[dict[str, Any]]) -> list[str]:
    return [
        " ".join(str(message.get("content", "")).split())
        for message in messages
        if message.get("role") == "user" and str(message.get("content", "")).strip()
    ]


def _prompt_summary(student_messages: list[str], detail: str) -> str:
    if not student_messages:
        return "Your main questions and requests will be summarized here after you start chatting."
    unique_prompts: list[str] = []
    for prompt in student_messages:
        if prompt not in unique_prompts:
            unique_prompts.append(prompt)
    limit = 3 if detail == "short" else 6
    selected = unique_prompts[-limit:]
    clipped = [
        prompt if len(prompt) <= 180 else f"{prompt[:177].rstrip()}…"
        for prompt in selected
    ]
    if len(clipped) == 1:
        return f'Your discussion is focused on: “{clipped[0]}”'
    return "Your discussion has focused on " + "; ".join(
        f"“{prompt}”" for prompt in clipped
    ) + "."


_DEFAULT_REVIEW_FEEDBACK: dict[str, tuple[str, tuple[str, str]]] = {
    "focus": (
        "You have identified a meaningful topic and are asking a question that can be refined.",
        (
            "Name the specific group, setting, or context you want to study.",
            "Choose one outcome that would show meaningful change.",
        ),
    ),
    "evidence": (
        "You are bringing evidence into the discussion instead of relying on a claim alone.",
        (
            "Compare the quality and relevance of your strongest sources.",
            "Name one limitation that could weaken the evidence.",
        ),
    ),
    "assumptions": (
        "You are beginning to make the reasoning behind your claim visible.",
        (
            "State the assumption connecting your evidence to your claim.",
            "Test what changes if that assumption is false.",
        ),
    ),
    "perspectives": (
        "You are considering more than one plausible interpretation.",
        (
            "Represent the strongest competing explanation fairly.",
            "Explain what evidence would distinguish between the views.",
        ),
    ),
    "synthesis": (
        "You are weighing evidence and alternatives rather than listing them separately.",
        (
            "Explain which consideration deserves the most weight and why.",
            "Qualify your claim where the evidence remains uncertain.",
        ),
    ),
    "conclusion": (
        "You are forming a conclusion that reflects the reasoning developed in this notebook.",
        (
            "State your confidence and the most important limitation.",
            "Identify the next justified question or action.",
        ),
    ),
}


def _latest_assessment(messages: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest assistant assessment payload, if one was persisted."""
    for message in reversed(list(messages)):
        if message.get("role") != "assistant":
            continue
        assessment = (message.get("metadata") or {}).get("assessment")
        if isinstance(assessment, dict) and assessment.get("recommendation"):
            return assessment
    return None


def _personalized_review_feedback(
    stage_id: str,
    assessment: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Build strengths and improvement items from the latest coach assessment."""
    fallback_strength, fallback_areas = _DEFAULT_REVIEW_FEEDBACK.get(
        stage_id,
        _DEFAULT_REVIEW_FEEDBACK["focus"],
    )
    if not assessment:
        return fallback_strength, list(fallback_areas)

    stage_assessment = " ".join(
        str(assessment.get("stage_assessment") or "").split()
    ).strip()
    contribution = " ".join(
        str(assessment.get("contribution_summary") or "").split()
    ).strip()
    evidence = [
        " ".join(str(item).split()).strip()
        for item in (assessment.get("evidence_identified") or [])
        if str(item).strip()
    ]
    if stage_assessment:
        strengths = stage_assessment
        if contribution and contribution.lower() not in strengths.lower():
            strengths = f"{strengths} Your latest contribution centered on: {contribution}"
    elif contribution:
        strengths = f"Recent progress: {contribution}"
    elif evidence:
        strengths = "Evidence noted: " + "; ".join(evidence[:2])
    else:
        strengths = fallback_strength

    missing = [
        " ".join(str(item).split()).strip()
        for item in (assessment.get("missing_reasoning_elements") or [])
        if str(item).strip()
    ]
    guidance = [
        " ".join(str(item).split()).strip()
        for item in (assessment.get("guidance_questions") or [])
        if str(item).strip()
    ]
    rationale = " ".join(
        str(assessment.get("recommendation_rationale") or "").split()
    ).strip()
    areas = missing[:3]
    if not areas and guidance:
        areas = guidance[:2]
    if not areas and rationale and str(assessment.get("recommendation")) == "stay":
        areas = [rationale]
    if not areas:
        areas = list(fallback_areas)
    return strengths, areas[:3]


def learning_review(
    messages: Iterable[dict[str, Any]],
    journey: dict[str, Any],
    *,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build the Review-tab payload for the current notebook.

    When the newest assistant message includes a structured ``assessment``,
    strengths, improvement areas, understanding level, conclusion, and
    reflection are personalized from that assessment. Otherwise stage fallbacks
    are used so empty notebooks still show guidance.

    Returns:
        A dict consumed by ``ui.studio.render_learning_review``, including
        ``strengths``, ``improvement_areas``, and ``has_personalized_assessment``.
    """
    message_list = list(messages)
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    student_messages = _student_messages(message_list)
    selected_detail = detail if detail in RESPONSE_DETAILS else normalized["response_detail"]
    contribution_limit = 3 if selected_detail == "short" else 8
    contributions = student_messages[-contribution_limit:]
    level, level_description = understanding_level(normalized)
    assessment = _latest_assessment(message_list)
    if assessment:
        assessed_level = str(
            assessment.get("critical_understanding_level") or ""
        ).strip()
        if assessed_level:
            level = assessed_level
            level_description = (
                " ".join(str(assessment.get("stage_assessment") or "").split()).strip()
                or level_description
            )
    strengths, improvement_areas = _personalized_review_feedback(stage.id, assessment)
    completed_labels = [
        STAGE_BY_ID[stage_id].label for stage_id in normalized["completed_stages"]
    ]
    notes = [
        {
            "stage": STAGE_BY_ID[stage_id].label,
            "note": normalized["stage_notes"].get(stage_id, ""),
        }
        for stage_id in normalized["completed_stages"]
        if normalized["stage_notes"].get(stage_id)
    ]
    conclusion = (
        (
            " ".join(str(assessment.get("working_conclusion") or "").split()).strip()
            if assessment
            else ""
        )
        or normalized["working_conclusion"]
        or "The coach has not identified a supported conclusion yet."
    )
    critical_reflection = (
        (
            " ".join(str(assessment.get("understanding_change") or "").split()).strip()
            if assessment
            else ""
        )
        or normalized["critical_reflection"]
        or "The coach will summarize how your understanding changes as the discussion develops."
    )
    return {
        "detail": selected_detail,
        "current_stage": stage.label,
        "progress": journey_progress(normalized),
        "understanding_level": level,
        "understanding_description": level_description,
        "completed_stages": completed_labels,
        "contributions": contributions,
        "prompt_summary": _prompt_summary(student_messages, selected_detail),
        "stage_notes": notes,
        "conclusion": conclusion,
        "critical_reflection": critical_reflection,
        "strengths": strengths,
        "improvement_areas": improvement_areas,
        "next_question": stage.reflection_prompt,
        "turn_count": len(student_messages),
        "has_personalized_assessment": assessment is not None,
    }
