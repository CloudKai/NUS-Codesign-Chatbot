"""Shared identity and validation for the research learning-workflow contract."""

from __future__ import annotations

from typing import Any


WORKFLOW_CONTRACT_KEY = "research_workflow_contract"
WORKFLOW_CONTRACT_VERSION = "cde2300-five-phase-v1"


def workflow_contract_payload() -> dict[str, str]:
    """Return a new serializable value for the current learning contract."""
    return {"version": WORKFLOW_CONTRACT_VERSION}


def workflow_contract_is_ready(value: Any) -> bool:
    """Return whether *value* identifies the current five-phase contract."""
    return isinstance(value, dict) and value.get("version") == WORKFLOW_CONTRACT_VERSION
