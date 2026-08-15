"""Fail-closed AgentCore model factory.

The production runtime must not construct a bare ``BedrockModel()``. The first
paid specialist evaluation uses Claude Sonnet 4.6 on Bedrock. Luna is an
optional second provider and never a silent fallback.

This module is Strands-import free except ``load_runtime_model``, so pytest can
assert constructor kwargs without AWS.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger("agentcore_runtime.model")

PROVIDER_BEDROCK = "bedrock"
PROVIDER_MANTLE_RESPONSES = "bedrock_mantle_responses"
ALLOWED_PROVIDERS = frozenset({PROVIDER_BEDROCK, PROVIDER_MANTLE_RESPONSES})

SONNET_4_6_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
LUNA_MODEL_ID = "openai.gpt-5.6-luna"
DEFAULT_MODEL_REGION = "us-west-2"

_PINNED_STRANDS = "1.52.0"
_PINNED_BEDROCK_AGENTCORE = "1.21.0"
_PINNED_PYDANTIC = "2.13.4"


class RuntimeModelError(RuntimeError):
    """Raised when runtime model configuration is missing or unsafe.

    Messages are category-safe. They must not include secrets, student text,
    or full environment dumps.
    """


@dataclass(frozen=True)
class RuntimeModelConfig:
    """Explicit model, region, and guardrail settings for one runtime process."""

    provider: str
    model_id: str
    region: str
    guardrail_id: str
    guardrail_version: str
    guardrail_latest_message: bool = True

    @property
    def uses_bedrock_model(self) -> bool:
        """Return True when Strands ``BedrockModel`` is the provider class."""
        return self.provider == PROVIDER_BEDROCK

    @property
    def uses_mantle_responses(self) -> bool:
        """Return True when Strands ``OpenAIResponsesModel`` is required."""
        return self.provider == PROVIDER_MANTLE_RESPONSES

    def provenance(self) -> dict[str, Any]:
        """Return internal evaluation metadata. Do not show this to students."""
        return {
            "agentcore_model_provider": self.provider,
            "foundation_model_id": self.model_id,
            "model_region": self.region,
            "guardrail_configured": bool(self.guardrail_id and self.guardrail_version),
            "guardrail_latest_message": bool(self.guardrail_latest_message)
            if self.uses_bedrock_model
            else False,
            "pinned_strands_agents": _PINNED_STRANDS,
            "pinned_bedrock_agentcore": _PINNED_BEDROCK_AGENTCORE,
            "pinned_pydantic": _PINNED_PYDANTIC,
        }


def _clean(value: Any) -> str:
    """Return a stripped string from an environment-like value."""
    return str(value or "").strip()


def runtime_model_config_from_mapping(values: Mapping[str, Any] | None) -> RuntimeModelConfig:
    """Build a config from a mapping of environment-style keys.

    Args:
        values: Typically ``os.environ``. Missing required keys fail closed.

    Returns:
        A validated :class:`RuntimeModelConfig`.

    Raises:
        RuntimeModelError: When provider, model, region, or guardrail is missing
            or when Luna is pointed at ``BedrockModel``.
    """
    data = values or {}
    provider = _clean(data.get("AGENTCORE_MODEL_PROVIDER")).lower()
    model_id = _clean(data.get("AGENTCORE_MODEL_ID"))
    region = _clean(data.get("AGENTCORE_MODEL_REGION")) or _clean(data.get("AWS_REGION"))
    guardrail_id = _clean(data.get("GUARDRAIL_ID"))
    guardrail_version = _clean(data.get("GUARDRAIL_VERSION"))
    if not provider:
        raise RuntimeModelError("AGENTCORE_MODEL_PROVIDER is not configured")
    if provider not in ALLOWED_PROVIDERS:
        raise RuntimeModelError("unsupported AGENTCORE_MODEL_PROVIDER")
    if not model_id:
        raise RuntimeModelError("AGENTCORE_MODEL_ID is not configured")
    if not region:
        raise RuntimeModelError("AGENTCORE_MODEL_REGION is not configured")
    if not guardrail_id or not guardrail_version:
        raise RuntimeModelError("GUARDRAIL_ID and GUARDRAIL_VERSION are required")
    if provider == PROVIDER_BEDROCK and model_id.lower().startswith("openai."):
        raise RuntimeModelError("Luna cannot use BedrockModel")
    if provider == PROVIDER_MANTLE_RESPONSES and not model_id.lower().startswith("openai."):
        raise RuntimeModelError("Mantle Responses requires an openai.* model id")
    return RuntimeModelConfig(
        provider=provider,
        model_id=model_id,
        region=region,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_latest_message=True,
    )


def runtime_model_config_from_environ() -> RuntimeModelConfig:
    """Load model configuration from process environment."""
    return runtime_model_config_from_mapping(os.environ)


def bedrock_model_kwargs(config: RuntimeModelConfig) -> dict[str, Any]:
    """Return explicit ``BedrockModel`` constructor kwargs.

    Args:
        config: Validated runtime model configuration.

    Returns:
        Keyword arguments including ``model_id``, ``region_name``, and
        guardrail settings. ``guardrail_latest_message`` is True so input
        evaluation targets the latest untrusted user turn, not the trusted
        system curriculum.

    Raises:
        RuntimeModelError: When the config is not the Bedrock Converse path.
    """
    if not config.uses_bedrock_model:
        raise RuntimeModelError("BedrockModel kwargs requested for a non-bedrock provider")
    return {
        "model_id": config.model_id,
        "region_name": config.region,
        "guardrail_id": config.guardrail_id,
        "guardrail_version": config.guardrail_version,
        "guardrail_latest_message": True,
    }


def mantle_responses_kwargs(config: RuntimeModelConfig) -> dict[str, Any]:
    """Return explicit ``OpenAIResponsesModel`` constructor kwargs.

    Official Strands docs: ``stateful`` defaults to False; this factory sets
    ``stateful=False`` so DSQL remains the transcript. ``bedrock_mantle_config``
    uses documented key ``region``. Guardrails are not a constructor field on
    this provider; the runtime applies Bedrock ``ApplyGuardrail`` separately.

    Args:
        config: Validated Mantle Responses configuration.

    Returns:
        Keyword arguments for ``OpenAIResponsesModel``.

    Raises:
        RuntimeModelError: When the config is not the Mantle path.
    """
    if not config.uses_mantle_responses:
        raise RuntimeModelError("OpenAIResponsesModel kwargs requested for a non-mantle provider")
    return {
        "model_id": config.model_id,
        "stateful": False,
        "bedrock_mantle_config": {"region": config.region},
    }


def log_runtime_model_config(config: RuntimeModelConfig) -> None:
    """Log category-only model provenance. Never logs student text or secrets."""
    meta = config.provenance()
    logger.info(
        "runtime_model_loaded provider=%s model_id=%s region=%s "
        "guardrail_configured=%s guardrail_latest_message=%s strands_pin=%s",
        meta["agentcore_model_provider"],
        meta["foundation_model_id"],
        meta["model_region"],
        str(meta["guardrail_configured"]).lower(),
        str(meta["guardrail_latest_message"]).lower(),
        meta["pinned_strands_agents"],
    )


def load_runtime_model(config: RuntimeModelConfig | None = None) -> Any:
    """Construct the Strands model for this process.

    Args:
        config: Optional pre-parsed config. ``None`` reads the environment.

    Returns:
        A Strands model instance.

    Raises:
        RuntimeModelError: When configuration is invalid, Strands imports fail,
            or Luna is requested without the OpenAI extra. Never falls back
            between Claude and Luna.
    """
    resolved = config or runtime_model_config_from_environ()
    log_runtime_model_config(resolved)
    if resolved.uses_bedrock_model:
        try:
            from strands.models import BedrockModel
        except ImportError as error:  # pragma: no cover - companion tests skip Strands
            raise RuntimeModelError("strands-agents is not installed") from error
        return BedrockModel(**bedrock_model_kwargs(resolved))
    try:
        from strands.models.openai_responses import OpenAIResponsesModel
    except ImportError as error:  # pragma: no cover - optional Luna extra
        raise RuntimeModelError(
            "Luna requires strands-agents[openai]; Claude was not substituted"
        ) from error
    return OpenAIResponsesModel(**mantle_responses_kwargs(resolved))
