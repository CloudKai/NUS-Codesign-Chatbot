"""First-pass evidence scope module: conflict matrix, helpers, import boundary.

Every case goes through ``decide_first_pass_scope`` with plain inputs, so the
precedence the module encodes is pinned without a store, a provider or a model.
Turn-level behaviour (snapshot, telemetry order, request stamps) is in
``test_evidence_scope_turn.py``. No AWS.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.coaching import evidence_scope as scope_module
from backend.coaching.evidence_scope import (
    CUE_ATTACHMENT_SCOPED,
    CUE_FORCE_RETRIEVAL,
    CUE_LECTURE_HELP,
    CUE_LOCAL_COURSE_INTENT,
    CUE_MISSING_IMAGE_QA,
    CUE_PROJECT_COACHING,
    CUE_STAGE_PROGRESSION,
    CUE_STAGE_STATUS,
    CUE_UPLOAD_POLICY,
    CUE_WORKFLOW_SKIPS_RETRIEVAL,
    FIRST_PASS_TELEMETRY_CUES,
    POST_MODEL_TELEMETRY_CUES,
    ScopeDecision,
    ScopeInputs,
    ScopeSource,
    course_catalog_cues,
    decide_first_pass_scope,
    is_chit_chat,
    is_image_source,
    is_searchable_student_upload,
    local_course_intent_candidate,
    scope_label,
    wants_course_catalog_retrieval,
    wants_source_need_check,
    wants_student_upload_retrieval,
)

# Messages. The stage predicates are real regex rules, so these are phrases the
# existing mode-classification tests already rely on.
STATUS = "what stage am I on?"
PROGRESSION = "let's go to concept generation"
WORKFLOW_ONLY = "what should I do next"
ATTACHMENT_Q = "summarise the uploaded file"
ATTACHMENT_VS_COURSE = "compare this attachment with Lecture 4"
COURSE_Q = "explain week 2 JTBD from the lecture notes"
NO_CUE_COURSE_Q = "what questions do we ask in the JTBD interview"
UPLOAD_Q = "what does the survey say about peak hours"
CHIT_CHAT = "thanks"
IMAGE_Q = "What is this image about?"

UPLOAD = ScopeSource("up-1", title="Survey results", filename="Survey results.pdf")
ATTACHMENT = ScopeSource(
    "att-1", title="Persona", filename="Persona.txt", is_attachment=True
)
COURSE_ROW = ScopeSource("course-1", title="Week 2 JTBD", is_course_library=True)
IMAGE_LOST = ScopeSource(
    "img-1", title="Sketch", filename="Sketch.png", is_image=True, image_bytes_resolved=False
)
IMAGE_OK = ScopeSource("img-2", title="Chart", filename="Chart.png", is_image=True)
ATTACHED_IMAGE_OK = ScopeSource(
    "att-img", title="Photo", filename="Photo.png", is_attachment=True, is_image=True
)


def decide(
    message: str,
    *sources: ScopeSource,
    promoted: bool = False,
    **options: Any,
) -> ScopeDecision:
    """Decide with ``attachment_count`` derived from the attachment sources."""
    options.setdefault("attachment_count", sum(1 for s in sources if s.is_attachment))
    return decide_first_pass_scope(
        ScopeInputs(
            message=message,
            current_stage="problem_identification",
            sources=tuple(sources),
            **options,
        ),
        course_intent_promoted=promoted,
    )


def fired(decision: ScopeDecision) -> set[str]:
    """Cues without the per-cue course-catalog entries."""
    return {cue for cue in decision.cues if not cue.startswith("course_catalog:")}


# --- the conflict matrix -----------------------------------------------------


def test_plain_gate_skip_searches_nothing_and_allows_the_second_chance() -> None:
    d = decide(NO_CUE_COURSE_Q)
    assert (d.needs_retrieval, d.include_course_catalog, d.searches_personal_files) == (
        False,
        False,
        False,
    )
    assert d.expected_mode == "coaching" and d.classifier_intent == "ambiguous"
    assert d.second_chance is True and d.cues == ()


def test_course_question_searches_the_catalog_only() -> None:
    d = decide(COURSE_Q)
    assert (d.include_course_catalog, d.searches_personal_files) == (True, False)
    assert d.expected_mode == "qa" and d.needs_retrieval is True
    assert d.second_chance is False
    assert any(cue.startswith("course_catalog:") for cue in d.cues)
    assert scope_label(d) == "course"


def test_course_question_with_an_upload_searches_both() -> None:
    d = decide(COURSE_Q, UPLOAD)
    assert scope_label(d) == "both"
    assert d.kept_source_ids == ("up-1",)


def test_upload_question_alone_is_a_gate_skip() -> None:
    d = decide(UPLOAD_Q, UPLOAD)
    assert scope_label(d) == "none" and d.needs_retrieval is False
    assert d.second_chance is True


def test_upload_policy_off_by_default_and_on_when_enabled() -> None:
    assert decide(UPLOAD_Q, UPLOAD).upload_policy_only is False
    d = decide(UPLOAD_Q, UPLOAD, upload_retrieval_enabled=True)
    assert d.upload_policy_only is True and d.needs_retrieval is True
    assert (d.include_course_catalog, d.searches_personal_files) == (False, True)
    assert CUE_UPLOAD_POLICY in d.cues
    assert d.expected_mode == "coaching"


@pytest.mark.parametrize(
    ("label", "message", "sources", "options"),
    [
        ("no sources", UPLOAD_Q, (), {}),
        ("only a course-library row", UPLOAD_Q, (COURSE_ROW,), {}),
        ("only an image", UPLOAD_Q, (IMAGE_OK,), {}),
        ("chit-chat", CHIT_CHAT, (UPLOAD,), {}),
        ("the gate already retrieves", COURSE_Q, (UPLOAD,), {}),
        ("stage status", STATUS, (UPLOAD,), {}),
        ("progression", PROGRESSION, (UPLOAD,), {}),
        ("workflow guidance", WORKFLOW_ONLY, (UPLOAD,), {}),
        ("attachment-only question", ATTACHMENT_Q, (UPLOAD, ATTACHMENT), {}),
        ("lecture help", UPLOAD_Q, (UPLOAD,), {"interaction_intent": "lecture_help"}),
        ("force_retrieval", UPLOAD_Q, (UPLOAD,), {"force_retrieval": True}),
    ],
)
def test_upload_policy_stays_off(label: str, message: str, sources: tuple, options: dict) -> None:
    d = decide(message, *sources, upload_retrieval_enabled=True, **options)
    assert d.upload_policy_only is False, label
    assert CUE_UPLOAD_POLICY not in d.cues


def test_upload_policy_ignores_an_unresolved_image_next_to_an_upload() -> None:
    d = decide(UPLOAD_Q, UPLOAD, IMAGE_LOST, upload_retrieval_enabled=True)
    assert d.upload_policy_only is True
    assert d.unresolved_image_ids == frozenset({"img-1"})
    assert d.searches_personal_files is True


def test_stage_status_clears_scope_and_workflow_cue_stays_silent() -> None:
    d = decide(STATUS, UPLOAD)
    assert d.scope_cleared is True and d.kept_source_ids == ()
    assert d.expected_mode == "qa" and d.needs_retrieval is False
    # The message also matches workflow guidance; status masks that cue.
    assert fired(d) == {CUE_STAGE_STATUS}
    assert d.evidence_scoped is True and d.second_chance is False


def test_progression_clears_scope_with_only_the_progression_cue() -> None:
    d = decide(PROGRESSION, UPLOAD)
    assert d.scope_cleared is True and d.kept_source_ids == ()
    assert d.expected_mode == "coaching" and d.needs_retrieval is False
    assert fired(d) == {CUE_STAGE_PROGRESSION}


def test_workflow_guidance_clears_scope_with_its_own_cue() -> None:
    d = decide(WORKFLOW_ONLY, UPLOAD)
    assert d.scope_cleared is True and d.expected_mode == "coaching"
    assert fired(d) == {CUE_WORKFLOW_SKIPS_RETRIEVAL}


@pytest.mark.parametrize("message", [STATUS, PROGRESSION, WORKFLOW_ONLY])
def test_lecture_help_wins_over_every_navigation_override(message: str) -> None:
    d = decide(message, UPLOAD, interaction_intent="lecture_help")
    assert d.scope_cleared is False and d.kept_source_ids == ("up-1",)
    assert d.mode_policy.intent == "high_confidence_source"
    assert d.expected_mode == "qa" and d.needs_retrieval is True
    assert (d.include_course_catalog, d.searches_personal_files) == (True, True)
    assert fired(d) == {CUE_LECTURE_HELP}


def test_lecture_help_with_an_attachment_question_stays_attachment_only() -> None:
    d = decide(ATTACHMENT_Q, UPLOAD, ATTACHMENT, interaction_intent="lecture_help")
    assert d.attachment_only is True and d.kept_source_ids == ("att-1",)
    assert d.include_course_catalog is False and d.needs_retrieval is True
    assert d.expected_mode == "qa"
    assert fired(d) == {CUE_LECTURE_HELP, CUE_ATTACHMENT_SCOPED}


@pytest.mark.parametrize(
    ("message", "mode", "needs"),
    [
        (STATUS, "qa", False),
        (PROGRESSION, "coaching", False),
        (COURSE_Q, "coaching", True),
    ],
)
def test_project_coaching_sets_the_mode_unless_navigation_overrides(
    message: str, mode: str, needs: bool
) -> None:
    d = decide(message, UPLOAD, interaction_intent="project_coaching")
    assert d.expected_mode == mode and d.needs_retrieval is needs
    assert CUE_PROJECT_COACHING in d.cues


def test_attachment_question_narrows_to_the_attachment_and_skips_the_catalog() -> None:
    d = decide(ATTACHMENT_Q, UPLOAD, ATTACHMENT)
    assert d.attachment_only is True and d.kept_source_ids == ("att-1",)
    assert d.needs_retrieval is True and d.include_course_catalog is False
    assert d.searches_personal_files is True and d.evidence_scoped is True
    assert d.second_chance is False
    assert CUE_ATTACHMENT_SCOPED in d.cues


def test_attachment_with_a_course_comparison_keeps_the_combined_scope() -> None:
    d = decide(ATTACHMENT_VS_COURSE, UPLOAD, ATTACHMENT)
    assert d.attachment_only is False
    assert d.kept_source_ids == ("up-1", "att-1")
    assert scope_label(d) == "both"


def test_attachment_question_drops_a_selected_course_image() -> None:
    d = decide(ATTACHMENT_Q, IMAGE_OK, ATTACHMENT)
    assert d.kept_source_ids == ("att-1",)
    assert d.missing_image_qa is False


def test_attachment_only_after_a_clear_keeps_needs_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the attachment rule on a cleared turn to pin its precedence."""
    monkeypatch.setattr(scope_module, "is_private_attachment_question", lambda *a, **k: True)
    d = decide(STATUS, UPLOAD, ATTACHMENT)
    assert d.scope_cleared is True and d.attachment_only is True
    assert d.needs_retrieval is True and d.kept_source_ids == ()
    assert d.include_course_catalog is False and d.searches_personal_files is False
    assert d.expected_mode == "qa"
    assert [c for c in d.cues if c in FIRST_PASS_TELEMETRY_CUES] == [
        CUE_STAGE_STATUS,
        CUE_ATTACHMENT_SCOPED,
    ]


