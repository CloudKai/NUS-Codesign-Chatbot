"""Unit tests for Enter-only rename draft cleanup and key scoping."""

from __future__ import annotations

import streamlit as st

from ui.rename import bump_rename_epoch, discard_rename_draft, rename_epoch


def test_discard_rename_draft_removes_only_prefixed_keys(monkeypatch):
    """Substring accidents must not wipe unrelated session keys."""
    state = {
        "rename-notebook-form-abc-0": True,
        "rename-notebook-abc-0-Untitled": "draft",
        "FormSubmitter:rename-notebook-form-abc-0-Apply": True,
        "notebook-rename-epoch-abc": 0,
        "unrelated-abc-rename-notebook-trap": "keep",
        "other": 1,
    }
    monkeypatch.setattr(st, "session_state", state)

    discard_rename_draft("notebook", "abc")

    assert "rename-notebook-form-abc-0" not in state
    assert "rename-notebook-abc-0-Untitled" not in state
    assert "FormSubmitter:rename-notebook-form-abc-0-Apply" not in state
    assert state["notebook-rename-epoch-abc"] == 0
    assert state["unrelated-abc-rename-notebook-trap"] == "keep"
    assert state["other"] == 1


def test_bump_rename_epoch_increments_and_is_readable(monkeypatch):
    state: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", state)

    assert rename_epoch("source", "src-1") == 0
    assert bump_rename_epoch("source", "src-1") == 1
    assert rename_epoch("source", "src-1") == 1
    assert bump_rename_epoch("source", "src-1") == 2
