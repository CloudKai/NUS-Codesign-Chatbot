"""Gemma native JSON transport regressions, using no SDK or AWS calls."""
from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import pytest

from agentcore_runtime.gemma_responses import gemma_native_model_class
from agentcore_runtime.models import FastChatTurnOutput


class _Responses:
    """Model seam exposing the real pinned SDK's request/event shapes."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events = events or []

    def _format_request(self, messages: Any, tool_specs: Any = None,
                        system_prompt: Any = None, tool_choice: Any = None,
                        model_state: Any = None) -> dict[str, Any]:
        return {'input': messages, 'tools': tool_specs, 'tool_choice': tool_choice,
                'parallel_tool_calls': False, 'stream': True, 'store': False}

    async def stream(self, *args: Any, **kwargs: Any):
        for event in self.events:
            yield copy.deepcopy(event)


def _spec() -> dict[str, Any]:
    """Return the framework's single structured-output tool shape."""
    return {'name': 'FastChatTurnOutput', 'inputSchema': {'json': {
        'type': 'object', 'properties': {'response_text': {'type': 'string'}},
        'required': ['response_text']}}}


def _events(text: str, reason: str = 'end_turn') -> list[dict[str, Any]]:
    """Split a native JSON reply as an upstream streaming provider does."""
    return [{'messageStart': {'role': 'assistant'}},
            {'contentBlockStart': {'start': {}}},
            *[{'contentBlockDelta': {'delta': {'text': part}}}
              for part in [text[:19], text[19:]]],
            {'contentBlockStop': {}}, {'messageStop': {'stopReason': reason}},
            {'metadata': {'usage': {'inputTokens': 10, 'outputTokens': 20}}}]


def test_request_uses_native_schema_without_mutating_the_framework_tool() -> None:
    """The unsupported tool-argument path must never reach Gemma."""
    tool = _spec()
    before = copy.deepcopy(tool)
    model = gemma_native_model_class(_Responses)()
    request = model._format_request([], [tool], 'coach', {'any': {}})
    assert 'tools' not in request and 'tool_choice' not in request
    assert 'parallel_tool_calls' not in request
    assert request['text']['format']['type'] == 'json_schema'
    assert request['text']['format']['strict'] is True
    assert request['text']['format']['schema']['additionalProperties'] is False
    assert request['store'] is False and request['stream'] is True
    assert tool == before


def test_stream_preserves_incremental_reply_json_and_usage() -> None:
    """Native text deltas become one framework tool, preserving streaming."""
    text = json.dumps({'mode': 'coaching', 'response_text': 'What evidence supports your assumption?',
                       'recommendation': 'stay', 'citations': [], 'hmw_scaffold_ready': False})
    model = gemma_native_model_class(_Responses)(_events(text))
    async def run():
        return [e async for e in model.stream([], [_spec()])]
    events = asyncio.run(run())
    starts = [e['contentBlockStart']['start']['toolUse'] for e in events if 'contentBlockStart' in e]
    assert len(starts) == 1 and starts[0]['name'] == 'FastChatTurnOutput'
    deltas = [e['contentBlockDelta']['delta']['toolUse']['input'] for e in events if 'contentBlockDelta' in e]
    assert len(deltas) == 2 and ''.join(deltas) == text
    assert FastChatTurnOutput.model_validate_json(''.join(deltas)).recommendation == 'stay'
    assert {'messageStop': {'stopReason': 'tool_use'}} in events
    assert events[-1]['metadata']['usage']['outputTokens'] == 20


@pytest.mark.parametrize('text,reason', [('{bad', 'end_turn'),
    ('{"response_text": ":"}', 'end_turn'),
    ('{"response_text": "What evidence?"}', 'max_tokens')])
def test_invalid_or_unusable_reply_never_emits_success(text: str, reason: str) -> None:
    """Lock down the observed colon failure and truncated/error cases."""
    model = gemma_native_model_class(_Responses)(_events(text, reason))
    events = []
    async def run():
        async for event in model.stream([], [_spec()]):
            events.append(event)
    with pytest.raises(ValueError):
        asyncio.run(run())
    assert not any(e.get('messageStop', {}).get('stopReason') == 'tool_use' for e in events)


def test_unexpected_multiple_tools_fail_before_inference() -> None:
    """This adapter cannot turn application tools into structured answers."""
    model = gemma_native_model_class(_Responses)()
    with pytest.raises(ValueError, match='single'):
        model._format_request([], [_spec(), _spec()])


def test_native_schema_preserves_nullable_recommendation_for_qa() -> None:
    """SDK flattening must not make Q&A choose a stage recommendation."""
    tool = _spec()
    tool['inputSchema']['json']['properties']['recommendation'] = {
        'type': ['string', 'null'], 'enum': ['stay', 'advance']}
    model = gemma_native_model_class(_Responses)()
    schema = model._format_request([], [tool])['text']['format']['schema']
    from jsonschema import validate
    validate(None, schema['properties']['recommendation'])


def test_native_citation_schema_rejects_sdk_invented_null_title() -> None:
    """Reject the v37 first-cycle null title before it incurs a repair call."""
    tool = _spec()
    tool['inputSchema']['json']['properties']['citations'] = {
        'type': 'array', 'items': {'type': 'object', 'properties': {
            'label': {'type': 'string'},
            'title': {'type': ['string', 'null'], 'default': ''},
            'source_id': {'type': ['string', 'null'], 'default': ''},
            'excerpt': {'type': ['string', 'null'], 'default': ''},
        }, 'required': ['label']}}
    before = copy.deepcopy(tool)
    model = gemma_native_model_class(_Responses)()
    schema = model._format_request([], [tool])['text']['format']['schema']
    from jsonschema import ValidationError, validate
    citation = schema['properties']['citations']['items']
    validate({'label': 'S1', 'title': '', 'source_id': 'S1', 'excerpt': ''}, citation)
    for field in ['title', 'source_id', 'excerpt']:
        value = {'label': 'S1', 'title': '', 'source_id': 'S1', 'excerpt': ''}
        value[field] = None
        with pytest.raises(ValidationError):
            validate(value, citation)
    assert tool == before


def test_eighty_streams_on_one_model_do_not_mix_replies_or_tool_ids() -> None:
    """Cached provider instances keep every concurrent request's state private."""
    class InterleavedResponses(_Responses):
        """Yield a different synthetic response per invocation with interleaving."""

        async def stream(self, messages: Any, *args: Any, **kwargs: Any):
            text = json.dumps({'response_text': f'Synthetic reply {messages}'})
            for event in _events(text):
                await asyncio.sleep(0)
                yield event

    model = gemma_native_model_class(InterleavedResponses)()

    async def one(index: int) -> tuple[str, str]:
        events = [event async for event in model.stream(index, [_spec()])]
        tool_id = next(event['contentBlockStart']['start']['toolUse']['toolUseId']
                       for event in events if 'contentBlockStart' in event)
        text = ''.join(event['contentBlockDelta']['delta']['toolUse']['input']
                       for event in events if 'contentBlockDelta' in event)
        return tool_id, json.loads(text)['response_text']

    async def run() -> list[tuple[str, str]]:
        return await asyncio.gather(*(one(index) for index in range(80)))

    results = asyncio.run(run())
    assert len({tool_id for tool_id, _ in results}) == 80
    assert [reply for _, reply in results] == [f'Synthetic reply {i}' for i in range(80)]
