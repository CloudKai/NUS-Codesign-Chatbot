"""Provider-neutral Bedrock ApplyGuardrail helpers for Mantle/Luna.

``BedrockModel`` applies ``GUARDRAIL_ID`` / ``GUARDRAIL_VERSION`` itself with
``guardrail_latest_message=True``. ``OpenAIResponsesModel`` does not expose
those constructor fields, so the Mantle path must call ApplyGuardrail on
untrusted input and on model output before the companion persists a turn.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

try:
    from model import RuntimeModelConfig
    from structured_coach import CoachTurnExtractionError
except ImportError:  # pragma: no cover - imported as agentcore_runtime.guardrails
    from agentcore_runtime.model import RuntimeModelConfig
    from agentcore_runtime.structured_coach import CoachTurnExtractionError

logger = logging.getLogger("agentcore_runtime.guardrails")

_BLOCKED_ACTIONS = frozenset({"GUARDRAIL_INTERVENED", "BLOCKED"})


def guardrail_response_is_blocked(response: Mapping[str, Any] | None) -> bool:
    """Return True when an ApplyGuardrail response blocked the content.

    Args:
        response: boto3-style ApplyGuardrail mapping or a test double.

    Returns:
        True when the action is a blocked/intervened outcome.
    """
    if not isinstance(response, Mapping):
        return False
    action = str(response.get("action") or "").strip().upper()
    return action in _BLOCKED_ACTIONS


def apply_guardrail(
    text: str,
    *,
    config: RuntimeModelConfig,
    source: str,
    client: Any,
) -> None:
    """Fail closed when Bedrock ApplyGuardrail blocks ``text``.

    Args:
        text: Untrusted student/evidence text or model output. Not logged.
        config: Runtime guardrail identifiers.
        source: ``INPUT`` or ``OUTPUT``.
        client: boto3 Bedrock Runtime client or a test double exposing
            ``apply_guardrail``.

    Raises:
        CoachTurnExtractionError: ``safety_blocked`` when the guardrail
            intervenes, or ``unavailable`` when the API call fails.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    qualifier = "guard_content" if source.upper() == "INPUT" else "query"
    try:
        response = client.apply_guardrail(
            guardrailIdentifier=config.guardrail_id,
            guardrailVersion=config.guardrail_version,
            source=source.upper(),
            content=[{"text": {"text": cleaned, "qualifiers": [qualifier]}}],
        )
    except CoachTurnExtractionError:
        raise
    except Exception as error:
        logger.exception("apply_guardrail_failed source=%s", source.upper())
        raise CoachTurnExtractionError("unavailable") from error
    if guardrail_response_is_blocked(response):
        logger.info("apply_guardrail_blocked source=%s", source.upper())
        raise CoachTurnExtractionError("safety_blocked")


def bedrock_runtime_client(region: str) -> Any:
    """Return a Bedrock Runtime boto3 client for ApplyGuardrail.

    Args:
        region: AWS region for the client.

    Returns:
        A boto3 client. Companion pytest injects fakes instead of calling this.
    """
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


def enforce_mantle_guardrail(
    text: str,
    *,
    config: RuntimeModelConfig,
    source: str,
    client: Any | None = None,
) -> None:
    """Apply the Luna/Mantle safety layer. No-op on the BedrockModel path.

    Args:
        text: Content to evaluate.
        config: Runtime model configuration.
        source: ``INPUT`` or ``OUTPUT``.
        client: Optional injected ApplyGuardrail client.
    """
    if not config.uses_mantle_responses:
        return
    runtime_client = client if client is not None else bedrock_runtime_client(config.region)
    apply_guardrail(text, config=config, source=source, client=runtime_client)
