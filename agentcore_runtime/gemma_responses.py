"""Bridge Gemma native JSON responses to Strands' validated output tool.

Gemma's Mantle function-argument path produced punctuation-only replies in
bounded live checks. Native JSON-schema output produced a useful reply. This
adapter changes only the provider transport: Strands/Pydantic still validate
the result, and the application still owns citations, persistence and stages.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
import json
from typing import Any
from uuid import uuid4


def _strict_schema(value: Any) -> None:
    """Make an isolated provider schema strict, without changing domain models."""
    if isinstance(value, dict):
        if (
            isinstance(value.get('type'), list) and 'null' in value['type']
            and isinstance(value.get('enum'), list) and None not in value['enum']
        ):
            # Strands flattens Optional[Literal[...]] to a nullable type but
            # leaves null out of enum. Restore the domain's actual null case;
            # otherwise strict Q&A output is forced to recommend a stage.
            value['enum'] = [*value['enum'], None]
        if isinstance(value.get('properties'), dict):
            value['additionalProperties'] = False
            value['required'] = list(value['properties'])
        for child in value.values():
            _strict_schema(child)
    elif isinstance(value, list):
        for child in value:
            _strict_schema(child)



def _restore_nullability(
    value: dict[str, Any], declared: dict[str, Any], definitions: dict[str, Any],
) -> None:
    """Remove SDK-added nulls using the original Pydantic type declarations.

    Strands treats an omittable defaulted field as nullable. Native strict JSON
    requires every field, so that broadening produces values Pydantic rejects.
    Resolve local definitions only; preserve genuine nullable domain fields.
    """
    if '$ref' in declared:
        reference = declared['$ref']
        if not isinstance(reference, str) or not reference.startswith('#/$defs/'):
            raise ValueError('Gemma output schema has an unsupported reference')
        declared = definitions[reference.removeprefix('#/$defs/')]
    variants = declared.get('anyOf', declared.get('oneOf', [declared]))
    nullable = any(
        item.get('type') == 'null'
        or (isinstance(item.get('type'), list) and 'null' in item['type'])
        for item in variants
    )
    known_type = any('type' in item for item in variants)
    if known_type and not nullable and isinstance(value.get('type'), list):
        types = [kind for kind in value['type'] if kind != 'null']
        value['type'] = types[0] if len(types) == 1 else types
    structural = next((item for item in variants if item.get('type') != 'null'), declared)
    for key, child in value.get('properties', {}).items():
        original = structural.get('properties', {}).get(key)
        if isinstance(child, dict) and isinstance(original, dict):
            _restore_nullability(child, original, definitions)
    if isinstance(value.get('items'), dict) and isinstance(structural.get('items'), dict):
        _restore_nullability(value['items'], structural['items'], definitions)


def _declared_output_schemas() -> dict[str, dict[str, Any]]:
    """Read canonical output types without importing an SDK or opening a client."""
    try:
        from models import (CoachTurnOutput, DeepReviewTurnOutput, FastChatTurnOutput,
                            QATurnOutput, ReviewTurnOutput, RouterOutput)
    except ImportError:
        from agentcore_runtime.models import (
            CoachTurnOutput, DeepReviewTurnOutput, FastChatTurnOutput,
            QATurnOutput, ReviewTurnOutput, RouterOutput,
        )
    return {model.__name__: model.model_json_schema() for model in (
        CoachTurnOutput, DeepReviewTurnOutput, FastChatTurnOutput,
        QATurnOutput, ReviewTurnOutput, RouterOutput,
    )}


def gemma_native_model_class(base_model: type[Any]) -> type[Any]:
    """Build the Gemma-specific adapter over an injected Responses SDK class.

    Args:
        base_model: Pinned Strands OpenAIResponsesModel, or an offline test seam.

    Returns:
        A subclass retaining upstream auth, media conversion and usage handling.
        No SDK import or network call occurs while building the class.
    """
    declared_schemas = _declared_output_schemas()

    class GemmaNativeJSONModel(base_model):
        """Use native JSON text for the sole framework structured-output tool."""

        def _format_request(
            self, messages: Any, tool_specs: Any = None,
            system_prompt: str | None = None, tool_choice: Any = None,
            model_state: Any = None,
        ) -> dict[str, Any]:
            """Replace one output tool with the proven native JSON wire format."""
            request = super()._format_request(
                messages, tool_specs, system_prompt, tool_choice, model_state
            )
            if not tool_specs:
                return request
            if len(tool_specs) != 1:
                raise ValueError('Gemma native output requires a single framework tool')
            spec = tool_specs[0]
            schema = deepcopy(spec['inputSchema']['json'])
            declared = declared_schemas.get(spec['name'])
            if declared is None:
                raise ValueError('Gemma output must use a canonical runtime contract')
            _restore_nullability(schema, declared, declared.get('$defs', {}))
            _strict_schema(schema)
            for key in ('tools', 'tool_choice', 'parallel_tool_calls'):
                request.pop(key, None)
            request['text'] = {'format': {
                'type': 'json_schema', 'name': spec['name'],
                'schema': schema, 'strict': True,
            }}
            return request

        async def stream(
            self, messages: Any, tool_specs: Any = None,
            system_prompt: str | None = None, *, tool_choice: Any = None,
            model_state: Any = None, **kwargs: Any,
        ) -> AsyncIterator[dict[str, Any]]:
            """Translate JSON text deltas into one validation-tool event stream.

            Per-invoke state stays local so cached model instances remain safe
            under concurrent requests. Errors/truncation never emit success.
            """
            if tool_specs and len(tool_specs) != 1:
                raise ValueError('Gemma native output requires a single framework tool')
            name = tool_specs[0]['name'] if tool_specs else None
            parts: list[str] = []
            started = False
            async for event in super().stream(
                messages, tool_specs, system_prompt, tool_choice=tool_choice,
                model_state=model_state, **kwargs,
            ):
                if name is None:
                    yield event
                    continue
                if 'messageStart' in event or 'metadata' in event:
                    yield event
                elif 'contentBlockDelta' in event:
                    delta = event['contentBlockDelta']['delta']
                    if 'text' not in delta:
                        # Reasoning is metered upstream but never exposed as
                        # user reply text or structured-output arguments.
                        continue
                    if not started:
                        yield {'contentBlockStart': {'start': {'toolUse': {
                            'name': name, 'toolUseId': 'native_' + uuid4().hex,
                        }}}}
                        started = True
                    text = delta['text']
                    parts.append(text)
                    yield {'contentBlockDelta': {'delta': {'toolUse': {'input': text}}}}
                elif 'messageStop' in event:
                    if event['messageStop']['stopReason'] != 'end_turn':
                        raise ValueError('Gemma native JSON response was incomplete')
                    payload = json.loads(''.join(parts))
                    if not isinstance(payload, dict):
                        raise ValueError('Gemma native JSON response must be an object')
                    reply = payload.get('response_text')
                    if reply is not None and (
                        not isinstance(reply, str) or not any(c.isalnum() for c in reply)
                    ):
                        raise ValueError('Gemma returned an unusable reply')
                    yield {'contentBlockStop': {}}
                    yield {'messageStop': {'stopReason': 'tool_use'}}

        async def structured_output(
            self, output_model: Any, prompt: Any,
            system_prompt: str | None = None, **kwargs: Any,
        ) -> AsyncIterator[dict[str, Any]]:
            """Keep the framework's repair path on the same native transport."""
            from strands.tools.structured_output import convert_pydantic_to_tool_spec

            parts: list[str] = []
            spec = convert_pydantic_to_tool_spec(output_model)
            async for event in self.stream(prompt, [spec], system_prompt, **kwargs):
                delta = event.get('contentBlockDelta', {}).get('delta', {})
                if 'toolUse' in delta:
                    parts.append(delta['toolUse']['input'])
            yield {'output': output_model.model_validate_json(''.join(parts))}

    return GemmaNativeJSONModel
