"""Validated deployment-scoped module identity shared with the application.

This file lives inside ``agentcore_runtime`` so a packaged AgentCore artifact
contains the same profile contract as FastAPI and Streamlit. The repository
root module is a compatibility re-export; do not duplicate validation there.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_MODULE_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_MODULE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,19}$")
_PROFILE_VERSION = re.compile(r"^[1-9][0-9]{0,3}$")
_FORBIDDEN = frozenset("<>`{}[]\\\x00\r\n")


def _required_text(name: str, value: str, maximum: int) -> str:
    """Return one safe display value or raise ``ValueError``."""
    raw = str(value or "")
    cleaned = " ".join(raw.split()).strip()
    if not cleaned or len(cleaned) > maximum or any(char in _FORBIDDEN for char in raw):
        raise ValueError(f"{name} is invalid")
    if cleaned.casefold().startswith("<") or "your_" in cleaned.casefold():
        raise ValueError(f"{name} is invalid")
    return cleaned


def normalize_course_prefix(value: str) -> str:
    """Return a safe course prefix with exactly one trailing slash."""
    cleaned = str(value or "").strip().replace("\\", "/").strip("/")
    if not cleaned or len(cleaned) > 160 or ".." in cleaned.split("/"):
        raise ValueError("COURSE_MATERIALS_PREFIX is invalid")
    if any(char in _FORBIDDEN for char in cleaned) or cleaned.startswith("users/"):
        raise ValueError("COURSE_MATERIALS_PREFIX is invalid")
    return f"{cleaned}/"


@dataclass(frozen=True)
class ModuleProfile:
    """Identity and course-content scope for one isolated deployment."""

    module_id: str
    module_code: str
    module_name: str
    product_title: str
    course_materials_prefix: str = "course/"
    profile_version: str = "1"

    def __post_init__(self) -> None:
        """Validate direct construction and normalize stable values."""
        module_id = str(self.module_id or "").strip()
        module_code = str(self.module_code or "").strip()
        version = str(self.profile_version or "").strip()
        if not _MODULE_ID.fullmatch(module_id) or module_id in {"replace-me", "placeholder", "example"}:
            raise ValueError("MODULE_ID is invalid")
        if not _MODULE_CODE.fullmatch(module_code):
            raise ValueError("MODULE_CODE is invalid")
        if not _PROFILE_VERSION.fullmatch(version):
            raise ValueError("MODULE_PROFILE_VERSION is invalid")
        object.__setattr__(self, "module_id", module_id)
        object.__setattr__(self, "module_code", module_code)
        object.__setattr__(self, "module_name", _required_text("MODULE_NAME", self.module_name, 100))
        object.__setattr__(self, "product_title", _required_text("MODULE_PRODUCT_TITLE", self.product_title, 120))
        object.__setattr__(self, "course_materials_prefix", normalize_course_prefix(self.course_materials_prefix))
        object.__setattr__(self, "profile_version", version)

    @classmethod
    def from_environment(cls) -> "ModuleProfile":
        """Load the explicit deployment contract from environment variables."""
        return cls(
            module_id=os.getenv("MODULE_ID", ""), module_code=os.getenv("MODULE_CODE", ""),
            module_name=os.getenv("MODULE_NAME", ""), product_title=os.getenv("MODULE_PRODUCT_TITLE", ""),
            course_materials_prefix=os.getenv("COURSE_MATERIALS_PREFIX", "course/"),
            profile_version=os.getenv("MODULE_PROFILE_VERSION", "1"),
        )


def development_module_profile() -> ModuleProfile:
    """Return the current local-demo identity when no profile is configured."""
    return ModuleProfile("cde2300", "CDE2300", "Product Design and Innovation", "CDE2300 Design Thinking Companion")


def load_module_profile(*, require_explicit: bool = False) -> ModuleProfile:
    """Load the deployment profile, allowing the local default only in development."""
    if require_explicit or any(os.getenv(name) is not None for name in ("MODULE_ID", "MODULE_CODE", "MODULE_NAME", "MODULE_PRODUCT_TITLE")):
        return ModuleProfile.from_environment()
    return development_module_profile()
