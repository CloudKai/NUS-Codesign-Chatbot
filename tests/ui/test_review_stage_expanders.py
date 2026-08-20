"""Review-tab stage expander remount keys. No Streamlit runtime required."""

from __future__ import annotations

from pathlib import Path

from backend.student_journey import THINKING_STAGES
from ui.panels.studio import (
    review_stage_expander_defaults,
    review_stage_expander_key,
)

_STAGE_IDS = [stage.id for stage in THINKING_STAGES]
_STUDIO = Path("ui/panels/studio.py").read_text(encoding="utf-8")


def test_problem_identification_defaults_only_current_open() -> None:
    defaults = review_stage_expander_defaults("problem_identification")
    assert defaults["problem_identification"] is True
    assert [stage_id for stage_id, open_ in defaults.items() if open_] == [
        "problem_identification"
    ]
    assert list(defaults) == _STAGE_IDS


def test_concept_generation_defaults_collapse_problem_identification() -> None:
    defaults = review_stage_expander_defaults("concept_generation")
    assert defaults["problem_identification"] is False
    assert defaults["concept_generation"] is True
    assert defaults["design_specification"] is False
    assert defaults["deep_analysis"] is False
    assert defaults["reflection"] is False


def test_design_specification_defaults_only_current_open() -> None:
    defaults = review_stage_expander_defaults("design_specification")
    assert defaults["problem_identification"] is False
    assert defaults["concept_generation"] is False
    assert defaults["design_specification"] is True


def test_stage_change_remounts_expander_keys() -> None:
    pi = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="problem_identification",
        stage_key="problem_identification",
    )
    after_advance = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="problem_identification",
    )
    cg_current = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="concept_generation",
    )
    ds_current = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="design_specification",
        stage_key="design_specification",
    )
    assert pi != after_advance
    assert "concept_generation" in cg_current
    assert cg_current != ds_current
    assert "problem_identification" in after_advance
    assert "concept_generation" in after_advance


def test_same_stage_rerender_keeps_stable_keys() -> None:
    first = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="problem_identification",
    )
    second = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="problem_identification",
    )
    assert first == second


def test_notebook_switch_does_not_reuse_expander_keys() -> None:
    notebook_a = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="concept_generation",
    )
    notebook_b = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_b",
        current_stage_id="concept_generation",
        stage_key="concept_generation",
    )
    assert notebook_a != notebook_b


def test_strengths_and_areas_share_defaults_and_remount_separately() -> None:
    defaults = review_stage_expander_defaults("concept_generation")
    strengths = review_stage_expander_key(
        key_prefix="strengths",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="concept_generation",
    )
    areas = review_stage_expander_key(
        key_prefix="improvements",
        thread_key="nb_a",
        current_stage_id="concept_generation",
        stage_key="concept_generation",
    )
    assert defaults["concept_generation"] is True
    assert defaults["problem_identification"] is False
    assert strengths != areas
    assert "_strengths_" in strengths
    assert "_improvements_" in areas


def test_studio_remounts_expanders_instead_of_writing_session_state() -> None:
    assert "def _sync_review_stage_expander_state" not in _STUDIO
    assert "st.session_state[expander_key]" not in _STUDIO
    assert "review_stage_expander_key(" in _STUDIO
    assert "review_stage_expander_defaults(" in _STUDIO
    assert 'key_prefix="strengths"' in _STUDIO
    assert 'key_prefix="improvements"' in _STUDIO
    assert "expanded=is_current" in _STUDIO
