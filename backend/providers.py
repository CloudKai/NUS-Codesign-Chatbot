"""Local and optional OpenAI model adapters for structured coaching output.

Providers return validated ``ProviderCoachOutput`` JSON. When
``CoachRequest.image_inputs`` is present, Ollama receives base64 ``images`` and
OpenAI receives multimodal ``input_image`` parts alongside the text prompt.
"""

from __future__ import annotations

from typing import Any

import httpx
from openai import OpenAI

from .domain import CoachRequest, ProviderCoachOutput, StageDecision, openai_strict_schema
from .mock_provider import DeterministicCoachProvider
from .settings import settings
from .student_journey import STAGE_BY_ID


class ProviderUnavailableError(RuntimeError):
    """Raised when a configured local or hosted model provider cannot be used."""


def _image_data_payloads(request: CoachRequest) -> list[str]:
    """Return raw base64 payloads for providers that reject data URLs (Ollama)."""
    payloads: list[str] = []
    for image in request.image_inputs:
        data_url = image.data_url
        if "," in data_url:
            payloads.append(data_url.split(",", 1)[1])
        else:
            payloads.append(data_url)
    return payloads


class OllamaCoachProvider:
    """Call a local Ollama chat model and validate its JSON coaching result."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 90.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def assess(self, request: CoachRequest) -> tuple[str, Any]:
        """Generate a JSON turn from Ollama without exposing provider details upstream."""
        schema = openai_strict_schema(ProviderCoachOutput)
        prompt = self._prompt(request)
        user_message: dict[str, Any] = {"role": "user", "content": prompt}
        image_payloads = _image_data_payloads(request)
        if image_payloads:
            user_message["images"] = image_payloads
        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "format": schema,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a university critical-thinking coach. Return only JSON "
                                "matching the supplied schema. Recommend advance when the "
                                "student has clearly met the current stage; otherwise stay."
                            ),
                        },
                        user_message,
                    ],
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            content = str(response.json()["message"]["content"])
            turn = ProviderCoachOutput.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise ProviderUnavailableError(
                "Ollama is unavailable or returned invalid structured output. Start Ollama, "
                f"then download the configured model with: ollama pull {self._model}"
            ) from error
        assessment = turn.assessment.model_copy(
            update={"current_stage": request.current_stage}
        )
        return turn.response_text, assessment

    @staticmethod
    def _prompt(request: CoachRequest) -> str:
        """Create a compact, history-aware prompt for one structured coaching turn."""
        stage = STAGE_BY_ID[request.current_stage]
        recent_history = "\n".join(
            f"{str(message.get('role', 'unknown')).title()}: "
            f"{' '.join(str(message.get('content', '')).split())[:800]}"
            for message in request.history[-6:]
            if str(message.get("content", "")).strip()
        )
        image_note = ""
        if request.image_inputs:
            labels = ", ".join(image.source_id for image in request.image_inputs)
            image_note = (
                f"Attached notebook images ({len(request.image_inputs)}): {labels}. "
                "Inspect the image content as selected evidence."
            )
        return "\n\n".join(
            part
            for part in (
                (
                    "You are a university critical-thinking coach. Assess only the current "
                    "stage and return the required structured result."
                    + (
                        " When you recommend advance, the application will automatically move "
                        "the student to the next stage."
                        if settings.auto_advance_stages
                        else " A recommendation to advance waits for student confirmation."
                    )
                ),
                f"Current stage: {stage.short_label} — {stage.description}",
                f"Stage question: {stage.reflection_prompt}",
                f"Response detail: {request.response_detail}",
                f"Recent conversation:\n{recent_history}" if recent_history else "",
                f"Student contribution: {request.student_message}",
                f"Selected source context:\n{request.source_context}" if request.source_context else "",
                image_note,
                (
                    "Broader knowledge is allowed when sources do not answer the question."
                    if request.allow_model_knowledge
                    else "Use selected sources as the factual evidence base."
                ),
                (
                    "Respond directly to the latest contribution. If the student should stay, "
                    "name one specific missing reasoning element and ask one tailored question. "
                    "Do not restate the student's contribution with phrases such as "
                    "'You're exploring' or 'I understand your contribution as'. "
                    "Do not repeat a generic reflection question that the student has already "
                    "attempted to answer. If the stage is sufficiently addressed, recommend "
                    "advance and explain what became clear. When recommending advance, put "
                    "one or two questions for the next stage in guidance_questions. Tailor "
                    "them to the student's specific topic and the selected course sources; "
                    "do not announce that the application moved stages."
                ),
                (
                    "Guidance mode: Quick. Recommend advance once the student has a "
                    "workable answer for this stage's core purpose, even if details "
                    "are still thin. Prefer progress, and keep follow-up questions light."
                    if request.response_detail == "short"
                    else (
                        "Guidance mode: Complex. Recommend advance only when the "
                        "contribution is thorough for this stage—specific claims, clear "
                        "reasoning, and limited ambiguity. Prefer stay when important "
                        "elements are still missing."
                    )
                ),
                (
                    "Stage-specific advance rule for Focus: recommend advance once the "
                    "student states a workable research question that names the group or "
                    "setting and the outcome of interest. Do not keep them on Focus only "
                    "because a measure is imperfectly defined; that belongs in Evidence. "
                    "For later stages, advance only when the contribution clearly addresses "
                    "that stage's purpose."
                    if request.current_stage == "focus"
                    else (
                        "Advance only when the contribution clearly addresses this stage's "
                        "purpose; otherwise stay with one precise missing element."
                    )
                ),
            )
            if part
        )


class OpenAICoachProvider:
    """Call the OpenAI Responses API for a validated structured coaching assessment."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reasoning_effort: str = "low",
    ) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort

    def assess(self, request: CoachRequest) -> tuple[str, Any]:
        """Request JSON-schema output from the optional paid OpenAI provider."""
        if not settings.openai_api_key:
            raise ProviderUnavailableError("OPENAI_API_KEY is not configured")
        try:
            prompt = OllamaCoachProvider._prompt(request)
            if request.image_inputs:
                content: list[dict[str, Any]] = [
                    {"type": "input_text", "text": prompt}
                ]
                for image in request.image_inputs:
                    content.append(
                        {
                            "type": "input_image",
                            "image_url": image.data_url,
                            "detail": "auto",
                        }
                    )
                model_input: Any = [{"role": "user", "content": content}]
            else:
                model_input = prompt
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": model_input,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "coach_turn",
                        "strict": True,
                        "schema": openai_strict_schema(ProviderCoachOutput),
                    }
                },
            }
            if self._reasoning_effort:
                create_kwargs["reasoning"] = {"effort": self._reasoning_effort}
            response = self._client.responses.create(**create_kwargs)
            turn = ProviderCoachOutput.model_validate_json(response.output_text)
        except Exception as error:  # Provider errors are translated at the application boundary.
            raise ProviderUnavailableError("OpenAI could not create a structured coaching turn") from error
        # The request owns the active stage; providers sometimes mis-label it.
        assessment = turn.assessment.model_copy(
            update={"current_stage": request.current_stage}
        )
        return turn.response_text, assessment


def configured_coach_provider():
    """Create the configured provider while keeping tests fully API-free by default."""
    if settings.model_provider == "mock":
        recommendation = StageDecision.ADVANCE if settings.mock_recommend_advance else None
        return DeterministicCoachProvider(recommendation)
    if settings.model_provider == "ollama":
        return OllamaCoachProvider(settings.ollama_base_url, settings.ollama_chat_model)
    if settings.model_provider == "openai":
        return OpenAICoachProvider(
            settings.openai_api_key,
            settings.openai_chat_model,
            reasoning_effort=settings.default_reasoning_effort,
        )
    raise ProviderUnavailableError(f"Unsupported MODEL_PROVIDER: {settings.model_provider}")
