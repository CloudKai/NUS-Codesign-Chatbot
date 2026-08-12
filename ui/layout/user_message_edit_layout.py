"""Size the inline user-message editor to match the 8-row bubble cap.

``USER_BUBBLE_MAX_ROWS`` is the single source of truth for the bubble and edit
cap. Keep ``ui/assets/styles/00-foundations.css`` ``--cd-user-bubble-max-rows`` in sync.
"""

from __future__ import annotations

import streamlit.components.v1 as components

# Keep in sync with --cd-user-bubble-max-rows / row-height tokens in styles/00-foundations.css.
USER_BUBBLE_MAX_ROWS = 8
USER_BUBBLE_FONT_REM = 0.9
USER_BUBBLE_LINE_HEIGHT = 1.45
# Streamlit ``st.text_area`` height is pixels; assume a 16px root font size.
USER_MESSAGE_EDIT_HEIGHT_PX = round(
    USER_BUBBLE_FONT_REM * 16 * USER_BUBBLE_LINE_HEIGHT * USER_BUBBLE_MAX_ROWS
)


def sync_user_message_edit_layout() -> None:
    """Grow the edit textarea with content, capped at the bubble row limit."""
    components.html(
        f"""
<script>
(() => {{
  const doc = window.parent.document;
  const win = window.parent;
  const FALLBACK_MAX_ROWS = {USER_BUBBLE_MAX_ROWS};

  function cleanupPrevious() {{
    const previous = win.__cdUserEditCleanup;
    if (typeof previous === "function") {{
      try {{ previous(); }} catch (error) {{ /* ignore stale teardown */ }}
    }}
    win.__cdUserEditCleanup = null;
  }}

  function resolveMaxRows() {{
    const raw = win
      .getComputedStyle(doc.documentElement)
      .getPropertyValue("--cd-user-bubble-max-rows")
      .trim();
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : FALLBACK_MAX_ROWS;
  }}

  function editRoot() {{
    return doc.querySelector('[class*="st-key-user_message_edit_"]');
  }}

  function textShells(textarea) {{
    const shells = [];
    let node = textarea.parentElement;
    for (let depth = 0; depth < 5 && node; depth += 1) {{
      const testId = node.getAttribute("data-testid") || "";
      if (testId === "stTextArea") {{
        shells.push(node);
        break;
      }}
      const isTextShell =
        node.getAttribute("data-baseweb") === "textarea" ||
        node === textarea.parentElement ||
        (!!node.querySelector &&
          !!node.querySelector("textarea") &&
          !node.querySelector('[data-testid="stChatInputSubmitButton"]'));
      if (isTextShell) shells.push(node);
      node = node.parentElement;
    }}
    return shells;
  }}

  function capTextarea(textarea) {{
    const maxRows = resolveMaxRows();
    const styles = win.getComputedStyle(textarea);
    const fontSize = parseFloat(styles.fontSize) || 14.4;
    const lineHeight = parseFloat(styles.lineHeight) || fontSize * 1.45;
    const maxHeight = lineHeight * maxRows;
    const minHeight = lineHeight;
    const shells = textShells(textarea);
    const textAreaWidget = textarea.closest('[data-testid="stTextArea"]');

    for (const shell of shells) {{
      shell.style.setProperty("height", "auto", "important");
      shell.style.setProperty("max-height", maxHeight + "px", "important");
      shell.style.setProperty("overflow", "hidden", "important");
    }}
    if (textAreaWidget) {{
      textAreaWidget.style.setProperty("max-height", maxHeight + "px", "important");
      textAreaWidget.style.setProperty("overflow", "hidden", "important");
    }}
    textarea.style.setProperty("max-height", maxHeight + "px", "important");
    textarea.style.setProperty("height", minHeight + "px", "important");
    textarea.style.setProperty("overflow-y", "hidden", "important");
    void textarea.offsetHeight;

    const measured = Math.max(textarea.scrollHeight, minHeight);
    const nextHeight = Math.min(measured, maxHeight);
    const needsScroll = measured > maxHeight;

    textarea.style.setProperty("height", nextHeight + "px", "important");
    textarea.style.setProperty(
      "overflow-y",
      needsScroll ? "auto" : "hidden",
      "important"
    );
    for (const shell of shells) {{
      shell.style.setProperty("height", nextHeight + "px", "important");
      shell.style.setProperty("max-height", maxHeight + "px", "important");
      shell.style.setProperty("overflow", "hidden", "important");
    }}
    if (textAreaWidget) {{
      textAreaWidget.style.setProperty("height", nextHeight + "px", "important");
      textAreaWidget.style.setProperty("max-height", maxHeight + "px", "important");
    }}
  }}

  function apply() {{
    const root = editRoot();
    if (!root) return false;
    const textarea = root.querySelector("textarea");
    if (!textarea) return false;
    capTextarea(textarea);
    win.requestAnimationFrame(() => {{
      capTextarea(textarea);
      win.requestAnimationFrame(() => capTextarea(textarea));
    }});
    return true;
  }}

  function bind() {{
    const root = editRoot();
    const textarea = root ? root.querySelector("textarea") : null;
    if (!root || !textarea) return false;

    cleanupPrevious();

    const schedule = () => win.requestAnimationFrame(apply);
    const onResize = () => schedule();
    textarea.addEventListener("input", schedule);
    textarea.addEventListener("change", schedule);
    const onPaste = () => {{
      win.setTimeout(schedule, 0);
      win.setTimeout(schedule, 50);
    }};
    textarea.addEventListener("paste", onPaste);
    win.addEventListener("resize", onResize);
    const observer = new win.MutationObserver(schedule);
    if (root instanceof win.Node) {{
      observer.observe(root, {{ childList: true, subtree: true, characterData: true }});
    }}
    let resizeObserver = null;
    if (typeof win.ResizeObserver === "function") {{
      resizeObserver = new win.ResizeObserver(schedule);
      resizeObserver.observe(textarea);
    }}

    win.__cdUserEditCleanup = () => {{
      textarea.removeEventListener("input", schedule);
      textarea.removeEventListener("change", schedule);
      textarea.removeEventListener("paste", onPaste);
      win.removeEventListener("resize", onResize);
      observer.disconnect();
      if (resizeObserver) resizeObserver.disconnect();
    }};

    apply();
    return true;
  }}

  function boot() {{
    if (bind()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {{
      attempts += 1;
      if (bind() || attempts > 60) win.clearInterval(timer);
    }}, 80);
  }}

  boot();
}})();
</script>
        """,
        height=0,
    )
