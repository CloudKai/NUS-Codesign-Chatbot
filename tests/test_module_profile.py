"""Contract tests for isolated deployment module profiles."""

from __future__ import annotations

import pytest

from module_profile import ModuleProfile, load_module_profile


def test_module_profile_normalizes_course_prefix() -> None:
    """A safe profile normalizes its shared course prefix once."""
    profile = ModuleProfile(
        module_id="des-1000",
        module_code="DES1000",
        module_name="Design Foundations",
        product_title="DES1000 Design Companion",
        course_materials_prefix="materials",
        profile_version="2",
    )
    assert profile.course_materials_prefix == "materials/"


@pytest.mark.parametrize("module_id", ["CDE2300", "cde_2300", "replace-me", "a"])
def test_module_profile_rejects_unsafe_or_placeholder_ids(module_id: str) -> None:
    """Deployment identifiers cannot become ambiguous resource names."""
    with pytest.raises(ValueError):
        ModuleProfile(module_id, "DES1000", "Design", "Companion")


def test_module_profile_requires_all_production_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial environment cannot silently select the development profile."""
    monkeypatch.setenv("MODULE_ID", "des-1000")
    monkeypatch.delenv("MODULE_CODE", raising=False)
    with pytest.raises(ValueError):
        load_module_profile()


def test_synthetic_module_profile_drives_ui_prompt_and_course_utilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One synthetic profile reaches packaged prompts and configured key helpers."""
    monkeypatch.setenv("MODULE_ID", "testmodule")
    monkeypatch.setenv("MODULE_CODE", "CDE9999")
    monkeypatch.setenv("MODULE_NAME", "Synthetic Design Module")
    monkeypatch.setenv("MODULE_PRODUCT_TITLE", "Synthetic Design Companion")
    monkeypatch.setenv("COURSE_MATERIALS_PREFIX", "materials/")

    from agentcore_runtime import module_profile as packaged_profile
    from agentcore_runtime.prompts import loader
    from backend.coaching.mode_policy import _module_identity_reference_pattern
    from scripts.diagnostics.check_knowledge_base_retrieve import (
        resolve_course_object_key as resolve_checked_key,
    )
    from scripts.diagnostics.test_course_retrieval import (
        resolve_course_object_key as resolve_tested_key,
    )
    from ui.constants import product_profile

    loader.load_fast_chat_prompt.cache_clear()
    profile = product_profile()
    prompt = loader.load_fast_chat_prompt()
    assert ModuleProfile is packaged_profile.ModuleProfile
    assert profile.module_code == "CDE9999"
    assert profile.product_title == "Synthetic Design Companion"
    assert "CDE9999" in prompt
    assert "Synthetic Design Module" in prompt
    assert "CDE2300" not in prompt
    assert "CDE2300" not in _module_identity_reference_pattern()
    assert resolve_checked_key("lectureNotes/week-01.pdf") == "materials/lectureNotes/week-01.pdf"
    assert resolve_tested_key("week-01.pdf") == "materials/lectureNotes/week-01.pdf"
    loader.load_fast_chat_prompt.cache_clear()
