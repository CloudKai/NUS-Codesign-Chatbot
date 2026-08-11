"""Helpers to remount select-only Streamlit popovers so they close after a pick.

Streamlit popovers stay open across a fragment/app rerun when their widget key
is unchanged. Bumping an epoch in the key remounts a closed popover.
"""

from __future__ import annotations

import streamlit as st


def menu_popover_widget_key(kind: str, *parts: str) -> str:
    """Return a popover widget key that includes the close epoch for *kind*."""
    suffix = "-".join(str(part) for part in parts if str(part))
    epoch = int(st.session_state.get(_epoch_state_key(kind, *parts)) or 0)
    if suffix:
        return f"{kind}-popover-{suffix}-{epoch}"
    return f"{kind}-popover-{epoch}"


def close_menu_popover(kind: str, *parts: str) -> None:
    """Bump the popover epoch so the next render mounts it closed."""
    state_key = _epoch_state_key(kind, *parts)
    st.session_state[state_key] = int(st.session_state.get(state_key) or 0) + 1


def _epoch_state_key(kind: str, *parts: str) -> str:
    suffix = "_".join(str(part) for part in parts if str(part))
    if suffix:
        return f"_menu_popover_epoch_{kind}_{suffix}"
    return f"_menu_popover_epoch_{kind}"
