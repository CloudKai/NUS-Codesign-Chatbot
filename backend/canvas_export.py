"""Pure canvas export rendering: bounded JSON, readable outline and legible SVG.

The canonical validated graph is the only input; workspace identifiers,
operational metadata and storage details never enter the output. All node and
relationship text is escaped so downloads stay inert, and the SVG always spans
the whole graph — including nodes outside the current viewport.
"""

from __future__ import annotations

import json
from typing import Any
from xml.sax.saxutils import escape

SUPPORTED_EXPORT_FORMATS = ('json', 'outline', 'svg')
_NODE_WIDTH = 190.0
_NODE_HEIGHT = 64.0
_PAD = 40.0


def _kind_labels() -> dict[str, str]:
    """Course-facing labels mirrored from the canvas operations allowlist."""
    return {
        'note': 'Note', 'problem': 'Problem', 'stakeholder': 'Stakeholder', 'need': 'User need',
        'evidence': 'Evidence', 'assumption': 'Assumption', 'constraint': 'Constraint',
        'concept': 'Concept', 'specification': 'Specification', 'ethics': 'Ethics',
        'evaluation': 'Evaluation', 'reflection': 'Reflection',
    }


def _relation_labels() -> dict[str, str]:
    return {
        'supports': 'supports', 'addresses': 'addresses', 'depends_on': 'depends on',
        'conflicts_with': 'conflicts with', 'requires': 'requires', 'derived_from': 'derived from',
        'alternative_to': 'alternative to', 'evaluated_against': 'evaluated against',
        'raises_concern': 'raises concern about',
    }


def _stage_labels() -> dict[str, str]:
    return {
        'problem_identification': 'Problem identification',
        'concept_generation': 'Concept generation',
        'design_specification': 'Design specification',
        'ethics_critical_thinking': 'Ethics & critical thinking',
        'reflection': 'Reflection',
    }


def render_canvas_outline(graph: dict[str, Any]) -> str:
    """Render the canonical graph as a bounded, human-readable outline."""
    kinds = _kind_labels()
    relations = _relation_labels()
    stages = _stage_labels()
    lines: list[str] = []
    for node in graph.get('nodes') or []:
        label = kinds.get(str(node.get('kind')), str(node.get('kind')))
        line = f'{label}: {node.get("title")}'
        stage = node.get('stage')
        if stage:
            line += f' · {stages.get(str(stage), str(stage))}'
        if node.get('description'):
            line += f' — {node["description"]}'
        lines.append(line)
    titles = {str(node.get('id')): str(node.get('title')) for node in graph.get('nodes') or []}
    for edge in graph.get('edges') or []:
        source = titles.get(str(edge.get('source')), str(edge.get('source')))
        target = titles.get(str(edge.get('target')), str(edge.get('target')))
        relation = relations.get(str(edge.get('relation')), str(edge.get('relation')))
        line = f'{source} — {relation} — {target}'
        if edge.get('explanation'):
            line += f' ({edge["explanation"]})'
        lines.append(line)
    return '\n'.join(lines)


