"""Shared Enter-only rename helpers for notebooks, sources, and the top bar.

Rename fields commit only when the student presses Enter (form submit). Closing
a dialog/popover without Enter discards the draft by deleting known widget keys
and bumping an epoch so the next open restores the saved title.
"""

from __future__ import annotations

from typing import Literal

import streamlit as st
import streamlit.components.v1 as components

RenameKind = Literal["notebook", "source", "topbar"]

# Mirrored by ``content:"Press Enter to apply"`` in ``ui/assets/template.css``.
_ENTER_HINT = "Press Enter to apply"

_KEY_PREFIXES: dict[RenameKind, tuple[str, ...]] = {
    "notebook": (
        "rename-notebook-form-",
        "rename-notebook-",
        "FormSubmitter:rename-notebook-form-",
    ),
    "source": (
        "rename-source-form-",
        "rename-source-input-",
        "FormSubmitter:rename-source-form-",
    ),
    "topbar": (
        "rename-topbar-form-",
        "topbar-notebook-title-",
        "FormSubmitter:rename-topbar-form-",
    ),
}


def rename_epoch(kind: RenameKind, item_id: str) -> int:
    """Return the current rename-widget epoch for ``item_id``."""
    return int(st.session_state.get(f"{kind}-rename-epoch-{item_id}") or 0)


def bump_rename_epoch(kind: RenameKind, item_id: str) -> int:
    """Invalidate rename widget keys for ``item_id`` and return the new epoch."""
    epoch_key = f"{kind}-rename-epoch-{item_id}"
    st.session_state[epoch_key] = int(st.session_state.get(epoch_key) or 0) + 1
    return int(st.session_state[epoch_key])


def discard_rename_draft(kind: RenameKind, item_id: str) -> None:
    """Delete known rename form/widget keys for one item.

    Only removes keys that start with documented prefixes and include the item
    id, so unrelated session state cannot be wiped by substring accidents.
    """
    item = str(item_id)
    prefixes = _KEY_PREFIXES[kind]
    for key in list(st.session_state.keys()):
        text = str(key)
        if item not in text:
            continue
        if any(text.startswith(prefix) for prefix in prefixes):
            del st.session_state[key]


def render_enter_to_apply_rename(
    *,
    kind: RenameKind,
    item_id: str,
    label: str,
    current_value: str,
    max_chars: int | None = None,
    label_visibility: Literal["visible", "hidden", "collapsed"] = "visible",
) -> tuple[bool, str]:
    """Render an Enter-only rename form and return ``(applied, cleaned_value)``.

    The Apply submit control is present for Streamlit form Enter handling and is
    visually hidden by CSS. Focused fields still show ``Press Enter to apply``
    via CSS; no Streamlit help icon is attached to the label.
    """
    epoch = rename_epoch(kind, str(item_id))
    safe_value = str(current_value or "").strip()
    if kind == "notebook":
        form_key = f"rename-notebook-form-{item_id}-{epoch}"
        input_key = f"rename-notebook-{item_id}-{epoch}-{safe_value}"
    elif kind == "source":
        form_key = f"rename-source-form-{item_id}-{epoch}"
        input_key = f"rename-source-input-{item_id}-{epoch}-{safe_value}"
    else:
        form_key = f"rename-topbar-form-{item_id}-{epoch}"
        input_key = f"topbar-notebook-title-{item_id}-{epoch}-{safe_value}"

    with st.form(key=form_key, border=False, enter_to_submit=True):
        kwargs: dict[str, object] = {
            "label": label,
            "value": safe_value,
            "key": input_key,
            "label_visibility": label_visibility,
        }
        if max_chars is not None:
            kwargs["max_chars"] = max_chars
        renamed = st.text_input(**kwargs)  # type: ignore[arg-type]
        applied = st.form_submit_button("Apply")
    cleaned = " ".join(str(renamed or "").split()).strip()
    return bool(applied), cleaned


def sync_rename_select_all(*, root_selector: str, aria_label: str = "Rename") -> None:
    """Select all rename text when the field inside ``root_selector`` is focused."""
    # Keep the selector/label substitution simple and quote-safe for the script.
    safe_root = root_selector.replace("\\", "\\\\").replace("'", "\\'")
    safe_label = aria_label.replace("\\", "\\\\").replace("'", "\\'")
    components.html(
        f"""
<script>
(() => {{
  const doc = window.parent.document;
  const win = window.parent;
  const rootSelector = '{safe_root}';
  const ariaLabel = '{safe_label}';

  function renameInput() {{
    const root = doc.querySelector(rootSelector);
    if (!root) return null;
    return (
      root.querySelector('input[aria-label="' + ariaLabel + '"]') ||
      root.querySelector('[data-testid="stTextInputRootElement"] input')
    );
  }}

  function bind(input) {{
    if (!input || input.dataset.cdRenameSelectBound === "1") return false;
    input.dataset.cdRenameSelectBound = "1";
    input.addEventListener("focus", () => {{
      win.requestAnimationFrame(() => {{
        try {{ input.select(); }} catch (err) {{}}
      }});
    }});
    return true;
  }}

  function boot() {{
    if (bind(renameInput())) return;
    let attempts = 0;
    const timer = win.setInterval(() => {{
      attempts += 1;
      if (bind(renameInput()) || attempts > 40) win.clearInterval(timer);
    }}, 50);
  }}

  boot();
}})();
</script>
        """,
        height=0,
    )
