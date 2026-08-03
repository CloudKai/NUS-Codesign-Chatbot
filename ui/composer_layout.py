"""Keep the chat composer in a Cursor-style card with a footer control row."""

from __future__ import annotations

import streamlit.components.v1 as components


def sync_composer_layout() -> None:
    """Pin the model chip beside the attach control on the composer footer."""
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

  function modelSlot(composer) {
    return composer ? composer.querySelector(".st-key-composer_model_slot") : null;
  }

  function modelPopover(composer) {
    const slot = modelSlot(composer);
    if (!slot) return null;

    // If a prior pass moved the chip into Streamlit's footer, pull it back.
    const moved = composer.querySelector(
      '[data-testid="stChatInput"] [data-testid="stPopover"]'
    );
    if (moved && !slot.contains(moved)) {
      const anchor =
        slot.querySelector('[data-testid="stElementContainer"]') ||
        slot.querySelector('[data-testid="stVerticalBlock"]') ||
        slot;
      anchor.appendChild(moved);
    }

    return slot.querySelector('[data-testid="stPopover"]');
  }

  function fileUpload(input) {
    return input
      ? input.querySelector('[data-testid="stChatInputFileUploadButton"]')
      : null;
  }

  function placeModel(composer, input) {
    const popover = modelPopover(composer);
    if (!popover || !input) return;

    const attach = fileUpload(input);
    const attachBtn = attach ? attach.querySelector("button") || attach : null;
    if (!attachBtn) return;

    const composerRect = composer.getBoundingClientRect();
    const attachRect = attachBtn.getBoundingClientRect();
    const chipHeight = Math.max(popover.getBoundingClientRect().height || 24, 24);
    const chipWidth = Math.min(
      Math.max(popover.getBoundingClientRect().width || 90, 72),
      168
    );

    const left = attachRect.right - composerRect.left + 10;
    const top = attachRect.top - composerRect.top + attachRect.height / 2 - chipHeight / 2;

    const maxLeft = composerRect.width - chipWidth - 56;
    const clampedLeft = Math.max(34, Math.min(left, maxLeft));

    popover.classList.add("cd-model-placed");
    popover.style.setProperty("position", "absolute", "important");
    popover.style.setProperty("left", clampedLeft + "px", "important");
    popover.style.setProperty("top", top + "px", "important");
    popover.style.setProperty("right", "auto", "important");
    popover.style.setProperty("bottom", "auto", "important");
    popover.style.setProperty("margin", "0", "important");
    popover.style.setProperty("transform", "none", "important");
    popover.style.setProperty("z-index", "45", "important");
    popover.style.setProperty("width", "max-content", "important");
    popover.style.setProperty("max-width", "10.5rem", "important");
    popover.style.setProperty("min-width", "max-content", "important");
    popover.style.setProperty("pointer-events", "auto", "important");
    popover.style.setProperty("white-space", "nowrap", "important");
    popover.style.setProperty("opacity", "1", "important");
    popover.style.setProperty("visibility", "visible", "important");
  }

  function capTextarea(textarea) {
    const styles = win.getComputedStyle(textarea);
    const lineHeight = parseFloat(styles.lineHeight) || parseFloat(styles.fontSize) * 1.45;
    const maxHeight = lineHeight * 3;
    textarea.style.setProperty("max-height", maxHeight + "px", "important");
    textarea.style.setProperty("overflow-y", "auto", "important");
    if (textarea.scrollHeight > maxHeight) {
      textarea.style.setProperty("height", maxHeight + "px", "important");
    } else {
      textarea.style.removeProperty("height");
    }
  }

  function apply() {
    const composer = root();
    const input = chatInput(composer);
    if (!composer || !input) return false;
    composer.classList.add("cd-composer-card");
    input.classList.add("cd-composer-card");
    const textarea = input.querySelector('[data-testid="stChatInputTextArea"], textarea');
    if (textarea) capTextarea(textarea);
    win.requestAnimationFrame(() => {
      placeModel(composer, input);
      if (textarea) capTextarea(textarea);
      win.requestAnimationFrame(() => {
        placeModel(composer, input);
        if (textarea) capTextarea(textarea);
      });
    });
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
    win.addEventListener("resize", schedule);
    const observer = new win.MutationObserver(schedule);
    observer.observe(input, { childList: true, subtree: true, characterData: true });
    const slot = modelSlot(composer);
    if (slot) observer.observe(slot, { childList: true, subtree: true });
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
