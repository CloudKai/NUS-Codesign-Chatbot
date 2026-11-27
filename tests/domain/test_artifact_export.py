"""Pure artifact export rendering: meaningful formats, inert URLs and bounded provenance only."""

import json

import pytest

from backend.artifact_export import render_artifact_export, render_artifact_markdown, render_artifact_text

DOCUMENT = {'type': 'doc', 'content': [
    {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': 'Crossing study'}]},
    {'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'Residents '},
        {'type': 'text', 'marks': [{'type': 'bold'}], 'text': 'struggle'},
        {'type': 'text', 'marks': [{'type': 'link', 'attrs': {'href': 'https://lta.gov.sg/x'}}], 'text': ' to cross'},
        {'type': 'text', 'marks': [{'type': 'link', 'attrs': {'href': 'javascript:alert(1)'}}], 'text': ' safely'},
    ]},
    {'type': 'bulletList', 'content': [
        {'type': 'listItem', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'Morning rush'}]}]},
        {'type': 'listItem', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'Evening rush'}]}]},
    ]},
]}


def test_markdown_export_is_meaningful_and_keeps_unsafe_urls_inert() -> None:
    """Headings, emphasis, lists and safe links render; unsafe schemes lose the link."""
    markdown = render_artifact_markdown(DOCUMENT)
    assert '## Crossing study' in markdown
    assert 'Residents **struggle**' in markdown
    assert '[ to cross](https://lta.gov.sg/x)' in markdown
    assert 'safely' in markdown
    assert 'javascript:' not in markdown
    assert '- Morning rush' in markdown and '- Evening rush' in markdown


def test_text_export_is_plain_and_provenance_only_envelope() -> None:
    """Plaintext keeps the words without markers; the JSON envelope carries no operational data."""
    text = render_artifact_text(DOCUMENT)
    assert 'Residents struggle' in text and 'to cross' in text
    assert '**' not in text and 'javascript:' not in text
    artifact = {'title': 'Field notes', 'kind': 'concept_generation', 'schema_version': 1,
                'revision': 4, 'origin': 'restore', 'created_at': 'c', 'updated_at': 'u',
                'document': DOCUMENT, 'id': 'a1', 'thread_id': 't1', 'restored_from': 1}
    body, media_type, suffix = render_artifact_export(artifact, 'json')
    envelope = json.loads(body)
    assert media_type == 'application/json' and suffix == 'json'
    assert envelope['title'] == 'Field notes' and envelope['revision'] == 4
    assert envelope['origin'] == 'restore' and envelope['document'] == DOCUMENT
    # No hidden prompts, storage or operational fields ever enter the envelope.
    assert 'id' not in envelope and 'thread_id' not in envelope and 'restored_from' not in envelope
    with pytest.raises(ValueError):
        render_artifact_export(artifact, 'html')
