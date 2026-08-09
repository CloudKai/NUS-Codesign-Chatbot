"""Compose shared + stage + turn context into one provider-ready prompt.

Composition only: no Streamlit, model-provider SDKs, cloud retrieval SDKs,
or persistence imports.

Current seam (selected sources → composer → provider)::

    Selected notebook source context
            ↓
    PromptComposer.compose / compose_coach_prompt
            ↓
    configured generation provider (local OpenAI test path today)

Future seam (Knowledge Base replaces only the retrieved-context producer)::

    Bedrock Knowledge Base retrieved chunks
            ↓  (becomes PromptContext.retrieved_course_context)
    PromptComposer  (unchanged composition contract)
            ↓
    configured generation provider

Course PDFs are never prompt-file content. Prompt markdown holds BEHAVIOUR;
retrieved_course_context holds KNOWLEDGE for the turn.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.domain import CoachRequest
from backend.settings import settings

from .loader import load_shared_prompt, load_stage_prompt

EMPTY_RETRIEVED_COURSE_CONTEXT = (
    "No retrieved source context was provided for this turn."
)

# Bound dynamic sections so composition never injects whole PDFs or unbounded history.
MAX_PROJECT_CONTEXT_CHARS = 8_000
MAX_RETRIEVED_CONTEXT_CHARS = 160_000
MAX_CONVERSATION_SUMMARY_CHARS = 4_000
MAX_RECENT_MESSAGES = 6
MAX_RECENT_MESSAGE_CHARS = 800
MAX_STUDENT_MESSAGE_CHARS = 12_000
MAX_RUNTIME_CHARS = 4_000
MAX_COMPOSED_PROMPT_CHARS = 200_000


class PromptContext(BaseModel):
    """Inputs for one composed coaching prompt (server-assembled only)."""

    model_config = ConfigDict(frozen=True)

    current_stage: str
    student_project_context: str = ""
    retrieved_course_context: str = ""
    conversation_summary: str = ""
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    student_message: str = ""
    response_detail: str = "short"
    allow_model_knowledge: bool = False
    image_note: str = ""


class PreparedCoachPrompt(BaseModel):
    """Shared, stage, and fully composed text for one provider invocation."""

    model_config = ConfigDict(frozen=True)

    shared_instructions: str
    stage_instructions: str
    composed_text: str


def _clip(text: str, limit: int) -> str:
    """Trim whitespace-normalized text to ``limit`` characters."""
    cleaned = str(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _format_recent_messages(messages: list[dict[str, Any]]) -> str:
    """Render a bounded recent-history block for the model."""
    lines: list[str] = []
    for message in messages[-MAX_RECENT_MESSAGES:]:
        content = " ".join(str(message.get("content", "")).split()).strip()
        if not content:
            continue
        role = str(message.get("role", "unknown")).title()
        lines.append(f"{role}: {_clip(content, MAX_RECENT_MESSAGE_CHARS)}")
    return "\n".join(lines)


def _runtime_instructions(context: PromptContext) -> str:
    """Build short turn-local guidance (detail, knowledge, images, transition)."""
    parts: list[str] = []
    if context.response_detail == "short":
        parts.append(
            "Guidance mode: Quick. Recommend advance once the student has a "
            "workable answer for this stage's core purpose, even if details "
            "are still thin. Prefer progress, and keep follow-up questions light."
        )
    else:
        parts.append(
            "Guidance mode: Complex. Recommend advance only when the "
            "contribution is thorough for this stage—specific claims, clear "
            "reasoning, and limited ambiguity. Prefer stay when important "
            "elements are still missing."
        )
    if context.allow_model_knowledge:
        parts.append(
            "Broader knowledge is allowed when sources do not answer the question."
        )
    else:
        parts.append(
            "Use selected sources as the factual evidence base when they matter."
        )
    if settings.auto_advance_stages:
        parts.append(
            "When you recommend advance, the application will automatically move "
            "the student to the next stage—write as if already coaching that next "
            "skill, with no confirmation language."
        )
    else:
        parts.append(
            "A recommendation to advance waits for student confirmation."
        )
    if context.image_note.strip():
        parts.append(context.image_note.strip())
    parts.append(
        "Return only the required structured JSON result. Include Facione scores "
        "for all six dimensions using 0=not started, 1=Weak, 2=Unacceptable, "
        "3=Acceptable, 4=Strong. Keep learning_summary synthesized—never paste "
        "prompts. Review strengths and improvements must be specific to this "
        "stage and must not copy the student's wording."
    )
    return _clip("\n".join(parts), MAX_RUNTIME_CHARS)


def _section(tag: str, body: str, *, attrs: str = "") -> str:
    """Wrap a body in an explicit delimiter block for model context boundaries."""
    open_tag = f"<{tag}{attrs}>"
    close_tag = f"</{tag}>"
    return f"{open_tag}\n{body.strip()}\n{close_tag}"


class PromptComposer:
    """Assemble shared + stage + turn context without calling a model provider."""

    def compose(self, context: PromptContext) -> PreparedCoachPrompt:
        """Compose one provider-ready prompt for the authoritative stage.

        Args:
            context: Server-built turn context. ``retrieved_course_context`` is
                currently selected-source text; a future KB producer may replace
                only that field.

        Returns:
            Prepared shared/stage fragments plus the ordered composed text.

        Raises:
            PromptLoadError: Propagated when stage or shared files are invalid.
        """
        shared = load_shared_prompt()
        stage = load_stage_prompt(context.current_stage)
        project = _clip(context.student_project_context, MAX_PROJECT_CONTEXT_CHARS)
        retrieved_raw = str(context.retrieved_course_context or "").strip()
        retrieved = (
            _clip(retrieved_raw, MAX_RETRIEVED_CONTEXT_CHARS)
            if retrieved_raw
            else EMPTY_RETRIEVED_COURSE_CONTEXT
        )
        summary = _clip(context.conversation_summary, MAX_CONVERSATION_SUMMARY_CHARS)
        recent = _format_recent_messages(list(context.recent_messages))
        student = _clip(context.student_message, MAX_STUDENT_MESSAGE_CHARS)
        runtime = _runtime_instructions(context)

        blocks = [
            _section("shared_coaching", shared),
            _section(
                "stage_instructions",
                stage,
                attrs=f' stage="{context.current_stage}"',
            ),
            _section(
                "student_project_context",
                project or "No student project context was provided for this turn.",
            ),
            _section("retrieved_course_context", retrieved),
            _section(
                "conversation_summary",
                summary or "No conversation summary was provided for this turn.",
            ),
            _section(
                "recent_messages",
                recent or "No recent messages were provided for this turn.",
            ),
            _section("student_message", student or "(empty student message)"),
            _section("runtime_instructions", runtime),
        ]
        composed = "\n\n".join(blocks)
        if len(composed) > MAX_COMPOSED_PROMPT_CHARS:
            composed = composed[: MAX_COMPOSED_PROMPT_CHARS - 1].rstrip() + "…"
        return PreparedCoachPrompt(
            shared_instructions=shared,
            stage_instructions=stage,
            composed_text=composed,
        )


def prompt_context_from_request(request: CoachRequest) -> PromptContext:
    """Build ``PromptContext`` from a server-authoritative ``CoachRequest``.

    ``request.source_context`` maps to ``retrieved_course_context`` (current
    selected-source producer). Future KB retrieval should replace only how that
    string is produced before this helper runs.
    """
    image_note = ""
    if request.image_inputs:
        labels = ", ".join(image.source_id for image in request.image_inputs)
        image_note = (
            f"Attached notebook images ({len(request.image_inputs)}): {labels}. "
            "Inspect the image content as selected evidence."
        )
    return PromptContext(
        current_stage=request.current_stage,
        student_project_context=request.student_project_context,
        retrieved_course_context=request.source_context,
        conversation_summary=request.conversation_summary,
        recent_messages=list(request.history),
        student_message=request.student_message,
        response_detail=request.response_detail,
        allow_model_knowledge=request.allow_model_knowledge,
        image_note=image_note,
    )


def compose_coach_prompt(request: CoachRequest) -> PreparedCoachPrompt:
    """Compose the coaching prompt for one authoritative coach request."""
    return PromptComposer().compose(prompt_context_from_request(request))
