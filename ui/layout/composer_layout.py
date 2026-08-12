"""Keep the chat composer compact while allowing multiline drafts.

``sync_composer_layout`` caps the native Streamlit chat input at five rows,
then enables internal scrolling. Call it once after rendering the composer.
"""

from __future__ import annotations

import streamlit.components.v1 as components


def sync_composer_layout() -> None:
    """Grow the native chat textarea with its draft, capped at five rows."""
    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;

  function root() {
    return doc.querySelector(".st-key-chat_composer");
  }

  function chatInput(composer) {
    return composer ? composer.querySelector('[data-testid="stChatInput"]') : null;
  }

  function textShells(textarea) {
    const shells = [];
    let node = textarea.parentElement;
    for (let depth = 0; depth < 5 && node; depth += 1) {
      const testId = node.getAttribute("data-testid") || "";
      if (testId === "stChatInput") break;
      const isTextShell =
        node.getAttribute("data-baseweb") === "textarea" ||
        node === textarea.parentElement ||
        (!!node.querySelector &&
          !!node.querySelector('[data-testid="stChatInputTextArea"], textarea') &&
          !node.querySelector('[data-testid="stChatInputSubmitButton"]'));
      if (isTextShell) shells.push(node);
      node = node.parentElement;
    }
    return shells;
  }

  function capTextarea(textarea) {
    const MAX_ROWS = 5;
    const styles = win.getComputedStyle(textarea);
    const fontSize = parseFloat(styles.fontSize) || 15.2;
    const lineHeight = parseFloat(styles.lineHeight) || fontSize * 1.45;
    const maxHeight = lineHeight * MAX_ROWS;
    const minHeight = lineHeight;
    const shells = textShells(textarea);

    for (const shell of shells) {
      shell.style.setProperty("height", "auto", "important");
      shell.style.setProperty("max-height", maxHeight + "px", "important");
      shell.style.setProperty("overflow", "hidden", "important");
    }
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
    for (const shell of shells) {
      shell.style.setProperty("height", nextHeight + "px", "important");
    }
  }

  function apply() {
    const composer = root();
    const input = chatInput(composer);
    if (!composer || !input) return false;
    composer.classList.add("cd-composer-card");
    input.classList.add("cd-composer-card");
    const textarea = input.querySelector(
      '[data-testid="stChatInputTextArea"], textarea'
    );
    if (textarea) capTextarea(textarea);
    return true;
  }

  function bind() {
    const composer = root();
    const input = chatInput(composer);
    const textarea = input
      ? input.querySelector('[data-testid="stChatInputTextArea"], textarea')
      : null;
    if (!composer || !input || !textarea) return false;

    if (composer.dataset.cdComposerBound === "1") {
      apply();
      return true;
    }
    composer.dataset.cdComposerBound = "1";

    const schedule = () => win.requestAnimationFrame(apply);
    textarea.addEventListener("input", schedule);
    textarea.addEventListener("change", schedule);
    textarea.addEventListener("paste", () => {
      win.setTimeout(schedule, 0);
      win.setTimeout(schedule, 50);
    });
    win.addEventListener("resize", schedule);
    const observer = new win.MutationObserver(schedule);
    if (input instanceof win.Node) {
      observer.observe(input, { childList: true, subtree: true, characterData: true });
    }
    if (typeof win.ResizeObserver === "function") {
      const resizeObserver = new win.ResizeObserver(schedule);
      resizeObserver.observe(input);
      resizeObserver.observe(textarea);
    }
    apply();
    return true;
  }

  function boot() {
    if (bind()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {
      attempts += 1;
      if (bind() || attempts > 60) win.clearInterval(timer);
    }, 80);
  }

  boot();
})();
</script>
        """,
        height=0,
    )
