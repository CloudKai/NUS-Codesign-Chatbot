"""Botocore retry-budget contracts for the AWS coach and retrieval clients.

Botocore normalises the legacy ``retries={"max_attempts": N}`` client-config key
to ``total_max_attempts = N + 1``. Every adapter here intends the configured
attempt count to be the *total* number of network attempts, so they must use
``total_max_attempts``. These tests inject fakes and never call AWS.
"""

from __future__ import annotations

from typing import Any

import pytest


def _capture_boto(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``boto3.client``/``botocore.config.Config`` and record kwargs."""
    import boto3
    import botocore.config

    observed: dict[str, Any] = {}
    sentinel = object()

    class FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            observed["config"] = kwargs

    def fake_client(service: str, *, region_name: str, config: Any) -> object:
        observed.update({"service": service, "region_name": region_name})
        return sentinel

    monkeypatch.setattr(botocore.config, "Config", FakeConfig)
    monkeypatch.setattr(boto3, "client", fake_client)
    observed["sentinel"] = sentinel
    return observed


def test_botocore_normalizes_legacy_max_attempts_to_one_extra_attempt() -> None:
    """Document the behaviour that makes ``total_max_attempts`` the correct key.

    Normalisation happens when the client is built, not in ``Config.__init__``.
    Building an STS client is offline: it only reads bundled service JSON.
    """
    import boto3
    from botocore.config import Config

    common = {
        "region_name": "us-east-1",
        "aws_access_key_id": "testing",
        "aws_secret_access_key": "testing",
    }
    legacy = boto3.client(
        "sts", config=Config(retries={"max_attempts": 1, "mode": "standard"}), **common
    )
    explicit = boto3.client(
        "sts",
        config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
        **common,
    )

    assert legacy.meta.config.retries["total_max_attempts"] == 2
    assert explicit.meta.config.retries["total_max_attempts"] == 1


def test_agentcore_client_uses_total_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTCORE_MAX_RETRIES=0 must mean exactly one InvokeAgentRuntime attempt."""
    from backend.agentcore_provider import AgentCoreCoachProvider

    observed = _capture_boto(monkeypatch)
    provider = AgentCoreCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness",
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
    )

    assert provider._runtime_client() is observed["sentinel"]
    assert observed["service"] == "bedrock-agentcore"
    assert observed["config"]["retries"] == {
        "total_max_attempts": 1,
        "mode": "standard",
    }


def test_bedrock_converse_client_uses_total_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct Bedrock Converse fallback keeps the same total-attempt budget."""
    from backend.bedrock_provider import BedrockCoachProvider

    observed = _capture_boto(monkeypatch)
    provider = BedrockCoachProvider(
        "us.anthropic.claude-test",
        region="us-west-2",
        timeout_seconds=110.0,
        max_retries=0,
    )

    assert provider._runtime_client() is observed["sentinel"]
    assert observed["service"] == "bedrock-runtime"
    assert observed["config"]["retries"] == {
        "total_max_attempts": 1,
        "mode": "standard",
    }


def test_knowledge_base_retrieve_client_uses_total_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Knowledge Base Retrieve already pinned one total attempt; keep it pinned."""
    from backend.bedrock_retrieve import BedrockKnowledgeBaseRetriever

    observed = _capture_boto(monkeypatch)
    retriever = BedrockKnowledgeBaseRetriever("JUQNP8AZAZ", region="us-west-2")

    assert retriever._runtime_client() is observed["sentinel"]
    assert observed["service"] == "bedrock-agent-runtime"
    assert observed["config"]["retries"] == {
        "total_max_attempts": 1,
        "mode": "standard",
    }
