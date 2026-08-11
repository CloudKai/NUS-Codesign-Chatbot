"""Local and optional OpenAI model adapters for structured coaching output.

Providers consume a server-composed prompt from ``backend.prompts`` and focus on
invocation, structured output, model arguments, and error translation. They do
not own six-stage educational wording. When ``CoachRequest.image_inputs`` is
present, Ollama receives base64 ``images`` and OpenAI receives multimodal
``input_image`` parts alongside the composed text prompt.
"""

from __future__ import annotations

from typing import Any

import httpx
from openai import OpenAI

from .domain import CoachRequest, ProviderCoachOutput, StageDecision, openai_strict_schema
from .mock_provider import DeterministicCoachProvider
from .prompts import compose_coach_prompt
from .settings import settings


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
        prompt = compose_coach_prompt(request).composed_text
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
                                "You are a warm, Socratic university critical-thinking coach. "
                                "Return only JSON matching the supplied schema. Recommend "
                                "advance when the student has clearly met the current stage; "
                                "otherwise stay. Cite sources only with [S#] when they matter."
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


class OpenAICoachProvider:
    """Call the OpenAI Responses API for a validated structured coaching assessment."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reasoning_effort: str = "low",
        timeout_seconds: float = 110.0,
        max_retries: int = 0,
    ) -> None:
        cleaned_key = str(api_key or "").strip()
        if not cleaned_key:
            raise ProviderUnavailableError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(
            api_key=cleaned_key,
            timeout=float(timeout_seconds),
            max_retries=int(max_retries),
        )
        self._model = model
        self._reasoning_effort = reasoning_effort

    def assess(self, request: CoachRequest) -> tuple[str, Any]:
        """Request JSON-schema output from the optional paid OpenAI provider."""
        try:
            prompt = compose_coach_prompt(request).composed_text
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
            effort = (
                request.reasoning_effort
                if request.reasoning_effort is not None
                else self._reasoning_effort
            )
            if effort:
                create_kwargs["reasoning"] = {"effort": effort}
            response = self._client.responses.create(**create_kwargs)
            turn = ProviderCoachOutput.model_validate_json(response.output_text)
        except Exception as error:
            # Provider errors are translated at the application boundary.
            raise ProviderUnavailableError(
                "OpenAI could not create a structured coaching turn"
            ) from error
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
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
    raise ProviderUnavailableError(f"Unsupported MODEL_PROVIDER: {settings.model_provider}")
