"""Pure artifact export rendering: bounded Markdown, plaintext and canonical JSON envelopes.

The canonical Tiptap document is the only input; hidden prompts, operational
metadata and storage details never enter the output. Unsafe or unapproved URL
schemes render as plain text so downloads stay inert.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

SUPPORTED_EXPORT_FORMATS = ('markdown', 'text', 'json')
_SAFE_URL = ('https://', 'http://', '/')


def _safe_url(url: str) -> bool:
    return url.startswith(_SAFE_URL)


def _inline(nodes: list[dict[str, Any]], format: str) -> str:
    """Render inline children; unsafe URLs degrade to plain text in every format."""
    parts: list[str] = []
    for node in nodes:
        kind = str(node.get('type') or '')
        text = str(node.get('text') or '')
        marks = {str(mark.get('type') or '') for mark in node.get('marks') or []}
        if kind == 'hardBreak':
            parts.append('\n' if format == 'markdown' else ' ')
            continue
        if kind == 'image':
            continue  # Stored image content is not part of the text export surface.
        segment = text
        if format == 'markdown':
            if 'bold' in marks and segment:
                segment = f'**{segment}**'
            if 'italic' in marks and segment:
                segment = f'*{segment}*'
            if 'code' in marks and segment:
                segment = f'`{segment}`'
        link = next((str(mark.get('attrs', {}).get('href') or '') for mark in node.get('marks') or []
                     if mark.get('type') == 'link'), None)
        if link is not None:
            if _safe_url(link) and segment:
                segment = f'[{segment}]({link})' if format == 'markdown' else f'{segment} ({link})'
            # Unsafe schemes lose the link entirely; the text stays as content.
        parts.append(segment)
    return ''.join(parts)


def _list_items(items: list[dict[str, Any]], format: str, marker: Callable[[int], str]) -> list[str]:
    """Render list items by flattening their inner paragraphs."""
    lines = []
    for index, item in enumerate(items, start=1):
        inner = ' '.join(_inline(child.get('content') or [], format)
                         for child in item.get('content') or [] if isinstance(child, dict))
        lines.append(f'{marker(index)} {inner}')
    return lines


def render_artifact_markdown(document: dict[str, Any]) -> str:
    """Render the canonical document as readable Markdown."""
    lines: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        kind = str(node.get('type') or '')
        content = node.get('content') or []
        if kind == 'heading':
            level = min(6, max(1, int(node.get('attrs', {}).get('level') or 1)))
            lines.append(f"{'#' * level} {_inline(content, 'markdown')}")
        elif kind == 'paragraph':
            lines.append(_inline(content, 'markdown'))
        elif kind == 'bulletList':
            lines.extend(_list_items(content, 'markdown', lambda _index: '-'))
        elif kind == 'orderedList':
            lines.extend(_list_items(content, 'markdown', str))
        elif kind == 'blockquote':
            for line in render_artifact_markdown(node).splitlines():
                lines.append(f'> {line}')
        elif kind == 'codeBlock':
            lines.append('```')
            lines.append(_inline(content, 'text'))
            lines.append('```')
        else:
            for child in content if isinstance(content, list) else []:
                walk(child)

    if isinstance(document.get('content'), list):
        for block in document['content']:
            if isinstance(block, dict):
                walk(block)
    return '\n\n'.join(line for line in lines if line.strip())


def render_artifact_text(document: dict[str, Any]) -> str:
    """Render the canonical document as bounded plaintext."""
    lines: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        content = node.get('content') or []
        if str(node.get('type') or '') in {'paragraph', 'heading', 'codeBlock'}:
            rendered = _inline(content, 'text')
            if rendered.strip():
                lines.append(rendered)
        else:
            for child in content if isinstance(content, list) else []:
                if isinstance(child, dict):
                    walk(child)

    if isinstance(document.get('content'), list):
        for block in document['content']:
            if isinstance(block, dict):
                walk(block)
    return '\n'.join(lines)


def render_artifact_export(artifact: dict[str, Any], format: str) -> tuple[str, str, str]:
    """Return (body, media_type, filename_suffix) for one supported export format.

    The JSON envelope carries title, kind, revision metadata, editor provenance
    and the canonical document — and nothing operational.
    """
    if format not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError('Unsupported export format')
    if format == 'json':
        envelope = {
            'title': artifact['title'], 'kind': artifact['kind'],
            'schema_version': artifact['schema_version'], 'revision': artifact['revision'],
            'origin': artifact['origin'], 'created_at': artifact['created_at'],
            'updated_at': artifact['updated_at'], 'document': artifact['document'],
        }
        return (json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                'application/json', 'json')
    if format == 'text':
        return (render_artifact_text(artifact['document']) + '\n', 'text/plain', 'txt')
    return (render_artifact_markdown(artifact['document']) + '\n', 'text/markdown', 'md')
