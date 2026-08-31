"""Compatibility import for the canonical packaged module-profile contract."""

from agentcore_runtime.module_profile import (
    ModuleProfile,
    development_module_profile,
    load_module_profile,
    normalize_course_prefix,
)

__all__ = (
    "ModuleProfile",
    "development_module_profile",
    "load_module_profile",
    "normalize_course_prefix",
)
