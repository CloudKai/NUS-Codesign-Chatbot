"""Pure canvas export rendering: bounded JSON, readable outline and legible SVG."""

import pytest

from backend.canvas_export import render_canvas_export

CANVAS = {
    'title': 'Crossing/../map', 'schema_version': 1, 'revision': 3, 'origin': 'editor',
    'created_at': '2026-11-25T00:00:00Z', 'updated_at': '2026-11-25T01:00:00Z',
    'graph': {
        'nodes': [
            {'id': 'n1', 'kind': 'problem', 'title': 'Unsafe <crossing>', 'description': 'left turns',
             'stage': 'problem_identification', 'x': 0, 'y': 0},
            {'id': 'n2', 'kind': 'stakeholder', 'title': 'Students', 'description': '',
             'x': 800, 'y': 600},
        ],
        'edges': [
            {'id': 'e1', 'source': 'n1', 'target': 'n2', 'relation': 'addresses',
             'explanation': 'students cross here'},
        ],
    },
}


def test_json_envelope_carries_provenance_but_no_identity() -> None:
    """The structured export excludes workspace identifiers and operational fields."""
    body, media_type, suffix = render_canvas_export(CANVAS, 'json')
    assert media_type == 'application/json' and suffix == 'json'
    envelope = __import__('json').loads(body)
    assert envelope['title'] == 'Crossing/../map' and envelope['revision'] == 3
    assert envelope['schema_version'] == 1 and envelope['origin'] == 'editor'
    assert envelope['graph']['nodes'][0]['stage'] == 'problem_identification'
    assert 'id' not in envelope and 'thread_id' not in envelope
    assert 'notebook_id' not in envelope and 'user_id' not in envelope


def test_outline_names_every_node_stage_and_relationship() -> None:
    """The readable outline includes kinds, stages, positions-free titles and labeled edges."""
    body, media_type, suffix = render_canvas_export(CANVAS, 'outline')
    assert media_type == 'text/plain' and suffix == 'txt'
    assert 'Problem: Unsafe <crossing> · Problem identification' in body
    assert 'Stakeholder: Students' in body
    assert 'Unsafe <crossing> — addresses — Students' in body
    assert 'n1' not in body  # Internal node ids stay out of the human-readable outline.


def test_svg_includes_off_screen_nodes_and_escapes_content() -> None:
    """The visual export spans the whole graph and renders hostile text inertly."""
    body, media_type, suffix = render_canvas_export(CANVAS, 'svg')
    assert media_type == 'image/svg+xml' and suffix == 'svg'
    assert body.startswith('<svg')
    # Off-screen nodes appear: the second node sits at (800, 600) but all nodes are drawn.
    assert 'Students' in body and 'Unsafe &lt;crossing&gt;' in body
    assert '<crossing>' not in body  # Raw markup never enters the SVG.
    assert 'addresses' in body


def test_unsupported_and_empty_cases_fail_or_degrade_honestly(tmp_path: object) -> None:
    """Unknown formats refuse; an empty canvas still exports a truthful visual."""
    with pytest.raises(ValueError, match='Unsupported export format'):
        render_canvas_export(CANVAS, 'html')
    empty = dict(CANVAS, graph={'nodes': [], 'edges': []})
    body, _media_type, _suffix = render_canvas_export(empty, 'svg')
    assert body.startswith('<svg') and 'empty' in body.lower()
