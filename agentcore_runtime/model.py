"""Fail-closed AgentCore model factory.

The production runtime must not construct a bare ``BedrockModel()``. Roles
select Claude Haiku 4.5 (router, Q&A, coaching, incremental Review) or
Claude Sonnet 4.6 (deep Review). There is no silent Haiku↔Sonnet
substitution. Mantle/Luna remains a supported historical provider pair.

This module is Strands-import free except ``load_runtime_model``, so pytest can
assert constructor kwargs without AWS.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("agentcore_runtime.model")

PROVIDER_BEDROCK = "bedrock"
PROVIDER_MANTLE_RESPONSES = "bedrock_mantle_responses"
ALLOWED_PROVIDERS = frozenset({PROVIDER_BEDROCK, PROVIDER_MANTLE_RESPONSES})

SONNET_4_6_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
HAIKU_4_5_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
LUNA_MODEL_ID = "openai.gpt-5.6-luna"
DEFAULT_MODEL_REGION = "us-west-2"

MODEL_ROLE_ROUTER = "router"
MODEL_ROLE_QA = "qa"
MODEL_ROLE_COACHING = "coaching"
MODEL_ROLE_FAST_CHAT = "fast_chat"
MODEL_ROLE_REVIEW_INCREMENTAL = "review_incremental"
MODEL_ROLE_REVIEW_DEEP = "review_deep"
MODEL_ROLES = (
    MODEL_ROLE_ROUTER,
    MODEL_ROLE_QA,
    MODEL_ROLE_COACHING,
    MODEL_ROLE_FAST_CHAT,
    MODEL_ROLE_REVIEW_INCREMENTAL,
    MODEL_ROLE_REVIEW_DEEP,
)
REQUIRED_MODEL_ROLES = (
    MODEL_ROLE_COACHING,
    MODEL_ROLE_FAST_CHAT,
    MODEL_ROLE_REVIEW_DEEP,
)
OPTIONAL_LEGACY_MODEL_ROLES = (
    MODEL_ROLE_ROUTER,
    MODEL_ROLE_QA,
    MODEL_ROLE_REVIEW_INCREMENTAL,
)
LIGHTWEIGHT_MODEL_ROLES = (
    MODEL_ROLE_ROUTER,
    MODEL_ROLE_QA,
    MODEL_ROLE_COACHING,
    MODEL_ROLE_FAST_CHAT,
    MODEL_ROLE_REVIEW_INCREMENTAL,
)
ROLE_ENV_KEYS: dict[str, tuple[str, str]] = {
    MODEL_ROLE_ROUTER: ("ROUTER_MODEL_PROVIDER", "ROUTER_MODEL_ID"),
    MODEL_ROLE_QA: ("QA_MODEL_PROVIDER", "QA_MODEL_ID"),
    MODEL_ROLE_COACHING: ("COACHING_MODEL_PROVIDER", "COACHING_MODEL_ID"),
    MODEL_ROLE_FAST_CHAT: ("COACHING_MODEL_PROVIDER", "COACHING_MODEL_ID"),
    MODEL_ROLE_REVIEW_INCREMENTAL: (
        "REVIEW_INCREMENTAL_MODEL_PROVIDER",
        "REVIEW_INCREMENTAL_MODEL_ID",
    ),
    MODEL_ROLE_REVIEW_DEEP: ("REVIEW_DEEP_MODEL_PROVIDER", "REVIEW_DEEP_MODEL_ID"),
}

# Keep these exact pins in lockstep with ``requirements.txt``. The deployed
# runtime reports provenance from these constants so a .py-only copy still
# works. ``tests/domain/test_runtime_model.py`` fails if they drift.
PINNED_RUNTIME_PACKAGES: dict[str, str] = {
    "strands-agents": "1.52.0",
    "bedrock-agentcore": "1.21.0",
    "pydantic": "2.13.4",
}
_PINNED_STRANDS = PINNED_RUNTIME_PACKAGES["strands-agents"]
_PINNED_BEDROCK_AGENTCORE = PINNED_RUNTIME_PACKAGES["bedrock-agentcore"]
_PINNED_PYDANTIC = PINNED_RUNTIME_PACKAGES["pydantic"]
_RUNTIME_PIN_NAMES = tuple(PINNED_RUNTIME_PACKAGES)
_REQUIREMENTS_PATH = Path(__file__).resolve().parent / "requirements.txt"


def parse_runtime_requirement_pins(text: str) -> dict[str, str]:
    """Parse exact ``package==version`` pins from runtime requirements text.

    Args:
        text: Contents of ``agentcore_runtime/requirements.txt``.

    Returns:
        Mapping of the three production package names to exact versions.

    Raises:
        ValueError: When a required pin is missing, duplicated, or not exact.
    """
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise ValueError("runtime requirements must use exact == pins")
        name, version = line.split("==", 1)
        name = name.strip()
        if "[" in name:
            continue
        version = version.split("#", 1)[0].strip()
        if not version or any(marker in version for marker in (">=", "<=", "~=", ">", "<", "!=")):
            raise ValueError("runtime requirement version is not exact")
        if name in _RUNTIME_PIN_NAMES:
            if name in pins:
                raise ValueError(f"duplicate runtime pin for {name}")
            pins[name] = version
    missing = [name for name in _RUNTIME_PIN_NAMES if name not in pins]
    if missing:
        raise ValueError("runtime requirements pins are incomplete")
    return pins


def load_runtime_requirement_pins(path: Path | None = None) -> dict[str, str]:
    """Load exact production pins from ``agentcore_runtime/requirements.txt``.

    Args:
        path: Optional requirements path. Defaults to the sibling file.

    Returns:
        Mapping of package name to exact version.

    Raises:
        ValueError: When the file is missing or pins are incomplete.
    """
    requirements_path = path or _REQUIREMENTS_PATH
    if not requirements_path.is_file():
        raise ValueError("agentcore_runtime/requirements.txt is missing")
    return parse_runtime_requirement_pins(
        requirements_path.read_text(encoding="utf-8")
    )


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
    role: str = ""

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
            "role": self.role or "legacy",
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


def validate_provider_model_pair(provider: str, model_id: str) -> None:
    """Reject unsafe provider/model combinations without substituting a model.

    Args:
        provider: ``bedrock`` or ``bedrock_mantle_responses``.
        model_id: Foundation model id.

    Raises:
        RuntimeModelError: When an ``openai.*`` id is pointed at ``BedrockModel``
            or Mantle is pointed at a non-OpenAI model. Never swaps Haiku,
            Sonnet, or Luna.
    """
    cleaned_provider = _clean(provider).lower()
    cleaned_model = _clean(model_id)
    if cleaned_provider not in ALLOWED_PROVIDERS:
        raise RuntimeModelError("unsupported AGENTCORE_MODEL_PROVIDER")
    if not cleaned_model:
        raise RuntimeModelError("AGENTCORE_MODEL_ID is not configured")
    if cleaned_provider == PROVIDER_BEDROCK and cleaned_model.lower().startswith(
        "openai."
    ):
        raise RuntimeModelError("Luna cannot use BedrockModel")
    if cleaned_provider == PROVIDER_MANTLE_RESPONSES and not cleaned_model.lower().startswith(
        "openai."
    ):
        raise RuntimeModelError("Mantle Responses requires an openai.* model id")


def role_env_keys_present(values: Mapping[str, Any] | None) -> bool:
    """Return whether any per-role model environment key is set."""
    data = values or {}
    for provider_key, model_key in ROLE_ENV_KEYS.values():
        if _clean(data.get(provider_key)) or _clean(data.get(model_key)):
            return True
    return False


def _shared_region_and_guardrail(
    values: Mapping[str, Any],
) -> tuple[str, str, str]:
    """Return region and guardrail identifiers shared by every model role."""
    region = _clean(values.get("AGENTCORE_MODEL_REGION")) or _clean(
        values.get("AWS_REGION")
    )
    guardrail_id = _clean(values.get("GUARDRAIL_ID"))
    guardrail_version = _clean(values.get("GUARDRAIL_VERSION"))
    if not region:
        raise RuntimeModelError("AGENTCORE_MODEL_REGION is not configured")
    if not guardrail_id or not guardrail_version:
        raise RuntimeModelError("GUARDRAIL_ID and GUARDRAIL_VERSION are required")
    return region, guardrail_id, guardrail_version


def runtime_model_config_from_mapping(values: Mapping[str, Any] | None) -> RuntimeModelConfig:
    """Build a config from a mapping of environment-style keys.

    Args:
        values: Typically ``os.environ``. Missing required keys fail closed.

    Returns:
        A validated :class:`RuntimeModelConfig`.

    Raises:
        RuntimeModelError: When provider, model, region, or guardrail is missing
            or when an ``openai.*`` id is pointed at ``BedrockModel``.
    """
    data = values or {}
    provider = _clean(data.get("AGENTCORE_MODEL_PROVIDER")).lower()
    model_id = _clean(data.get("AGENTCORE_MODEL_ID"))
    region = _clean(data.get("AGENTCORE_MODEL_REGION")) or _clean(data.get("AWS_REGION"))
    guardrail_id = _clean(data.get("GUARDRAIL_ID"))
    guardrail_version = _clean(data.get("GUARDRAIL_VERSION"))
    if not provider:
        raise RuntimeModelError("AGENTCORE_MODEL_PROVIDER is not configured")
    if not region:
        raise RuntimeModelError("AGENTCORE_MODEL_REGION is not configured")
    if not guardrail_id or not guardrail_version:
        raise RuntimeModelError("GUARDRAIL_ID and GUARDRAIL_VERSION are required")
    validate_provider_model_pair(provider, model_id)
    return RuntimeModelConfig(
        provider=provider,
        model_id=model_id,
        region=region,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_latest_message=True,
        role="legacy",
    )


def role_model_config_from_mapping(
    values: Mapping[str, Any] | None, role: str
) -> RuntimeModelConfig:
    """Build one role's model config from environment-style keys.

    When no per-role keys are present, every role reuses the legacy
    ``AGENTCORE_MODEL_*`` pair. When any role key is present, required
    active roles (Q&A optional, Coaching/fast_chat, Deep Review) must be
    complete. Legacy router and Incremental Review are validated only when
    their environment keys are set. Partial required configuration fails
    closed instead of substituting Haiku for Sonnet.

    Args:
        values: Typically ``os.environ``.
        role: One of :data:`MODEL_ROLES`.

    Returns:
        A validated :class:`RuntimeModelConfig` for that role.

    Raises:
        RuntimeModelError: When the role, provider/model pair, region, or
            guardrail is missing or unsafe.
    """
    cleaned_role = _clean(role).lower()
    if cleaned_role not in ROLE_ENV_KEYS:
        raise RuntimeModelError("unsupported model role")
    data = values or {}
    provider_key, model_key = ROLE_ENV_KEYS[cleaned_role]
    role_provider = _clean(data.get(provider_key)).lower()
    role_model_id = _clean(data.get(model_key))
    if role_env_keys_present(data):
        if not role_provider:
            raise RuntimeModelError(f"{provider_key} is not configured")
        if not role_model_id:
            raise RuntimeModelError(f"{model_key} is not configured")
        region, guardrail_id, guardrail_version = _shared_region_and_guardrail(data)
        validate_provider_model_pair(role_provider, role_model_id)
        return RuntimeModelConfig(
            provider=role_provider,
            model_id=role_model_id,
            region=region,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            guardrail_latest_message=True,
            role=cleaned_role,
        )
    config = runtime_model_config_from_mapping(data)
    return replace(config, role=cleaned_role)


def role_model_config_from_environ(role: str) -> RuntimeModelConfig:
    """Load one role's model configuration from process environment."""
    return role_model_config_from_mapping(os.environ, role)


