"""Canonical course_material_id and Bedrock sidecar payload tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.retrieval import course_material_id_from_object_key
from backend.sources.kb_metadata import (
    bedrock_course_material_sidecar_payload,
    expected_sidecar_material_id,
    is_metadata_sidecar_key,
    sidecar_json_bytes,
    sidecar_material_id_from_payload,
    sidecar_object_key,
)

_WEEK1_KEY = "course/lectureNotes/Week 1 Introduction to innovation v3.pdf"
_WEEK1_ID = "lecture_week_1_introduction_to_innovation_v3"


def test_week1_object_key_has_stable_canonical_id() -> None:
    assert course_material_id_from_object_key(_WEEK1_KEY) == _WEEK1_ID
    assert course_material_id_from_object_key(_WEEK1_KEY) == _WEEK1_ID
    assert expected_sidecar_material_id(_WEEK1_KEY) == _WEEK1_ID


def test_course_material_id_handles_spaces_case_punctuation_and_nested_prefix() -> None:
    assert (
        course_material_id_from_object_key("course/lectureNotes/week_02_jtbd.pdf")
        == "lecture_week_02_jtbd"
    )
    assert (
        course_material_id_from_object_key("course/LectureNotes/WEEK_02_JTBD.PDF")
        == "lecture_week_02_jtbd"
    )
    assert (
        course_material_id_from_object_key("course/readings/Pixar: analogical thinking!.pdf")
        == "reading_pixar_analogical_thinking"
    )
    assert (
        course_material_id_from_object_key("course/readings/archive/week1.pdf")
        == "reading_archive_week1"
    )
    assert course_material_id_from_object_key("course/readings/week1.pdf") == "reading_week1"
    assert (
        course_material_id_from_object_key("course/readings/myweek1.pdf")
        == "reading_myweek1"
    )


def test_unicode_only_stem_does_not_invent_a_second_slugger() -> None:
    assert course_material_id_from_object_key("course/lectureNotes/测试.pdf") == "lecture"


def test_sidecar_key_and_payload_match_bedrock_s3_metadata_schema() -> None:
    assert sidecar_object_key(_WEEK1_KEY) == f"{_WEEK1_KEY}.metadata.json"
    assert is_metadata_sidecar_key(sidecar_object_key(_WEEK1_KEY)) is True
    payload = bedrock_course_material_sidecar_payload(_WEEK1_KEY)
    assert payload == {
        "metadataAttributes": {
            "course_material_id": {
                "value": {"type": "STRING", "stringValue": _WEEK1_ID},
                "includeForEmbedding": False,
            }
        }
    }
    parsed = json.loads(sidecar_json_bytes(_WEEK1_KEY).decode("utf-8"))
    assert sidecar_material_id_from_payload(parsed) == _WEEK1_ID
    assert parsed["metadataAttributes"]["course_material_id"]["includeForEmbedding"] is False
    assert sidecar_json_bytes(_WEEK1_KEY) == sidecar_json_bytes(_WEEK1_KEY)


def test_sidecar_generator_refuses_nested_metadata_files() -> None:
    with pytest.raises(ValueError, match="sidecar"):
        bedrock_course_material_sidecar_payload(f"{_WEEK1_KEY}.metadata.json")
    assert expected_sidecar_material_id(f"{_WEEK1_KEY}.metadata.json") == ""


def test_local_sidecar_path_is_sibling(tmp_path: Path) -> None:
    from backend.sources.kb_metadata import local_sidecar_path

    source = tmp_path / "Week 1 Introduction to innovation v3.pdf"
    assert local_sidecar_path(source) == Path(f"{source}.metadata.json")