def render_canvas_svg(graph: dict[str, Any]) -> str:
    """Render the whole graph — including off-screen nodes — as a legible deterministic SVG.

    Node positions define the canvas extent, so the export never clips to a
    viewport. All text is XML-escaped; untrusted content can never inject markup.
    """
    kinds = _kind_labels()
    relations = _relation_labels()
    nodes = [node for node in graph.get('nodes') or [] if isinstance(node, dict)]
    edges = [edge for edge in graph.get('edges') or [] if isinstance(edge, dict)]
    if not nodes:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="80">'
                '<text x="16" y="44" font-size="14">This canvas is empty.</text></svg>')
    min_x = min(float(node.get('x', 0)) for node in nodes) - _PAD
    min_y = min(float(node.get('y', 0)) for node in nodes) - _PAD
    max_x = max(float(node.get('x', 0)) + _NODE_WIDTH for node in nodes) + _PAD
    max_y = max(float(node.get('y', 0)) + _NODE_HEIGHT for node in nodes) + _PAD
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    positions = {str(node.get('id')): (float(node.get('x', 0)), float(node.get('y', 0)))
                 for node in nodes}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="{min_x:.0f} {min_y:.0f} {width:.0f} {height:.0f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
    ]
    for edge in edges:
        source = positions.get(str(edge.get('source')))
        target = positions.get(str(edge.get('target')))
        if not source or not target:
            continue
        x1, y1 = source[0] + _NODE_WIDTH / 2, source[1] + _NODE_HEIGHT / 2
        x2, y2 = target[0] + _NODE_WIDTH / 2, target[1] + _NODE_HEIGHT / 2
        parts.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                     'stroke="#4a6fa5" stroke-width="2"/>')
        label = relations.get(str(edge.get('relation')), str(edge.get('relation')))
        if edge.get('explanation'):
            label += f': {edge["explanation"]}'
        parts.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 6:.0f}" '
                     f'font-size="12" text-anchor="middle" fill="#333">{escape(label)}</text>')
    for node in nodes:
        x, y = positions[str(node.get('id'))]
        kind = kinds.get(str(node.get('kind')), str(node.get('kind')))
        parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{_NODE_WIDTH:.0f}" '
                     f'height="{_NODE_HEIGHT:.0f}" rx="9" fill="#f4f6fa" stroke="#7a869a"/>')
        parts.append(f'<text x="{x + 10:.0f}" y="{y + 22:.0f}" font-size="12" '
                     f'fill="#556">{escape(kind)}</text>')
        parts.append(f'<text x="{x + 10:.0f}" y="{y + 46:.0f}" font-size="14" '
                     f'fill="#111">{escape(str(node.get("title")))}</text>')
    parts.append('</svg>')
    return '\n'.join(parts)


def render_canvas_selection_text(graph: dict[str, Any], node_ids: list[str]) -> str:
    """Render the server-resolved text for selected nodes plus their direct neighbors.

    The output labels every node with its course-aligned kind, optional stage
    and description, and lists each direct relationship. All content comes from
    the stored canonical graph — never from the request body.
    """
    kinds = _kind_labels()
    relations = _relation_labels()
    stages = _stage_labels()
    nodes = {str(node.get('id')): node for node in graph.get('nodes') or [] if isinstance(node, dict)}
    edges = [edge for edge in graph.get('edges') or [] if isinstance(edge, dict)]
    lines: list[str] = []
    for node_id in node_ids:
        node = nodes.get(node_id)
        if node is None:
            continue
        kind = kinds.get(str(node.get('kind')), str(node.get('kind')))
        line = f"Node '{node.get('title')}' ({kind}"
        if node.get('stage'):
            line += f"; {stages.get(str(node['stage']), str(node['stage']))}"
        line += ')'
        if node.get('description'):
            line += f": {node['description']}"
        lines.append(line)
    selected = set(node_ids)
    titles = {str(node.get('id')): str(node.get('title')) for node in nodes.values()}
    for edge in edges:
        if str(edge.get('source')) in selected or str(edge.get('target')) in selected:
            relation = relations.get(str(edge.get('relation')), str(edge.get('relation')))
            lines.append(f"Connected: '{titles.get(str(edge.get('source')), edge.get('source'))}' "
                         f"{relation} '{titles.get(str(edge.get('target')), edge.get('target'))}'")
    return '\n'.join(lines)


def render_canvas_export(canvas: dict[str, Any], format: str) -> tuple[str, str, str]:
    """Return (body, media_type, filename_suffix) for one supported export format.

    The JSON envelope carries title, revision metadata, editor provenance and
    the canonical graph — and nothing operational.
    """
    if format not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError('Unsupported export format')
    if format == 'json':
        envelope = {
            'title': canvas['title'], 'schema_version': canvas['schema_version'],
            'revision': canvas['revision'], 'origin': canvas['origin'],
            'created_at': canvas['created_at'], 'updated_at': canvas['updated_at'],
            'graph': canvas['graph'],
        }
        return (json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                'application/json', 'json')
    if format == 'outline':
        return (render_canvas_outline(canvas['graph']) + '\n', 'text/plain', 'txt')
    return (render_canvas_svg(canvas['graph']), 'image/svg+xml', 'svg')
