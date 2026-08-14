"""Compose shared + stage + turn context into one provider-ready prompt.

Composition only: no Streamlit, model-provider SDKs, cloud retrieval SDKs,
or persistence imports.

Current seam (selected sources → local chunk retrieval → composer → provider)::

    Query-ranked excerpts from selected notebook sources
            ↓
    PromptComposer.compose / compose_coach_prompt
            ↓
    configured generation provider (local OpenAI test path today)

Future seam (Knowledge Base replaces only the retriever implementation)::

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
COACH_PROMPT_VERSION = "five-phase-research-v1"

# Bound dynamic sections so composition never injects whole PDFs or unbounded history.
# Retrieved context is capped economically for the temporary pre-Bedrock OpenAI
# testing path; a future KB adapter must respect the same composition budget.
MAX_PROJECT_CONTEXT_CHARS = 8_000
MAX_RETRIEVED_CONTEXT_CHARS = 24_000
MAX_CONVERSATION_SUMMARY_CHARS = 4_000
MAX_RECENT_MESSAGES = 6
MAX_RECENT_MESSAGE_CHARS = 800
MAX_STUDENT_MESSAGE_CHARS = 12_000
MAX_RUNTIME_CHARS = 4_000
MAX_COMPOSED_PROMPT_CHARS = 200_000

_EMPTY_PROJECT = "No student project context was provided for this turn."
_EMPTY_SUMMARY = "No conversation summary was provided for this turn."
_EMPTY_RECENT = "No recent messages were provided for this turn."
_EMPTY_STUDENT = "(empty student message)"


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
    response_language: str = "English"
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
    if limit <= 0:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    if limit == 1:
        return "…"
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _format_recent_messages(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = MAX_RECENT_MESSAGES,
) -> str:
    """Render a bounded recent-history block for the model.

    Older messages are dropped first when ``max_messages`` shrinks for budget.
    """
    if max_messages <= 0:
        return ""
    lines: list[str] = []
    for message in messages[-max_messages:]:
        content = " ".join(str(message.get("content", "")).strip().split())
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
            "Guidance mode: Strict. Recommend advance only when the "
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
    language = " ".join(str(context.response_language or "English").split())[:50]
    parts.append(
        f"Respond to the student in {language}. Keep source labels such as [S1] unchanged."
    )
    if settings.effective_auto_advance_stages:
        parts.append(
            "When you recommend advance, the application will automatically move "
            "the student to the next stage—write as if already coaching that next "
            "skill, with no confirmation language."
        )
    elif settings.student_stage_selection:
        parts.append(
            "The student can choose any Thinking Path stage in Journey. Recommend "
            "ADVANCE only when the current stage purpose is adequately met; do not "
            "assume a fixed linear order. A recommendation may wait for student "
            "confirmation via Next, or the student may switch stages themselves."
        )
    else:
        parts.append(
            "A recommendation to advance waits for student confirmation."
        )
    if context.image_note.strip():
        parts.append(context.image_note.strip())
    if context.retrieved_course_context.strip():
        parts.append(
            "Grounding mode: retrieved blocks are query-ranked excerpts, not "
            "complete documents. Use only excerpt content that directly supports "
            "the claim. Put the stable [S#] citation immediately after the "
            "supported claim; do not expose internal excerpt/chunk identifiers."
        )
    parts.append(
        "Return only the required one-call structured JSON envelope containing "
        "the complete coaching result and optional provisional research coding. "
        "Research coding must never alter coaching or stage progression. Include Facione scores "
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


def _join_sections(
    *,
    shared: str,
    stage: str,
    stage_id: str,
    project: str,
    retrieved: str,
    summary: str,
    recent: str,
    student: str,
    runtime: str,
) -> str:
    """Assemble the ordered prompt with explicit section delimiters."""
    return "\n\n".join(
        [
            _section("shared_coaching", shared),
            _section(
                "stage_instructions",
                stage,
                attrs=f' stage="{stage_id}"',
            ),
            _section("student_project_context", project or _EMPTY_PROJECT),
            _section("retrieved_course_context", retrieved),
            _section("conversation_summary", summary or _EMPTY_SUMMARY),
            _section("recent_messages", recent or _EMPTY_RECENT),
            _section("student_message", student or _EMPTY_STUDENT),
            _section("runtime_instructions", runtime),
        ]
    )


class PromptComposer:
    """Assemble shared + stage + turn context without calling a model provider."""

    def compose(self, context: PromptContext) -> PreparedCoachPrompt:
        """Compose one provider-ready prompt for the authoritative stage.

        Mandatory sections (shared coaching, stage instructions, current student
        message, runtime instructions) are never cut by the final length budget.
        When the total would exceed ``MAX_COMPOSED_PROMPT_CHARS``, lower-priority
        dynamic context is trimmed first: retrieved source text, then older
        recent messages, then conversation summary / project context.

        Args:
            context: Server-built turn context. ``retrieved_course_context`` is
                currently query-ranked local source chunks; a future KB adapter
                may replace only that producer.

        Returns:
            Prepared shared/stage fragments plus the ordered composed text.

        Raises:
            PromptLoadError: Propagated when stage or shared files are invalid.
            ValueError: When mandatory sections alone exceed the total budget.
        """
        shared = load_shared_prompt()
        stage = load_stage_prompt(context.current_stage)
        student = _clip(context.student_message, MAX_STUDENT_MESSAGE_CHARS)
        runtime = _runtime_instructions(context)

        project = _clip(context.student_project_context, MAX_PROJECT_CONTEXT_CHARS)
        retrieved_raw = str(context.retrieved_course_context or "").strip()
        has_retrieved = bool(retrieved_raw)
        retrieved = (
            _clip(retrieved_raw, MAX_RETRIEVED_CONTEXT_CHARS)
            if has_retrieved
            else EMPTY_RETRIEVED_COURSE_CONTEXT
        )
        summary = _clip(context.conversation_summary, MAX_CONVERSATION_SUMMARY_CHARS)
        recent_limit = MAX_RECENT_MESSAGES
        recent = _format_recent_messages(
            list(context.recent_messages),
            max_messages=recent_limit,
        )

        def build() -> str:
            return _join_sections(
                shared=shared,
                stage=stage,
                stage_id=context.current_stage,
                project=project,
                retrieved=retrieved,
                summary=summary,
                recent=recent,
                student=student,
                runtime=runtime,
            )

        composed = build()
        if len(composed) <= MAX_COMPOSED_PROMPT_CHARS:
            return PreparedCoachPrompt(
                shared_instructions=shared,
                stage_instructions=stage,
                composed_text=composed,
            )

        # 1) Shrink retrieved source text first (never inject whole PDFs).
        retrieved_budget = len(retrieved) if has_retrieved else 0
        while (
            len(composed) > MAX_COMPOSED_PROMPT_CHARS
            and has_retrieved
            and retrieved_budget > 0
        ):
            overflow = len(composed) - MAX_COMPOSED_PROMPT_CHARS
            retrieved_budget = max(
                0,
                retrieved_budget - max(overflow, retrieved_budget // 2 or 1),
            )
            if retrieved_budget:
                retrieved = _clip(retrieved_raw, retrieved_budget)
            else:
                retrieved = EMPTY_RETRIEVED_COURSE_CONTEXT
                has_retrieved = False
            composed = build()

        # 2) Drop older recent messages next.
        while len(composed) > MAX_COMPOSED_PROMPT_CHARS and recent_limit > 0:
            recent_limit -= 1
            recent = _format_recent_messages(
                list(context.recent_messages),
                max_messages=recent_limit,
            )
            composed = build()

        # 3) Trim conversation summary, then project context.
        for label in ("summary", "project"):
            while len(composed) > MAX_COMPOSED_PROMPT_CHARS:
                current = summary if label == "summary" else project
                if not current:
                    break
                overflow = len(composed) - MAX_COMPOSED_PROMPT_CHARS
                next_limit = max(0, len(current) - max(overflow, len(current) // 2 or 1))
                trimmed = _clip(current, next_limit) if next_limit else ""
                if label == "summary":
                    summary = trimmed
                else:
                    project = trimmed
                composed = build()
                if trimmed == current:
                    break

        if len(composed) > MAX_COMPOSED_PROMPT_CHARS:
            raise ValueError(
                "Composed coaching prompt exceeds the length budget even after "
                "trimming dynamic context; mandatory shared/stage/student/runtime "
                "sections alone are too large."
            )

        return PreparedCoachPrompt(
            shared_instructions=shared,
            stage_instructions=stage,
            composed_text=composed,
        )


def prompt_context_from_request(request: CoachRequest) -> PromptContext:
    """Build ``PromptContext`` from a server-authoritative ``CoachRequest``.

    ``request.source_context`` maps to ``retrieved_course_context`` (current
    query-ranked local retriever). Future KB retrieval replaces only how that
    string and its audit references are produced before this helper runs.
    """
    image_note = ""
    if request.image_inputs:
        labels_by_source = {
            chunk.source_id: chunk.label for chunk in request.retrieved_chunks
        }
        labels = ", ".join(
            labels_by_source.get(image.source_id, image.source_id)
            for image in request.image_inputs
        )
        image_note = (
            f"Attached notebook images ({len(request.image_inputs)}): {labels}. "
            "Inspect the image content as selected evidence and use its [S#] "
            "label only when the image supports the claim."
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
        response_language=request.response_language,
        image_note=image_note,
    )


def compose_coach_prompt(request: CoachRequest) -> PreparedCoachPrompt:
    """Compose the coaching prompt for one authoritative coach request."""
    return PromptComposer().compose(prompt_context_from_request(request))
