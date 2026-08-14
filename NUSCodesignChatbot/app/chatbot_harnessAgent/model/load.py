import os

from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    kwargs = {}
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    guardrail_version = os.environ.get("GUARDRAIL_VERSION")
    if guardrail_id and guardrail_version:
        kwargs["guardrail_id"] = guardrail_id
        kwargs["guardrail_version"] = guardrail_version
    return BedrockModel(model_id="global.anthropic.claude-sonnet-4-6", **kwargs)