def _role_env_configured(values: Mapping[str, Any] | None, role: str) -> bool:
    """Return whether provider or model env keys are set for one role."""
    cleaned = _clean(role).lower()
    keys = ROLE_ENV_KEYS.get(cleaned)
    if not keys:
        return False
    data = values or {}
    return bool(_clean(data.get(keys[0])) or _clean(data.get(keys[1])))


def validate_all_role_configs(
    values: Mapping[str, Any] | None = None,
) -> dict[str, RuntimeModelConfig]:
    """Validate required model roles. Optional legacy roles load when configured.

    Args:
        values: Optional mapping. Defaults to ``os.environ``.

    Returns:
        Mapping of role name to validated config.

    Raises:
        RuntimeModelError: When a required role cannot be loaded.
    """
    data = values if values is not None else os.environ
    if not role_env_keys_present(data):
        return {role: role_model_config_from_mapping(data, role) for role in MODEL_ROLES}
    roles: dict[str, RuntimeModelConfig] = {}
    for role in REQUIRED_MODEL_ROLES:
        roles[role] = role_model_config_from_mapping(data, role)
    for role in OPTIONAL_LEGACY_MODEL_ROLES:
        if _role_env_configured(data, role):
            roles[role] = role_model_config_from_mapping(data, role)
    return roles


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
        "runtime_model_loaded role=%s provider=%s model_id=%s region=%s "
        "guardrail_configured=%s guardrail_latest_message=%s strands_pin=%s",
        meta["role"],
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
            or Mantle is requested without the OpenAI extra. Never falls back
            between Haiku, Sonnet, and Luna.
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
            "Mantle requires strands-agents[openai]; Claude was not substituted"
        ) from error
    return OpenAIResponsesModel(**mantle_responses_kwargs(resolved))


