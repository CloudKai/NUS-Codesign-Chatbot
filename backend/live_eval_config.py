"""Server-side live-evaluation model configuration (GPT-5.6 Luna only).

This module is the trusted override for isolated InvokeHarness evaluation.
Browser, Streamlit, and CoachRequest fields must never supply the model id.
Production ``MODEL_PROVIDER=agentcore`` InvokeAgentRuntime traffic is unchanged.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

LIVE_EVAL_MODEL_ID = "openai.gpt-5.6-luna"
LIVE_EVAL_API_FORMAT = "responses"
LIVE_EVAL_CLAUDE_FALLBACK = False
LIVE_EVAL_INVOCATION = "AgentCore InvokeHarness"
_FORBIDDEN_MODEL_MARKERS = ("claude", "anthropic")


class LiveEvalConfigurationError(ValueError):
    """Raised when a live evaluation call is not proven to use Luna."""


class LiveEvalModelConfig(BaseModel):
    """Trusted server-side Luna override for every paid evaluation invoke."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(default=LIVE_EVAL_MODEL_ID, min_length=1, max_length=120)
    api_format: str = Field(default=LIVE_EVAL_API_FORMAT, min_length=1, max_length=40)
    claude_fallback: bool = False
    invocation: str = LIVE_EVAL_INVOCATION

    @model_validator(mode="after")
    def luna_only_without_claude_fallback(self) -> "LiveEvalModelConfig":
        """Reject any non-Luna id, Responses-format mismatch, or Claude fallback."""
        model_id = str(self.model_id or "").strip()
        api_format = str(self.api_format or "").strip()
        lowered = model_id.casefold()
        if model_id != LIVE_EVAL_MODEL_ID:
            raise LiveEvalConfigurationError(
                "Live evaluation model must be openai.gpt-5.6-luna"
            )
        if api_format != LIVE_EVAL_API_FORMAT:
            raise LiveEvalConfigurationError(
                "Live evaluation API format must be responses"
            )
        if self.claude_fallback or LIVE_EVAL_CLAUDE_FALLBACK:
            raise LiveEvalConfigurationError("Claude fallback must stay disabled")
        if any(marker in lowered for marker in _FORBIDDEN_MODEL_MARKERS):
            raise LiveEvalConfigurationError("Claude and Anthropic models are forbidden")
        return self

    def bedrock_model_config(self) -> dict[str, str]:
        """Return the InvokeHarness ``bedrockModelConfig`` object."""
        self.assert_ready()
        return {"modelId": self.model_id, "apiFormat": self.api_format}

    def invoke_model_override(self) -> dict[str, dict[str, str]]:
        """Return the top-level InvokeHarness ``model`` override."""
        return {"bedrockModelConfig": self.bedrock_model_config()}

    def assert_ready(self) -> None:
        """Fail closed when the resolved override is not Luna Responses."""
        if self.model_id != LIVE_EVAL_MODEL_ID:
            raise LiveEvalConfigurationError(
                "Live evaluation model must be openai.gpt-5.6-luna"
            )
        if self.api_format != LIVE_EVAL_API_FORMAT:
            raise LiveEvalConfigurationError(
                "Live evaluation API format must be responses"
            )
        if self.claude_fallback:
            raise LiveEvalConfigurationError("Claude fallback must stay disabled")


def live_eval_banner(config: LiveEvalModelConfig | None = None) -> str:
    """Return the mandatory preflight banner that must be logged before AWS calls."""
    resolved = config or LiveEvalModelConfig()
    resolved.assert_ready()
    return "\n".join(
        [
            "LIVE EVALUATION CONFIGURATION",
            "",
            "Model:",
            resolved.model_id,
            "",
            "API format:",
            resolved.api_format,
            "",
            "Invocation:",
            resolved.invocation,
            "",
            "Claude fallback:",
            "DISABLED",
            "",
            "Production DEFAULT:",
            "UNCHANGED",
        ]
    )


def assert_live_eval_invoke_kwargs(kwargs: dict[str, Any]) -> LiveEvalModelConfig:
    """Prove one outbound InvokeHarness request carries the Luna override.

    Args:
        kwargs: Keyword arguments about to be sent to ``invoke_harness``.

    Returns:
        The validated live-eval configuration extracted from *kwargs*.

    Raises:
        LiveEvalConfigurationError: When the override is missing, mutated,
            Claude-shaped, or tools are unrestricted.
    """
    dumped = str(kwargs)
    lowered = dumped.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_MODEL_MARKERS):
        raise LiveEvalConfigurationError(
            "Claude or Anthropic model identifiers are present in the live eval path"
        )
    model = kwargs.get("model")
    if not isinstance(model, dict):
        raise LiveEvalConfigurationError("InvokeHarness model override is missing")
    bedrock = model.get("bedrockModelConfig")
    if not isinstance(bedrock, dict):
        raise LiveEvalConfigurationError("bedrockModelConfig is missing")
    model_id = str(bedrock.get("modelId") or "").strip()
    api_format = str(bedrock.get("apiFormat") or "").strip()
    if model_id != LIVE_EVAL_MODEL_ID:
        raise LiveEvalConfigurationError(
            "Live evaluation model must be openai.gpt-5.6-luna"
        )
    if api_format != LIVE_EVAL_API_FORMAT:
        raise LiveEvalConfigurationError(
            "Live evaluation API format must be responses"
        )
    config = LiveEvalModelConfig(
        model_id=model_id,
        api_format=api_format,
        claude_fallback=False,
    )
    config.assert_ready()
    tools = kwargs.get("tools")
    allowed = kwargs.get("allowedTools")
    if tools not in (None, [], ()):
        raise LiveEvalConfigurationError(
            "Live coaching harness must not expose unrestricted tools"
        )
    if allowed not in (None, [], ()):
        raise LiveEvalConfigurationError(
            "Live coaching harness must not allow unrestricted tools"
        )
    return config