def test_status_and_progression_together_end_in_coaching_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production runs the progression block after status, so it wins the mode."""
    monkeypatch.setattr(scope_module, "is_current_stage_status_request", lambda *_: True)
    monkeypatch.setattr(scope_module, "is_stage_progression_request", lambda *_: True)
    d = decide("anything", UPLOAD)
    assert d.expected_mode == "coaching" and d.scope_cleared is True
    assert [c for c in d.cues if c in FIRST_PASS_TELEMETRY_CUES] == [
        CUE_STAGE_STATUS,
        CUE_STAGE_PROGRESSION,
    ]


def test_missing_image_question_fails_closed_to_qa() -> None:
    d = decide(IMAGE_Q, IMAGE_LOST)
    assert d.missing_image_qa is True and d.expected_mode == "qa"
    assert d.needs_retrieval is True and d.evidence_scoped is True
    assert d.kept_source_ids == ("img-1",)
    assert d.unresolved_image_ids == frozenset({"img-1"})
    assert (d.include_course_catalog, d.searches_personal_files) == (False, False)
    assert CUE_MISSING_IMAGE_QA in d.cues and d.second_chance is False


@pytest.mark.parametrize(
    ("label", "message", "sources"),
    [
        ("not an information request", "nice", (IMAGE_LOST,)),
        ("a text upload is also selected", IMAGE_Q, (IMAGE_LOST, UPLOAD)),
        ("another image did load", IMAGE_Q, (IMAGE_LOST, IMAGE_OK)),
        ("the image loaded", IMAGE_Q, (IMAGE_OK,)),
        ("no sources", IMAGE_Q, ()),
    ],
)
def test_missing_image_rule_needs_every_condition(
    label: str, message: str, sources: tuple
) -> None:
    d = decide(message, *sources)
    assert d.missing_image_qa is False, label
    assert d.expected_mode == d.mode_policy.expected_mode


def test_missing_image_with_a_stage_clear_is_not_missing_image_qa() -> None:
    d = decide(STATUS, IMAGE_LOST)
    assert d.scope_cleared is True and d.missing_image_qa is False
    assert d.unresolved_image_ids == frozenset()


def test_missing_image_with_an_attachment_question_keeps_the_attachment_only() -> None:
    d = decide(ATTACHMENT_Q, IMAGE_LOST, ATTACHMENT)
    assert d.attachment_only is True and d.missing_image_qa is False
    assert d.kept_source_ids == ("att-1",) and d.unresolved_image_ids == frozenset()


def test_attached_image_that_loaded_keeps_attachment_scope() -> None:
    d = decide(IMAGE_Q, IMAGE_LOST, ATTACHED_IMAGE_OK)
    assert d.attachment_only is True
    assert d.kept_source_ids == ("att-img",)
    assert d.unresolved_image_ids == frozenset()
    assert d.missing_image_qa is False


def test_force_retrieval_with_sources_retrieves_and_scopes_evidence() -> None:
    d = decide(CHIT_CHAT, UPLOAD, force_retrieval=True)
    assert d.needs_retrieval is True and d.evidence_scoped is True
    assert (d.include_course_catalog, d.searches_personal_files) == (False, True)
    assert d.second_chance is False and CUE_FORCE_RETRIEVAL in d.cues


def test_force_retrieval_without_sources_does_not_retrieve() -> None:
    d = decide(CHIT_CHAT, force_retrieval=True)
    assert d.needs_retrieval is False and d.evidence_scoped is True
    assert CUE_FORCE_RETRIEVAL not in d.cues


def test_force_retrieval_reads_the_original_sources_after_a_clear() -> None:
    d = decide(STATUS, UPLOAD, force_retrieval=True)
    assert d.scope_cleared is True and d.kept_source_ids == ()
    assert d.needs_retrieval is True and d.include_course_catalog is False
    assert d.searches_personal_files is False and d.expected_mode == "qa"


def test_force_retrieval_lets_a_course_cue_add_the_catalog() -> None:
    d = decide(COURSE_Q, UPLOAD, force_retrieval=True)
    assert scope_label(d) == "both"


def test_workflow_guidance_with_force_retrieval_never_adds_the_catalog() -> None:
    d = decide(WORKFLOW_ONLY, force_retrieval=True)
    assert d.include_course_catalog is False and d.scope_cleared is True


# --- Laya course-intent hook -------------------------------------------------


def test_course_intent_eligible_on_an_ambiguous_turn_with_no_evidence_route() -> None:
    d = decide(NO_CUE_COURSE_Q)
    assert d.course_intent_eligible is True and d.course_intent_promoted is False


def test_course_intent_promotion_adds_the_catalog_in_qa_mode() -> None:
    d = decide(NO_CUE_COURSE_Q, promoted=True)
    assert d.course_intent_promoted is True and d.include_course_catalog is True
    assert d.needs_retrieval is True and d.expected_mode == "qa"
    assert d.mode_policy.retrieve is True and d.mode_policy.intent == "ambiguous"
    assert d.classifier_retrieve is False
    assert CUE_LOCAL_COURSE_INTENT in d.cues and scope_label(d) == "course"


@pytest.mark.parametrize(
    ("label", "message", "sources", "options"),
    [
        ("a course cue already searches", COURSE_Q, (), {}),
        ("chit-chat", CHIT_CHAT, (), {}),
        ("a source is selected", NO_CUE_COURSE_Q, (UPLOAD,), {}),
        ("an interaction intent is set", NO_CUE_COURSE_Q, (), {"interaction_intent": "project_coaching"}),
        ("a frozen Deep Review history", NO_CUE_COURSE_Q, (), {"frozen_history": True}),
        ("force_retrieval", NO_CUE_COURSE_Q, (), {"force_retrieval": True}),
        ("stage status", STATUS, (), {}),
        ("progression", PROGRESSION, (), {}),
        ("workflow guidance", WORKFLOW_ONLY, (), {}),
    ],
)
def test_course_intent_is_not_eligible_when_an_evidence_route_exists(
    label: str, message: str, sources: tuple, options: dict
) -> None:
    d = decide(message, *sources, **options)
    assert d.course_intent_eligible is False, label
    # A promotion request on an ineligible turn changes nothing.
    assert decide(message, *sources, promoted=True, **options) == d


def test_course_intent_promotion_runs_before_the_upload_rule() -> None:
    # Eligibility needs no selected source, so use the promotion call directly
    # with an upload enabled: it cannot also fire the upload policy.
    d = decide(NO_CUE_COURSE_Q, promoted=True, upload_retrieval_enabled=True)
    assert d.upload_policy_only is False and CUE_UPLOAD_POLICY not in d.cues


# --- second chance and helpers -----------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "searched", "scoped", "expected"),
    [
        (True, False, False, True),
        (True, True, False, False),
        (True, False, True, False),
        (True, True, True, False),
        (False, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, True, True, False),
    ],
)
def test_wants_source_need_check_truth_table(
    enabled: bool, searched: bool, scoped: bool, expected: bool
) -> None:
    assert (
        wants_source_need_check(enabled=enabled, searched=searched, evidence_scoped=scoped)
        is expected
    )


@pytest.mark.parametrize(
    ("enabled", "needs", "has_upload", "scoped", "message", "expected"),
    [
        (True, False, True, False, UPLOAD_Q, True),
        (False, False, True, False, UPLOAD_Q, False),
        (True, True, True, False, UPLOAD_Q, False),
        (True, False, False, False, UPLOAD_Q, False),
        (True, False, True, True, UPLOAD_Q, False),
        (True, False, True, False, CHIT_CHAT, False),
    ],
)
def test_wants_student_upload_retrieval_truth_table(
    enabled: bool, needs: bool, has_upload: bool, scoped: bool, message: str, expected: bool
) -> None:
    assert (
        wants_student_upload_retrieval(
            enabled=enabled,
            needs_retrieval=needs,
            has_student_upload=has_upload,
            evidence_scoped=scoped,
            student_message=message,
        )
        is expected
    )


def test_course_catalog_cues_agree_with_the_boolean() -> None:
    for message in (COURSE_Q, NO_CUE_COURSE_Q, UPLOAD_Q, CHIT_CHAT, "What is a persona?"):
        assert wants_course_catalog_retrieval(message, mode_retrieve=True) is bool(
            course_catalog_cues(message)
        )
        assert wants_course_catalog_retrieval(message, mode_retrieve=False) is False


def test_image_and_upload_predicates() -> None:
    assert is_image_source(kind="image", mime="") and is_image_source(kind="", mime="Image/PNG")
    assert not is_image_source(kind="file", mime="application/pdf")
    assert is_searchable_student_upload(is_course_library=False, is_image=False)
    assert not is_searchable_student_upload(is_course_library=True, is_image=False)
    assert not is_searchable_student_upload(is_course_library=False, is_image=True)


def test_chit_chat_and_candidate_helpers() -> None:
    assert is_chit_chat("thanks") and not is_chit_chat("hi, what does my survey say?")
    assert local_course_intent_candidate(
        NO_CUE_COURSE_Q, intent="ambiguous", evidence_scoped=False, searched=False
    )
    assert not local_course_intent_candidate(
        NO_CUE_COURSE_Q, intent="ambiguous", evidence_scoped=True, searched=False
    )


def test_decision_is_pure_and_leaves_inputs_alone() -> None:
    inputs = ScopeInputs(
        message=COURSE_Q,
        current_stage="problem_identification",
        sources=(UPLOAD, ATTACHMENT),
        attachment_count=1,
    )
    assert decide_first_pass_scope(inputs) == decide_first_pass_scope(inputs)
    assert inputs.sources == (UPLOAD, ATTACHMENT)


def test_telemetry_cue_groups_are_ordered_and_disjoint() -> None:
    assert FIRST_PASS_TELEMETRY_CUES == (
        CUE_STAGE_STATUS,
        CUE_STAGE_PROGRESSION,
        CUE_WORKFLOW_SKIPS_RETRIEVAL,
        CUE_ATTACHMENT_SCOPED,
    )
    assert POST_MODEL_TELEMETRY_CUES == (CUE_LOCAL_COURSE_INTENT, CUE_UPLOAD_POLICY)
    assert not set(FIRST_PASS_TELEMETRY_CUES) & set(POST_MODEL_TELEMETRY_CUES)


# --- import boundary ---------------------------------------------------------

_MODULE_PATH = Path(scope_module.__file__)
_ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "backend.coaching.mode_policy",
    "backend.coaching.workflow_navigation",
    "backend.retrieval",
    "backend.retrieval_gate",
    "backend.specialists.routing",
}
_FORBIDDEN_ROOTS = {"boto3", "botocore", "openai", "sqlite3", "requests", "httpx"}
_FORBIDDEN_BACKEND = (
    "backend.persistence",
    "backend.student_store",
    "backend.sources",
    "backend.source_library",
    "backend.providers",
    "backend.settings",
    "backend.repositories",
    "backend.agentcore_provider",
    "backend.bedrock_provider",
    "backend.bedrock_retrieve",
)


def _imported_modules() -> set[str]:
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are not allowed"
            found.add(str(node.module))
    return found


def test_module_imports_only_pure_dependencies() -> None:
    imported = _imported_modules()
    assert imported <= _ALLOWED_IMPORTS, sorted(imported - _ALLOWED_IMPORTS)
    assert not {name.split(".")[0] for name in imported} & _FORBIDDEN_ROOTS
    assert not [n for n in imported if n.startswith(_FORBIDDEN_BACKEND)]


def test_importing_the_module_loads_no_storage_provider_or_settings() -> None:
    code = (
        "import sys, backend.coaching.evidence_scope\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in {'boto3', 'botocore'}"
        " or m.startswith(%r))\n"
        "print(bad)\n"
    ) % (_FORBIDDEN_BACKEND,)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=_MODULE_PATH.parents[2],
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout
