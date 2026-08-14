"""Coach provider selection and optional OpenAI adapter.

Providers consume a server-composed prompt from ``backend.prompts`` and focus on
invocation, structured output, model arguments, and error translation. They do
not own five-stage educational wording. When ``CoachRequest.image_inputs`` is
present, OpenAI receives multimodal ``input_image`` parts alongside the composed
text prompt. Bedrock lives in ``backend.bedrock_provider`` and is selected here.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from .domain import (
    CoachRequest,
    ProviderAssessmentResult,
    ProviderCoachOutput,
    StageDecision,
    openai_strict_schema,
)
from .mock_provider import DeterministicCoachProvider
from .prompts import compose_coach_prompt
from .settings import settings


class ProviderUnavailableError(RuntimeError):
    """Raised when a configured local or hosted model provider cannot be used."""


class OpenAICoachProvider:
    """Call the OpenAI Responses API for a validated structured coaching assessment."""

    provider_id = "openai"

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

    def model_id_for(self, request: CoachRequest) -> str:
        """Return the actual OpenAI model invoked for this request."""
        return self._model

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
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
        return ProviderAssessmentResult(
            response_text=turn.response_text,
            assessment=assessment,
            research_coding=turn.research_coding,
        )


def configured_coach_provider():
    """Create the configured provider while keeping tests fully API-free by default."""
    if settings.model_provider == "mock":
        recommendation = StageDecision.ADVANCE if settings.mock_recommend_advance else None
        return DeterministicCoachProvider(recommendation)
    if settings.model_provider == "openai":
        return OpenAICoachProvider(
            settings.openai_api_key,
            settings.openai_chat_model,
            reasoning_effort=settings.default_reasoning_effort,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
    if settings.model_provider == "bedrock":
        from backend.bedrock_provider import BedrockCoachProvider

        return BedrockCoachProvider(
            settings.bedrock_model_id,
            region=settings.aws_region,
            timeout_seconds=settings.bedrock_timeout_seconds,
            max_retries=settings.bedrock_max_retries,
        )
    raise ProviderUnavailableError(f"Unsupported MODEL_PROVIDER: {settings.model_provider}")
