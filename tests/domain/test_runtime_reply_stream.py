"""Runtime streaming contract with a deterministic Strands SDK substitute."""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

from agentcore_runtime.model import HAIKU_4_5_MODEL_ID, SONNET_4_6_MODEL_ID, ROLE_ENV_KEYS, clear_role_model_cache
from agentcore_runtime.models import FastChatTurnOutput


def test_runtime_yields_model_input_before_structured_generation_finishes(monkeypatch) -> None:
    """The public streaming invoke yields a real SDK fragment before the result."""
    import agentcore_runtime.main as runtime

    for provider, model in ROLE_ENV_KEYS.values():
        monkeypatch.delenv(provider, raising=False)
        monkeypatch.delenv(model, raising=False)
    for key, value in {
        'COACHING_MODEL_PROVIDER': 'bedrock', 'COACHING_MODEL_ID': HAIKU_4_5_MODEL_ID,
        'REVIEW_DEEP_MODEL_PROVIDER': 'bedrock', 'REVIEW_DEEP_MODEL_ID': SONNET_4_6_MODEL_ID,
        'AGENTCORE_MODEL_REGION': 'us-west-2', 'GUARDRAIL_ID': 'test', 'GUARDRAIL_VERSION': '1',
    }.items():
        monkeypatch.setenv(key, value)
    clear_role_model_cache()

    async def check() -> None:
        release = asyncio.Event()

        class Agent:
            def __init__(self, **kwargs: Any) -> None:
                self.callback = kwargs['callback_handler']

            async def invoke_async(self, prompt: Any, **kwargs: Any) -> Any:
                self.callback(delta={'toolUse': {'input': '{"response_text":"Hello '}}, current_tool_use={'toolUseId': 'one'})
                await release.wait()
                self.callback(delta={'toolUse': {'input': 'world"}'}}, current_tool_use={'toolUseId': 'one'})
                return SimpleNamespace(stop_reason='end_turn', structured_output=FastChatTurnOutput.model_validate({'mode': 'qa', 'response_text': 'Hello world', 'citations': []}), message=None)

        class SDKObject:
            def __init__(self, **kwargs: Any) -> None:
                pass

        sdk = types.ModuleType('strands')
        sdk.Agent = Agent
        sdk.ModelRetryStrategy = SDKObject
        models = types.ModuleType('strands.models')
        models.BedrockModel = SDKObject
        monkeypatch.setitem(sys.modules, 'strands', sdk)
        monkeypatch.setitem(sys.modules, 'strands.models', models)
        stream = runtime.fast_chat_stream({'phase': 'fast_chat', 'output_contract': 'fast_chat_turn', 'messages': [{'role': 'user', 'content': [{'text': 'Hello'}]}]})
        try:
            first = await asyncio.wait_for(anext(stream), timeout=2)
            assert first == {'event': 'model_delta', 'tool_id': 'one', 'input': '{"response_text":"Hello '}
            release.set()
            rest = [item async for item in stream]
            assert rest[-1]['event'] == 'result'
            assert rest[-1]['payload']['response_text'] == 'Hello world'
        finally:
            release.set()
            await stream.aclose()

    try:
        asyncio.run(check())
    finally:
        clear_role_model_cache()