class RuntimeModelRegistry:
    """Cache Strands model instances per role for one runtime process."""

    def __init__(self) -> None:
        """Create an empty per-role cache."""
        self._models: dict[str, Any] = {}
        self._configs: dict[str, RuntimeModelConfig] = {}

    def config_for(
        self, role: str, values: Mapping[str, Any] | None = None
    ) -> RuntimeModelConfig:
        """Return the validated config for ``role``, loading it once."""
        cleaned = _clean(role).lower()
        if cleaned not in self._configs:
            data = values if values is not None else os.environ
            self._configs[cleaned] = role_model_config_from_mapping(data, cleaned)
        return self._configs[cleaned]

    def model_for(
        self, role: str, values: Mapping[str, Any] | None = None
    ) -> Any:
        """Return a cached Strands model for ``role``.

        Args:
            role: One of :data:`MODEL_ROLES`.
            values: Optional env mapping used on first load.

        Returns:
            The Strands model instance for that role.
        """
        cleaned = _clean(role).lower()
        if cleaned not in self._models:
            config = self.config_for(cleaned, values)
            self._models[cleaned] = load_runtime_model(config)
        return self._models[cleaned]

    def clear(self) -> None:
        """Drop cached models. Used by tests."""
        self._models.clear()
        self._configs.clear()


_REGISTRY = RuntimeModelRegistry()


def get_role_model(
    role: str, values: Mapping[str, Any] | None = None
) -> Any:
    """Return the process-wide cached model for one role."""
    return _REGISTRY.model_for(role, values)


def get_role_config(
    role: str, values: Mapping[str, Any] | None = None
) -> RuntimeModelConfig:
    """Return the process-wide cached config for one role."""
    return _REGISTRY.config_for(role, values)


def clear_role_model_cache() -> None:
    """Clear the process-wide role model cache."""
    _REGISTRY.clear()
